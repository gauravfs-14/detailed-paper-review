# detailed-paper-review

An agent skill for Claude Code and Codex that audits a scientific manuscript before submission or for a revision.

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

Install it globally, so it is available in every project. One copy serves both agents: Codex reads skills
from `~/.agents/skills/`, and a symlink makes the same copy visible to Claude Code in `~/.claude/skills/`.

**Quickest way:** paste this one line into Claude Code or Codex:

```text
Install the skill from https://github.com/gauravfs-14/detailed-paper-review globally: clone it into ~/.agents/skills/detailed-paper-review, symlink it to ~/.claude/skills/detailed-paper-review, and run its scripts/setup_env.sh
```

**Or run this in a terminal:**

```bash
mkdir -p ~/.agents/skills ~/.claude/skills && git clone https://github.com/gauravfs-14/detailed-paper-review ~/.agents/skills/detailed-paper-review && ln -sfn ~/.agents/skills/detailed-paper-review ~/.claude/skills/detailed-paper-review && bash ~/.agents/skills/detailed-paper-review/scripts/setup_env.sh
```

`setup_env.sh` creates a private Python environment at `~/.cache/detailed-paper-review/venv` with PyMuPDF
and python-docx. It needs network access the first time. PDF reports also need `pandoc` and `xelatex`.

### Recommended setup

These are optional, but they make reviews faster and avoid repeated downloads.

**Contact email.** Crossref and OpenAlex give faster limits to requests that include one:

```bash
~/.cache/detailed-paper-review/venv/bin/python ~/.agents/skills/detailed-paper-review/scripts/configure.py set-email you@example.org
```

**OpenAlex API key.** Free; about 3 times faster, with 10 times the daily budget. Create an account at
https://openalex.org/signup and copy your key from https://openalex.org/settings/api-key. Then run this in
your own terminal. It asks for the key and stores it in the macOS Keychain (or the Linux secret service),
never in a file:

```bash
~/.cache/detailed-paper-review/venv/bin/python ~/.agents/skills/detailed-paper-review/scripts/configure.py openalex-key
```

The agent will not create the account for you. Check your settings at any time with `configure.py status`.

**Zotero as the paper library.** With the Zotero desktop app (version 7 or later) open, and its local API
turned on (Zotero Settings > Advanced > "Allow other applications on this computer to communicate with
Zotero"), the skill:

- looks in your library before downloading a paper, and reuses the PDF you already have;
- files each review's verified references in a "Detailed Paper Review" collection, which it creates itself
  the first time;
- never duplicates or edits papers you already have, and never touches other collections;
- fills metadata from the verified registry record, attaches the saved PDF, sets the citation key, and adds
  the tags `dpr:<review>`, `dpr:verified` or `dpr:needs-check`, and `dpr:fulltext`.

No Zotero API key is needed: it works through the desktop app, like the browser connector.

### Requests and caching

Each service is rate-limited separately, below its published limits:
- Crossref: 5 per second without a contact email, 10 with one;
- OpenAlex: 10 per second without a key, 30 with one;
- Semantic Scholar: about 1 per second;
- arXiv: 1 every 3 seconds.

Retry-After and Backoff headers are respected. Registry answers are cached for 30 days in
`~/.cache/detailed-paper-review/http-cache.sqlite`, so a rerun or a later review does not look up the same
paper again.

## Use

Ask something like "review this paper" or "check the references in main.tex". In Codex you can also call it
by name with `$detailed-paper-review`.

The review needs network access for reference lookups and downloads. Before starting, the skill runs
`scripts/preflight.py`. If the agent's sandbox blocks the network, preflight stops the review and says how to
fix it, so no reference is ever reported as checked when it was not.

- **Claude Code:** approve the commands when the permission prompt appears.
- **Codex:** the default workspace sandbox blocks the network. Start Codex with network allowed in the sandbox:

  ```bash
  codex -s workspace-write -c sandbox_workspace_write.network_access=true
  ```

  Or approve each command when Codex asks to run it outside the sandbox. Subagents, which the fact check and
  peer review use, are on by default in current Codex releases.

## Token usage

A full review is expensive, because every reference and every cited sentence is checked by a subagent.
The figures below are subagent tokens as reported by Claude Code in test runs on real papers (Codex usage
has not been measured yet). They
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
