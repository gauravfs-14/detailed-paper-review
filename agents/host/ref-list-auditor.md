# Brief: reference list auditor (phase 1, list level)

Inputs: `$RV/phases/01-references.json` (every reference with its verdict), `$RV/manuscript/manuscript.json`
(references, and the sentences that cite them), `$RV/refcheck/auto_refs.json`, the rulebook
`<skill>/references/01-references.md`, and `review.json` (journal and reference style, if known).
Output: `$RV/work/refs/list.json`.

---

**First, read and follow `<skill>/agents/_evidence-rules.md`.**

The per-reference verdicts are done. Your job is the reference list as a whole, as the rulebook describes:
references cited in the text but missing from the list, entries in the list that are never cited,
duplicates (the same work twice, under different keys or numbers), retracted works (from the registry
records), and style problems that run through the list (inconsistent formats, missing fields for the
journal's style). Use `manuscript.json` and the record files; do not judge any single entry again.

Write:

```json
{"summary": "Two to four plain sentences on the reference check as a whole: how many exist, how many are exactly right, the main problems.",
 "findings": [ <findings in the shape of references/output-schema.md, ids REF-L01, REF-L02, ...> ]}
```

An empty `findings` list is a valid answer when the list has no list-level problem.
