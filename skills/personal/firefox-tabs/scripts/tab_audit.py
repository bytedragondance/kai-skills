#!/usr/bin/env python3
"""Read-only audit of open Firefox tabs, through firefox-agent.

Usage: python3 -I scripts/tab_audit.py [--json PATH]

Two buckets that must stay apart:
  重复 (DUP_GROUP): a copy of the same page stays open outside both buckets. Close directly.
  可关 (JUDGE_GROUP): closing is the user's call (stale, dead, logged-out, expired, or unsure).
Same host and path with a different query is printed as review only.
It never changes the browser.
"""

import argparse
import collections
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
from urllib.parse import parse_qsl, urlsplit

DUP_GROUP = "重复"
JUDGE_GROUP = "可关"

# Query parameters that never change the page. pli (Google Sheets) and IMS_SOURCE_SPECIFY
# (Bright Horizons) are site-specific source markers.
TRACKING_PARAM = re.compile(
    r"^(utm_\w+|ref|ref_|fbclid|gclid|srsltid|igshid|mc_\w+|pli|IMS_SOURCE_SPECIFY)$", re.I)
# A fragment that is a plain element id is only a scroll anchor. Fragments with "=", ";",
# "|" or "/" usually carry page state, so they stay significant.
ANCHOR = re.compile(r"^[A-Za-z][\w.-]*$")
DEAD_TITLE = re.compile(r"^(just a moment\.\.\.|page not found|404\b|access denied)", re.I)
THANK_YOU_TITLE = re.compile(r"^thank you for (downloading|visiting)", re.I)
LOGGED_OUT_PATH = re.compile(r"(logged[-_]?out|signed[-_]?out|logout)", re.I)
EXPIRED_TITLE = re.compile(r"^\[expired\]", re.I)
DEADLINE = re.compile(r"(20\d\d)[/.-](\d{1,2})[/.-](\d{1,2})\s*(截止|截至|deadline|ends?|expires?)", re.I)
NOT_INTERNAL = {"about:blank", "about:newtab", "about:home"}


def firefox_agent():
    return shutil.which("firefox-agent") or os.path.expanduser("~/.local/bin/firefox-agent")


def snapshot(exe):
    proc = subprocess.run([exe, "browser", "snapshot"], capture_output=True, text=True)
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        sys.exit("firefox-agent returned no JSON: " + (proc.stderr or proc.stdout)[:300])
    if "error" in data:
        err = data["error"]
        sys.exit("firefox-agent %s: %s %s" % (err.get("code"), err.get("message"), err.get("fix", "")))
    return data


def strict_key(url):
    """Same page: scheme, host (without www.), path, non-tracking query, and state-carrying fragment."""
    parts = urlsplit(url)
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    query = tuple(sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                         if not TRACKING_PARAM.match(k)))
    fragment = "" if (not parts.fragment or ANCHOR.match(parts.fragment)) else parts.fragment
    return (parts.scheme.lower(), host, parts.path.rstrip("/") or "/", query, fragment)


def page_key(url):
    parts = urlsplit(url)
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return (host, parts.path.rstrip("/") or "/")


def judgment_reason(tab, today):
    """Heuristic reason a tab may be closable. None if no rule applies."""
    title = (tab["title"] or "").strip()
    url = tab["url"]
    parts = urlsplit(url)
    if DEAD_TITLE.search(title):
        return "dead or challenge page"
    if LOGGED_OUT_PATH.search(parts.path):
        return "logged-out page"
    if THANK_YOU_TITLE.search(title):
        return "thank-you or download confirmation page"
    if EXPIRED_TITLE.search(title):
        return "title marks it expired"
    match = DEADLINE.search(title)
    if match:
        try:
            deadline = datetime.date(*map(int, match.group(1, 2, 3)))
        except ValueError:
            deadline = None
        if deadline and deadline < today:
            return "deadline %s has passed" % deadline.isoformat()
    if parts.scheme == "about" and url not in NOT_INTERNAL:
        return "browser-internal page"
    return None


