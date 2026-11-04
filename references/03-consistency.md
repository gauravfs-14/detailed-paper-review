# Phase 3: consistency

Goal: the paper agrees with itself. Every manuscript that went through several rounds of editing drifts:
one variable gets four names, a number changes in the results but not the abstract, the methods describe
one split and the results imply another. Referees check this because it is cheap for them and it signals
how carefully everything else was done.

Start from `work/consistency_auto.json` (`text_checks.py consistency`). Its counts are candidates only:
capitalized headings, sentence-initial words, and real conceptual differences cause false hits. Open the
context of every minority form before reporting it. A term used 30 times one way and once another way is
almost always a slip; a 5/4 split usually means two different concepts are being conflated, which is a
bigger finding.

## What to check, in this order (content before wording)

1. **Numbers that appear more than once.** Abstract, introduction, results prose, tables, figure captions,
   discussion, conclusion. Every repeated number (sample sizes, splits, counts, percentages, metrics) must
   be identical, at the same precision. Use `work/numbers.json`; group by what the number measures, not by
   its value.
2. **Headline counts derivable from the methods.** If the abstract says N items from M sources, the
   methods must show how N and M arise, and parts must add up (`recompute_metrics.py sum`).
3. **Methods described the same way everywhere.** Same model list, same split, same preprocessing, same
   hyperparameters, same evaluation metric, same baselines in methods, tables and discussion. A model in a
   table that is never described, or described but missing from the table, is a finding.
4. **Claims against the paper's own data.** Every superlative ("best on all metrics", "consistently",
   "significantly") checked against the table behind it. Overlapping uncertainty does not support
   "outperformed". Also check for under-claiming that throws away a real result.
5. **Internal summaries agree.** Abstract, contributions list, discussion and conclusion state the same
   findings with the same strength and the same caveats.
6. **Contrasting methodology.** Statements that cannot both be true (e.g. "labels were human-coded" in one
   place and "labels came from an LLM" in another; "stratified split" vs "temporal split").
7. **Terminology.** One name per concept, one concept per name. Model and method names spelled and
   capitalized the same way each time. Same quantity in the same unit.
8. **Statistical terms.** SD vs s.d. vs Std; SE vs SEM; confidence vs prediction interval used correctly.
9. **Style axes.** US vs UK spelling, hyphenation of compound modifiers, self-reference ("this study" vs
   "this paper"), tense in parallel lists, number formatting (thousands separators, percent spacing),
   cross-reference style (`Figure 2` vs `Fig. 2`).

Run more than one pass: fixing one axis exposes the next.

## Splitting the work

For manuscripts over about 5,000 words, run `review_tool.py plan-sections` and give each part to a
`section-auditor` agent for items 6 to 9 (local consistency), while the main agent (or one agent with the
whole paper) does items 1 to 5, which need the whole document at once. Global checks must never be split.

## Output

`phases/03-consistency.json`: `coverage` in `sections` (all sections read), one finding per inconsistency
with every location (put the main one in `location` and list the others in `evidence` as `manuscript`
entries quoting each place). In fix mode, add find/replace pairs for wording fixes; number conflicts need
the author to say which value is right unless the paper's own data decides it.
