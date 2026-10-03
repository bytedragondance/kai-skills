# Tidy plan format

Use one JSON object. IDs are numeric Vivaldi tab IDs from the same pre-tidy
snapshot. The plan is disposable run state; do not commit real browsing data.

```json
{
  "workspace": 123456,
  "window_id": 456,
  "protected": [101, 102, 140],
  "keep_ungrouped": [101, 102, 199],
  "close": [
    {
      "tab_id": 121,
      "keep_tab_id": 120,
      "reason": "exact_url_duplicate"
    },
    {
      "tab_id": 131,
      "keep_tab_id": 130,
      "reason": "same_merge_request"
    }
  ],
  "assign": [
    {
      "tab_id": 140,
      "target_stack": "工具｜账号与权限",
      "target_kind": "new"
    },
    {
      "tab_id": 141,
      "source_stack": "当前｜Old Scope",
      "target_stack": "当前｜Expanded Scope",
      "target_kind": "renamed"
    }
  ],
  "needs_confirmation": [151]
}
```

Rules enforced by `tidy-plan.mjs validate`:

- `workspace` must resolve to the audited Workspace. Use `"window"` only for
  tabs outside named Workspaces, and bind that scope to one `--window-id`.
- `window_id` is copied from the audit result and binds every later validation
  and mutation to the same browser window.
- `protected` must include every active and pinned tab plus the user's fixed
  entrypoints. Protected tabs cannot be closed.
- The validator independently resolves each repeated `--fixed-url` argument.
  Those tabs must also appear in `protected` and `keep_ungrouped`; the plan does
  not get to self-declare which entrypoints are fixed.
- Every loose tab, unnamed-stack member, and proposed redundant exact or
  same-MR duplicate has exactly one disposition across `keep_ungrouped`,
  `close`, `assign`, and `needs_confirmation`.
- An `exact_url_duplicate` close points to the safety-ranked keeper with the
  exact same full URL. A `same_merge_request` close points to the safety-ranked
  keeper for the same Codebase repository and numeric MR IID. Only
  `code.byted.org` MR main and `/changes` pages qualify; query strings and
  fragments are ignored for this identity. These are the only automatic close
  reasons. A duplicate group that contains a lower-ranked protected tab or
  distinct named-stack contexts must be deferred as a whole through
  `needs_confirmation`. A same-MR group must also be deferred if canonicalizing
  it would change a fixed entrypoint URL.
- A tab appears in at most one assignment. Existing targets must resolve to one
  named stack. New targets use one `角色｜主题` name and contain at least two
  assigned tabs.
- `renamed` targets require `source_stack`. The source must resolve to exactly
  one named stack, the target name must not already exist, and the emitted
  `complete_member_ids` always includes every surviving source member. Use this
  only when the task scope genuinely expanded, not as cosmetic cleanup.
- A stable named-stack tab cannot move to another stack in the default tidy
  flow except through an explicit `renamed` target, and closing must not leave
  a named stack with fewer than two members.
- `execution_groups[].target_color` is the existing stack color or the standard
  role color for a new stack. Preserve that value during execution.
- Fixed entrypoints stay ungrouped. Pinned tabs preserve their baseline grouping
  and cannot be assigned or closed. Active unpinned tabs may be assigned but
  remain protected from closure.

The validator emits `execution_groups`. For an existing target,
`complete_member_ids` includes both the old members and new assignments. Use
that complete set if Vivaldi requires `stack create` to rebuild the stack.

The validator also emits `url_normalizations` for every same-MR group that will
be closed whose keeper is not already canonical. Each entry contains
`tab_id`, `from_url`, and the required parameterless `to_url`. Apply and read
back that navigation before closing the group's redundant tabs. Verification
accepts only that exact planned URL transition; all other survivor URL changes
remain errors.
