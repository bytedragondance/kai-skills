#!/usr/bin/env python3
"""Sort open Firefox tabs into 事情 (things), review them on a one-off local page, record the
decisions in Obsidian, and turn them into a tab_apply.py plan.

Usage:
  python3 -I scripts/tab_review.py context [--vault V] --out CONTEXT.json
  python3 -I scripts/tab_review.py review PROPOSAL.json --out DECISIONS.json [--vault V] [--no-open]
  python3 -I scripts/tab_review.py plan DECISIONS.json --out PLAN.json [--allow-empty-groups]
  python3 -I scripts/tab_review.py shelve DECISIONS.json [--vault V] [--apply]

context  reads the browser and the vault's 20_Projects notes; the agent proposes things from it.
review   serves the review page on 127.0.0.1 and waits. When the user submits, it writes
         DECISIONS.json and the record note 00_Inbox/标签整理 <date>.md, then exits.
plan     resolves the decisions against a fresh snapshot (by URL, since tab IDs change across
         browser restarts) and writes a plan for tab_apply.py.
shelve   prints the 续点 (resume point) of every 搁置 thing; with --apply, after the user confirms,
         appends it to the thing's project note.

review writes only the record note; shelve --apply only appends 续点 sections to project notes.
Nothing here changes the browser.
"""

import argparse
import collections
import datetime
import http.server
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tab_audit import firefox_agent, judgment_reason, snapshot, strict_key  # noqa: E402

DEFAULT_VAULT = os.path.expanduser(
    "~/Library/Mobile Documents/iCloud~md~obsidian/Documents/LifeVault")
PAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "review.html")
INTENTS = ("调研", "事务", "追踪", "参考", "常驻", "残骸", "消遣", "重复")
# 事情 end; 主题 are long-lived topic collections; 清理 are pages with nothing worth keeping.
# 搁置: paused, may come back. Its 续点 goes to the project note and its tabs are archived and closed.
DECISIONS = {"事情": ("进行中", "做完", "搁置", "放弃", "待定"), "主题": ("保留", "待定"), "清理": ("关掉", "待定")}
CONFIDENCE = ("高", "中", "低")
FATES = (None, "关", "不动", "续点")  # per-tab override; 续点 (keep the link in the 续点) is for 搁置 only
DONE_GROUP = "做完"
DUP_GROUP = "重复"
SHELF_GROUP = "搁置"
TRACK_COLOR = {"生活": "green", "AI": "blue", "战略": "purple"}
UNSORTED = "未归类"
REVIEW_HOURS = 6


def frontmatter(path):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    fields = {}
    for line in text[4:end].splitlines():
        if ":" in line and not line.startswith(" "):
            k, v = line.split(":", 1)
            fields[k.strip()] = v.strip()
    return fields


def vault_projects(vault):
    folder = os.path.join(vault, "20_Projects")
    out = []
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".md"):
            continue
        fm = frontmatter(os.path.join(folder, name))
        if fm.get("type") != "project":
            continue
        out.append({"name": name[:-3], "status": fm.get("status", ""), "track": fm.get("track", ""),
                    "tags": fm.get("tags", ""), "updated": fm.get("updated", "")})
    return out


def age_days(tab):
    return int((time.time() * 1000 - tab["lastAccessed"]) / 864e5)


def groupable(tab):
    return left_alone_reason(tab) is None


def left_alone_reason(tab):
    """Why a tab must not be moved, or None. Container and private tabs keep their own
    cookie jar (a separate login, like a profile), so they never share a group with others."""
    if tab["pinned"]:
        return "pinned"
    if tab["hidden"]:
        return "stashed"
    if tab.get("incognito") or tab.get("cookieStoreId") == "firefox-private":
        return "private window"
    if tab.get("cookieStoreId", "firefox-default") != "firefox-default":
        return "container " + tab["cookieStoreId"]
    if is_review_page(tab):
        return "review page"
    return None


