# Phase 3b: every headline claim mapped to its evidence

Goal: each claim the paper wants readers to remember (abstract, contributions, discussion, conclusion,
and any "first / best / significant / outperforms / demonstrates" statement) points to the result that
supports it, and says no more than that result shows. This is the clearest test of overclaiming.

Input: `work/claimmap_auto.json` (`claim_tools.py claims`), the candidate claims. Also read the abstract,
introduction contributions and conclusion in full yourself: add any claim the script missed.
`coverage.total` is at least the number of candidates.

## For each claim

1. Split it into atomic claims (one finding, one number, one comparison each).
2. Find the evidence **in this paper**: the table cell, figure panel, analysis or computation. Quote it with
   its location. For a number, recompute it from the table or data with code and record the command.
3. Decide:

| Verdict | Meaning | Severity |
|---|---|---|
| `supported` | The evidence shows exactly this, at this strength and scope. | none |
| `overstated` | Evidence shows something weaker or narrower: "outperforms" from one run with no test, "demonstrates" from association, "generalises" from one dataset, a number rounded in the claim's favour. | major for abstract/conclusion, minor elsewhere |
| `unsupported` | No result in the paper shows it (and no citation carries it). | critical in abstract/conclusion, major elsewhere |
| `contradicted` | The paper's own results say otherwise. | critical |
| `understated` | The paper undersells a real result (report as info, it is useful to the author). | info |
| `cited_support` | The claim rests on a citation, checked in phase 2. Give the item id. | as phase 2 |

4. Check the claims agree with each other: abstract vs conclusion vs contributions list.

Propose a rewrite for every overstated claim that matches what the evidence shows.

## Output

`phases/03b-claim-map.json`: `coverage.unit = "headline claims"`, items
`{"claim", "line", "atoms": [...], "evidence": "Table 3, RoBERTa macro-F1 0.8239", "command": "...", "verdict"}`,
findings for overstated, unsupported and contradicted claims (with `issue_key`).
