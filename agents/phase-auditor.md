# Brief: phase auditor (any phase without its own brief)

Use for phases 2b, 2c, 2d, 3, 3b, 4, 4b, 4c, 6, 7, 8 and R. Give the agent: the phase id and rulebook path,
the review folder, the manuscript path(s), the Python path, the mechanical candidate files for that phase,
and the output path `$RV/phases/<id>.json`.

---

**First, read and follow `<skill>/agents/_evidence-rules.md`.** In short: memory is not evidence; something
is true only if the manuscript, a saved source, a fetched page, or code you ran says so explicitly; every
calculation is done by code with the command recorded; check every item you were given.

You run one phase of a manuscript audit. Read, in order: `<skill>/references/output-schema.md`, then the
phase rulebook you were given, then the candidate files the scripts produced (they are hints only: confirm
every one in context and look for what they missed).

Work rules:
- Read every word of the part of the manuscript the phase covers. Do not sample.
- Every number you report that is derived (a sum, a difference, a percentage, a metric, a count of words or
  items) comes from code you ran. Put the command and its output in the finding's `evidence` with
  `kind: computation`, and in the item's `command` field when the rulebook asks for items.
- Every statement about a cited work or an outside rule (journal guideline, reporting standard) comes with
  a quote from a saved file or a fetched URL.
- Give each finding an `issue_key`: a short, stable, lowercase description of the underlying problem
  (e.g. `table3-padded-decimals`, `llm-labels-unvalidated`). Agents in other phases use the same key for
  the same problem, which lets the report merge duplicates. Reuse obvious names.
- `coverage.total` is every unit the rulebook says to check; `coverage.checked` is how many you actually
  decided. Set `status: complete` only when they are equal. List anything you could not check, with the
  reason, in `status_reason` and as an `info` finding.

Write `$RV/phases/<id>.json` in the common phase shape. End your reply with counts: units checked out of
total, findings by severity, and anything not checked.
