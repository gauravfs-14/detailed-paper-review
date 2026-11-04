# Brief: adjudicator (phase 2, disagreements)

Input: `$RV/work/factcheck/adjudication-input.json`: items where the first and the independent second
checker gave different verdicts, with both verdicts and their evidence. The source texts are in
`$RV/sources/text/<key>.txt`; the rules are in `<skill>/references/02-fact-check.md`.
Output: `$RV/work/factcheck/adjudication.json`.

---

**First, read and follow `<skill>/agents/_evidence-rules.md`.**

For every item: read the manuscript claim, both checkers' quotes, and the passages around them in the
source text. Decide the verdict the rulebook gives, using only what the source says. A quote a script could
not find in the source (`quote_match: not_found`) counts as no evidence. Do not split the difference: pick
the verdict the text supports and say why in one or two sentences, naming the deciding passage and page.

Write:

```json
{"items": [{"id": "<item id>", "verdict": "supported|partial|not_supported|contradicted|cannot_verify", "reason": "..."}]}
```

The number of items must equal the number in the input.
