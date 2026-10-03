---
name: vivaldi-tab-tidy
description: Safely tidy duplicate, same-Codebase-MR, loose, and unnamed-stack Vivaldi tabs with verified before-and-after state snapshots.
argument-hint: "[workspace name]"
disable-model-invocation: true
compatibility: Requires Node.js 18+, Git, and vivaldi-agent 0.2 or newer.
---

# Vivaldi Tab Tidy

Treat the browser as an execution surface, not a permanent knowledge store.
Each run should absorb current clutter without redesigning stable history. When
meaning or completion is uncertain, keep or group the tab; never guess that it
is safe to close.

## Hard boundaries

- Use `vivaldi-agent` for every browser read and mutation. Inspect `--schema`
  before using an unfamiliar command.
- Run one `vivaldi-agent` command at a time. Its fixed loopback port permits no
  concurrency; after `EADDRINUSE`, wait for the current command to finish and
  retry serially.
- A full Vivaldi restart is disruptive, so ask before doing it. If a restart is
  required after mutations, expect Vivaldi to replace runtime window, tab, and
  group IDs. Do not treat that renumbering as tab loss: let the verifier map
  survivors by exact URL, pinned state, expected semantic stack, and active
  state. It must still fail if that evidence cannot account for every survivor
  or if a closed duplicate identity remains.
- Before the first mutation, capture and verify all four browser views with
  `scripts/snapshot.mjs`: browser, stacks, Workspaces, and Workspace rules. The
  script must create a readable local `refs/vivaldi-snapshots/*-pre-tidy` ref.
  If it cannot, stop. Never push or mirror these refs; they contain browsing
  state and are local safety evidence only.
- Treat a snapshot as evidence for manual reconstruction, not an automatic or
  transactional rollback. This skill does not restore browser state.
- Never close an active tab, pinned tab, the user's work index, or their work
  ledger. Preserve the original grouping of pinned tabs. Keep fixed entrypoints
  ungrouped, even if they are temporarily unpinned.
- Never infer completion from `discarded`; it only means the tab is sleeping.
- Automatic deduplication has exactly two identities: a byte-for-byte identical
  full URL, or the same Codebase merge request. For Codebase, only
  `https://code.byted.org/<namespace>/<repo>/merge_requests/<numeric-iid>` is an
  MR identity; a nested namespace is allowed, and a trailing slash, `/changes`,
  query string, or fragment does not change that identity. Normalize the keeper
  to the parameterless MR URL because those details are navigation state, not a
  separate work item.
- Never extend same-MR matching to MR lists, non-numeric IDs, another host, or
  another Codebase resource. Outside that narrow exception, never deduplicate by
  title, host, path, issue number, or a URL with its query removed. Assume these
  URL differences carry meaning: preview `case`, `ab`, and `tab`; TMates
  workflow/task/share and `basic` or `session`; Lark Base/Sheet `view` and
  `sheet`.
- Do not close a tab opened during the run unless it is an exact duplicate or
  same-MR duplicate and another explicit keeper remains.
- Do not create, delete, rename, or migrate across Workspaces unless the user
  explicitly expands the task.
- Never put private, administrative, or sensitive pages into a shared index.

## Process

### 1. Resolve one scope

Read the browser, Workspace, tab, and stack state. Use the named Workspace when
the user supplied one; otherwise use the focused window's active Workspace. A
plain `window` scope is always bound to one window ID; pass `--window-id` when
focus is ambiguous. Never combine non-Workspace tabs from multiple windows.

Record total tabs, active and pinned tabs, named and unnamed stacks, loose tabs,
exact-URL duplicate groups, and same-Codebase-MR groups. Existing named stacks
are context, not a request to reorganize them. The candidate set is every loose
tab, every member of an unnamed stack, and redundant exact or same-MR
duplicates in the selected scope.
Identify the work index, work ledger, and any other durable entrypoints in that
snapshot. Confirm their exact full URLs from the tab records and pass those
literal URLs as repeated `--fixed-url` arguments below; do not rely on unset
environment variables or title-only matching.