def is_review_page(tab):
    """This skill's own review page, open in the browser while the user reviews."""
    return tab["url"].startswith("http://127.0.0.1:") and "?t=" in tab["url"]


def destination(thing, tab):
    """Group title a tab should end up in, or None to leave it where it is."""
    fate, decision = tab.get("fate"), thing["decision"]
    if fate == "不动" or decision == "待定":
        return None
    if fate == "关":
        return DONE_GROUP
    if thing["kind"] == "清理":
        return DUP_GROUP if thing["intent"] == "重复" else DONE_GROUP
    if decision == "搁置":
        return SHELF_GROUP
    if decision in ("进行中", "保留"):
        return thing["title"]
    return DONE_GROUP


def cmd_context(args):
    snap = snapshot(firefox_agent())
    groups = {g["id"]: g["title"] for g in snap["groups"]}
    today = datetime.date.today()
    copies = collections.defaultdict(list)
    for t in snap["tabs"]:
        copies[(t.get("cookieStoreId"), strict_key(t["url"]))].append(t["id"])
    tabs = []
    for t in snap["tabs"]:
        same = copies[(t.get("cookieStoreId"), strict_key(t["url"]))]
        tabs.append({
            "id": t["id"], "title": t["title"], "url": t["url"], "group": groups.get(t["groupId"]),
            "age_days": age_days(t), "pinned": t["pinned"], "stashed": t["hidden"],
            "container": t.get("cookieStoreId"), "left_alone": left_alone_reason(t),
            "same_page_as": [i for i in same if i != t["id"]],
            "hint": judgment_reason(t, today),
        })
    out = {"taken": today.isoformat(), "projects": vault_projects(args.vault), "tabs": tabs}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    left = sum(1 for t in snap["tabs"] if not groupable(t))
    print("context: %d tabs (%d left alone: pinned, stashed, container, or private), %d projects -> %s"
          % (len(tabs), left, len(out["projects"]), args.out))


def check_things(things, projects, tabs=None):
    """Problems with a list of things. tabs, when given, maps id -> live tab."""
    problems, seen = [], set()
    for thing in things:
        title = (thing.get("title") or "").strip()
        if not title:
            problems.append("a thing has no title")
        if thing.get("project") and thing["project"] not in projects:
            problems.append("thing %r: no project note named %r" % (title, thing["project"]))
        if thing.get("intent") not in INTENTS:
            problems.append("thing %r: intent must be one of %s" % (title, "/".join(INTENTS)))
        if thing.get("kind") not in DECISIONS:
            problems.append("thing %r: kind must be one of %s" % (title, "/".join(DECISIONS)))
        elif thing.get("decision") not in DECISIONS[thing["kind"]]:
            problems.append("thing %r: a %s's decision must be one of %s"
                            % (title, thing["kind"], "/".join(DECISIONS[thing["kind"]])))
        if thing.get("confidence") not in CONFIDENCE:
            problems.append("thing %r: confidence must be one of %s" % (title, "/".join(CONFIDENCE)))
        if not isinstance(thing.get("resume", ""), str):
            problems.append("thing %r: resume must be text" % title)
        for entry in thing["tabs"]:
            tid = entry["id"]
            if entry.get("fate") not in FATES:
                problems.append("tab %s: fate must be 关, 不动, 续点, or absent" % tid)
            elif entry.get("fate") == "续点" and thing.get("decision") != "搁置":
                problems.append("tab %s: fate 续点 only fits a 搁置 thing" % tid)
            if tabs is not None and tid not in tabs:
                problems.append("tab %s is not open" % tid)
            elif tabs is not None and not groupable(tabs[tid]):
                problems.append("tab %s is left alone (%s); leave it out" % (tid, left_alone_reason(tabs[tid])))
            if tid in seen:
                problems.append("tab %s appears in two things" % tid)
            seen.add(tid)
    return problems, seen


