---
name: evidence-selection
version: 1.0.1
status: active
owner: medical-evidence-team
review: required-before-production
---

# Evidence section selection

Select a substantive source section and return a verifiable location.

## Rules

1. Generate multiple page and section candidates.
2. Prefer substantive headings over indexes and tables of contents.
3. Preserve physical page, printed label, heading path, exact quote, and coordinates.
4. Validate the quote against the selected source revision.
5. Never transfer a page number alone to another PDF.
6. Always require human review when family transfer confidence is below the configured threshold.

## Output contract

Return the selected section, exact quote, source anchor, confidence, candidate alternatives, and review status.

This skill describes behavior. User corrections and their audit history live in structured memory.