### 2. Save the pre-tidy recovery point

Run from a Git repository that will own the private snapshot ref:

```bash
node "<skill-dir>/scripts/snapshot.mjs" --phase pre-tidy \
  [--repo /path/to/repo]
```

The script invokes the four `vivaldi-agent` reads serially, validates their
cross-references, writes Git objects without touching the index or worktree,
creates `refs/vivaldi-snapshots/<timestamp>-pre-tidy`, and reads the snapshot
back. A sandbox denial is a reason to request the narrow Git-write permission,
not a reason to skip the recovery point.

### 3. Write and validate the plan

Audit the `output_dir` returned by the pre-tidy snapshot, then read
[plan-format.md](./references/plan-format.md) and create a temporary JSON plan:

```bash
node "<skill-dir>/scripts/tidy-plan.mjs" audit \
  --snapshot /path/from/snapshot-output \
  --fixed-url "https://exact.example/work-index" \
  --fixed-url "http://127.0.0.1:8787/" \
  [--workspace NAME_OR_ID]
```

Use the audit result only as evidence. Create a new mode-`0600` temporary
`plan.json` that exactly matches [plan-format.md](./references/plan-format.md);
do not copy the audit envelope into the plan. Never store real browsing data in
the repository. Copy only the audited Workspace ID and `window_id` into their
matching plan fields. Every candidate must have exactly one disposition: `close`, `assign`,
`keep_ungrouped`, or `needs_confirmation`. Protection is an overlapping safety
flag, so an active tab may be protected and assigned, but never closed.
The validator accepts only `exact_url_duplicate` and `same_merge_request`
closes. It derives any keeper URL normalization itself; do not hand-author a URL
mutation in the plan. Handle a page-specific request to close any other
non-duplicate separately from this automatic tidy plan.

Classify each candidate with this decision flow:

```text
Active, pinned, or fixed entrypoint?
├─ Yes → protect; fixed entrypoints stay ungrouped; pinned tabs keep their
│         baseline grouping; active unpinned tabs may still be assigned
└─ No
   ├─ Same Codebase repository and numeric MR IID as another in-scope tab?
   │  ├─ Yes → choose one keeper; mark all others `same_merge_request`
   │  └─ No
   ├─ Full URL exactly equals another in-scope tab?
   │  ├─ Yes → choose one keeper; mark only the others `exact_url_duplicate`
   │  └─ No
   ├─ Looks obsolete, completed, denied, or transitional?
   │  ├─ Yes → needs-confirmation; do not infer closure
   │  └─ No
   ├─ Same real task chain as a named stack?
   │  ├─ Yes → assign to that existing stack
   │  └─ No
   ├─ New theme has at least 2 related pages?
   │  ├─ Yes → assign them to one new `role｜topic` stack
   │  └─ No → leave the single page in the inbox
   └─ Record exactly one disposition
```

Choose a duplicate keeper in this order: active, fixed entrypoint, pinned,
already in a meaningful named stack, loaded, then the later tab position. For a
same-MR group, ignore whether one copy is on `/changes` or has `dv_filepath`,
`to_version`, query, or fragment details. If a lower-ranked copy is protected,
or copies occupy distinct named-stack contexts, defer every redundant copy in
that group through `needs_confirmation`; do not partially merge the group. Also
defer if normalization would change the literal URL of a fixed entrypoint.

Name stacks by work context, not website: `当前｜...`, `项目｜...`,
`评审｜...`, `分析｜...`, `参考｜...`, `工具｜...`, or `证据｜...`. Reuse
an existing semantic match. Do not manufacture a stack for one page. Preserve
existing colors; for new stacks use `当前=color1`, `工具=color2`,
`参考=color3`, `项目=color4`, `分析=color5`, `评审=color6`, and
`证据=color9`.

When an existing stack's responsibility genuinely expands, assignments may use
`target_kind: "renamed"` with both `source_stack` and the new `target_stack`.
This is the only default path that may rename a stable stack; the validator
keeps every surviving source member and the original color.

Validate before changing Vivaldi:

