---
name: advance-project
description: Resume, coordinate, or close a multi-session project by reconciling its current state and delivering a bounded next outcome. Use for project continuation, parallel-work consolidation, or delivery closeout; not isolated edits or general questions.
---

# Advance Project

Reduce the owner's work of recovering context, coordinating agents, and accepting results. Use the project's existing documents and execution conventions. This skill adds continuity around implementation; it does not prescribe an implementation method or a new project-management system.

## Fit the request

- Preserve the user's objective, explicit scope, and existing authorization. A read-only assessment stays read-only, including project status and backlog files.
- Apply only the parts needed now. A small, clear edit does not need project discovery, a planning document, or an acceptance ceremony, even when this skill is explicitly invoked.
- For an assessment, produce findings and a recommended next outcome. For execution, carry the authorized work through implementation, appropriate verification, and handoff. Do not stop at a proposal or first implementation when more was requested.

## Recover the relevant state

Read the applicable repository instructions and locate the existing current-state, decision, and active-work records. Follow relevant links rather than loading the whole documentation tree or replaying all conversation history.

Check the actual working state needed for this task: relevant files, Git branch and changes when available, and targeted read-only evidence. Prior assistant completion reports and old test results are leads, not fresh verification. Resolve conflicting claims using dated evidence and explicit owner corrections; if unresolved, state the uncertainty rather than silently choosing a convenient version.

Establish, briefly:

- What the user wants to become usable, and which confirmed decisions still apply.
- What is implemented, what has been verified and how, and what has been accepted in real use.
- What is in progress or blocked, the specific missing input, and the next useful action.

Missing records mean unknown, not undone. Record the coverage and observation date when stale or partial data would change a conclusion. Do not derive reminders, completion claims, or abandonment from silence.

When a confirmed decision replaces an earlier plan, identify the superseded plan explicitly and use the confirmed direction for the next action. Do not combine incompatible alternatives into a current architecture; preserve the decision's stated roles and constraints.

Reopen an established decision when the user asks or relevant conditions change. A new session alone is not a reason to redesign it.

## Define the next outcome

Use the existing task or plan to identify the consumer, deliverable, observable acceptance condition, and this round's boundary. Infer routine details from the request and evidence; ask only for missing choices that materially affect the result. Continue independent authorized work while a necessary answer is pending.

If no plan is needed, a short statement in the conversation is sufficient. Do not create a contract, issue, status file, or approval step just to satisfy this skill.

In exploratory work, end with a recommendation and what would justify acting on it. Distinguish proposed choices from owner-confirmed decisions. In execution, complete the agreed outcome. Necessary fixes and validation belong to that outcome; unrelated opportunities do not silently expand it. When maintaining notes is in scope, put useful follow-ups in the existing backlog, otherwise report them briefly. A round boundary does not cancel already-authorized subsequent work.

## Coordinate execution

Use existing implementation and domain workflows when appropriate and available; do not require another named skill, a particular agent, worktrees, or a full test suite for every task.

When concurrent work is present, identify modification boundaries and who integrates the result. Prefer one writer for overlapping files; independent worktrees are an option for independent write tasks. Do not infer authorship from untracked status or missing Git history. Before editing or staging shared files, inspect their actual changes; isolate this task's changes or leave ambiguous portions untouched and explain the narrow conflict. Continue unaffected work.

For cross-project dependencies, establish who produces the relevant fact or artifact, who may revise it, and which version the consumer uses. Exercise an existing interface with a concrete example before introducing a shared abstraction. Do not consolidate repositories or migrate their tooling merely to make them uniform.

## Verify and prepare acceptance

Choose checks that answer the task's actual uncertainty. Distinguish implementation, engineering verification, and real-use acceptance in ordinary language; do not impose new status enums. Tests, consistency checks, and stable model outputs do not by themselves establish usefulness or accuracy. Label historical results and untested device or production behavior explicitly.

Design required human review to minimize repeated effort: group equivalent decisions, show the affected scope, offer a recommendation, and supply representative evidence and counterexamples. Where evaluating quality, include ordinary samples as well as suspected failures; machine-selected exceptions alone cannot establish overall accuracy.

Before asking for acceptance, finish the authorized preparation and provide a directly usable artifact or reproducible entry point. Explain only the decisions the owner must make, why they matter, and what can proceed without them. Reuse existing authorization; do not add signoffs for routine steps. Do not turn owner preferences into automatic recurring tasks.

## Close or hand off

Within the authorized scope, update the existing current-state entry with the outcome, evidence date, remaining uncertainty, and next action. Preserve prior decisions and useful history without appending another competing current-state summary. Use existing storage conventions; avoid new dashboards, registries, or duplicate handoff documents.

Save code according to the project's Git conventions, separating a recoverable work checkpoint from product acceptance or release. Inspect and stage only attributable changes; never sweep in unrelated work or private runtime data. Do not make pushing, publishing, or deploying an implicit part of closeout.

The final handoff should make these answers easy to find, with detail proportional to the task:

- What is now usable, and where to open or run it.
- What was actually verified, versus what remains unverified.
- Where the work is saved, including relevant commit or uncommitted state.
- Any specific owner decision or blocker, with the recommended next action.

If blocked, hand off the completed independent work and precise blocker. If further execution is already authorized and possible, continue rather than returning an artificial approval gate.
