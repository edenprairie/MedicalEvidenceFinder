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


def remember(document, memory, query, page, quote, author, reason):
    if not normalize(query) or not author.strip() or not reason.strip():
        raise ValueError("Query, author, and reason are required")
    evidence_page(document, page, quote)
    records = load_memory(memory)
    record = dict(id=str(uuid.uuid4()), document_id=document["id"],
                  revision=fingerprint(document), query=normalize(query), page=page,
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
    for record in reversed(load_memory(memory)):
        if not record["active"] or record["document_id"] != document["id"] or record["query"] != normalized:
            continue
        if record["revision"] != fingerprint(document):
            diagnostics.append("Skipped stale correction " + record["id"])
            continue
        try:
            page = evidence_page(document, record["page"], record["quote"])
        except ValueError:
            diagnostics.append("Skipped invalid evidence in correction " + record["id"])
            continue
        return dict(source=document["source"], page=page["page"], quote=record["quote"],
                    anchor=anchor(document, page, record["quote"]),
                    method="user correction", correction_id=record["id"], diagnostics=diagnostics)
    terms = set(normalized.split())
    ranked = sorted(document["pages"], key=lambda p: -len(terms & set(normalize(p["text"]).split())))
    if not ranked or not terms & set(normalize(ranked[0]["text"]).split()):
        return dict(result=None, diagnostics=diagnostics)
    page = ranked[0]
    return dict(source=document["source"], page=page["page"], quote=page["text"],
                anchor=anchor(document, page, page["text"]),
                method="lexical candidate (unverified relevance)", diagnostics=diagnostics)


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
            result = remember(document, args.memory, args.query, args.page, args.quote, args.author, args.reason)
        elif args.command == "revoke":
            result = revoke(args.memory, args.id)
        else:
            result = load_memory(args.memory)
        print(json.dumps(result, indent=2))
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(2, f"Error: {error}\n")


if __name__ == "__main__":
    main()
