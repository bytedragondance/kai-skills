---
name: portfolio-brief
description: Read-only overview of all the user's allowlisted projects as one local HTML page — workstream state in plain language, decisions that need the user grouped across projects, work that can move without them, and risk flags. Use when the user asks to look across all projects ("看下所有项目", "portfolio brief"); for one project use advance-project.
---

# Portfolio Brief

Show the user, on one page, where every allowlisted project stands and what actually needs them. This skill reads and summarizes; it never changes a project, starts an agent, or dispatches work. For resuming or advancing a single project, use `advance-project`.

Run the scripts from this skill's directory: `python3 -I scripts/<name>.py`.

## Allowlist

Projects come only from `~/.config/portfolio-brief/projects.json`:

```json
{"projects": [{"alias": "P1", "domain": "dev", "path": "~/personal/example"}]}
```

Read nothing outside these paths. If the file is missing, stop and ask the user which projects to include. Do not discover projects yourself. Never read Claude Code or Codex session history unless the user asks for it in this conversation.

## 1. Scan

Run `python3 -I scripts/portfolio_scan.py > "$TMPDIR/portfolio-scan.json"`. It is read-only and records, for each project:
- the Git state: branch, last commit, uncommitted counts, ahead/behind;
- the instruction files present;
- the most recently changed status, plan and decision docs;
- the Backlog.md listing, when the project has one.

Done when every allowlisted project appears; a missing path is reported, not skipped.

## 2. Recover each project's state, briefly

Per project, read only what the scan points to:
- the current-direction part of the instruction file;
- the newest one or two state docs;
- the Backlog listing.

Aim for about six reads per project, and follow a link only when a conclusion depends on it. With many projects, one read-only sub-agent per project is fine; give each the same budget and this section's rules.

Apply `advance-project`'s evidence rules:
- missing records mean unknown, not undone;
- earlier completion claims are leads, not verification;
- a confirmed decision replaces the plan it supersedes;
- note the observation date wherever stale data would change a conclusion.

## 3. Write the brief JSON

Write `$TMPDIR/portfolio-brief.json`:

```json
{"generated_at": "...",
 "projects": [{"alias": "", "domain": "", "last_commit": "", "uncommitted": "", "observed_at": "",
               "workstreams": [{"name": "", "state": "", "next": ""}], "unknowns": [""]}],
 "decisions": [{"project": "", "group": "", "question": "", "why_now": "", "if_wait": ""}],
 "advisory": [{"project": "", "work": "", "why_no_human": ""}],
 "risks": [{"project": "", "kind": "", "detail": ""}]}
```

Rules:
- **Plain language.** Write in the user's language. Name a workstream by what it does; if the project uses a code name, add a few words saying what it means. No unexplained jargon or internal IDs.
- **Decisions are only things the user must decide or accept.** Merge equivalent ones and give them a shared `group` (for example, several "accept on device" items). Every decision says why it matters now and what happens if it waits. Do not invent urgency.
- **Advisory work** must be startable within authorization the user has already given, with a stated reason it does not need them. It is a suggestion: never start it.
- **Risks** worth flagging:
  - work uncommitted for a long time;
  - a decision that lives only in another repository;
  - acceptance deferred repeatedly;
  - sources too stale to trust.
- Put anything you could not establish in `unknowns`.

## 4. Render and hand off

Run `python3 -I scripts/render_brief.py "$TMPDIR/portfolio-brief.json"`. It prints the HTML path, under the system temp directory.

Reply with the path and at most five lines:
- how many decisions need the user;
- the most important one;
- anything flagged as a risk.

Do not act on anything in the brief unless the user asks.
