# MedicalEvidenceFinder correction memory example

This runnable local example demonstrates persistent, user-editable correction memory with source-page validation.
It uses entirely fictional extracted page records, not medical evidence.
The selected project folder was empty and had no Git repository, application stack, PDFs, or existing failures to diagnose.
This is a standalone demonstration, not an integration with your existing RAG system.

## Externalized agent skills

The `skills/` directory is a versioned, reviewable behavior layer.
`skills/evidence-selection/SKILL.md` describes how to select sections, validate anchors, handle family transfer, and abstain.
`skill_registry.py` loads active markdown skills and builds a bounded prompt context for an optional LLM adapter.
The registry does not call an LLM and is intentionally framework-neutral, so it can later connect to an LLM wiki, hosted prompt registry, or your Python application's own model client.
Markdown skills explain reusable behavior; JSON or database records retain user corrections and audit history.
The `/api/skill-context` endpoint shows the exact assembled context for a query without exposing source PDFs.

## Browser demo

```sh
python3 prototype.py
```

Open http://127.0.0.1:8765 in your browser.
The server listens only on loopback; use this computer for presenting or screen sharing.
The browser interface supports source highlighting, correction teaching, vocabulary aliases, reference notes, editable previews, history, and revocation.
Browser memory is stored in `local-data/corrections.json` and `local-data/knowledge.json`, separate from the CLI's `corrections.json`.
Restarting the server retains lessons.
Use `python3 prototype.py --port 8766 --data /private/tmp/evidence-presentation` to run an isolated presentation workspace instead.

### Five-minute presenter walkthrough

1. In memory management, expand **Presenter controls** and reset demo memory if you want a fresh session.
2. Search `amber review criteria` and show the incorrect index result on page 1.
3. Click **Preview lesson** with the prefilled correction, inspect page 2 and the exact quote, then click **Save lesson**.
4. The result changes to page 2; click **Open highlighted passage** and show the precise substantive sentence.
5. Reload the browser to demonstrate persistence.
6. Search `blue review criteria` to show that the unrelated result remains page 3.
7. Expand **Try a supported phrase**, click **Teach vocabulary**, then preview and save it.
8. Search `amber eligibility` and show the visible alias resolution to `amber review criteria` and corrected passage.
9. Use **Add a reference note** to save a human lesson; it appears separately as user knowledge, never as source evidence.
10. In memory management, inspect provenance, edit a lesson, or revoke the correction and search again to demonstrate user control.

The phrase parser accepts the three displayed example forms, using double quotes around fields.
It does not interpret arbitrary language, infer synonyms, or train a model.
Vocabulary maps a complete normalized query once; it does not replace substrings or recursively expand aliases.
Notes match the original or resolved complete query and never influence ranking.
Every lesson is scoped to this synthetic document revision.
Reset clears only the selected browser data directory's two memory files, including history; it does not change the fixture or CLI memory.

### Validation

`python3 -m unittest -v` runs 12 tests covering CLI persistence, correction/edit/revoke flows, vocabulary, reference notes, document isolation, quote validation, reset, and local HTTP origin protection.
The browser flow was also exercised manually through the interface: save, reload, unrelated search, vocabulary, invalid-quote rejection, edit history, revoke, and highlighted source navigation.

## Run

Requires Python 3.10 or newer and no dependencies, credentials, or network access.
From this folder:

```sh
python3 evidence_demo.py demo
python3 -m unittest -v
```

The demo first reproduces a synthetic retrieval failure: an index page outranks the actual fictional worksheet.
It then writes a correction to a temporary file, searches again using that file, checks an unrelated query, and revokes the correction.
The demo's temporary memory is discarded when it exits.
The following commands use persistent `corrections.json` instead.

```sh
python3 evidence_demo.py search 'amber review criteria'
python3 evidence_demo.py remember 'amber review criteria' --page 2 --quote 'The fictional amber pathway requires a completed sample checklist.' --author Jun --reason 'Remember this: use the eligibility worksheet instead of the index.'
python3 evidence_demo.py search 'amber review criteria'
python3 evidence_demo.py search 'blue review criteria'
python3 evidence_demo.py list
```

