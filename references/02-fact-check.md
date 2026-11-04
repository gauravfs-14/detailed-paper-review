# Phase 2: fact check of every cited sentence

Goal: for every sentence that cites a work, and for every work it cites, decide whether the cited source
actually says what the sentence attributes to it, and show the exact words in the source that decide it.
The user must be able to click any claim in the dashboard and see the highlighted passage in the source.

## Why this is strict

Citation errors are the cheapest thing for a referee to find and the most damaging to trust: one wrong
number attributed to a source makes every other citation suspect. Language models are especially prone to
"remembering" that a paper says something close to the claim. So the rule is absolute: the verdict comes
from the saved text, read in this session, quoted exactly. The quote checker (`verify-quotes`) rejects any
quote that is not in the saved source and downgrades the verdict automatically.

## Inputs per batch (`work/factcheck/batch-NN.json`)

- `sentences`: id, file, line, plain text, raw LaTeX, cited keys.
- `sources`: for each cited key, `text_file` (`sources/text/<key>.txt`, page-marked) and `kind`
  (`fulltext`, `webpage`, `abstract`, `none`).

## Procedure for each (sentence, cited key) pair

1. **Split the claim.** A sentence often cites several works for different parts. Decide which part this
   key is cited for. Write it in `claim`. If the sentence gives a number, a sample size, a year, a
   direction of effect, a population, or a method, those details are part of the claim.
2. **Read the source.** Open the text file and read all of it for full texts up to about 40 pages; for
   longer documents read the abstract, introduction, results, discussion and conclusion in full and search
   (Grep) for every key term and number in the claim. Do not stop at the first passage that looks close.
3. **Find the deciding passage** and copy it exactly (15 to 60 words) with its `=== PAGE n ===` number.
   If support is spread over two places, give two evidence entries. If the source says something that
   contradicts the claim, quote that too with `"supports": false`.
4. **Decide** using the definitions below. Numbers must match exactly (allowing only rounding the paper
   states, e.g. 7,522 vs "about 7,500" is fine if the sentence says "about").
5. **Explain** in `reasoning`, in one to three sentences, naming any difference in number, scope,
   population, time period, or strength of wording.
6. **Suggest** a fix for anything not fully supported: wording the source does support, a different
   citation if the claim is right but the source is wrong (only if you verified that other source), or
   removal of the claim.

## Verdicts

| Verdict | Use when | Severity of the finding |
|---|---|---|
| `supported` | The quoted passage states the claim, including every number and qualifier. | none |
| `partial` | The source supports the gist but not a detail: a number, a scope (e.g. "all" vs "some"), a stronger causal word, a different population or year. | major |
| `not_supported` | The source does not say this anywhere in the available text. For full texts, this is a real finding. | critical |
| `contradicted` | The source says the opposite, or a different number. | critical |
| `cannot_verify` | No text is available, or only an abstract that does not cover this detail. This is not a pass. | major, listed in "could not check" |

Special cases:
- **Abstract only.** If the abstract states the claim, `supported` with `checked_against: abstract` is
  fine. If the claim is a detail usually found in the body (a sample size, a method detail, a secondary
  result), and the abstract does not state it, the verdict is `cannot_verify`, never `supported`.
- **Secondary citation.** The source reports someone else's finding ("X et al. found..."). Note it in
  `reasoning`; the claim is supported by this source only as a report of that finding.
- **Definition or general background** ("Framing refers to..."): the source must define or describe it in
  substantially the same way. Paraphrase is fine; a different definition is `partial`.
- **Method or tool citations** ("we used RoBERTa [x]"): the source must be the work that introduced or
  describes that method or tool. Check the name and version.
- **Data source citations** (government statistics): every number in the sentence must appear in the
  report. These are often wrong by a year or by a table.
- **The manuscript cites itself or unpublished work**: `cannot_verify`, say so.

## Second check

Every item that is not `supported` goes to a `second-checker` agent with the sentence, the claim, and the
source text file, but not the first verdict or reasoning. It writes its own verdict and quote. Store it as
`second_check: {verdict, agrees, note}`. If the two disagree, both stay visible on the dashboard; the main
agent reads both quotes and decides, and the finding states the disagreement. A sample of `supported`
items (at least 10 percent, at least 3) also gets a second check, to catch over-generous first passes.

## Coverage and completion

`merge-factcheck` reports `checked/total` sentence-citation pairs and lists every pair without a verdict,
every missing batch file, and every flag without a second check. The phase is complete only when that
list is empty. Then `build_dashboard.py` runs the quote verification. Any item downgraded because its
quote is not in the source must be redone by a fresh agent before the phase is reported as finished.

## What the user sees

For each claim: the manuscript sentence with its neighbors, the verdict, the reasoning, the second check,
and for each evidence quote the rendered PDF page with the passage highlighted, plus a link to open the
PDF at that page. This is why exact quotes and page numbers matter: they are what make a pass traceable.
