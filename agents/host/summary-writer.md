# Brief: summary (phase 10)

Inputs: every `$RV/phases/*.json` (including `_issues.json` and `_status.json`), `$RV/review.json` and
`$RV/sources/to_download.json`. Rules: `<skill>/references/10-final-report.md` and the `00-summary.json`
shape in `<skill>/references/output-schema.md`. Outputs: `$RV/phases/00-summary.json`, and
`$RV/phases/_merge.json` only if you find duplicates the automatic grouping missed.

---

**First, read and follow `<skill>/agents/_evidence-rules.md`.**

Follow the rulebook's "Before writing anything" and "Write phases/00-summary.json" sections. Count and
describe issues (from `_issues.json`), not raw findings. Every phase that is not complete is named first,
with what is missing. Everything that was not checked goes in `could_not_check`. Plain words, short
sentences, most important first, nothing softened. Base every statement on the phase files.

If `_issues.json` lists the same problem as separate issues, write `phases/_merge.json`
(`{"merge": [["CON-002", "TAB-001"]]}`); the app reruns the grouping.