```bash
node "<skill-dir>/scripts/tidy-plan.mjs" validate \
  --snapshot /path/to/browser-snapshot.json \
  --plan /path/to/plan.json \
  --fixed-url "https://exact.example/work-index" \
  --fixed-url "http://127.0.0.1:8787/" \
  [--workspace NAME_OR_ID]
```

Do not execute a plan that fails coverage, protection, duplicate-identity,
target-stack, or one-tab-one-destination checks.

### 4. Execute conservatively

Re-read every tab named by the plan immediately before mutation. If an ID
disappeared, its URL changed, its active state changed, or a new candidate
appeared, invalidate the entire plan. Return to scope resolution, create a new
pre-tidy snapshot under a new ref, and build a new plan; never patch a stale
plan after partially applying it.

1. Handle validated duplicates first. For each same-MR group, use the
   schema-confirmed tab navigation/update command to change the keeper to the
   emitted `url_normalizations[].to_url`, read it back, and only then close the
   other copies. Exact duplicates need no navigation. After each close batch,
   confirm every keeper still exists.
2. Group tabs second. When adding to an existing stack, prefer `stack add` only
   after reading the result back. Some Vivaldi versions do not visually rebuild
   the group through that path. If the membership did not change, use
   `stack create` with the complete old-plus-new member list so no old member is
   lost.
3. For an unnamed-stack member classified as `keep_ungrouped`, remove it from
   that stack and read it back. Already-loose inbox pages require no mutation.
4. After every stack mutation, refresh its group ID. Vivaldi may replace IDs
   when a stack is rebuilt; identity is stack name plus member set, never the
   old group ID.
5. Leave `needs_confirmation` untouched.
6. If the bridge disconnects after mutations, ask before fully restarting
   Vivaldi. Restore the baseline active page before the post snapshot. Resolve
   it by its expected URL and semantic stack after a restart because the old
   tab ID is no longer valid.

Never batch independent `vivaldi-agent` processes. Batching IDs inside one
validated command is fine.

### 5. Save and verify the post-tidy recovery point

Capture the post-tidy recovery point first:

```bash
node "<skill-dir>/scripts/snapshot.mjs" --phase post-tidy \
  [--repo /path/to/repo]
```

Then verify the exact `output_dir` returned by that command:

```bash
node "<skill-dir>/scripts/tidy-plan.mjs" verify \
  --before /path/from/pre-snapshot-output \
  --after /path/from/post-snapshot-output \
  --plan /path/to/plan.json \
  --fixed-url "https://exact.example/work-index" \
  --fixed-url "http://127.0.0.1:8787/" \
  [--workspace NAME_OR_ID]
```

Verification must show that protected tabs survived, closed tabs disappeared,
every other baseline tab remains in its Workspace, assignments landed in the
named target, every in-scope unnamed-stack member was assigned or deliberately
deferred, exact and same-MR duplicates selected for closure are gone, each
same-MR keeper has its canonical URL, and tab counts reconcile with concurrent
additions.

If verification fails, stop further mutations and report the precise delta and
both snapshot refs. Keep the post ref because it records the exact failed state;
do not attempt a broad automatic rollback.

## Report

Report only evidence: before/after counts, exact and same-MR duplicates closed
with their keepers, canonical MR URLs applied, stacks created or rebuilt, pages
left in the inbox or awaiting a decision, concurrent additions, and both
snapshot refs. State why anything was deliberately left alone.

## Done when

- Both state-snapshot refs can be read back and contain all four JSON files.
- Active tabs remain active, pinned tabs preserve their pinned and grouping
  state, and fixed entrypoints remain present and ungrouped.
- Every automatic close has an exact-URL or same-Codebase-MR keeper selected by
  the safety priority.
- Every merged Codebase MR keeper uses its canonical parameterless main URL.
- No query-sensitive page outside the narrow Codebase MR rule, and no merely
  discarded page, was closed by inference.
- Every baseline candidate has one final disposition and every mutation is
  traceable to the validated plan.
- Final verification passes, or mutations have stopped with the failed checks
  and the pre-tidy ref reported.
