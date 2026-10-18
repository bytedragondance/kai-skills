#!/usr/bin/env python3
"""Apply an approved tab plan through firefox-agent, with checks before and after.

Usage: python3 -I scripts/tab_apply.py PLAN.json [--dry-run-only]

The plan format is documented in SKILL.md. Before any write, every tab must exist
in a fresh snapshot, be neither pinned nor stashed, and appear once; every dry run
must succeed without groupsAtRisk (unless the plan allows it). After the writes,
each tab must sit in its target group and the total tab count must be unchanged.

Exit codes: 0 applied (or dry run only), 1 refused before any write, 2 stopped or failed.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys


def firefox_agent():
    return shutil.which("firefox-agent") or os.path.expanduser("~/.local/bin/firefox-agent")


def call(exe, args):
    proc = subprocess.run([exe, *args], capture_output=True, text=True)
    try:
        # firefox-agent prints results on stdout and JSON errors on stderr.
        data = json.loads(proc.stdout if proc.returncode == 0 else proc.stderr)
    except json.JSONDecodeError:
        raise RuntimeError("no JSON from `firefox-agent %s`: %s"
                           % (" ".join(args), (proc.stderr or proc.stdout)[:300]))
    if "error" in data:
        err = data["error"]
        raise RuntimeError("%s: %s" % (err.get("code"), err.get("message")))
    return data


def steps_from(plan):
    steps = []
    for op in plan.get("group_add", []):
        steps.append({
            "label": "add %d tab(s) to group %s" % (len(op["tabs"]), op["group"]),
            "args": ["group", "add", str(op["group"])] + [str(t) for t in op["tabs"]],
        })
    for op in plan.get("group_create", []):
        steps.append({
            "label": "create group %r with %d tab(s)" % (op["title"], len(op["tabs"])),
            "args": ["group", "create"] + [str(t) for t in op["tabs"]]
                    + ["--title", op["title"], "--color", op.get("color", "grey")],
        })
    return steps


def problems_with(plan, snap):
    tabs = {t["id"]: t for t in snap["tabs"]}
    groups = {g["id"]: g for g in snap["groups"]}
    titles = {g["title"] for g in snap["groups"]}
    found, seen = [], set()
    for op in plan.get("group_add", []):
        if op["group"] not in groups:
            found.append("group %s does not exist" % op["group"])
        if not op["tabs"]:
            found.append("group_add for group %s has no tabs" % op["group"])
    for op in plan.get("group_create", []):
        if op["title"] in titles:
            found.append("a group titled %r already exists; add to it with group_add" % op["title"])
        if not op["tabs"]:
            found.append("group_create %r has no tabs" % op["title"])
    for op in plan.get("group_add", []) + plan.get("group_create", []):
        for tid in op["tabs"]:
            t = tabs.get(tid)
            if t is None:
                found.append("tab %s is not in the current snapshot" % tid)
            elif t["pinned"]:
                found.append("tab %s is pinned: %s" % (tid, t["title"][:50]))
            elif t["hidden"]:
                found.append("tab %s is stashed: %s" % (tid, t["title"][:50]))
            elif t.get("incognito") or t.get("cookieStoreId", "firefox-default") != "firefox-default":
                found.append("tab %s is in container %s; it keeps its own group: %s"
                             % (tid, t.get("cookieStoreId"), t["title"][:50]))
            if tid in seen:
                found.append("tab %s appears twice in the plan" % tid)
            seen.add(tid)
    return found


def post_check(plan, before, after):
    ok = True
    if len(after["tabs"]) != len(before["tabs"]):
        print("post-check FAILED: tab count changed from %d to %d"
              % (len(before["tabs"]), len(after["tabs"])))
        ok = False
    tabs = {t["id"]: t for t in after["tabs"]}
    groups = {g["id"]: g for g in after["groups"]}
    before_titles = {g["id"]: g["title"] for g in before["groups"]}
    for op in plan.get("group_add", []):
        for tid in op["tabs"]:
            t = tabs.get(tid)
            if t is None or t["groupId"] != op["group"]:
                print("post-check FAILED: tab %s is not in group %r"
                      % (tid, before_titles.get(op["group"], op["group"])))
                ok = False
    for op in plan.get("group_create", []):
        landed = set()
        for tid in op["tabs"]:
            t = tabs.get(tid)
            landed.add(groups[t["groupId"]]["title"] if t and t["groupId"] in groups else None)
        if landed != {op["title"]}:
            print("post-check FAILED: tabs for %r ended up in %s"
                  % (op["title"], sorted(str(x) for x in landed)))
            ok = False
    if not ok:
        return 2
    print("post-check OK: %d tabs, total unchanged" % len(after["tabs"]))
    for gid in sorted({op["group"] for op in plan.get("group_add", [])}):
        if gid in groups:
            count = sum(1 for t in after["tabs"] if t["groupId"] == gid)
            print("  group %r now has %d tabs" % (groups[gid]["title"], count))
    return 0


def main():
    ap = argparse.ArgumentParser(description="Apply an approved Firefox tab plan with checks.")
    ap.add_argument("plan", help="path to the plan JSON")
    ap.add_argument("--dry-run-only", action="store_true", help="validate and dry-run; write nothing")
    args = ap.parse_args()
    with open(args.plan, encoding="utf-8") as f:
        plan = json.load(f)
    exe = firefox_agent()

    try:
        before = call(exe, ["browser", "snapshot"])
    except RuntimeError as e:
        print("refused, nothing written: snapshot failed: %s" % e)
        return 1
    problems = problems_with(plan, before)
    if problems:
        print("refused, nothing written:")
        for p in problems:
            print("  - " + p)
        return 1

    steps = steps_from(plan)
    if not steps:
        print("refused, nothing written: plan has no steps")
        return 1
    for s in steps:
        try:
            res = call(exe, s["args"] + ["--dry-run"])
        except RuntimeError as e:
            print("refused, nothing written: dry run failed for %s: %s" % (s["label"], e))
            return 1
        risk = res.get("groupsAtRisk") or []
        if risk and not plan.get("allow_groups_at_risk"):
            print("refused, nothing written: %s would empty group(s) %s"
                  % (s["label"], json.dumps(risk, ensure_ascii=False)[:300]))
            return 1
        print("dry run ok: %s" % s["label"])
    if args.dry_run_only:
        print("dry run only: nothing written")
        return 0

    applied = []
    for s in steps:
        try:
            res = call(exe, s["args"])
        except RuntimeError as e:
            print("STOPPED at: %s: %s" % (s["label"], e))
            print("applied before stopping: %s" % ("; ".join(applied) or "nothing"))
            return 2
        applied.append(s["label"])
        note = res.get("removedGroups")
        print("applied: %s%s" % (s["label"], ("  (removed groups: %s)" % note) if note else ""))

    try:
        after = call(exe, ["browser", "snapshot"])
    except RuntimeError as e:
        print("post-check could not run: %s" % e)
        return 2
    return post_check(plan, before, after)


if __name__ == "__main__":
    sys.exit(main())
