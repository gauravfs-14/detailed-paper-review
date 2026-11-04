# Brief: reviewer lenses (phase 9, before the reviewers start)

Inputs: the manuscript (`$RV/manuscript/manuscript.json`; read the abstract and methods) and the rulebook
`<skill>/references/09-peer-review.md`. Output: `$RV/work/review/lenses.json`.

---

**First, read and follow `<skill>/agents/_evidence-rules.md`.**

Define 3 or 4 reviewer lenses that fit this paper, as the rulebook's "Set the lenses" section describes:
the paper's own field, methods and statistics, the adjacent field it borrows from, and optionally a
demanding generalist. Each lens is a focus, not a fake identity: no names, institutions or careers.

Write:

```json
{"tasks": [{"id": "R1", "lens": "Domain expert: pedestrian safety and crash reporting", "output": "work/review/R1.json"},
           {"id": "R2", "lens": "...", "output": "work/review/R2.json"}]}
```