To revoke, copy the correction's `id` from `list` and run `python3 evidence_demo.py revoke ID`.
You can also edit `corrections.json` directly, including setting `active` to `false`.
Each search reloads the file, so edits take effect on the next run.
If multiple active corrections match, the last entry in the file wins; revoking it can expose an older active correction.
Keep only one active correction per scope unless that fallback is intended.

Corrections can be scoped to an exact revision (the default) or to a document family with the CLI `--scope family` option.
Family rules store a structural profile and may relocate the verified quote when pagination changes.
Transferred rules are labeled separately, receive a confidence score, and require review when the profile match is weak.
The family scope is intentionally conservative: it transfers a unique quoted passage, never a bare page number.

## What is remembered

A correction records an exact normalized query, document ID, SHA-256 of the entire document record, physical page number, verbatim quote, author, reason, timestamp, and active status.
It applies only to that query and exact document revision.
Capitalization, punctuation, and spacing are normalized; paraphrases are deliberately not inferred.
The next search revalidates the quote against the specified page before returning it.
A unique quote also yields a precise anchor within the extracted page text: physical page number and start/end Unicode character offsets, bound to the document revision.
Repeated quotes on the same page are rejected as ambiguous; select a longer unique passage.
The corrected demo anchors the substantive sentence after the worksheet heading rather than the whole page.
`pdf_destination` is explicitly null because this fixture has no PDF coordinates.
This is a text-span destination for a viewer integration, not a created PDF bookmark or a verified section boundary.
A changed document causes the correction to be skipped with a diagnostic.
Unknown queries with no lexical overlap return no result.
Baseline lexical matches are explicitly labeled as candidates with unverified relevance.

This is persistent application memory, not model training: no model weights change and no LLM is used.
The free-text reason is provenance for a human, not executable instructions.
The browser's limited phrase parser proposes these structured fields for user review.
The example does not automatically interpret arbitrary “remember this” messages.

## How this fits the real system

Keep PDF extraction and layout diagnosis separate from correction memory.
Your clarification is that extraction and OCR appear adequate, so the next integration should concentrate on candidate page/section selection and destination mapping.
Use the confirmed quote span to locate the corresponding PDF text boxes and derive a viewer destination, then verify it opens the intended substantive section.
An OCR failure, lost table structure, repeated headers, or wrong page mapping cannot be repaired reliably by a retrieval preference.
The integration boundary here is `fixtures/synthetic.json`: a source identity and a list of physical page numbers with extracted text.
A real adapter should preserve the original PDF hash, physical PDF page index, printed page label, and bounding boxes where available.
This demo hashes extracted JSON only and cannot validate the fidelity of extraction to an original PDF.

Your existing retriever can replace the small lexical ranking block in `search`.
For a production design, compare lexical and semantic retrieval using actual failing documents, combine their candidates, and validate quoted spans before creating bookmarks.
Hybrid retrieval, embeddings, OCR, actual PDF reading, PDF bookmarks, clinical interpretation, and performance on 1,000-page PDFs are not implemented or evaluated here.
The synthetic case demonstrates the memory mechanism only and provides no estimate of clinical accuracy.

The test suite includes a pagination-change fixture demonstrating family transfer to a new physical page with review required.

An editable wiki can explain extraction patterns and reviewed lessons, but structured records should control runtime corrections.
Start with narrow document/query scope; add a reviewed template or document-family rule only after demonstrating that it transfers to separate fixtures without harming unrelated cases.
Do not treat text inside a retrieved PDF as permission to write memory.
In a real application, capture authorized user feedback through a dedicated correction action.

## Limits and next integration step

This CLI assumes a trusted local user and a single writer.
JSON replacement is atomic, but there is no concurrent-write locking, access control, tamper-proof audit log, or encryption.
Quotes may contain private content if you later use real records; keep both those records and correction files local under your existing private-data controls.
Nothing is uploaded by this example.

To diagnose the actual failures next, provide the existing project location and a locally available failing example or sanitized extracted-page fixture, with the expected evidence location.
That enables an end-to-end reproduction before changing the actual extraction or retrieval code.
