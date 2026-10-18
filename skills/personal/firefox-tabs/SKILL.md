---
name: firefox-tabs
description: Sort open Firefox tabs into one-off things, long-lived topics, and cleanup, matched to LifeVault projects; review them on a one-off local page, record the decisions in Obsidian, regroup the browser by the user's decisions, and close the finished tabs after archiving them to the vault, once the user approves.
disable-model-invocation: true
---

# Firefox Tabs

Tidy the user's open Firefox tabs with `firefox-agent`, their local CLI from `~/dotfiles`. Tabs are decided in bundles, never one by one. A one-off **事情** (thing) ends: a booking, a purchase, a research question. A **主题** (topic) is a long-lived collection that stays. **清理** (cleanup) is pages with nothing to keep. The agent proposes a decision for every bundle, and on a one-off local review page the user looks only at the ones the agent is unsure of. The decisions are recorded in Obsidian, the browser is regrouped to match, and the finished tabs are archived and closed once the user says so.

The vault is LifeVault (`~/Library/Mobile Documents/iCloud~md~obsidian/Documents/LifeVault`; override with `--vault` or `FIREFOX_TABS_VAULT`). Run the scripts from this skill's directory as `python3 -I scripts/<name>.py`. Keep working files in a temporary directory, not in the vault.

Tabs close only in step 6, through `firefox-agent tab close`, which writes every tab to the vault's archive before closing it and refuses pinned, stashed, private, and container tabs. Nothing closes until the user approves the counts in this session.

## 1. Preflight

Run `firefox-agent doctor`. Done when `live.ok` is `true`. If it reports `HOST_OFFLINE`, `HOST_INSTALL_REQUIRED`, or `EXTENSION_RELOAD_REQUIRED`, stop and follow `~/dotfiles/docs/firefox-agent.md`. Don't reinstall or restart Firefox without asking. In a Codex sandbox, a failure to connect to `~/.local/state/firefox-agent/agent.sock` is a sandbox block. Report it, don't work around it.

## 2. Context

Run `scripts/tab_review.py context --out <ctx.json>`. It reads the browser and the vault's `20_Projects/` notes and writes, for each tab, its group, age, same-page copies, and a rule hint. It also lists the projects with their status and track.

Read the project notes that tabs seem to belong to. Their timelines often settle whether a thing is finished, for example "已订" or "已提交". Never invent an outcome the notes and tabs don't show.

## 3. Propose

Sort every tab into one of three kinds, and give each one a candidate decision. Don't leave decisions blank for the user to fill in: the user should only have to look at what you're unsure of.

- **事情** (thing): a one-off that will end, such as a booking, a purchase, a claim, or a research question. Decisions: 进行中 / 做完 / 放弃 / 待定. A 进行中 thing becomes its own Firefox group, named after the thing, so give it a short title. Don't make a thing out of one tab; fold it into a topic.
- **主题** (topic): a long-lived, scattered collection, such as forum threads, tool links, or local outings. Decisions: 保留 / 待定. A kept topic becomes a group; reuse an existing Firefox group's name so its tabs stay put. Inside a topic, mark tabs to close one by one (`"fate": "关"`, with `why`), for example ones untouched for a long time, expired deals, or bare home and login pages.
- **清理** (cleanup): pages with nothing to keep, such as logins, thank-you pages, expired pages, entertainment, and duplicates. Decisions: 关掉 / 待定. Exact duplicates get their own 清理 item with intent 重复; never mix them with judgment calls.

Write `<proposal.json>`:

```json
{"things": [{"kind": "事情", "title": "台北住宿（已订）", "project": "2026 冬季回国计划", "intent": "事务",
             "decision": "做完", "confidence": "高", "note": "项目笔记：住宿已订",
             "tabs": [{"id": 100}, {"id": 213, "fate": "不动", "why": "售后可能没处理完"}]}]}
```

- `project` must be an exact note name in `20_Projects/`. Match tabs to projects first, and read those notes: their timelines often settle whether a thing has ended, for example "已订" or "已提交". Never invent an outcome the notes and tabs don't show.
- `intent` is one of 调研, 事务, 追踪, 参考, 常驻, 残骸, 消遣, 重复.
- `confidence` is 高, 中, or 低. Anything below 高 lands on the page's "需要你看" view. Use 高 only when the project notes or the tabs themselves back the decision. Even at 低, still give your best-guess decision, and say in `note` what would change it.
- `fate` on a tab overrides its thing: 关 sends that tab to 做完, and 不动 leaves it where it is.
- Signals: tabs opened together (similar `age_days`), `utm_source=chatgpt.com` (left over from a research chat), and URL shape (login, checkout, confirmation, releases, a forum page number).
- Leave out every tab with a `left_alone` reason in the context: pinned tabs, stashed tabs, private-window tabs, container tabs, and the review page itself. The scripts refuse them anyway.

