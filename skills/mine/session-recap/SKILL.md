---
name: session-recap
description: Reconstruct one work-day from AI coding-session history and optionally backfill a daily note. Type its name to run it.
argument-hint: "[YYYY-MM-DD] [optional daily-note path]"
disable-model-invocation: true
---

# Session Recap

Reconstruct what happened during one **work-day** from Cursor, Claude Code,
Trae CLI, Codex CLI, and optionally TMates. The defining constraint is
**coverage before conclusions**: a silent or unavailable source is not evidence
that no work happened.

The work-day boundary is 04:00 local time by default, so activity between
midnight and 03:59 belongs to the previous date.

This skill is an evidence adapter, not a session database or task tracker. Keep
projects, issues, and todos in their existing source of truth; a future session
manager may index and link them, but this skill must not maintain a second copy
of their lifecycle state.

## Prerequisites

- Python 3.9 or newer for the bundled extractor.
- `bytedcli` authentication only when TMates coverage is requested.
- An exact note path when the user wants a note updated. Recap-only runs do not
  write files.

## Process

### 1. Set the scope

Use the date supplied by the user. If no date is supplied, use the previous
work-day, calculated with the same 04:00 boundary as the extractor.

Treat a note path as optional. Do not guess a vault location or search broadly
for a writable note when the user asked only for a recap.

### 2. Extract the evidence

Run the bundled script:

```bash
python3 "<skill-dir>/scripts/extract_sessions.py" [YYYY-MM-DD]
```

`<skill-dir>` is the directory containing this `SKILL.md`.

The local sources are read automatically. TMates is intentionally opt-in
because managed-agent IDs are user-specific:

```bash
python3 "<skill-dir>/scripts/extract_sessions.py" 2026-07-27 \
  --tmates-agent 531
```

Use `--tmates-run <run-id>` to pin a known run and `--note <path>` to harvest
run IDs mentioned in an existing note. Multiple IDs may be comma-separated or
the option may be repeated.

Environment equivalents:

- `SESSION_RECAP_TMATES_AGENTS`
- `SESSION_RECAP_TMATES_RUNS`
- `SESSION_RECAP_TMATES_SITE` (default: `i18n-tt`)
- `SESSION_RECAP_DAY_START_HOUR` (default: `4`)
- `SESSION_RECAP_CURSOR_DB`
- `SESSION_RECAP_CLAUDE_ROOT`
- `SESSION_RECAP_TRAE_ROOT`
- `SESSION_RECAP_CODEX_ROOT`

The extractor prints Markdown to stdout and does not modify the source
histories or the target note. A configured TMates source that cannot be read is
a coverage failure: the script exits with status `2`. Fix the source or label
the recap incomplete; never turn that failure into "no cloud work."

TMates runs already carry platform identifiers such as run, project, space, and
branch. Preserve those identifiers when a downstream tool imports the recap.
Attach external work through typed references such as an issue URL or todo path;
do not infer an issue from prompt wording and write that guess back.

### 3. Sweep evidence before reading the plan

Read every session block once and collect candidate outcomes before mapping
them to planned tasks. Short sessions can contain a shipped fix while a long
session contains only exploration.

Ignore obvious meta-work such as a workflow whose sole purpose was generating
the recap itself. Keep new milestones on continuing threads: implementation,
verification, review, merge, deployment, and publication are distinct outcomes
when they occurred on different days.

### 4. Verify outcomes

Local extracts contain user turns, which establish intent and activity but
usually not completion. A prompt such as "merge this" is not evidence that a
merge happened.

Verify candidate outcomes against the cheapest authoritative artifact
available:

- Git history and working-tree state for code changes.
- Test or build results for verification claims.
- MR/PR state for review and merge claims.
- Generated files or published records for reports and documents.
- TMates agent replies when they state an outcome clearly.

If the artifact is unavailable, mark the outcome `unverified` and ask the user.
Offline meetings and manual work may have no session trace, so absence from the
extract is not proof they did not happen.

### 5. Report the recap

Use the user's language and keep evidence separate from conclusions:

```markdown
## Coverage
- Cursor: complete / unavailable / no activity
- Claude Code: complete / unavailable / no activity
- Trae CLI: complete / unavailable / no activity
- Codex CLI: complete / unavailable / no activity
- TMates: complete / not configured / incomplete

## Outcomes
| Time | Thread | Evidence | Outcome | Confidence |
| --- | --- | --- | --- | --- |
| HH:MM | ... | ... | ... | verified / partial / unverified |

## Follow-ups
- ...
```

Mention a source in an outcome only when it contributed evidence. Preserve
uncertainty instead of filling gaps with plausible prose.

### 6. Backfill only when requested

When the user asked to update a daily note:

1. Read the exact target note and preserve its structure and language.
2. Map verified outcomes to existing tasks by topic, not exact wording.
3. Mark a task complete only for a verified delivered outcome.
4. Record partial or unverified work explicitly; do not silently downgrade or
   omit it.
5. Add unplanned delivered work as an additional completed item.
6. Append a compact source/coverage note.
7. Preserve unrelated content and make the smallest possible edit.

If completion remains ambiguous, show the proposed change and ask before
writing it.

## Done When

- Every requested source is classified as complete, unavailable, not
  configured, or no activity.
- Every claimed outcome points to evidence stronger than user intent alone.
- Uncertainty and offline blind spots are visible.
- No note was modified unless the user requested a backfill.
