---
name: portfolio-brief
description: Read-only overview of all the user's allowlisted projects as one local HTML page — workstream state in plain language, decisions that need the user grouped across projects, work that can move without them, and risk flags. Use when the user asks to look across all projects ("看下所有项目", "portfolio brief"); for one project use advance-project.
---

# Portfolio Brief

Show the user, on one page, where every allowlisted project stands and what actually needs them. This skill reads and summarizes; it never changes a project, starts an agent, or dispatches work. The current agent performs the entire brief sequentially, without delegation. For resuming or advancing a single project, use `advance-project` in that project's existing conversation when requested; this skill does not invoke its execution workflow.

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

Git read failures remain `null` with an explanation, not zero. Backlog includes `text`, `truncated`, `total_chars`, `displayed_chars`, and `error`; truncation means coverage is incomplete. The scanner does not fetch remotes or identify active sessions. Commit age does not establish the age of uncommitted changes.

Done when every allowlisted project appears; a missing path is reported, not skipped.

## 2. Recover each project's state, briefly

Per project, read only what the scan points to:
- the current-direction part of the instruction file;
- the newest one or two state docs;
- the Backlog listing.

Aim for about six reads per project, and follow a link only when a conclusion depends on it. Process projects sequentially with the current agent. If a source is unavailable, truncated, or outside the approved scope, record the gap rather than discovering more projects or reading session history.

Apply `advance-project`'s evidence rules:
- missing records mean unknown, not undone;
- earlier completion claims are leads, not verification;
- a confirmed decision replaces the plan it supersedes;
- note the observation date wherever stale data would change a conclusion.

## 3. Write the brief JSON

Write `$TMPDIR/portfolio-brief.json`:

```json
{"projects": [{"alias": "P1",
               "workstreams": [{"name": "", "state": "", "next": "", "sources": []}], "unknowns": [""]}],
 "decisions": [{"project": "P1", "group": "", "question": "", "why_now": "", "if_wait": "",
                "sources": [{"path": "docs/decisions.md", "line": 12,
                             "source_date": null, "observed_at": "2026-10-17T12:00:00+00:00"}]}],
 "advisory": [{"project": "", "work": "", "why_no_human": ""}],
 "risks": [{"project": "", "kind": "", "detail": ""}]}
```

Rules:
- Include every scan alias exactly once. Do not copy Git counts, commit facts, domain, or observation time into project entries: the renderer joins them directly from the scan and rejects copied fact fields. Do not restate those numbers in narrative text.
- Each decision needs a real project-relative source file and line, the source's stated date (`null` if unknown), and the actual timezone-qualified observation time. Do not substitute file modification time for a decision date. Workstream source links use the same shape. The renderer checks provenance structure and file boundaries, not the truth of the agent's interpretation; compare each decision with its cited passage before delivery.
- **Plain language.** Write in the user's language. Name a workstream by what it does; if the project uses a code name, add a few words saying what it means. No unexplained jargon or internal IDs.
- **Decisions are only things the user must decide or accept.** Merge equivalent ones and give them a shared `group` (for example, several "accept on device" items). Every decision says why it matters now and what happens if it waits. Do not invent urgency.
- **Advisory work** must be startable within authorization the user has already given, with a stated reason it does not need them. It is a suggestion: never start it.
- **Risks** worth flagging:
  - work uncommitted for a long time;
  - a decision that lives only in another repository;
  - acceptance deferred repeatedly;
  - sources too stale to trust.
- Put anything you could not establish in `unknowns`.
- Before delivery, check coverage, numbers, superseded decisions, duplicates, and missing evidence. A source date, an assistant completion claim, or a passing test does not establish user acceptance. Already-running work is not a new advisory dispatch; if active execution is not visible, say so.

## 4. Render and hand off

Run `python3 -I scripts/render_brief.py "$TMPDIR/portfolio-brief.json" "$TMPDIR/portfolio-scan.json"`. It validates alias coverage, scan-derived facts, and dated decision sources before writing; Git failures and Backlog truncation also appear in the HTML. It prints the HTML path, under the system temp directory. A validation error must be corrected before delivery, not bypassed by hand-editing the HTML.

Reply with the path and at most five lines:
- how many decisions need the user;
- the most important one;
- anything flagged as a risk.

Do not act on anything in the brief unless the user asks.
