# detailed-paper-review

An agent skill for Claude Code that audits a scientific manuscript before submission or for a revision.

It does the following:
- checks every reference against Crossref, OpenAlex, DataCite and publisher records, and downloads the cited papers;
- fact-checks every cited sentence against the source, with highlighted evidence;
- finds uncited claims, missing literature and copied text;
- checks consistency, methods, statistics, equations, acronyms, figures, tables, cross-references and editorial readiness, recomputing reported numbers with code;
- runs a blind multi-expert peer review;
- for revisions, checks the response letter and tracked changes.

It produces a dashboard, a plain-English summary and a PDF report. When source files (LaTeX, Word) are provided, it can also apply fixes, colour-marked and verified.

See [SKILL.md](SKILL.md) for the full workflow.

## Install

Install it globally (user level, in `~/.claude/skills/`) so it is available in every project, not just one.

**Quickest way:** paste this one line into Claude Code:

```text
Install the skill from https://github.com/gauravfs-14/detailed-paper-review globally: clone it into ~/.claude/skills/detailed-paper-review and run its scripts/setup_env.sh
```

**Or run this in a terminal:**

```bash
git clone https://github.com/gauravfs-14/detailed-paper-review ~/.claude/skills/detailed-paper-review && bash ~/.claude/skills/detailed-paper-review/scripts/setup_env.sh
```

`setup_env.sh` creates a private Python environment at `~/.cache/detailed-paper-review/venv` with PyMuPDF and python-docx. PDF reports also need `pandoc` and `xelatex`.

Optional: set `OPENALEX_API_KEY` or `OPENALEX_MAILTO` for faster, more reliable OpenAlex lookups.

Then ask Claude Code something like "review this paper" or "check the references in main.tex".

## Token usage

A full review is expensive, because every reference and every cited sentence is checked by a subagent.
The figures below are subagent tokens as reported by Claude Code in test runs on real papers. They
leave out the main agent's own orchestration tokens, which add more on top.

| Work | Measured cost |
|---|---|
| Reference check | 7.5k to 11k tokens per reference |
| Fact check | 16k to 21k tokens per cited sentence-citation pair |
| Blind second check | about 3k to 6k tokens per re-checked claim |
| Each other text phase (consistency, methods and statistics, equations, figures, editorial, literature, and so on) | about 100k to 170k tokens |
| Blind peer review | about 90k tokens per reviewer (3 reviewers by default) |
| Fix verification, or revision check | about 100k tokens each |

Measured totals:

| Paper | Size | Phases run | Subagent tokens |
|---|---|---|---|
| Journal paper (LaTeX) | 319 sentences, 18 references, 25 citations | all phases | 2.1M |
| Conference paper (PDF only) | 762 sentences, 53 references, 78 citations | references and fact check | 1.8M |
| Technical report (Word) | 42 references | references only | 0.33M |

A rough guide for a typical paper with about 50 references and 100 citations: **about 3M to 4.5M tokens**
for a full review. Most of that is the fact check, so cost grows with the number of citations. To
reduce it, run only the phases you need (for example, references only).

## Layout

| Folder | Contents |
|---|---|
| `SKILL.md` | Orchestrator: intake questions, the phases, fix mode, revision mode |
| `references/` | Rulebook for each phase, plus the JSON output schema |
| `agents/` | Briefs for subagents, all bound by `agents/_evidence-rules.md` |
| `scripts/` | Python tools for extraction, reference lookup, source download, checks, the dashboard and the report |
| `assets/dashboard/` | Offline dashboard template with bundled fonts and icons (licences in `vendor/LICENSES.txt`) |

See [NOTICE.md](NOTICE.md) for attribution.
