#!/usr/bin/env python3
"""Close the 做完 and 重复 tabs from a review, archiving each one to LifeVault first.

Usage: python3 -I scripts/tab_close.py DECISIONS.json [--vault V] [--yes]

Resolves every tab the decisions send to 做完 or 重复 against a fresh snapshot, by URL, and
keeps only those still sitting in that group: a tab the user dragged out has changed its
mind. Each thing becomes one `firefox-agent tab close` call with its own reason, and every
call is dry-run first. Without --yes it stops there and closes nothing. With --yes (only
after the user approves the printed counts) firefox-agent appends each tab to
60_Archive/标签存档/<YYYY-MM>.jsonl, with account-key-like query parameters stripped, and
closes it.

Exit codes: 0 dry run or closed, 1 refused before any close, 2 stopped or failed partway.
"""

import argparse
import collections
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tab_apply import call  # noqa: E402
from tab_audit import firefox_agent  # noqa: E402
from tab_review import DEFAULT_VAULT, DONE_GROUP, DUP_GROUP, destination, left_alone_reason  # noqa: E402

ARCHIVE_DIR = os.path.join("60_Archive", "标签存档")


def archive_path(vault, today):
    return os.path.join(vault, ARCHIVE_DIR, today.strftime("%Y-%m") + ".jsonl")


def batches_from(decisions, snap):
    """[(reason, [tab ids])] for tabs to close, plus notes on the ones left open."""
    taken = decisions.get("taken") or "?"
    tabs = {t["id"]: t for t in snap["tabs"]}
    by_url = collections.defaultdict(list)
    for t in snap["tabs"]:
        by_url[t["url"]].append(t["id"])
    group_title = {g["id"]: g["title"] for g in snap["groups"]}

    batches, used, notes = collections.OrderedDict(), set(), []
    for thing in decisions["things"]:
        for item in thing["tabs"]:
            target = destination(thing, item)
            if target not in (DONE_GROUP, DUP_GROUP):
                continue
            # Same resolution as `tab_review.py plan`: IDs change across restarts, URLs don't.
            tid = item["id"]
            if tid not in tabs or tabs[tid]["url"] != item["url"] or tid in used:
                spare = [i for i in by_url.get(item["url"], [])
                         if i not in used and group_title.get(tabs[i]["groupId"]) == target]
                spare = spare or [i for i in by_url.get(item["url"], []) if i not in used]
                tid = spare[0] if spare else None
            if tid is None:
                notes.append("already closed: %s" % (item.get("title") or item["url"])[:60])
                continue
            used.add(tid)
            t = tabs[tid]
            reason = left_alone_reason(t)
            if reason:
                notes.append("left open (%s): %s" % (reason, t["title"][:50]))
                continue
            if group_title.get(t["groupId"]) != target:
                notes.append("left open, no longer in %s (now in %s): %s"
                             % (target, group_title.get(t["groupId"], "no group"), t["title"][:50]))
                continue
            why = "关" if item.get("fate") == "关" else ("重复" if target == DUP_GROUP else thing["decision"])
            label = "标签整理 %s · %s · %s" % (taken, thing["title"], why)
            batches.setdefault(label, []).append(tid)

    closing = {tid for ids in batches.values() for tid in ids}
    for gid, title in group_title.items():
        if title not in (DONE_GROUP, DUP_GROUP):
            continue
        extra = [t for t in snap["tabs"] if t["groupId"] == gid and t["id"] not in closing]
        if extra:
            notes.append("left open: %d tab(s) in %s are not in these decisions, e.g. %s"
                         % (len(extra), title, extra[0]["title"][:50]))
    children = [t for t in snap["tabs"] if t.get("openerTabId") in closing and t["id"] not in closing]
    for t in children:
        notes.append("stays open, opened from a tab being closed: %s" % t["title"][:50])
    return list(batches.items()), notes


def close_args(ids, archive, reason):
    return ["tab", "close"] + [str(t) for t in ids] + ["--archive", archive, "--reason", reason]


def main():
    ap = argparse.ArgumentParser(description="Archive to LifeVault, then close the 做完/重复 tabs.")
    ap.add_argument("decisions", help="the review's DECISIONS.json")
    ap.add_argument("--vault", default=os.environ.get("FIREFOX_TABS_VAULT", DEFAULT_VAULT))
    ap.add_argument("--yes", action="store_true", help="close for real; only after the user approves")
    args = ap.parse_args()
    with open(args.decisions, encoding="utf-8") as f:
        decisions = json.load(f)
    exe = firefox_agent()
    archive = archive_path(args.vault, datetime.date.today())

    try:
        before = call(exe, ["browser", "snapshot"])
    except RuntimeError as e:
        print("refused, nothing closed: snapshot failed: %s" % e)
        return 1
    batches, notes = batches_from(decisions, before)
    if not batches:
        print("refused, nothing closed: no 做完 or 重复 tab is open")
        for n in notes:
            print("note: " + n)
        return 1

    by_group = collections.Counter()
    tabs = {t["id"]: t for t in before["tabs"]}
    group_title = {g["id"]: g["title"] for g in before["groups"]}
    for reason, ids in batches:
        try:
            res = call(exe, close_args(ids, archive, reason) + ["--dry-run"])
        except RuntimeError as e:
            print("refused, nothing closed: dry run failed for %r: %s" % (reason, e))
            return 1
        for t in res["tabs"]:
            by_group[group_title.get(t["groupId"], "no group")] += 1
        print("dry run ok: %3d  %s" % (len(ids), reason))
    total = sum(len(ids) for _, ids in batches)
    print("would close %d of %d tabs: %s" % (total, len(before["tabs"]),
          ", ".join("%s %d" % kv for kv in by_group.most_common())))
    print("archive: %s" % archive)
    for n in notes:
        print("note: " + n)
    if not args.yes:
        print("dry run only: nothing archived or closed; rerun with --yes once the user approves")
        return 0

    closed = []
    for reason, ids in batches:
        try:
            call(exe, close_args(ids, archive, reason))
        except RuntimeError as e:
            print("STOPPED at %r: %s" % (reason, e))
            print("closed before stopping: %d tabs" % len(closed))
            return 2
        closed.extend(ids)
        print("closed: %3d  %s" % (len(ids), reason))

    try:
        after = call(exe, ["browser", "snapshot"])
    except RuntimeError as e:
        print("post-check could not run: %s" % e)
        return 2
    still_open = [tid for tid in closed if tid in {t["id"] for t in after["tabs"]}]
    if still_open:
        print("post-check FAILED: %d closed tab(s) are still open: %s"
              % (len(still_open), ", ".join(tabs[t]["title"][:40] for t in still_open[:5])))
        return 2
    print("post-check OK: closed %d tabs, %d remain; archived to %s"
          % (len(closed), len(after["tabs"]), archive))
    return 0


if __name__ == "__main__":
    sys.exit(main())