## 4. Review page

Run `scripts/tab_review.py review <proposal.json> --out <decisions.json>` in the background. It refuses bad kinds, decisions, confidence values, or projects, and any tab listed twice. Tabs the proposal misses go to `未归类`. It then serves `scripts/review.html` on `127.0.0.1`, behind a random token, opens the page, and waits up to 6 hours. Pass `--no-open` to print the URL without opening it. Tell the user the page is open.

The page opens on "需要你看", which holds only the items below 高 confidence, least sure first. The user accepts a suggestion with "✓ 就这样" (Enter), or changes the decision (keys `1`–`4`) or single tabs (跟着走 / 关 / 不动). They can also move tabs between items, rename items, or browse the 事情 / 主题 / 清理 views. Submitting writes `<decisions.json>` and the record note `00_Inbox/标签整理 <date>.md`, and then the server exits. Commit only that note in the vault, following the vault's AGENTS.md.

## 5. Plan and apply

Run `scripts/tab_review.py plan <decisions.json> --out <plan.json>`. It resolves the decisions against a fresh snapshot, matching by URL because tab IDs change across browser restarts, and prints what will move:

- 进行中 thing, or 保留 topic → a group with that title (it adds to the group if one already has that name)
- 做完 / 放弃 / 关掉, or a tab marked 关 → the `做完` group, to close in step 6
- a 清理 item with intent 重复 → the `重复` group
- 待定, or a tab marked 不动 → left where it is

Show the printout to the user. If it lists groups that will be emptied (Firefox deletes an empty group), get explicit approval, then rebuild with `--allow-empty-groups`. Run `scripts/tab_apply.py <plan.json> --dry-run-only`, then without the flag. Done when it prints `post-check OK`. Set the record note's `status:` to `applied` and commit it.

Do not change project notes, project status, or reminders in this skill. The vault's rules require the user's confirmation for those.

## 6. Close

Run `scripts/tab_close.py <decisions.json>`. It takes a fresh snapshot and resolves every tab the decisions send to `做完` or `重复`, by URL like `plan`, keeping only tabs that still sit in that group: a tab the user dragged out has changed its mind. It dry-runs one `firefox-agent tab close` per thing, with the reason `标签整理 <date> · <thing> · <decision>`, then prints the counts per group, the archive path, and notes: tabs left open, tabs already closed, and child tabs (`openerTabId`) of closing tabs that stay open. It closes nothing.

Show the printout to the user and ask whether to close. Only on a clear yes in this session, run it again with `--yes`. firefox-agent appends one JSON line per tab (URL with account-key-like query parameters such as `account_key` stripped, title, group, window, container, last access, closing time, reason) to `60_Archive/标签存档/<YYYY-MM>.jsonl` in the vault and fsyncs it before closing; if the write fails, nothing closes. Done when it prints `post-check OK`. Commit only that month's archive file in the vault.

If the dry run fails with `EXTENSION_RELOAD_REQUIRED`, the running extension predates `tab close`: stop and tell the user. Signing and installing the new version is theirs to approve.

## 7. Hand off

Tell the user:

- how many tabs were closed and where they are archived, or that the `做完` and `重复` groups are still waiting for their go-ahead;
- which things and topics are now their own groups;
- what was left alone (待定, tabs marked 不动, pinned, stashed, container, private) and why.

## Fallback: rule-only audit

`scripts/tab_audit.py` is the older audit: duplicates (`重复`), rule-based closable tabs (`可关`), and same-path review pairs. It's useful for a quick pass without the vault. Its plans also go through `tab_apply.py`.

## Gotchas

- Container tabs (`cookieStoreId` other than `firefox-default`) work like separate profiles; the `Yue` group is one. Each carries its own login, so it is never moved into a shared group, and the same URL in another container is not a duplicate. Private-window tabs can't join a normal window's group either. Mention them in the hand-off as left alone.
- Window, group, and tab IDs last only for the current browser session. `plan` re-resolves by URL. Never reuse an old plan JSON.
- If the review page opens in Firefox, it is one more open tab. It is not in the decisions, so `plan` ignores it. The user closes it after submitting.
- Creating a group from tabs in several windows moves them all into the first tab's window.
- Tree Style Tab keeps its own tree, which firefox-agent cannot see; `openerTabId` is the nearest signal. `tab_close.py` lists open children of closing tabs, so mention them before the user approves.
- To reopen an archived tab, look it up in `60_Archive/标签存档/<YYYY-MM>.jsonl`; stripped query parameters are gone for good, so a page that needed one may ask for a login.
- In zsh, pass each argument to `firefox-agent` as its own word. The scripts build argument lists, so they avoid this.
