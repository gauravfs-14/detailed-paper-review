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

```bash
git clone https://github.com/gauravfs-14/detailed-paper-review ~/.claude/skills/detailed-paper-review
bash ~/.claude/skills/detailed-paper-review/scripts/setup_env.sh
```

`setup_env.sh` creates a private Python environment with PyMuPDF and python-docx at
`~/.cache/detailed-paper-review/venv`. PDF reports need `pandoc` and `xelatex`.

Optional, for faster and more reliable OpenAlex lookups: set `OPENALEX_API_KEY` or `OPENALEX_MAILTO`.

## Layout

| Folder | Contents |
|---|---|
| `SKILL.md` | Orchestrator: intake questions, the phases, fix mode, revision mode |
| `references/` | Rulebook for each phase, plus the JSON output schema |
| `agents/` | Briefs for subagents, all bound by `agents/_evidence-rules.md` |
| `scripts/` | Python tools for extraction, reference lookup, source download, checks, the dashboard and the report |
| `assets/dashboard/` | Offline dashboard template with bundled fonts and icons (licences in `vendor/LICENSES.txt`) |

See [NOTICE.md](NOTICE.md) for attribution.