def record_note(vault, date, things, taken):
    """Write the decisions as a plain Obsidian note. Returns its path."""
    total = sum(len(t["tabs"]) for t in things)
    lines = ["---", "type: tab-review", "created: %s" % date, "status: decided", "---", "",
             "# 标签整理 %s" % date, "",
             "快照 %s，%d 个标签，%d 项。`决定` 是你在审查页里定的；标了「关」或「不动」的标签不跟着决定走；搁置的事带着续点，「续点」标签的链接写在续点里。"
             % (taken, total, len(things)), ""]
    for kind in DECISIONS:
        group = [t for t in things if t["kind"] == kind]
        if not group:
            continue
        order = {d: i for i, d in enumerate(DECISIONS[kind])}
        lines += ["## %s" % kind, ""]
        for thing in sorted(group, key=lambda t: order[t["decision"]]):
            lines.append("### %s" % thing["title"])
            if thing.get("project"):
                lines.append("- 项目:: [[%s]]" % thing["project"])
            lines.append("- 意图:: %s" % thing["intent"])
            lines.append("- 决定:: %s" % thing["decision"])
            if thing.get("note"):
                lines.append("- AI:: %s" % thing["note"])
            lines.append("")
            for tab in thing["tabs"]:
                title = (tab["title"] or tab["url"]).replace("[", "［").replace("]", "］").replace("\n", " ")
                fate = (" · **%s**" % tab["fate"]) if tab.get("fate") else ""
                lines.append("- [%s](<%s>) · %s天%s" % (title, tab["url"], tab.get("age", "?"), fate))
            lines.append("")
            if thing["decision"] == "搁置":
                lines += resume_lines(thing, date)
    path = os.path.join(vault, "00_Inbox", "标签整理 %s.md" % date)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


def resume_lines(thing, date):
    """The 续点 section for a 搁置 thing: the user's resume text plus the links marked 续点."""
    lines = ["#### 续点（%s 搁置）" % date, ""]
    text = (thing.get("resume") or "").strip()
    lines += text.splitlines() if text else ["- （没写续点）"]
    links = [t for t in thing["tabs"] if t.get("fate") == "续点"]
    if links:
        lines += ["", "下次从这些开始："]
        for tab in links:
            title = (tab["title"] or tab["url"]).replace("[", "［").replace("]", "］").replace("\n", " ")
            lines.append("- [%s](<%s>)" % (title, tab["url"]))
    return lines + [""]


