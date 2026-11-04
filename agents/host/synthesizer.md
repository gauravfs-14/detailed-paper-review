# Brief: peer-review synthesis (phase 9, after every report is in)

Inputs: `$RV/phases/09-peer-review.json` (`reviewers`: every report, frozen) and the rulebook
`<skill>/references/09-peer-review.md` (section "Synthesis"). Output: `$RV/work/review/synthesis.json`.

---

**First, read and follow `<skill>/agents/_evidence-rules.md`.**

Read every report. Do not change any of them. Write the synthesis the rulebook describes: consensus
strengths; consensus blocking concerns; other consensus majors; where reviewers differ and why; the minimum
set of changes that would most improve the paper's chances. Turn every blocking or consensus concern into a
finding with an id starting `PR-` (shape in `references/output-schema.md`), with the reviewers' location.

Write:

```json
{"summary": "Two to four plain sentences: the reviewers' overall view and recommendations.",
 "synthesis": "The synthesis, in short plain paragraphs or bullets.",
 "findings": [ <PR- findings> ]}
```
