# Phases 10 and 11: telling the user

The user may be tired, busy, or not a native English speaker, and may have ADHD. They asked for the whole
truth in a form they can act on. So: short sentences, common words, one idea per line, most important
first, nothing hidden, no softening, no padding.

## Before writing anything

1. `build_dashboard.py` and `review_tool.py coverage`. Read every phase status.
2. If any phase is not complete, that is the first thing the user hears, with what is missing.
3. Run `review_tool.py dedupe` and read `phases/_issues.json`: one entry per real problem, with every phase
   that found it. Merge any obvious duplicates it missed via `phases/_merge.json` and rerun. Count and talk
   about **issues**, not raw findings (the same padded table reported by four phases is one problem).
4. Pick the 3 to 5 issues that most affect whether the paper is accepted and believed: `top_problems`.
5. Collect everything that was not checked: intake gaps from `review.json`, skipped or incomplete phases,
   claims checked against abstracts only, and the papers in `sources/TO_DOWNLOAD.md`.

## Write `phases/00-summary.json`

See `output-schema.md`. Rules for the text in it:
- `overview`: 3 or 4 sentences. What the paper does, how ready it is, the single biggest risk.
- `short_version`: 5 to 7 bullets. Each under 20 words. Concrete ("3 references have the wrong DOI"), not
  vague ("some reference issues").
- `top_problems`: each with `why` (one sentence on the consequence) and `fix` (one sentence on what to do).
- `could_not_check`: every limit, named plainly ("No text was available for 3 cited works, so 4 claims
  citing them are unchecked: ...").
- Say good things only when true and specific ("All 18 references exist and 15 are exactly right").

## Chat answer format

```
**Verdict: Not ready yet.** <one sentence why>

**Fix these first**
1. <problem> -> <fix>
2. ...

**What I checked**
- References: 18 of 18 checked. 3 need fixes.
- Cited claims: 25 of 25 checked. 2 not supported, 1 partly, 3 could not be verified (no text).
- ... one line per phase, including any phase that is NOT finished and why.

**What I could not check**
- ...

**Papers to download** (so the claims citing them can be checked against full text)
- <key>: <title> (<n> claims depend on it), from sources/TO_DOWNLOAD.md

(For a revision: one line per reviewer: N comments, N addressed, N partially, N not addressed, N claimed changes not found.)
(After fixes: resolved N, still open N, new N, from COMPARISON.md.)

Dashboard: <path>   PDF report: <path>   (Fixed files: <path>, only in fix mode)
```

Style rules for the chat answer and every summary field:
- Plain words: "wrong", "missing", "does not match", "not in the source". Avoid jargon unless it is the
  paper's own term.
- Numbers instead of adjectives.
- No hedging filler ("it may be worth considering"). Say "Change X to Y".
- No praise sandwich. Strengths go in one short line if real.
- Bold only the verdict and the section labels.
- Never say "everything checked" or "fully verified" unless coverage says so.

## PDF

`build_report.py` turns the phase files and the summary into `REPORT.md` and `REPORT.pdf` with the same
order: verdict, short version, fix first, coverage table, what could not be checked, each phase, and
appendices with every reference and every claim. Do not write the report by hand.
