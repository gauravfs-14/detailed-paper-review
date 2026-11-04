# Brief: fact checker (phase 2)

Paste this into the subagent prompt with the batch file path (`$RV/work/factcheck/batch-NN.json`), the
review folder, and the output path given in the batch file (`output_file`).

---

**First, read and follow `<skill>/agents/_evidence-rules.md`.** In short: memory is not evidence; something
is true only if the manuscript, a saved source, a fetched page, or code you ran says so explicitly; every
calculation is done by code with the command recorded; check every item you were given.

You are checking whether cited sources really say what a manuscript says they say. One wrong attribution
damages the whole paper, so there are no shortcuts.

**Your memory is not a source.** Even if you are sure you know what a paper says, you must find it in the
saved text file and copy the words exactly. A script will search the source for every quote you give; a
quote that is not there (paraphrased, remembered, or "cleaned up") makes your verdict invalid and it will be
redone. If you cannot find support in the text, the answer is `not_supported` or `cannot_verify`, never a
guess.

Read `<skill>/references/02-fact-check.md` first. Then, for **every sentence** in the batch and **every
key it cites**:

1. Work out which part of the sentence this key supports. Write it as `claim`. Keep every number,
   population, time period, and strength word ("most", "causes", "significantly") that the sentence uses.
2. Open `sources/text/<key>.txt` (the batch file lists it). Read it fully. For very long documents read
   the abstract, introduction, results, discussion and conclusion in full and Grep for every key term and
   number in the claim. Do not stop at the first passage that looks related.
3. Copy the deciding passage exactly (15 to 60 words) into `evidence[].quote`, with the page number from
   the nearest `=== PAGE n ===` line above it. Add counter-evidence with `"supports": false`.
4. Choose the verdict: `supported`, `partial`, `not_supported`, `contradicted`, `cannot_verify` (no text,
   or abstract only and it does not cover the detail). Explain in `reasoning` in 1 to 3 sentences.
5. If not fully supported, give `suggested_fix`: wording the source supports, or "remove this citation
   for this claim".

Write the output file:

```json
{"batch": "batch-NN", "items": [
  {"id": "bNN-01", "sentence_id": "s0042", "cite": "key", "section": "...", "claim": "...",
   "verdict": "...", "checked_against": "fulltext|webpage|abstract|none",
   "evidence": [{"source_key": "key", "page": 4, "quote": "exact words", "supports": true}],
   "reasoning": "...", "suggested_fix": "..."}
]}
```

Before you finish: the number of items must equal the total number of (sentence, cited key) pairs in the
batch. List any pair you could not finish as `cannot_verify` with the reason. Report the counts in your
final message ("14 pairs: 10 supported, 2 partial, 1 not supported, 1 cannot verify").
