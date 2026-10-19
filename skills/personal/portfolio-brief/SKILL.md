---
name: portfolio-brief
description: Use Attune to report across the user's allowlisted projects when asked "用 Attune 汇报项目", "看下所有项目", or "portfolio brief". Deliver a complete source-dated report and local HTML, separating actual decisions, natural-use feedback and parked work. For one project's execution use advance-project.
---

# Portfolio Brief

Show the user, on one page, where every allowlisted project stands and what actually needs them. This skill reads and summarizes; it never changes a project, starts an agent, or dispatches work. The current agent performs the entire brief sequentially, without delegation. For resuming or advancing a single project, use `advance-project` in that project's existing conversation when requested; this skill does not invoke its execution workflow.

The user-facing entry is **“用 Attune 汇报我的项目”**. The current executor handles the tools and source reading; the user does not prepare JSON, repeat project context, or run these commands. This is an on-demand report, not a recurring trial or scheduler.

Run the scripts from this skill's directory: `python3 -I scripts/<name>.py`.

## Allowlist

Projects come only from `~/.config/portfolio-brief/projects.json`:

```json
{"projects": [{"alias": "P1", "domain": "dev", "path": "~/personal/example"}]}
```

Read nothing outside these paths. If the file is missing, stop and ask the user which projects to include. Do not discover projects yourself. Never read Claude Code or Codex session history unless the user asks for it in this conversation.

## 1. Scan

Use a fresh local temp directory for this request and retain its `scan.json` and `brief.json`. Run `python3 -I scripts/portfolio_scan.py > "$RUN_DIR/scan.json"`. It is read-only and records, for each project:
- the Git state: branch, last commit, uncommitted counts, ahead/behind;
- the instruction files present;
- the most recently changed status, plan and decision docs;
- the Backlog.md listing, when the project has one;
- for Backlog projects, every open task's status, labels, readiness, dependencies, file and short description (`backlog_tasks`), read through `backlog task list --json` and `backlog task <id> --json`.

Git read failures remain `null` with an explanation, not zero. Backlog includes `text`, `truncated`, `total_chars`, `displayed_chars`, and `error`; truncation means coverage is incomplete. `backlog_tasks` is `null` without a Backlog; a failed listing keeps `tasks: null` with an error, and a task whose detail fails keeps its listing fields with an error. The scanner does not fetch remotes or identify active sessions. Commit age does not establish the age of uncommitted changes.

Done when every allowlisted project appears; a missing path is reported, not skipped.

## 2. Recover each project's state, briefly

**Backlog projects** follow Attune's project task convention v0 (`docs/experiments/att-8-project-task-convention-v0.md` in the Attune repo). The renderer classifies their open tasks mechanically from status and labels:
- `Waiting` with `needs-human:decision` or `needs-human:acceptance` goes to *needs you*, ordered `attn:light` → `attn:read` → `attn:focus`. A `Waiting` task with no `needs-human:*` label is flagged and kept there.
- `Waiting` with `needs-human:feedback` goes to natural-use feedback.
- `Parked` goes to parked, with its restart condition.
- `To Do` + `agent-ready` with dependencies done goes to *when remote capacity is abundant*, mainline first. `gpu` tasks are listed separately, by local GPU availability rather than remote quota.
- The next mainline steps per project go to *when remote capacity is scarce*.
- `irreversible` is flagged wherever it appears; `agent-ready` + `irreversible` is shown as a label conflict.

Do not restate these tasks as `decisions`, `feedback` or `parked` in the brief: the renderer rejects brief items that cite `backlog/tasks/` files. For Backlog projects, read the status document only for workstream narrative, `today`, unknowns and anything the tasks do not cover, and report label gaps as unknowns or risks rather than re-classifying them.

Per project, read only what the scan points to:
- the current-direction part of the instruction file;
- the newest one or two state docs;
- the Backlog listing.

Aim for about six reads per project, and follow a link only when a conclusion depends on it. Process projects sequentially with the current agent. If a source is unavailable, truncated, or outside the approved scope, record the gap rather than discovering more projects or reading session history.

Do not stop at a document's opening summary. In each selected status source, inspect the dated headings and execution/approval gates (a targeted `rg -n` is enough to navigate), then read the relevant later passage. A newer dated paragraph may supersede an older header or pending list. Distinguish the fact date, file modification time, and this run's observation time. If current activity is not visible, keep that uncertainty; do not duplicate another executor's work.

