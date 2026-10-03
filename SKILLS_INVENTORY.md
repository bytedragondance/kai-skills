# Skills Inventory

This document is the working map for managing agent skills on this machine.
It separates source directories, tool entrypoints, plugin-managed skills, and
runtime caches so cleanup does not delete the wrong thing.

## Management Model

Use four layers:

1. Source layer: edit skills here.
2. Shared hub layer: expose stable cross-tool skills here.
3. Tool entrypoint layer: make a specific tool see a selected subset.
4. Plugin/runtime layer: treat generated caches as read-only.

The practical rule is:

- Edit source repos, not installed cache directories.
- Use `~/.agents/skills` as the cross-tool hub.
- Use `~/.trae/skills`, `~/.claude/skills`, and `~/.codex/skills` as entrypoint
  directories only.
- Treat `.tmp/`, `plugins/cache/`, and marketplace checkout folders as runtime
  or install artifacts unless explicitly working on a plugin source checkout.

## Historical Snapshot

The counts and plugin lists below come from an earlier local audit. They are
retained as context, not a live inventory. Re-run the commands under Cleanup
Policy before changing installations.

| Location | Role | Resolved `SKILL.md` count | Notes |
| --- | --- | ---: | --- |
| `/Users/kai/.agents/skills` | Shared hub | 49 | Main hub for ByteDance/internal skills, browser skills, HDT, and TUX symlinks. |
| `/Users/kai/.trae/skills` | Trae entrypoints | 6 | System skill helpers plus `agent-browser`, `bytedcli`, and `hdtcli`. |
| `/Users/kai/.claude/skills` | Claude entrypoints | 49 | Mostly symlinks into `~/.agents/skills`, plus local `bytedcli` and `hdtcli` entries. |
| `/Users/kai/.codex/skills` | Codex entrypoints | 12 | Codex system skills, `figma`, `hdtcli`, and TUX entries. |
| `/Users/kai/.tux-skills/tux-skills/current` | TUX source/install | 6 | Official TikTok/TUX skill set; exposed to other tools through symlinks. |
| `/Users/kai/code/kai-skills/skills` | Personal source repo | 24 | Personal Matt Pocock-derived source repo; do not auto-install wholesale. |

## Plugin State at That Audit

Trae:

- Enabled plugins: `ai-contribution@traex-bd-plugins`, `traex-guide@traex-bd-plugins`.
- Trae plugin cache is under `/Users/kai/.trae/plugins/cache`.
- Trae marketplace checkouts are under `/Users/kai/.trae/.tmp/marketplaces`.

Codex:

- Enabled primary runtime plugins: `documents`, `pdf`, `spreadsheets`,
  `presentations`, `template-creator`.
- Enabled bundled plugins: `sites`, `browser`, `computer-use`, `visualize`.
- `openai-curated` has many available plugins in `.tmp`, but most are not
  installed. Do not count them as active skills.

Claude:

- Enabled plugins: `claude-hud`, `codex`, `compound-engineering`,
  `frontend-design`, `ralph-loop`, `typescript-lsp`.
- Claude can also load one-off plugins with `--plugin-dir`, which is useful for
  testing a source plugin without installing it globally.

## Ownership Rules

Every skill should have exactly one owner:

| Skill family | Owner/source | Install strategy |
| --- | --- | --- |
| ByteDance platform skills | `~/.agents/skills` or upstream internal source | Link into tool entrypoint dirs as needed. |
| Browser/API discovery skills | `~/.agents/skills` | Link into tool entrypoint dirs as needed. |
| HDT skill | `~/.agents/skills/hdtcli` unless a tool needs a local copy | Prefer link or explicit sync, avoid hand editing copies. |
| TUX/TikTok skills | `~/.tux-skills/tux-skills/current` | Expose through symlinks from `~/.agents/skills` and tool entrypoints. |
| Personal engineering skills | `/Users/kai/code/kai-skills` | Install only a curated allowlist into target tools. |
| Plugin-provided skills | Plugin source or marketplace | Manage by plugin install/enable/disable; do not edit plugin cache. |

## Personal Skill Allowlist

Do not install all of `/Users/kai/code/kai-skills/skills` into every tool.
Start with a narrow allowlist:

- `skills/engineering/diagnosing-bugs`
- `skills/engineering/tdd`
- `skills/engineering/code-review`
- `skills/engineering/domain-modeling`
- `skills/engineering/codebase-design`
- `skills/productivity/handoff`
- `skills/mine/distill`

Keep these as manual or tool-specific until they have proven useful:

- `skills/engineering/grill-with-docs`
- `skills/engineering/to-prd`
- `skills/engineering/to-issues`
- `skills/engineering/triage`
- `skills/engineering/improve-codebase-architecture`
- `skills/engineering/prototype`
- `skills/mine/session-recap` — read-only session evidence adapter; TMates
  access is opt-in and project/issue lifecycle stays in external systems.
- `skills/mine/vivaldi-tab-tidy` — manual, local-browser maintenance with
  mandatory state snapshots before any destructive action.

Do not globally install experimental or personal workflow skills by default:

- `skills/in-progress/*`
- `skills/personal/*`
- broad orchestration skills that overlap with active tool behavior

## Cleanup Policy

Before deleting or moving anything:

1. Check whether the path is source, entrypoint, plugin-managed, or cache.
2. If it is cache or `.tmp`, prefer plugin commands over manual deletion.
3. If it is an entrypoint and the source still exists, remove or adjust only the
   entrypoint.
4. If there are duplicate names, choose the owner first, then convert other
   copies to symlinks or disable them.
5. Keep tool-specific system skills in their tool directories.

Useful commands:

```bash
find -L ~/.agents/skills ~/.trae/skills ~/.claude/skills ~/.codex/skills \
  -maxdepth 3 -name SKILL.md -print | sort

find -L ~/.agents/skills ~/.trae/skills ~/.claude/skills ~/.codex/skills \
  -maxdepth 3 -name SKILL.md -print \
  | sed 's#/SKILL.md$##' \
  | awk -F/ '{print $NF}' \
  | sort | uniq -c | sort -nr

traecli plugin list
traecli mcp list
codex plugin list
codex mcp list
claude plugin list
```

Known benign warning in this sandboxed environment:

- `traecli` and `codex` may print an `Operation not permitted` warning while
  trying to update PATH aliases. The command output can still be valid.

## Recommended Next Step

Add a small install script for this repo that links only the personal allowlist
into selected target tools. The script should be explicit about targets, for
example:

```text
scripts/install-personal-skills.sh --target agents
scripts/install-personal-skills.sh --target trae
scripts/install-personal-skills.sh --target claude
scripts/install-personal-skills.sh --target codex
```

The script should be conservative:

- refuse to overwrite real directories without `--force`;
- create symlinks instead of copying;
- print a dry-run by default;
- keep a generated manifest of links it owns.
