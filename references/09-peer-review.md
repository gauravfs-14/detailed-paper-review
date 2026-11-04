# Phase 9: blind expert peer review

Goal: simulate what three or four critical, competent referees from different angles would say, so the
author hears it before the journal does. Reviewers are independent: each runs in its own subagent, sees
only the manuscript (and figures, and supplement if given), and never sees the other reviews or the
findings of phases 1 to 8. Agreement that emerges independently is strong evidence; forced agreement is
worthless.

## Set the lenses before launching anyone

Read the abstract and methods, then define 3 or 4 lenses that fit this paper. Each lens is a focus, not a
fake identity: do not invent names, institutions or careers. Typical set:

1. **Domain expert**: the paper's own field (e.g. "pedestrian safety and crash reporting"). Novelty against
   the literature the paper cites and the field's standard knowledge, importance, whether conclusions
   follow, what the field would object to.
2. **Methods and statistics expert**: design, validity, leakage, statistics, reproducibility,
   uncertainty, whether the numbers support the claims.
3. **Adjacent-field expert**: the second discipline the paper draws on (e.g. "NLP text classification" for
   an applied-NLP paper, "epidemiology" for a clinical ML paper). Whether the borrowed methods are used
   correctly and current.
4. Optional **demanding generalist / editor-minded reader**: clarity for non-specialists, framing,
   overclaiming, whether the paper's story holds together, broad interest.

Every reviewer must be critical. Being critical means finding real weaknesses with evidence from the
manuscript, not inventing problems or being harsh in tone. If a reviewer finds no major concern, it says
so plainly.

## Each reviewer assesses

- Originality: what is new, and is it distinguished from prior work in the paper itself?
- Importance: who would care and why; field-local vs broad.
- Technical soundness: which links in the evidence chain are weak; missing controls, baselines,
  validations, analyses.
- Claims vs evidence: overreach, causal language, generalization beyond the data.
- Reproducibility and transparency.
- Clarity for a non-specialist.
- Internal coverage checklist (use only where relevant): novelty, mechanism evidence, experimental design,
  statistical rigor, reproducibility, clinical validity, ethics and governance, data quality, figures and
  tables, writing clarity, claim moderation, causal vs correlational.

## Concern format

Each concern: stable ID (`R1-M1` for major, `R1-m1` for minor), severity, `blocking` (only for majors that
prevent the central claim from being established), a title, the detail (what is weak and why it matters),
an `evidence_pointer` to the real location (file:line, Table N, Figure N; write "location not given" rather
than inventing one), and `resolution` (the analysis, experiment, clarification, or claim change that would
close it). No quota: do not invent concerns to fill a list.

Reviewers judge the manuscript in front of them. They may say "the paper does not compare against X" only
by pointing to what the paper does compare against; they must not assert facts about the outside
literature from memory as if checked. If a reviewer wants to say "prior work already did this", it must
name the cited work from the manuscript's own reference list or mark it "to verify".

## Recommendation

Each reviewer ends with one of: accept, minor revision, major revision, reject, with two sentences why.

## Synthesis (main agent, after all reports are frozen)

- Consensus strengths; consensus blocking concerns; other consensus majors; where reviewers differ and why;
  the minimum set of changes that would most improve the paper's chances.
- Do not edit the individual reports after reading them together.
- Turn every blocking or consensus concern into a finding (`PR-...`) so it appears in "fix these first".

## Output

`phases/09-peer-review.json` with `reviewers`, `synthesis`, `findings` (see `output-schema.md`).
