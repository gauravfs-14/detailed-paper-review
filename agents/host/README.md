# Briefs for host apps

When the skill runs in Claude Code or Codex, the main agent does these tasks itself, as `SKILL.md`
describes. An app that drives the review step by step from `pipeline.json` (for example Lexiq Writer) has
no main agent, so it gives each of these tasks to a model as its own brief. Agents running the skill
normally do not need this folder.

Every brief starts with `agents/_evidence-rules.md`, like every other brief.
