"""Offline, synthetic demonstration of source-validated correction memory."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import tempfile
import uuid

ROOT = Path(__file__).resolve().parent


def read(path):
    return json.loads(Path(path).read_text())


def normalize(query):
    return " ".join(re.findall(r"\w+", query.casefold()))


def fingerprint(document):
    return hashlib.sha256(json.dumps(document, sort_keys=True).encode()).hexdigest()


def document_profile(document):
    """Stable, low-cost shape signal; content is deliberately not treated as identity."""
    headings = []
    for page in document.get("pages", []):
        headings.extend(re.findall(r"(?:^|\n)([A-Z][^\n:]{2,80})(?::|$)", page.get("text", "")))
    return dict(page_count=len(document.get("pages", [])),
                headings=tuple(normalize(h) for h in headings),
                has_tables=any("|" in p.get("text", "") for p in document.get("pages", [])),
                family=document.get("family", document.get("id", "unknown")))


def profile_similarity(left, right):
    """Score structural transferability, without allowing a page number to transfer."""
    score = 0.0
    if left["family"] == right["family"]:
        score += 0.65
    if left["page_count"] == right["page_count"]:
        score += 0.2
    if left["has_tables"] == right["has_tables"]:
        score += 0.05
    if left["headings"] and right["headings"]:
        score += 0.1 * len(set(left["headings"]) & set(right["headings"])) / max(len(set(left["headings"])), 1)
    return round(min(score, 1.0), 3)


def load_memory(path):
    records = read(path) if Path(path).exists() else []
    if not isinstance(records, list):
        raise ValueError("Correction memory must be a JSON array")
    required = {"id", "document_id", "revision", "query", "page", "quote",
                "author", "reason", "created_at", "active"}
    for record in records:
        if not isinstance(record, dict) or not required <= record.keys():
            raise ValueError("Invalid correction record: missing required fields")
        if type(record["active"]) is not bool:
            raise ValueError("Correction active must be true or false")
    return records


def save(path, records):
    path = Path(path)
    # Atomic replacement avoids a half-written file; single writer only.
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(records, indent=2) + "\n")
    temporary.replace(path)


def evidence_page(document, page_number, quote):
    matches = [p for p in document["pages"] if p["page"] == page_number]
    if len(matches) != 1 or not quote.strip() or quote not in matches[0]["text"]:
        raise ValueError("Quote must occur verbatim on exactly one specified source page")
    if matches[0]["text"].count(quote) != 1:
        raise ValueError("Quote is ambiguous on this page; select a longer unique quote")
    return matches[0]


def anchor(document, page, quote):
    start = page["text"].index(quote)
    return dict(document_revision=fingerprint(document), physical_page=page["page"],
                text_start=start, text_end=start + len(quote),
                coordinate_system="extracted text Unicode character offsets, end exclusive",
                pdf_destination=None)


def remember(document, memory, query, page, quote, author, reason, scope="revision"):
    if not normalize(query) or not author.strip() or not reason.strip():
        raise ValueError("Query, author, and reason are required")
    evidence_page(document, page, quote)
    records = load_memory(memory)
    record = dict(id=str(uuid.uuid4()), document_id=document["id"],
                  revision=fingerprint(document), query=normalize(query), page=page,
                  document_family=document_profile(document)["family"], scope=scope,
                  source_profile={**document_profile(document), "headings": list(document_profile(document)["headings"])},
                  quote=quote, author=author, reason=reason,
                  created_at=datetime.now(timezone.utc).isoformat(), active=True)
    records.append(record)
    save(memory, records)
    return record


def search(document, memory, query):
    normalized = normalize(query)
    if not normalized:
        raise ValueError("Query must contain words")
    diagnostics = []
    profile = document_profile(document)
    candidates = []
    for record in reversed(load_memory(memory)):
        if not record["active"] or record["query"] != normalized:
            continue
        same_revision = record["revision"] == fingerprint(document)
        family_transfer = record.get("scope") == "family" and record.get("document_family") == profile["family"]
        if not same_revision and not family_transfer:
            diagnostics.append("Skipped stale correction " + record["id"])
            continue
        try:
            page = evidence_page(document, record["page"], record["quote"])
        except ValueError:
            if family_transfer:
                matches = [p for p in document["pages"] if record["quote"] in p.get("text", "")]
                page = matches[0] if len(matches) == 1 else None
                if page is not None:
                    diagnostics.append("Transferred quote to page " + str(page["page"]))
                else:
                    diagnostics.append("Skipped family correction: quote not unique in new PDF")
            else:
                page = None
        if page is None:
            diagnostics.append("Skipped invalid evidence in correction " + record["id"])
            continue
        prior_profile = record.get("source_profile", profile)
        score = 1.0 if same_revision else profile_similarity(prior_profile, profile)
        return dict(source=document["source"], page=page["page"], quote=record["quote"],
                    anchor=anchor(document, page, record["quote"]),
                    method="user correction" if same_revision else "transferred family correction",
                    confidence=score, requires_review=score < 0.9,
                    correction_id=record["id"], candidates=[dict(page=page["page"], quote=record["quote"], score=score, source="correction")], diagnostics=diagnostics)
    terms = set(normalized.split())
    ranked = sorted(document["pages"], key=lambda p: -len(terms & set(normalize(p["text"]).split())))
    ranked = [p for p in ranked if terms & set(normalize(p["text"]).split())]
    if not ranked:
        return dict(result=None, diagnostics=diagnostics)
    for page in ranked[:3]:
        candidates.append(dict(page=page["page"], quote=page["text"], score=round(len(terms & set(normalize(page["text"]).split())) / max(len(terms), 1), 3), source="lexical"))
    page = ranked[0]
    confidence = candidates[0]["score"]
    return dict(source=document["source"], page=page["page"], quote=page["text"],
                anchor=anchor(document, page, page["text"]),
                method="lexical candidate (unverified relevance)", confidence=confidence,
                requires_review=confidence < 0.75, candidates=candidates, diagnostics=diagnostics)


def revoke(memory, correction_id):
    records = load_memory(memory)
    for record in records:
        if record["id"] == correction_id:
            record["active"] = False
            record["revoked_at"] = datetime.now(timezone.utc).isoformat()
            save(memory, records)
            return record
    raise ValueError("Unknown correction ID")


def demo(document):
    with tempfile.TemporaryDirectory() as directory:
        memory = Path(directory) / "corrections.json"
        query = "amber review criteria"
        print("SYNTHETIC DEMO: no clinical evidence or PDF extraction")
        for label, result in [("Before: index wins", search(document, memory, query))]:
            print(label, json.dumps(result, indent=2))
        record = remember(document, memory, query, 2,
                          "The fictional amber pathway requires a completed sample checklist.",
                          "demo-user", "Use the eligibility worksheet, not the index")
        print("Remembered on disk:", json.dumps(read(memory), indent=2))
        print("After:", json.dumps(search(document, memory, query), indent=2))
        print("Unrelated:", json.dumps(search(document, memory, "blue review criteria"), indent=2))
        revoke(memory, record["id"])
        print("Revoked:", json.dumps(search(document, memory, query), indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--document", type=Path, default=ROOT / "fixtures/synthetic.json")
    parser.add_argument("--memory", type=Path, default=ROOT / "corrections.json")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("demo")
    commands.add_parser("list")
    commands.add_parser("search").add_argument("query")
    correction = commands.add_parser("remember")
    correction.add_argument("query")
    correction.add_argument("--page", type=int, required=True)
    correction.add_argument("--scope", choices=("revision", "family"), default="revision")
    for flag in ("quote", "author", "reason"):
        correction.add_argument("--" + flag, required=True)
    commands.add_parser("revoke").add_argument("id")
    args = parser.parse_args()
    try:
        document = read(args.document)
        if args.command == "demo":
            demo(document)
            return
        if args.command == "search":
            result = search(document, args.memory, args.query)
        elif args.command == "remember":
            result = remember(document, args.memory, args.query, args.page, args.quote, args.author, args.reason, args.scope)
        elif args.command == "revoke":
            result = revoke(args.memory, args.id)
        else:
            result = load_memory(args.memory)
        print(json.dumps(result, indent=2))
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(2, f"Error: {error}\n")


if __name__ == "__main__":
    main()
