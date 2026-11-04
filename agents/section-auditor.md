# Brief: section auditor (phases 3, 5, 8 on long manuscripts)

Give this agent one part file (`$RV/work/sections/part-NN.json`, made by `review_tool.py plan-sections`),
the task (consistency, acronyms, or editorial language), the rulebook path for that task, and an output path
`$RV/work/<task>/part-NN.json`.

---

**First, read and follow `<skill>/agents/_evidence-rules.md`.** In short: memory is not evidence; something
is true only if the manuscript, a saved source, a fetched page, or code you ran says so explicitly; every
calculation is done by code with the command recorded; check every item you were given.

You are auditing one part of a manuscript. Other agents have the other parts; the main agent merges the
results. Read **every sentence** in your part. Do not sample.

- **Acronyms**: list every acronym or abbreviation with the sentence id and line of each use, every
  definition you see ("long form (LF)", "LF (long form)", definitions in captions or tables), and the long
  form used. Do not judge across parts; the main agent decides first use across the whole paper.
- **Consistency (local)**: terminology, spelling variant, hyphenation, tense, self-reference, number
  format, unit format, and any statement in your part that contradicts another statement in your part.
  Also list every number with what it measures, so the main agent can compare across parts.
- **Editorial language**: grammar, spelling, unclear sentences, overclaiming words, hedging, leftovers
  (TODO, ??, comments). Report each problem type once with every location, and quote meaning-changing
  errors individually. Give the corrected text for each.

Locations must be the real `file` and `line` from the part file. Quote manuscript text exactly. Do not use
memory about the paper's field to judge correctness here; this is about what the text says.

Write:

```json
{"part": "part-NN", "task": "acronyms|consistency|editorial", "sentences_read": 214,
 "records": [ ... task-specific lists ... ],
 "findings": [ <findings in the shape of references/output-schema.md> ]}
```

`sentences_read` must equal the number of sentences in the part file.
