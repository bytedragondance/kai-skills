---
name: distill
description: Periodic ritual — turn a window of real work into durable lessons and skill changes. Type its name to run it.
disable-model-invocation: true
---

# Distill

Turn a **window** of real work into two durable outputs: **lessons** you will reuse, and **frictions** that reshape your skills. Raw sessions are sediment; distilling pulls the reusable signal out before it settles and is lost.

The ritual is periodic and run by hand — invoke it when a chunk of work has piled up (weekly by default).

## What you are hunting

Two artifacts, nothing else:

- A **lesson** is a transferable rule: a **trigger** ("next time you are X") plus a **move** ("do Y"), earned from something that went wrong, got reworked, or was discovered the hard way. A lesson that fits only the one task that spawned it is a diary entry — drop it.
- A **friction** is a workflow snag: a skill misfired or was missing, a manual step that should be automated, a tool that fought you. Every friction routes to a skill change.

## Steps

### 1. Set the window
Find the corpus since the last distill (default: the last 7 days). Gather:
- Claude Code sessions under `~/.claude/projects/**` modified in the window.
- Optionally `git log --since` across the repos touched this window.

**Done when** you hold a concrete list of sessions (and commits) in scope — not a vague sense of "this week."

### 2. Mine the corpus
Read every session in scope. In each, hunt corrections, reworks, dead-ends, and discoveries — the moments where the work changed direction. Tag each as a candidate **lesson** or **friction**.

**Done when** every session in scope has been read and yielded its candidates (zero is a valid count) — exhaustive legwork, not a sampled skim.

### 3. Grill each candidate
For each **lesson**, sharpen the war story into a bare **trigger + move**: strip the specifics until what remains transfers to a task you have not met yet. Kill candidates with no transfer value. For each **friction**, name the skill it implicates.

**Done when** each surviving candidate is one sentence you could hand to a fresh agent with no other context.

### 4. Route
- Each **lesson** → a note in the Obsidian vault, wikilinked to related notes (use the `obsidian-vault` skill).
- Each **friction** → a skill change: edit the implicated skill, or draft a new one under `skills/mine/`. If you cannot act now, capture it as a vault note tagged for later.

**Done when** every candidate is either written somewhere or dropped with a stated reason — none left dangling.

### 5. Close the loop
Record the date this distill ran (so the next window starts here) and a one-line tally: N lessons, M frictions, what changed.
