# Phase 2d: text copied from sources

Goal: no sentence reproduces a cited (or saved) source's wording without quotation marks. Editors run
similarity checks; long verbatim runs from a source, even when the source is cited, read as plagiarism.

Input: `work/overlap_auto.json` (`claim_tools.py overlap`): every manuscript sentence that shares 10 or more
consecutive words with a saved source text, with the source, page, run length, and whether the sentence
cites that source. Text inside quotation marks is excluded already. The scan covers only sources the review
saved (`sources/text/`); it says how many were indexed. Works with no saved text could not be scanned: list
them as not checked.

## Decide each flagged sentence

Open the source page and the manuscript sentence and compare them yourself (quote both).

| Verdict | Use when | Severity |
|---|---|---|
| `copied` | A sentence or clause is taken from the source with little or no change and is not quoted. | major (critical if several sentences or a whole passage) |
| `close_paraphrase` | Structure and most wording kept, a few words swapped. | minor to major by length |
| `acceptable` | Shared run is a standard term, title, dataset name, definition the field uses verbatim, or a formula. | none |
| `self_overlap` | Source is the authors' own earlier paper. Still report: many journals require disclosure or rewording. | minor |

Fix: quote and cite it, or rewrite in the authors' own words (suggest a rewrite that keeps the meaning and
is supported by the source, checked like a phase 2 claim).

Also check within the manuscript itself: the same paragraph repeated in two sections (the abstract and
conclusion may echo each other; whole repeated paragraphs elsewhere are a minor finding).

## Output

`phases/02d-text-overlap.json`: `coverage.unit = "sentences with verbatim overlap"`, total at least the
number of flagged sentences, items per sentence with verdict and both quotes, findings for `copied`,
`close_paraphrase` and `self_overlap`, and an info finding listing sources that could not be scanned.