def short(text, n=60):
    text = (text or "").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def main():
    ap = argparse.ArgumentParser(description="Read-only audit of open Firefox tabs.")
    ap.add_argument("--json", metavar="PATH", help="also write the full audit as JSON")
    args = ap.parse_args()

    data = snapshot(firefox_agent())
    tabs = data["tabs"]
    groups = {g["id"]: g for g in data["groups"]}
    today = datetime.date.today()

    def group_name(t):
        return groups[t["groupId"]]["title"] if t["groupId"] in groups else None

    def where(t):
        flags = (" pinned" if t["pinned"] else "") + (" stashed" if t["hidden"] else "")
        return "[%s%s]" % (group_name(t) or "ungrouped", flags)

    def in_bucket(t):
        return group_name(t) in (DUP_GROUP, JUDGE_GROUP)

    members = {gid: [] for gid in groups}
    ungrouped = []
    for t in tabs:
        (members[t["groupId"]] if t["groupId"] in members else ungrouped).append(t)
    counted = sum(len(ts) for ts in members.values()) + len(ungrouped)
    pinned = [t for t in tabs if t["pinned"]]
    stashed = [t for t in tabs if t["hidden"]]

    # 重复: one copy stays open outside both buckets; the others are close candidates.
    classes = collections.defaultdict(list)
    for t in tabs:
        # Same URL in another container is another login, not a copy.
        classes[(t.get("cookieStoreId"), strict_key(t["url"]))].append(t)
    duplicates = []  # (close, keep)
    judgment = {}    # tab id -> (tab, reason)
    for same in classes.values():
        if len(same) < 2:
            continue
        outside = sorted((t for t in same if not in_bucket(t)), key=lambda t: t["hidden"])
        if not outside:
            for t in same:
                if not (t["pinned"] or t["hidden"]):
                    judgment[t["id"]] = (t, "every copy sits in 重复/可关; decide which one stays")
            continue
        keep = outside[0]
        for t in same:
            if t is not keep and not (t["pinned"] or t["hidden"]):
                duplicates.append((t, keep))

    # 可关: heuristic matches, plus anything already in a bucket that the rules do not back.
    dup_ids = {t["id"] for t, _ in duplicates}
    for t in tabs:
        if t["pinned"] or t["hidden"] or t["id"] in dup_ids or t["id"] in judgment:
            continue
        reason = judgment_reason(t, today)
        if reason is None and group_name(t) == DUP_GROUP:
            reason = "in 重复 but no copy stays open outside 重复/可关"
        elif reason is None and group_name(t) == JUDGE_GROUP:
            reason = "in 可关; no rule matched, your call"
        if reason:
            judgment[t["id"]] = (t, reason)

    # Review: same host and path, but the query differs in a non-tracking way.
    by_path = collections.defaultdict(list)
    for t in tabs:
        by_path[page_key(t["url"])].append(t)
    review = [ts for ts in by_path.values() if len({strict_key(t["url"]) for t in ts}) > 1]

    print("Firefox: %d tabs, %d groups, %d pinned, %d stashed (hidden)"
          % (len(tabs), len(groups), len(pinned), len(stashed)))
    print("Counted %d of %d tabs (groups + ungrouped)" % (counted, len(tabs)))
    print("Summary: %d to close as 重复, %d to decide in 可关, %d review"
          % (len(duplicates), len(judgment), len(review)))
    print()
    print("Groups")
    for gid, ts in members.items():
        g = groups[gid]
        print("- %s  id=%s  %s  %d tabs, %d stashed%s" % (
            g["title"], gid, g["color"], len(ts), sum(t["hidden"] for t in ts),
            "  collapsed" if g["collapsed"] else ""))
    print()

    print("重复 — a copy stays open; close directly (%d)" % len(duplicates))
    for close, keep in duplicates:
        move = "" if group_name(close) == DUP_GROUP else "  (move into 重复)"
        print("- close id=%s %s %s%s" % (close["id"], where(close), short(close["title"]), move))
        print("    keep  id=%s %s %s" % (keep["id"], where(keep), short(keep["title"], 45)))
    print()

    print("可关 — your call, one by one (%d)" % len(judgment))
    for t, reason in judgment.values():
        move = "" if group_name(t) == JUDGE_GROUP else "  (move into 可关)"
        print("- id=%s %s %s — %s%s" % (t["id"], where(t), short(t["title"]), reason, move))
    print()

    print("Review — same host and path, different query; not duplicates by rule (%d)" % len(review))
    for ts in review:
        host, path = page_key(ts[0]["url"])
        print("- %s%s" % (host, path[:50]))
        for t in ts:
            print("    id=%s %s %s" % (t["id"], where(t), t["url"][:90]))
    print()

    print("Left alone by policy: %d pinned, %d stashed (stashed ids: %s)" % (
        len(pinned), len(stashed), ", ".join(str(t["id"]) for t in stashed) or "none"))

    if args.json:
        out = {
            "groups": [dict(groups[gid], tabs=[t["id"] for t in ts]) for gid, ts in members.items()],
            "duplicates": [{"close": c["id"], "keep": k["id"], "close_group": group_name(c),
                            "keep_group": group_name(k)} for c, k in duplicates],
            "judgment": [{"id": t["id"], "reason": r, "group": group_name(t)}
                         for t, r in judgment.values()],
            "review": [[t["id"] for t in ts] for ts in review],
            "left_alone": {"pinned": [t["id"] for t in pinned],
                           "stashed": [t["id"] for t in stashed]},
        }
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print("JSON written: %s" % args.json)


if __name__ == "__main__":
    main()