Apply `advance-project`'s evidence rules:
- missing records mean unknown, not undone;
- earlier completion claims are leads, not verification;
- a confirmed decision replaces the plan it supersedes;
- note the observation date wherever stale data would change a conclusion.

## 3. Write the brief JSON

Write `$RUN_DIR/brief.json`:

```json
{"capacity": null,
 "projects": [{"alias": "P1",
               "today": {"outcome": "One useful result", "mode": "feedback", "reason": "Why this is the right next step"},
               "workstreams": [{"name": "", "state": "", "next": "", "sources": []}], "unknowns": [""]}],
 "decisions": [{"project": "P1", "group": "", "question": "", "why_now": "", "if_wait": "",
                "sources": [{"path": "docs/decisions.md", "line": 12,
                             "source_date": null, "observed_at": "2026-10-17T12:00:00+00:00"}]}],
 "feedback": [{"project": "P1", "question": "What to observe", "when": "At the next natural use, without a separate task", "sources": []}],
 "parked": [{"project": "P1", "item": "Old optional scope", "default": "Keep parked unless the user wants to resume", "sources": []}],
 "advisory": [{"project": "", "work": "", "why_no_human": ""}],
 "risks": [{"project": "", "kind": "", "detail": ""}]}
```

Rules:
- `capacity` is the remote model quota mode **as the user stated it** in this conversation: `"abundant"`, `"scarce"`, or `null` when unstated (rendered as "按紧张处理"). Do not guess it from usage.
- Include every scan alias exactly once. Do not copy Git counts, commit facts, domain, or observation time into project entries: the renderer joins them directly from the scan and rejects copied fact fields. Do not restate those numbers in narrative text.
- Give each project one useful `today` outcome and the evidence-based mode: `proceed` (within existing authorization), `feedback` (needs real use), or `paused` (do not start new work here). This is prioritization, not dispatch. If today's actual goal cannot be established, say so rather than inventing a deliverable.
- Each decision needs a real project-relative source file and line, the source's stated date (`null` if unknown), and the actual timezone-qualified observation time. Do not substitute file modification time for a decision date. Workstream source links use the same shape. The renderer checks provenance structure and file boundaries, not the truth of the agent's interpretation; compare each decision with its cited passage before delivery.
- **Plain language.** Write in the user's language. Name a workstream by what it does; if the project uses a code name, add a few words saying what it means. No unexplained jargon or internal IDs.
- **Decisions** are choices that block a specific next action: an execution authorization, material scope change or trade-off. Say what action waits and what happens meanwhile. Completed or superseded approvals are excluded; do not invent urgency.
- Put ordinary real-use/device feedback in **`feedback`**, with its natural occasion. Put old options with a safe inactive default in **`parked`**. Both need the same source format as decisions. They do not increase the decision count. The renderer validates structure, not these semantic judgments; the executor still checks each classification against its passage.
- **Advisory work** must be startable within authorization the user has already given, with a stated reason it does not need them. It is a suggestion: never start it.
- **Risks** worth flagging:
  - work uncommitted for a long time;
  - a decision that lives only in another repository;
  - acceptance deferred repeatedly;
  - sources too stale to trust.
- Put anything you could not establish in `unknowns`.
- Before delivery, check coverage, numbers, superseded decisions, duplicates, and missing evidence. A source date, an assistant completion claim, or a passing test does not establish user acceptance. Already-running work is not a new advisory dispatch; if active execution is not visible, say so.

## 4. Render and hand off

Run `python3 -I scripts/render_brief.py "$RUN_DIR/brief.json" "$RUN_DIR/scan.json"`. One command validates the input and produces matching HTML and a complete Markdown report under the system temp directory. It prints the HTML path; the `.md` file has the same stem. This local report is the result record, not another writable project-state store. Git failures and Backlog truncation appear in both formats. Correct validation errors before delivery, without hand-editing the HTML.

Use that report to give the user a complete useful answer: the actual decision(s), each project's current result and next step with fact dates, safe suggestions, and important unknowns. Natural-use feedback and parked options remain separate. Include the artifact links as supporting material; counts and a temporary HTML link alone do not satisfy the request. Preserve source dates and limitations if shortening the generated text.

Writing a sanitized observation into Attune's development log is separate from the read-only portfolio operation and follows the user's existing authorization. Do not reopen a trial, mark benefit established, or start recurring work merely because a report ran successfully.

Do not act on anything in the brief unless the user asks.
