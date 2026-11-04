# Running the review from an app (`pipeline.json`)

`SKILL.md` is written for an agent such as Claude Code or Codex, which reads it and runs the review itself.
`pipeline.json` describes the same review as a list of steps, for an app that runs the review itself
(for example Lexiq Writer) and gives only the judgment tasks to a language model. Both describe one
workflow; when the workflow changes, both change (`tools/gen_pipeline.py` writes `pipeline.json`, and
`tests/test_pipeline.py` checks every file it names exists).

Nothing here changes how the skill behaves when an agent runs it from `SKILL.md`.

## Files

- `skill.json`: name, version, and the schema versions an app needs to check before using this copy:
  `pipeline_schema` (this file's format) and `results_schema` (the shape of `dashboard/data.json`).
- `pipeline.json`: the steps.
- `dashboard/data.json` in the review folder, written by `build_dashboard.py`: every verified result (the
  same data as the dashboard). Read this, not the raw `phases/*.json`: the dashboard step re-verifies every
  quote and overrides any "complete" that the files cannot prove.

## Steps

Every step has an `id` and a `kind`, and may have:

- `after`: ids of steps that must finish first. Steps whose `after` are all finished may run at the same
  time. A step with no `after` key runs after the step before it in the list.
- `when`: run only if the condition holds, otherwise the step counts as finished (skipped):
  - `revision`: `review.json` says `"submission": "revision"`;
  - `fix`: `review.json` says `"mode": "fix"` and the manuscript is an editable source;
  - `long`: `work/sections/plan.json` reports more than 5,000 words;
  - `zotero`: the user wants references filed in Zotero and `zotero_lib.py status` is ready.
- `optional`: a failure is recorded and the review continues.
- `phase`: the phase the step belongs to (for progress display). `label`: a short description.

### `script`

`run` is a script path (relative to the skill folder) and its arguments. Run it as `$PY -I <skill>/<run...>`
with the review folder as the working directory. Placeholders in `{BRACES}` are filled in (below). A nested
list is an optional group: it is left out when any placeholder in it is empty. A non-zero exit code is a
failure (unless `optional`).

### `agent` and `agents`

One model task (`agent`), or one per task in a plan file (`agents`). The prompt is, in this order:

1. the text of `agents/_evidence-rules.md` (`evidence_rules`), unchanged;
2. the text of `brief`, with `<skill>` replaced by the skill folder and `$RV` by the review folder;
3. "Rulebook: <rulebook path>" when there is a `rulebook`, and the folders and files in `reads` as hints;
4. `task`, with placeholders filled in.

`plan` names a plan file written by an earlier script step: `{"tasks": [{"id", "input", "output", ...}]}`.
Run one task per entry (in parallel where possible); every key of the entry is a placeholder for that
task (`{id}`, `{input}`, `{output}`, `{keys}`, `{lens}`). A plan with no tasks means nothing to do.

`outputs` lists the files the task must write, and `may_write` files it may also write (relative to the
review folder, placeholders filled); it writes nothing else. After the task, every file in `outputs` must
exist and be valid JSON; otherwise retry the task once, then fail it. `{output}` in a `task` is the first
entry of `outputs`.

`tools` says what the model needs:

- `read`: read and search files in the review folder, the skill folder and the manuscript's folder;
- `write`: write the files in `outputs`;
- `scripts`: run the skill's own scripts (`$PY -I <skill>/scripts/<name>.py ...`, e.g. `recompute_metrics.py`,
  `fetch_sources.py --add`, `lit_search.py`, `render_pages.py`) and short Python commands for calculations;
- `web`: fetch public web pages (and search, where the host can).

`isolated`: the task must not see other phases' results (`phases/`, `work/` other than its own input):
the blind reviewers and the independent second checker. `vision`: the task looks at images (figures,
rendered pages); a host without image input tells the model so, and the phase reports figures as
"not inspected".

## Placeholders

From the host: `{SKILL}` (skill folder), `{RV}` (review folder), `{PY}` (Python with the packages
`setup_env.sh` installs). From `review.json` `inputs`, as absolute paths (empty when not given):
`{MANUSCRIPT}`, `{BIB}`, `{PDF}`, `{LOCAL_PDFS}`, `{SOURCE_DIR}` (the folder of the manuscript),
`{RESPONSE}`, `{PREVIOUS}`, `{ANNOTATED}`, `{COMMENTS}` (from `inputs.revision`).

## Settings a host can pass (environment)

All are optional; without them the skill behaves exactly as when an agent runs it.

| Variable | Effect |
|---|---|
| `DPR_CONFIG_DIR`, `DPR_CACHE_DIR` | where settings and the registry cache live (default `~/.config/` and `~/.cache/detailed-paper-review`) |
| `DPR_VENV` | where `setup_env.sh` creates the Python environment |
| `DPR_MAILTO`, `OPENALEX_API_KEY`, `SEMANTIC_SCHOLAR_API_KEY` | contact email and keys, instead of the config file and keychain |
| `DPR_ZOTERO_COLLECTION` | the Zotero collection to file papers in (default: config `zotero_collection`, else "Detailed Paper Review") |
| `DPR_ZOTERO_EXISTING=link` | for papers the library already has, only record which item it is: no collection, tag or field change |
| `DPR_ZOTERO=on` / `off` | the app decided whether this review files papers: `off` never writes (including the automatic sync after `fetch_sources.py` and `build_dashboard.py`); `on` syncs even if this copy's setup skipped Zotero |
| `ZOTERO_LOCAL_API_KEY` with `DPR_ZOTERO_KEYCHAIN=0` | use the host's own Zotero key, and never read or store one in the keychain |

`zotero_lib.py` takes a lock in the cache folder (`zotero-write.lock`, a directory) while it looks a paper up
and creates it. A host that also files papers in Zotero should take the same lock (create the directory;
remove it when done; treat one older than two minutes as stale), so the same paper is never created twice.
