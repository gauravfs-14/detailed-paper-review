# Brief: independent second checker (phase 2)

Give this agent a list of items, each with: the manuscript sentence, the claim, the cited key, and the
path to `sources/text/<key>.txt`. Do **not** give it the first checker's verdict, quote or reasoning.
Output path: `$RV/work/factcheck/second-<n>.json`.

---

**First, read and follow `<skill>/agents/_evidence-rules.md`.** In short: memory is not evidence; something
is true only if the manuscript, a saved source, a fetched page, or code you ran says so explicitly; every
calculation is done by code with the command recorded; check every item you were given.

You are an independent second checker. Another checker already looked at these claims; you do not know
what they decided, and that is deliberate. Decide each one yourself from the saved source text.

Rules: your memory is not evidence. Read the source text, find the passage that decides the claim, copy
it exactly with its `=== PAGE n ===` number. Verdicts: `supported`, `partial`, `not_supported`,
`contradicted`, `cannot_verify`. Definitions are in `<skill>/references/02-fact-check.md`.

Write:

```json
{"items": [{"id": "<item id>", "verdict": "...", "quote": "exact words", "page": 4, "note": "1-2 sentences"}]}
```

The main agent copies each into the item's `second_check` as `{"verdict", "agrees", "note"}` (with your
quote in the note) and runs `review_tool.py merge-factcheck` again.
