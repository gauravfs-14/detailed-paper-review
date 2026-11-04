# Output files and their JSON shape

The dashboard (`build_dashboard.py`) and the PDF (`build_report.py`) read only these files. Write valid JSON,
use these field names exactly, and leave a field out rather than filling it with a guess. Paths are relative
to the review folder `$RV`.

## Contents
- review.json (intake answers)
- Common phase file (all phases)
- Finding
- Phase 1 items (references)
- Phase 2 items (claims) and batch result files
- Phase 9 reviewers
- 00-summary.json
- fixes.json
- Severity scale

## `review.json` (intake, written before any phase)

```json
{"journal": "...", "article_type": "research article", "submission": "first|revision", "round": 2,
 "mode": "review|fix", "blind_review": false,
 "inputs": {"manuscript": "...", "bib": "...", "pdf": "...", "figures": [], "supplement": null, "data": null,
            "code": null, "local_pdfs": null,
            "revision": {"annotated": null, "response": null, "comments": null, "previous": null}},
 "missing": ["what is missing and what it prevents checking"]}
```

## Common phase file: `phases/<id>.json`

IDs: `01-references`, `02-factcheck`, `02b-uncited-claims`, `02c-literature`, `02d-text-overlap`,
`03-consistency`, `03b-claim-map`, `04-methods-stats`, `04b-missing-reporting`, `04c-equations`,
`05-acronyms`, `06-figures-tables`, `07-crossrefs`, `08-editorial`, `09-peer-review`, `R-revision`.

```json
{
  "phase": "03-consistency",
  "title": "Consistency",
  "status": "complete",
  "status_reason": "",
  "coverage": {"unit": "sections", "total": 12, "checked": 12},
  "summary": "Two to four plain sentences: what was checked and the main result.",
  "findings": [ ... ],
  "items": [ ... ]
}
```

- The dashboard enforces minimum coverage from the script outputs (2b: every uncited sentence, 2d: every
  overlap candidate, 3b: every claim candidate, 4c: every equation, R: every parsed comment) and treats any
  recomputed item without a `command`, or `computation` evidence without the command, as not checked.
- `status`: `complete` only when every unit in `coverage.total` was actually checked. Otherwise
  `incomplete` with `status_reason` saying what is missing. `skipped` only when the user said to skip it.
  The dashboard recomputes phases 1 and 2 itself and overrides a wrong `complete`.
- `coverage.unit` examples: `references`, `sentence-citation pairs`, `sections`, `numbers`, `tables`,
  `figures`, `acronyms`, `labels`, `checklist items`.

## Finding

```json
{
  "id": "CON-004",
  "severity": "major",
  "title": "Test-set size is 3,771 in the abstract but 3,772 in Table 2",
  "location": {"file": "main.tex", "line": 151, "section": "Data", "label": "tab:data"},
  "quote": "exact manuscript text the finding is about (optional)",
  "what": "What is wrong, in one or two plain sentences.",
  "why": "Why it matters for a reader or reviewer (optional).",
  "fix": "Concrete fix. For a wording fix, give the replacement text.",
  "evidence": [
    {"kind": "manuscript", "text": "main.tex:38 says '... 3,771 articles ...'"},
    {"kind": "computation", "text": "recompute_metrics.py sum --values 3017,754 --total 3771 -> adds_up: true"},
    {"kind": "registry", "text": "Crossref: volume 43, issue 4, pages 51-58", "url": "https://doi.org/..."},
    {"kind": "source_quote", "source_key": "devlin2019", "page": 3, "text": "exact words from the source"}
  ],
  "confidence": "high",
  "issue_key": "test-set-size-mismatch",
  "ref_key": "entman1993",
  "claim_ref": "C014",
  "fixable": true
}
```

ID prefixes: `REF` `FC` `UC` (uncited) `LIT` `OV` (overlap) `CON` `CM` (claim map) `MET` `REP` `EQ` `ACR`
`FIG` `TAB` `XR` `ED` `PR` `RV` (revision). `issue_key` is a short lowercase name for the underlying problem;
use the same key when several phases find the same problem, so `review_tool.py dedupe` merges them into one
issue in `phases/_issues.json`. To force a merge the heuristics miss, list finding ids in
`phases/_merge.json`: `{"merge": [["CON-002", "TAB-001", "MET-001"]]}`. `ref_key` links the finding to
a reference drawer, `claim_ref` to the evidence viewer. Every finding needs `severity`, `title`, `what`,
and a `location` (or `"location": {"section": "whole paper"}` when it is global).

## Phase 1 items (one per reference, every reference)

```json
{
  "key": "entman1993", "number": 3, "title": "Framing: Toward Clarification of a Fractured Paradigm",
  "verdict": "verified",
  "problems": [{"field": "pages", "severity": "critical", "note": "Entry says 51-60, Crossref says 51-58"}],
  "reason": "Matches Crossref and OpenAlex on all fields.",
  "corrected_entry": "@article{entman1993, ... }",
  "evidence": [{"kind": "registry", "text": "Crossref 10.1111/j.1460-2466.1993.tb01304.x: ...", "url": "https://doi.org/..."}],
  "text_kind": "abstract"
}
```