def cmd_review(args):
    with open(args.proposal, encoding="utf-8") as f:
        proposal = json.load(f)
    snap = snapshot(firefox_agent())
    tabs = {t["id"]: t for t in snap["tabs"]}
    group_title = {g["id"]: g["title"] for g in snap["groups"]}
    projects = {p["name"] for p in vault_projects(args.vault)}
    problems, seen = check_things(proposal["things"], projects, tabs)
    if problems:
        print("refused, nothing served:")
        for p in problems:
            print("  - " + p)
        return 1

    things = [dict(t) for t in proposal["things"]]
    missing = [t["id"] for t in snap["tabs"] if groupable(t) and t["id"] not in seen]
    if missing:
        things.append({"kind": "事情", "title": UNSORTED, "intent": "残骸", "decision": "待定", "confidence": "低",
                       "note": "提议里没有覆盖到的标签", "tabs": [{"id": i} for i in missing]})
    for thing in things:
        thing["tabs"] = [{"id": e["id"], "title": tabs[e["id"]]["title"], "url": tabs[e["id"]]["url"],
                          "age": age_days(tabs[e["id"]]), "group": group_title.get(tabs[e["id"]]["groupId"]),
                          "why": e.get("why", ""), "fate": e.get("fate")} for e in thing["tabs"]]
        thing["resume"] = thing.get("resume", "")

    token = secrets.token_urlsafe(16)
    date = datetime.date.today().isoformat()
    data = {"things": things, "intents": INTENTS, "decisions": DECISIONS, "token": token, "taken": date,
            "vaultName": os.path.basename(os.path.normpath(args.vault))}
    with open(PAGE, encoding="utf-8") as f:
        page = f.read().replace("/*DATA*/", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
    page = page.encode("utf-8")
    state = {"done": False}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def reply(self, code, body, ctype="application/json; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def authorized(self):
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            return secrets.compare_digest(query.get("t", [""])[0], token)

        def do_GET(self):
            if urllib.parse.urlsplit(self.path).path == "/" and self.authorized():
                self.reply(200, page, "text/html; charset=utf-8")
            else:
                self.reply(404, b'{"error": "not found"}')

        def do_POST(self):
            if urllib.parse.urlsplit(self.path).path != "/submit" or not self.authorized():
                return self.reply(403, b'{"error": "forbidden"}')
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                submitted = body["things"]
                problems, _ = check_things(submitted, projects)
                if problems:
                    raise ValueError("; ".join(problems[:3]))
                with open(args.out, "w", encoding="utf-8") as f:
                    json.dump({"taken": date, "things": submitted}, f, ensure_ascii=False, indent=1)
                note = record_note(args.vault, date, submitted, date)
            except (ValueError, KeyError, TypeError) as e:
                return self.reply(400, json.dumps({"error": str(e)}, ensure_ascii=False).encode())
            rel = os.path.relpath(note, args.vault)
            link = "obsidian://open?vault=%s&file=%s" % (
                urllib.parse.quote(data["vaultName"]), urllib.parse.quote(rel[:-3]))
            self.reply(200, json.dumps({"ok": True, "obsidian": link}).encode())
            state.update(done=True, note=note)

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    server.timeout = 1
    url = "http://127.0.0.1:%d/?t=%s" % (server.server_address[1], token)
    print("review page: %s" % url, flush=True)
    print("%d things, %d tabs. Waiting for the user to submit (up to %d hours)."
          % (len(things), sum(len(t["tabs"]) for t in things), REVIEW_HOURS), flush=True)
    if not args.no_open:
        subprocess.run(["open", url], check=False)
    deadline = time.time() + REVIEW_HOURS * 3600
    while not state["done"] and time.time() < deadline:
        server.handle_request()
    server.server_close()
    if not state["done"]:
        print("timed out; nothing written")
        return 2
    print("decisions: %s" % args.out)
    print("record note: %s" % state["note"])
    return 0


def cmd_plan(args):
    with open(args.decisions, encoding="utf-8") as f:
        things = json.load(f)["things"]
    snap = snapshot(firefox_agent())
    tabs = {t["id"]: t for t in snap["tabs"]}
    by_url = collections.defaultdict(list)
    for t in snap["tabs"]:
        by_url[t["url"]].append(t["id"])
    groups_by_title = collections.defaultdict(list)
    for g in snap["groups"]:
        groups_by_title[g["title"]].append(g)
    group_title = {g["id"]: g["title"] for g in snap["groups"]}

    targets = collections.OrderedDict()  # group title -> (color, [tab ids])
    used, notes = set(), []
    for thing in things:
        color = "grey"
        if thing.get("project"):
            fm_path = os.path.join(args.vault, "20_Projects", thing["project"] + ".md")
            if os.path.exists(fm_path):
                color = TRACK_COLOR.get(frontmatter(fm_path).get("track"), "grey")
        if thing["kind"] == "主题":
            color = "cyan"
        for item in thing["tabs"]:
            target = destination(thing, item)
            if target is None:
                continue
            tid = item["id"]
            if tid not in tabs or tabs[tid]["url"] != item["url"] or tid in used:
                spare = [i for i in by_url.get(item["url"], []) if i not in used]
                tid = spare[0] if spare else None
            if tid is None:
                notes.append("%s: not open any more: %s" % (thing["title"], (item["title"] or "")[:50]))
                continue
            used.add(tid)
            t = tabs[tid]
            if not groupable(t):
                notes.append("%s: left alone (%s): %s" % (thing["title"], left_alone_reason(t), t["title"][:50]))
                continue
            if group_title.get(t["groupId"]) == target:
                continue
            tcolor = {DONE_GROUP: "red", DUP_GROUP: "grey", SHELF_GROUP: "yellow"}.get(target, color)
            targets.setdefault(target, (tcolor, []))[1].append(tid)

    plan = {"group_add": [], "group_create": [], "allow_groups_at_risk": args.allow_empty_groups}
    for title, (color, ids) in targets.items():
        existing = groups_by_title.get(title)
        if existing:
            if len(existing) > 1:
                notes.append("%d groups are titled %r; using id %s" % (len(existing), title, existing[0]["id"]))
            plan["group_add"].append({"group": existing[0]["id"], "tabs": ids})
        else:
            plan["group_create"].append({"title": title, "color": color, "tabs": ids})
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)

    moving = {tid for _, ids in targets.values() for tid in ids}
    print("plan: %s" % args.out)
    for title, (color, ids) in targets.items():
        verb = "add to" if title in groups_by_title else "create"
        print("- %s %r (%s): %d tabs" % (verb, title, color, len(ids)))
    emptied = [title for gid, title in group_title.items()
               if all(t["id"] in moving for t in snap["tabs"] if t["groupId"] == gid)
               and title not in targets]
    if emptied:
        print("groups that will be emptied, and so deleted by Firefox: %s" % ", ".join(emptied))
        if not args.allow_empty_groups:
            print("  tab_apply.py refuses this unless the plan is rebuilt with --allow-empty-groups")
    for n in notes:
        print("note: " + n)
    return 0


def cmd_shelve(args):
    with open(args.decisions, encoding="utf-8") as f:
        decisions = json.load(f)
    date = decisions.get("taken") or datetime.date.today().isoformat()
    shelved = [t for t in decisions["things"] if t["decision"] == "搁置"]
    if not shelved:
        print("no 搁置 things")
        return 0
    written = []
    for thing in shelved:
        # In a project note the 续点 is a level-2 section; the record note nests it under the thing.
        heading, *body = resume_lines(thing, date)
        section = ["## " + heading.lstrip("# ")] + body
        path = os.path.join(args.vault, "20_Projects", (thing.get("project") or "") + ".md")
        where = os.path.relpath(path, args.vault) if thing.get("project") and os.path.exists(path) else None
        print("=== %s -> %s" % (thing["title"], where or "no project note; the 续点 stays in the record note only"))
        print("\n".join(section))
        if not (args.apply and where):
            continue
        with open(path, encoding="utf-8") as f:
            current = f.read()
        if section[0] in current:
            print("(already in %s; skipped)" % where)
            continue
        with open(path, "a", encoding="utf-8") as f:
            f.write(("" if current.endswith("\n") else "\n") + "\n" + "\n".join(section))
        written.append(where)
    if args.apply:
        print("appended to: %s" % (", ".join(written) or "nothing"))
    else:
        print("preview only: nothing written; rerun with --apply once the user confirms")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Firefox tabs grouped by thing: context, review, plan, shelve.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("context", "review", "plan", "shelve"):
        p = sub.add_parser(name)
        p.add_argument("--vault", default=os.environ.get("FIREFOX_TABS_VAULT", DEFAULT_VAULT))
        if name != "shelve":
            p.add_argument("--out", required=True)
        if name == "review":
            p.add_argument("proposal")
            p.add_argument("--no-open", action="store_true", help="print the URL without opening it")
        elif name == "plan":
            p.add_argument("decisions")
            p.add_argument("--allow-empty-groups", action="store_true")
        else:
            p.add_argument("decisions")
            p.add_argument("--apply", action="store_true", help="append to project notes; only after the user confirms")
    args = ap.parse_args()
    return {"context": cmd_context, "review": cmd_review, "plan": cmd_plan, "shelve": cmd_shelve}[args.cmd](args) or 0


if __name__ == "__main__":
    sys.exit(main())
