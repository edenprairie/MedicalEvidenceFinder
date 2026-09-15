"""Local single-user UI. Run: python3 prototype.py"""
import argparse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import re
import uuid

from evidence_demo import ROOT, evidence_page, fingerprint, load_memory, normalize, read, remember, revoke, save, search
from skill_registry import SkillRegistry
from production_registry import ProductionSkillRegistry


class Prototype:
    def __init__(self, data):
        data.mkdir(parents=True, exist_ok=True)
        self.corrections = data / "corrections.json"
        self.knowledge = data / "knowledge.json"
        self.document = read(ROOT / "fixtures/synthetic.json")
        self.skills = SkillRegistry(ROOT / "skills")
        self.production_skills = ProductionSkillRegistry(data / "production-skills.sqlite")
        if not self.production_skills.versions("evidence-selection"):
            skill = self.skills.list()[0]
            draft = self.production_skills.submit(skill["name"], skill["version"], self.skills.content(skill["name"]), "system-seed", "Initialize production registry demo")
            approved = self.production_skills.approve(draft["id"], "system-seed")
            self.production_skills.activate("production", approved["id"], "system-seed")

    def state(self):
        return dict(document=self.document, corrections=load_memory(self.corrections),
                    knowledge=read(self.knowledge) if self.knowledge.exists() else [],
                    skills=self.skills.list(),
                    production_skill=self.production_skills.current("production", "evidence-selection"),
                    production_versions=self.production_skills.versions("evidence-selection"))

    def preview(self, text, query):
        # Deliberately bounded grammar; never executes instructions from source text.
        match = re.fullmatch(r'remember(?: this)?:?\s*use page (\d+)\s+for\s+"([^"]+)"\s+quote\s+"([^"]+)"', text.strip(), re.I)
        if match:
            page, query, quote = match.groups()
            evidence_page(self.document, int(page), quote)
            return dict(kind="correction", query=query, page=int(page), quote=quote, reason=text)
        match = re.fullmatch(r'remember(?: this)?:?\s*"([^"]+)"\s+means\s+"([^"]+)"', text.strip(), re.I)
        if match:
            return dict(kind="vocabulary", term=match[1], value=match[2], reason=text)
        match = re.fullmatch(r'note\s+"([^"]+)":\s*(.+)', text.strip(), re.I | re.S)
        if match:
            return dict(kind="note", term=match[1], value=match[2], reason=text)
        raise ValueError('Unsupported phrase. Use an example below or edit structured fields. No lesson was saved.')

    def action(self, route, body):
        if route == "/api/reset":
            if body.get("confirmation") != "RESET DEMO":
                raise ValueError("Explicit demo reset confirmation required")
            save(self.corrections, [])
            save(self.knowledge, [])
            return dict(reset=True)
        if route == "/api/preview":
            return self.preview(body["text"], body.get("query", ""))
        if route == "/api/skill-context":
            profile = self.document.get("family", self.document["id"])
            memory = dict(active_corrections=sum(r["active"] for r in load_memory(self.corrections)),
                          active_knowledge=sum(r.get("active", False) for r in self.state()["knowledge"]))
            return dict(context=self.skills.build_prompt_context(body.get("query", ""), profile, memory), skills=self.skills.list())
        if route == "/api/skill-publish":
            return self.skills.publish(body["name"], body["content"], body.get("author", ""), body.get("reason", ""))
        if route == "/api/skill":
            return dict(name=body["name"], content=self.skills.content(body["name"]))
        if route == "/api/production-registry":
            return dict(current=self.production_skills.current("production", body.get("name", "evidence-selection")), versions=self.production_skills.versions(body.get("name", "evidence-selection")))
        if route == "/api/search":
            query = body["query"]
            resolved = query
            lessons = self.state()["knowledge"]
            applied = []
            for record in reversed(lessons):
                if record["active"] and record["kind"] == "vocabulary" and record["revision"] == fingerprint(self.document) and normalize(record["term"]) == normalize(query):
                    resolved = record["value"]
                    applied.append(record["id"])
                    break
            result = search(self.document, self.corrections, resolved)
            return dict(result=result, query=query, resolved_query=resolved, vocabulary_ids=applied,
                        notes=[r for r in lessons if r["active"] and r["kind"] == "note" and r["revision"] == fingerprint(self.document) and normalize(r["term"]) in {normalize(query), normalize(resolved)}])
        if route == "/api/save":
            kind = body["kind"]
            author = body.get("author", "").strip()
            reason = body.get("reason", "").strip()
            if not author or not reason:
                raise ValueError("Author and reason are required")
            old_id = body.get("id")
            if kind == "correction":
                records = load_memory(self.corrections)
                if old_id and not any(r["id"] == old_id for r in records):
                    raise ValueError("Unknown correction")
                record = remember(self.document, self.corrections, body["query"], int(body["page"]), body["quote"], author, reason)
                if old_id:
                    revoke(self.corrections, old_id)
                return record
            if kind not in {"note", "vocabulary"}:
                raise ValueError("Unknown lesson kind")
            term, value = body["term"].strip(), body["value"].strip()
            if not normalize(term) or not normalize(value):
                raise ValueError("Term and value are required")
            records = self.state()["knowledge"]
            if old_id and not any(r["id"] == old_id and r["kind"] == kind for r in records):
                raise ValueError("Unknown knowledge record")
            now = datetime.now(timezone.utc).isoformat()
            for record in records:
                if record["id"] == old_id:
                    record.update(active=False, revoked_at=now)
            record = dict(id=str(uuid.uuid4()), kind=kind, term=term, value=value,
                          author=author, reason=reason, created_at=now, active=True,
                          document_id=self.document["id"], revision=fingerprint(self.document))
            records.append(record)
            save(self.knowledge, records)
            return record
        if route == "/api/revoke":
            if body["kind"] == "correction":
                return revoke(self.corrections, body["id"])
            records = self.state()["knowledge"]
            for record in records:
                if record["id"] == body["id"]:
                    record.update(active=False, revoked_at=datetime.now(timezone.utc).isoformat())
                    save(self.knowledge, records)
                    return record
            raise ValueError("Unknown knowledge record")
        raise ValueError("Unknown action")


