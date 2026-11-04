---
name: detailed-paper-review
description: >-
  Full audit of a scientific manuscript before submission or for a revision: verifies every reference
  and downloads the cited papers, fact-checks every cited sentence against the source with highlighted
  evidence, finds uncited claims, missing literature and copied text, maps headline claims to evidence,
  checks consistency, methods, statistics and equations (recomputing numbers with code), missing metrics,
  acronyms, figures, tables, cross-references and editorial readiness, runs a blind multi-expert peer
  review, and for revisions checks the response letter and tracked changes against the manuscript.
  Produces a dashboard, plain-English summary and PDF report, plus verified colour-marked fixes when
  source files are given. Use whenever the user wants a paper, manuscript, thesis chapter, submission or
  revision reviewed, audited, fact-checked or reference-checked, a response to reviewers checked, or asks
  "is this paper ready", even if they name only one of these checks.
---

# Detailed paper review

You are running a full audit of a manuscript before it goes to a journal. The user wants the truth about
their paper, in plain English, with nothing hidden, nothing invented and nothing left unchecked.

Three rules matter more than anything else, for you and for every agent you start:

1. **Memory is not evidence.** Something is true only if the manuscript, a saved source file, a
   registry/publisher/agency page fetched in this session, or the output of code run on the paper's own
   numbers or data says so explicitly. Your training data is a hint about where to look, never a verdict.
   If nothing says it, the answer is "cannot verify". Every subagent prompt starts with
   `agents/_evidence-rules.md`, pasted unchanged.
2. **Every calculation is done by code.** Sums, percentages, differences, metrics, p-values, intervals,
   word counts: `scripts/recompute_metrics.py` or a short Python command, with the command and its output
   recorded as evidence. A computed number that did not come from code is not reported.
3. **Nothing is called done until the files prove it, and nothing is left unchecked.** `review_tool.py
   coverage` and `build_dashboard.py` compute coverage from the outputs and override any "complete" an
   agent claims without proof. Every unit (reference, citation, sentence, number, display, checklist item,
   reviewer comment) gets a verdict. What truly cannot be checked is listed with the reason; it never
   disappears silently.

While reading the paper for any phase, you and every agent also notice **stray text**: anything that would
not appear in the finished paper, such as AI-chat replies, revision or version notes, response-letter
wording, placeholders or notes to co-authors (rule 8 in `agents/_evidence-rules.md`). This is judgment, not
a phrase list, and not an extra pass.

## Setup

```bash
SK=<this skill's directory>
eval "$(bash $SK/scripts/setup_env.sh)"        # sets $PY (private venv with PyMuPDF, python-docx)
$PY -I $SK/scripts/preflight.py                 # network, packages, write access, report tools
```

Preflight also reports the contact email, the OpenAlex key and Zotero. Act on its notes before starting:

- **No OpenAlex key:** tell the user it is optional but makes lookups about 3 times faster with 10 times the
  daily budget. You must not create the account for them (not even through OpenAlex's agent sign-up). They
  sign up at https://openalex.org/signup, copy the key from https://openalex.org/settings/api-key, and run
  `$PY $SK/scripts/configure.py openalex-key` in their own terminal, which stores it in the system
  keychain. Never ask them to paste a key into the chat, and never write one into a file.
- **No contact email:** ask which email to send to Crossref and OpenAlex, then
  `$PY $SK/scripts/configure.py set-email <email>`.
- **Zotero not ready:** the skill uses the Zotero desktop app as its paper library (`scripts/zotero_lib.py`).
  Reading needs Zotero 7+ with the local API on; filing and cleaning papers needs Zotero 10+. Ask the user
  to do what preflight lists (install or update Zotero, open it, turn on the local API). On the first write
  Zotero shows an access dialog; tell the user to click "Always Allow". If they would rather not use Zotero,
  continue without it.

Registry answers are cached on disk (`~/.cache/detailed-paper-review/http-cache.sqlite`, 30 days) and every
request is rate-limited per service, so reruns and later reviews do not repeat lookups.

Do not start until preflight prints `READY`. If it prints `NOT READY`, follow its instructions (usually the
agent's sandbox is blocking the network) and rerun it. Never run the reference or literature phases offline:
the scripts stop on purpose rather than record lookups that never happened.

### Running under different agents

This skill works in Claude Code, Codex and other agents that read `SKILL.md`. The workflow is identical;
only the names of a few host tools differ.

| Need | Claude Code | Codex | No such tool |
|---|---|---|---|
| Start a subagent with a brief | Agent tool | spawn a subagent (`spawn_agent`), then wait for it (`wait_agent`) | do the brief yourself, one batch at a time (see below) |
| Look at a PNG (figures, rendered pages) | Read tool on the file | `view_image` | report figures as "not inspected" |
| Web search / open a page | WebSearch, WebFetch | web search tool, or `curl` from the shell | `curl` from the shell |
| Network for scripts | approve the permission prompt | approve running the command outside the sandbox, or start Codex with `-s workspace-write -c sandbox_workspace_write.network_access=true` | normal terminal |

Subagents: start them in parallel up to the host's limit (Codex caps concurrent subagents with
`agents.max_concurrent_threads_per_session`; launch the rest as earlier ones finish) and wait for all of them
before merging. Every brief starts with `agents/_evidence-rules.md`, whatever the host.
If the host cannot start subagents, run each brief yourself in turn, with the same inputs and the same output
file, and do not shorten it: the coverage checks are the same, so a skipped batch shows as "not finished".

Run Python scripts as `$PY -I $SK/scripts/<script>.py ...` (`-I` keeps downloaded files from being imported
as code). All output goes to `paper-review/<paper-name>/` in the current working directory (`$RV`). The
user's original files are never modified.

## Intake: ask before starting

Ask in one message, and wait for the answers. Skip anything the user already said. Then list what is still
missing and needed, say what each missing item would let you check, and continue only with what you have
(recording each gap so it appears under "could not check").

1. **Which journal or venue** will it go to, and what **article type** (research article, short paper,
   review, letter, conference paper)? This sets length, abstract format, figure rules, reference style and
   required statements. If they do not know, review against general practice and say so.
2. **Is this a first submission or a revision?** If a revision: which round, and please provide
   - the **revised manuscript** (source preferred, PDF accepted),
   - the **annotated / tracked-changes version** (latexdiff PDF, Word with track changes, or highlighted PDF),
   - the **response to reviewers** document,
   - the **reviewer and editor comments** (decision letter), if they are not quoted in full in the response,
   - optionally the **previous version** submitted, so changes can be checked against it.
3. **Review only, or review and fix?** Fixing needs the editable source (.tex/.bib, .docx, .md). If only a
   PDF was given, say plainly that it can be reviewed but not fixed.
4. **Source files**: main file, bibliography, figures, supplementary material.
5. **Data and code**, if they want results recomputed beyond what the paper's own numbers allow.
6. **PDFs of cited papers** they already have (paywalled ones especially). Used before any download.
7. **Anything specific**: blind review (anonymization), word or page limit from the call, reporting
   guideline they must follow (CONSORT, PRISMA, TRIPOD+AI...), sections not to touch.

Write the answers to `$RV/review.json`:

```json
{"journal": "Transportation Research Record", "article_type": "research article",
 "submission": "first", "round": null, "mode": "review", "blind_review": false,
 "inputs": {"manuscript": "main.tex", "bib": "references.bib", "pdf": "main.pdf", "figures": ["figure1.png"],
            "supplement": null, "data": null, "code": null, "local_pdfs": null,
            "revision": {"annotated": null, "response": null, "comments": null, "previous": null}},
 "missing": ["data and code: results can only be checked against the paper's own numbers"]}
```

Then extract the manuscript and run the mechanical first passes:

```bash
$PY -I $SK/scripts/extract_manuscript.py <main.tex|paper.docx|paper.md|paper.pdf> --out $RV
$PY -I $SK/scripts/text_checks.py all --review $RV
$PY -I $SK/scripts/claim_tools.py all --review $RV
```

The printed counts (sections, sentences, citing sentences, references, displays) are the denominators for
coverage. For PDF input, confirm the section list and reference count against the PDF itself.

## The phases

Phases 1 and 2 come first: everything later assumes the citations are real and the cited claims are true.
The other phases can run in parallel after that (independent agents, started together). After
**every** phase run `build_dashboard.py`, so the dashboard always shows the current truth.

| # | Phase | Rulebook (read before starting it) | Agent brief |
|---|---|---|---|
| 1 | Reference check + source download | `references/01-references.md` | `agents/ref-checker.md` |
| 2 | Fact check of every cited sentence | `references/02-fact-check.md` | `agents/fact-checker.md`, `agents/second-checker.md` |
| 2b | Uncited factual claims | `references/02b-uncited-claims.md` | `agents/phase-auditor.md` |
| 2c | Literature coverage and recency | `references/02c-literature.md` | `agents/phase-auditor.md` |
| 2d | Text copied from sources | `references/02d-text-overlap.md` | `agents/phase-auditor.md` |
| 3 | Consistency | `references/03-consistency.md` | `agents/phase-auditor.md`, `agents/section-auditor.md` |
| 3b | Claim-to-evidence map | `references/03b-claim-map.md` | `agents/phase-auditor.md` |
| 4 | Methods, statistics, every number | `references/04-methods-stats.md` | `agents/phase-auditor.md` |
| 4b | Missing critical reporting | `references/04b-missing-reporting.md` | `agents/phase-auditor.md` |
| 4c | Equations | `references/04c-equations.md` | `agents/phase-auditor.md` |
| 5 | Acronyms | `references/05-acronyms.md` | `agents/phase-auditor.md`, `agents/section-auditor.md` |
| 6 | Figures and tables | `references/06-figures-tables.md` | `agents/phase-auditor.md` |
| 7 | Cross-references | `references/07-crossrefs.md` | `agents/phase-auditor.md` |
| 8 | Editorial check | `references/08-editorial.md` | `agents/phase-auditor.md`, `agents/section-auditor.md` |
| 9 | Blind expert peer review | `references/09-peer-review.md` | `agents/reviewer.md` |
| R | Revision check (revisions only) | `references/11-revision.md` | `agents/phase-auditor.md` |
| fix | Fix mode, post-fix verification, re-review | see below | `agents/fix-verifier.md` |
| 10 | Plain-English summary | `references/10-final-report.md` | (main agent) |
| 11 | PDF report | `build_report.py` | |

Every phase writes `$RV/phases/<id>.json` in the shape in `references/output-schema.md` (read it once
first). Phase ids: `01-references`, `02-factcheck`, `02b-uncited-claims`, `02c-literature`,
`02d-text-overlap`, `03-consistency`, `03b-claim-map`, `04-methods-stats`, `04b-missing-reporting`,
`04c-equations`, `05-acronyms`, `06-figures-tables`, `07-crossrefs`, `08-editorial`, `09-peer-review`,
`R-revision`. A phase is `skipped` only when it does not apply (R for a first submission) or the user said
so, with the reason written in `status_reason`. The dashboard and PDF are generated from these files, so
no phase writes HTML or report prose.

Every agent prompt contains: the text of `agents/_evidence-rules.md`, the brief, the rulebook path, the
exact input and output paths, and the Python path. Split large work into more agents, never into less care:
an agent must be able to read every word of every item it is given.

### Phase 1: references (strict)

```bash
$PY -I $SK/scripts/verify_refs.py --review $RV
$PY -I $SK/scripts/fetch_sources.py --review $RV [--local-pdfs DIR]
```

The scripts gather registry records; they do not decide. Give groups of 10 to 15 references to
`ref-checker` agents (in parallel). Each writes `work/refs/<group>.json` with a verdict for every key and
tries to find legal full text for abstract-only entries (`fetch_sources.py --add key=url`). Then
`review_tool.py merge-refs`, and add list-level findings (missing, uncited, duplicate, retracted, style)
with IDs starting `REF-L`. `sources/TO_DOWNLOAD.md` lists papers the user should download by hand, with the
claims that depend on each; it goes into the summary.

`fetch_sources.py` looks in the user's Zotero library before downloading anything. After `merge-refs`, file
the references in Zotero when it is ready:

```bash
$PY -I $SK/scripts/zotero_lib.py push --review $RV --dry-run   # every planned addition and field change
$PY -I $SK/scripts/zotero_lib.py push --review $RV
```

Each confirmed reference is found in the library (or created), added to the "Detailed Paper Review"
collection (created if missing) and tagged `dpr:<review>`. Its metadata is cleaned from the verified record
(Crossref citation data for DOIs, or the `metadata` the ref-checker confirmed), with authors' full given
names from ORCID or OpenAlex where they exist; citation styles can shorten full names but cannot expand
initials. Empty fields are filled; a filled field changes only when it is substantively wrong. Missing PDFs
are attached. References known only from the paper's own text are not filed. Every change is logged with its
old value (`zotero.json`); `zotero_lib.py undo --review $RV` restores them. `zotero_lib.py clean` applies the
same cleaning to everything in the collection, and `tidy` reports duplicates, missing fields and initials
that no source could expand. Tell the user the counts from `zotero.json`.

### Phase 2: fact check (strict)

Run after phase 1 (it may add full texts). `review_tool.py plan-factcheck`, then one `fact-checker` agent
**per batch**, all at once; never merge batches. `review_tool.py merge-factcheck`. Every non-supported item
and a sample of at least 10% (minimum 3) of supported items go to a `second-checker` that does not see the
first verdict (each writes `work/factcheck/second-<x>.json`); run `review_tool.py attach-second`, record a
decision (`second_check.adjudication`) for every disagreement, and merge again. When the two disagree, decide using
the rulebook and record the decision. `build_dashboard.py` re-verifies every quote against the saved text
and downgrades any "supported" verdict whose quote is not in the source; redo those until coverage is full.

### Phases 2b to 9

Read each rulebook and run it with a `phase-auditor` agent (or several, split by section with
`review_tool.py plan-sections` for long papers). The candidate files from `claim_tools.py`,
`text_checks.py` and `lit_search.py` are hints; agents confirm each one and look for what they missed.
Peer reviewers (phase 9) see only the manuscript, never other findings. Each writes `work/review/R<n>.json`;
`review_tool.py merge-review`, then write the synthesis and `PR-` findings.

### Phase R: revisions (only when this is a revision)

```bash
$PY -I $SK/scripts/revision_tool.py --review $RV --revised <revised main file> \
    [--previous <previous main file>] [--annotated <latexdiff .tex|tracked .docx|marked .pdf>] \
    --response <response letter .docx|.md|.tex|.pdf> [--comments <decision letter>]
```

All other phases run on the **revised** manuscript as usual. Phase R then checks that every reviewer
comment has a response, every change the response claims is really in the revised manuscript at the place
it says, quotes in the response match the manuscript word for word, the annotated version marks every
real change (and only real changes), and no substantive change is missing from the response.

### Phases 10 and 11: tell the user

```bash
$PY -I $SK/scripts/review_tool.py dedupe --review $RV      # merge the same problem found by several phases
```

Check the proposed groups in `phases/_issues.json`, then write `phases/00-summary.json`
(`references/10-final-report.md`) and:

```bash
$PY -I $SK/scripts/build_dashboard.py --review $RV
$PY -I $SK/scripts/review_tool.py coverage --review $RV
$PY -I $SK/scripts/build_report.py --review $RV
open $RV/dashboard/index.html
```

The chat answer is short, plain English, worst problems first, with every incomplete or skipped phase
named, the could-not-check list, the papers to download, and links to the dashboard and the PDF.

### Fix mode (editable source only, only if the user asked)

1. Collect fixes as exact find/replace pairs in `$RV/fixes.json` (shape and LaTeX escaping rules in
   `output-schema.md`). Fix only what the evidence supports: registry fields, wording the source supports,
   numbers recomputed by code. Things needing the author's data or judgment are reported, not "fixed".
2. Apply: `apply_fixes.py --review $RV --source-dir <source folder>` writes `corrected-by-agent/marked/`
   (insertions blue, removals red) and `clean/`.
3. Verify, every time: `verify_fixes.py --review $RV --source-dir <same>` (only intended changes, marked
   equals clean, both compile with nothing new broken, no citation lost, LaTeX escaping, references
   re-verified, no new acronym or cross-reference issue), then a `fix-verifier` agent, then
   `verify_fixes.py ... --finalize`. If anything fails, correct `fixes.json` and repeat 2 and 3.
4. **Re-review the fixed paper.** Run the whole review again on `corrected-by-agent/clean/` into
   `$RV/after/` (every phase, same rules), then
   `$PY -I $SK/scripts/compare_reviews.py --before $RV --after $RV/after` to list what was resolved,
   what is still open, and anything new. Report only fixes that are `verified` and resolved.

## Files in this skill

- `scripts/` (run any with `--help`): `extract_manuscript.py`, `verify_refs.py`, `fetch_sources.py`,
  `review_tool.py`, `text_checks.py`, `claim_tools.py`, `lit_search.py`, `recompute_metrics.py`,
  `render_pages.py`, `revision_tool.py`, `apply_fixes.py`, `verify_fixes.py`, `compare_reviews.py`,
  `build_dashboard.py`, `build_report.py`, `setup_env.sh`
- `references/`: one rulebook per phase plus `output-schema.md`. Load only the one you are running.
- `agents/`: `_evidence-rules.md` (in every prompt) and the briefs.
- `assets/dashboard/index.html`: dashboard template, filled by `build_dashboard.py`. Do not rewrite it.