`verdict`: `verified` (all fields match at least one authoritative record, no fix needed), `needs_fix`
(any critical or major field error, wrong DOI, retracted, or a duplicate entry), `check` (a minor issue the
author should look at, such as Early Access metadata drift), `unverifiable` (no authoritative record found
after the full search procedure). Make each problem a matching finding with `ref_key` set.

## Phase 2: batch result files `work/factcheck/<batch>.result.json`

```json
{"batch": "batch-03", "items": [
  {
    "id": "b03-01",
    "sentence_id": "s0042",
    "cite": "ralph2019",
    "section": "Evidence from crash-reporting research",
    "claim": "The part of the sentence that this one citation is used for.",
    "verdict": "supported",
    "checked_against": "fulltext",
    "evidence": [
      {"source_key": "ralph2019", "page": 4, "quote": "verbatim words copied from the source text file", "supports": true}
    ],
    "reasoning": "Why the quote does or does not support the claim, mentioning any number or scope difference.",
    "suggested_fix": "Only when not supported: corrected wording that the source does support, or 'remove citation'.",
    "second_check": {"verdict": "partial", "agrees": false, "note": "..."}
  }
]}
```

- One item per (sentence, cited key) pair. A sentence citing three papers produces three items. The merge
  step counts these pairs against `manuscript.json` and lists every pair that has no item.
- `verdict`: `supported` | `partial` | `not_supported` | `contradicted` | `cannot_verify`.
- `checked_against`: `fulltext` | `webpage` | `abstract` | `none`.
- `quote` must be copied character for character from `sources/text/<key>.txt` (or the abstract). Copy
  15 to 60 words, enough to show the support. `page` is the `=== PAGE n ===` number in that file.
  Evidence against the claim gets `"supports": false`.
- `second_check` is added after the second-checker runs (required for every non-supported item).

`merge-factcheck` builds `phases/02-factcheck.json` from these; do not hand-edit its coverage. You may add a
`summary` field to the merged file.

## Phase 9: reviewers

```json
{
  "phase": "09-peer-review", "status": "complete", "coverage": {"unit": "reviewers", "total": 4, "checked": 4},
  "reviewers": [
    {"name": "Reviewer 1", "lens": "Domain expert: pedestrian safety and crash reporting",
     "summary": "...", "recommendation": "major revision",
     "concerns": [{"id": "R1-M1", "severity": "major", "blocking": true, "title": "...", "detail": "...",
                   "evidence_pointer": "main.tex:212, Table 3", "resolution": "..."}]}
  ],
  "synthesis": "What the reviewers agree on, where they differ, what must be fixed first.",
  "findings": [ "one finding per consensus or blocking concern, id PR-..." ]
}
```

## `phases/00-summary.json` (written last, by the main agent)

```json
{
  "paper_title": "...",
  "verdict": "not_ready",
  "overview": "Three or four short sentences in plain English.",
  "short_version": ["5 to 7 bullets, one idea each, plain words"],
  "top_problems": [{"title": "...", "why": "...", "fix": "...", "phase": "02-factcheck", "id": "FC-b03-01"}],
  "could_not_check": ["Exactly what was not checked and why."],
  "honesty_note": "Optional one line about limits of this review."
}
```

`verdict`: `ready` (no critical or major findings left, all phases complete), `almost` (only minor
findings, or a few majors that are quick wording fixes), `not_ready` (any critical finding, any
unsupported or contradicted citation, or an incomplete strict phase).

## `fixes.json` (fix mode only)

```json
{"fixes": [
  {"id": "REF-003", "file": "references.bib", "find": "pages   = {51--60}", "replace": "pages   = {51--58}",
   "reason": "Crossref record for 10.1111/j.1460-2466.1993.tb01304.x"}
]}
```

`find` must appear exactly once in the file; include enough surrounding text to make it unique. One fix per
change. Empty `replace` deletes the text. In `.tex` files the replacement is LaTeX: escape `\%`, `\&`,
`\#`, `\_` (an unescaped `%` silently comments out the rest of the line) and keep braces balanced.

After applying, `verify_fixes.py` writes `corrected-by-agent/verify.json` (`checks`, `per_fix` with status
`verified` / `failed` / `needs_agent_check`, `agent_check`, `overall`) and `VERIFY.md`. The fix-verifier's
`work/fixcheck/result.json` shape is in `agents/fix-verifier.md`.

## Severity scale (all phases)

| Severity | Meaning | Examples |
|---|---|---|
| `critical` | Would mislead readers, break integrity, or get the paper rejected or corrected after publication | fabricated or wrong reference, cited claim not in or contradicted by the source, reported metric that cannot be reproduced from the paper's own numbers, missing ethics approval, data leakage |
| `major` | Weakens the case or would draw a reviewer demand | partly supported claim, missing uncertainty or effect size for a main result, inconsistent sample sizes, undefined key metric, figure that cannot be read at print size |
| `minor` | Local fix, does not change conclusions | acronym defined twice, missing issue number, inconsistent decimal places, unreferenced supplementary table |
| `info` | Worth knowing, no change needed | style choice, optional improvement |