def handler(prototype):
    class Handler(BaseHTTPRequestHandler):
        def respond(self, status, content, content_type="application/json"):
            encoded = content.encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type + "; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(encoded)

        def local_request(self):
            host = self.headers.get("Host")
            expected = f"127.0.0.1:{self.server.server_port}"
            return host == expected and self.headers.get("Origin", "http://" + expected) == "http://" + expected

        def do_GET(self):
            if not self.local_request():
                self.respond(403, '{"error":"Local origin required"}')
            elif self.path == "/":
                self.respond(200, (ROOT / "index.html").read_text(), "text/html")
            elif self.path == "/api/state":
                self.respond(200, json.dumps(prototype.state()))
            elif self.path.startswith("/skills/") and self.path.endswith("/SKILL.md"):
                name = self.path[len("/skills/"):-len("/SKILL.md")]
                self.respond(200, prototype.skills.content(name), "text/markdown")
            else:
                self.respond(404, '{"error":"Not found"}')

        def do_POST(self):
            if not self.local_request() or self.headers.get("Content-Type") != "application/json":
                self.respond(403, '{"error":"Local JSON requests only"}')
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                if not 0 < length <= 65536:
                    raise ValueError("Request too large or empty")
                body = json.loads(self.rfile.read(length))
                self.respond(200, json.dumps(prototype.action(self.path, body)))
            except (ValueError, KeyError, TypeError) as error:
                self.respond(400, json.dumps(dict(error=str(error))))

    return Handler


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data", type=Path, default=ROOT / "local-data")
    args = parser.parse_args()
    server = HTTPServer(("127.0.0.1", args.port), handler(Prototype(args.data)))
    print(f"Open http://127.0.0.1:{server.server_port} - Ctrl+C to stop", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
