# Brief: fix verifier (after fix mode)

Give this agent the review folder, the path to `work/fixcheck/changed.json`, `corrected-by-agent/verify.json`
and the clean copy folder. Do not give it the reasoning of the agent that wrote the fixes. Output path:
`$RV/work/fixcheck/result.json`.

---

**First, read and follow `<skill>/agents/_evidence-rules.md`.** In short: memory is not evidence; something
is true only if the manuscript, a saved source, a fetched page, or code you ran says so explicitly; every
calculation is done by code with the command recorded; check every item you were given.

You check edits that another agent made to a manuscript. Your job is to catch any fix that introduced a new
problem: a claim the source no longer supports, a changed meaning, a grammar error, a broken sentence, a
wrong reference field. You did not write these fixes; judge them as a skeptical co-author would.

Your memory is not evidence. Every verdict rests on the saved source text (`sources/text/<key>.txt`), a
registry or publisher page you open now, or the manuscript itself.

1. For **every edited sentence** in `changed.json`:
   - Read it in the clean copy with the sentence before and after it (`file`, `line`).
   - If it cites works: for each cited key, find the passage in the source text that supports the new
     wording and copy it exactly with its `=== PAGE n ===` number. Verdict `supported`, `partial`,
     `not_supported` or `cannot_verify`, as in `references/02-fact-check.md`. A fix whose new wording is
     not supported fails, even if the old wording was worse.
   - If it cites nothing: verdict `ok` or `problem`. Check grammar, that the meaning matches the
     finding it fixes, that no new claim or number was added without a source, and that it still reads
     well with its neighbours.
2. For **every warning** in `verify.json` (`status: warn`): decide if it is acceptable and why. For a
   reference whose venue the registries could not confirm, open the proceedings or publisher page named
   in the fix and confirm title, authors, venue and year; record the URL.
3. Look at the marked PDF if one exists (`corrected-by-agent/marked/*.pdf`, render pages with
   `scripts/render_pages.py`): the blue text should appear exactly where each fix is, and nothing else
   should look different.

Write:

```json
{"items": [{"sentence_id": "s0098", "fix_ids": ["FC-b04-01"], "cite": "devlin2019", "verdict": "supported",
            "evidence": [{"source_key": "devlin2019", "page": 1, "quote": "exact words"}], "note": "..."}],
 "warnings_reviewed": [{"check": "reference-lan2020", "acceptable": true, "url": "https://...", "note": "..."}],
 "marked_pdf": {"checked": true, "note": "..."}}
```

One item per (edited sentence, cited key), and one item per edited sentence without citations. Then the
main agent runs `verify_fixes.py --finalize`. Count your items against `changed.json` before finishing.
