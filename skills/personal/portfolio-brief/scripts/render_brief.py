"""Render one brief into matching local HTML and a complete Markdown report.

Usage: python3 -I render_brief.py BRIEF.json SCAN.json
Prints the HTML path; the Markdown report has the same stem and .md suffix.
Writes only under $TMPDIR/portfolio-brief/.

Layout: what needs the user (one batched list) → one project table grouped by
whose turn it is, each row expandable to its detail → a small capacity panel →
notes on coverage. Every project fact appears in one place only.
"""
import datetime as dt
import copy
import html
import json
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

MODES = {"proceed": "可推进", "feedback": "等使用反馈", "paused": "暂停"}
GROUPS = {"decide": "等你决定", "proceed": "可以推进", "feedback": "用的时候顺便看", "paused": "暂停", "unknown": "状态未知"}
CAPACITY = {"abundant": "充裕", "scarce": "紧张"}
ATTN = {"attn:light": "看一眼", "attn:read": "要读材料", "attn:focus": "要专门安排"}
DECISION_ATTN = {"light": "attn:light", "read": "attn:read", "focus": "attn:focus"}
NEEDS = {"needs-human:decision": "决定", "needs-human:acceptance": "验收", "needs-human:feedback": "使用反馈"}
SIZE_ORDER = {"size:s": 0, "size:m": 1, "size:l": 2}
LABELS = {"mainline": "主线", "size:s": "额度小", "size:m": "额度中", "size:l": "额度大", "gpu": "本地 GPU"}
SCAN_ERRORS = {
    "Upstream comparison unavailable": "没有可比较的 upstream，领先/落后未知（未联网刷新）",
    "Git repository could not be established": "无法确认 Git 仓库，Git 情况未知",
    "Last commit unavailable": "读不到最近提交（可能还没有提交）",
    "Last commit date could not be parsed": "最近提交日期无法解析",
    "git status failed": "git status 失败，未提交数量未知",
    "Current branch could not be read": "读不到当前分支",
    "Backlog JSON listing failed": "Backlog 任务列表读取失败，任务状态未知",
    "Backlog CLI listing failed": "Backlog 清单读取失败，任务状态未知",
}

CSS = """
:root{--bg:#fbfaf7;--card:#fff;--text:#2c2c2a;--muted:#6b6a65;--line:#e3e1d9;--soft:#f3f1ea;--accent:#534ab7;--accentbg:#eeedfe;--warn:#854f0b;--warnbg:#faeeda;--ok:#3b6d11;--okbg:#eaf3de}
@media (prefers-color-scheme:dark){:root{--bg:#1f1f1d;--card:#2a2a28;--text:#ecebe6;--muted:#a3a29b;--line:#3d3d3a;--soft:#323230;--accent:#afa9ec;--accentbg:#26215c;--warn:#fac775;--warnbg:#412402;--ok:#c0dd97;--okbg:#173404}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.6 -apple-system,"PingFang SC",sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:22px;font-weight:500;margin:0}h2{font-size:17px;font-weight:500;margin:32px 0 10px}
h3{font-size:14px;font-weight:500;margin:14px 0 4px;color:var(--muted)}
a{color:var(--accent)}
.muted{color:var(--muted)}.small{font-size:13px}
.lede{margin:6px 0 0}
.chip{display:inline-block;font-size:12px;line-height:20px;padding:0 8px;border-radius:10px;background:var(--soft);color:var(--muted);margin:0 4px 2px 0;white-space:nowrap}
.chip.accent{background:var(--accentbg);color:var(--accent)}.chip.warn{background:var(--warnbg);color:var(--warn)}.chip.ok{background:var(--okbg);color:var(--ok)}
.asks{list-style:none;padding:0;margin:0}
.asks{background:var(--card);border:1px solid var(--line);border-radius:12px;counter-reset:ask}
.asks li{padding:8px 16px;border-top:1px solid var(--line);counter-increment:ask}.asks li:first-child{border-top:0}
.asks summary{list-style:none;cursor:pointer}.asks summary::-webkit-details-marker{display:none}
.asks summary::before{content:counter(ask) ".";color:var(--muted);margin-right:6px}
.asks .q{font-weight:500;margin-right:4px}
.clamp{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.asks details[open] .clamp{display:none}
.why{color:var(--muted);font-size:13px;margin-top:2px}
.src{color:var(--muted);font-size:12px}.src a{color:inherit}
.board{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden}
.grid{display:grid;grid-template-columns:170px minmax(0,1fr) 150px 64px 180px;gap:14px;padding:10px 16px;align-items:start}
.head{font-size:12px;color:var(--muted)}
.group{padding:6px 16px;font-size:13px;color:var(--muted);background:var(--soft);border-top:1px solid var(--line)}
details.row{border-top:1px solid var(--line)}
details.row>summary{list-style:none;cursor:pointer}
details.row>summary::-webkit-details-marker{display:none}
details.row>summary:hover,details.row[open]>summary{background:var(--soft)}
.proj b{font-weight:500}.proj .caret{display:inline-block;width:14px;color:var(--muted);transition:transform .15s}
details.row[open] .caret{transform:rotate(90deg)}
.detail{padding:4px 16px 16px 30px;border-top:1px dashed var(--line)}
.detail ul{margin:2px 0;padding-left:18px}
table{border-collapse:collapse;width:100%}td,th{text-align:left;vertical-align:top;padding:6px 8px;border-top:1px solid var(--line);font-size:14px}
th{font-weight:500;color:var(--muted);font-size:12px;border-top:0}
.panel{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.box{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 16px}
.box h3{margin-top:0}.box.now{border-color:var(--accent)}
.box ul{margin:4px 0;padding-left:18px}
.notes{color:var(--muted);font-size:13px}.notes ul{padding-left:18px}
@media (max-width:760px){
 .grid{grid-template-columns:1fr;gap:4px}.head{display:none}
 .c[data-label]::before{content:attr(data-label) "：";color:var(--muted);font-size:12px}
 .detail{padding-left:16px}.panel{grid-template-columns:1fr}
}
"""


def e(x):
    return html.escape(str(x)) if x not in (None, "") else '<span class="muted">未知</span>'


def short_date(value, year):
    """'2026-10-18' → '10/18' within the observation year; None stays None."""
    if not value:
        return None
    d = dt.date.fromisoformat(str(value)[:10])
    return f"{d.month}/{d.day}" if d.year == year else d.isoformat()


def local_time(value):
    t = dt.datetime.fromisoformat(value).astimezone()
    return f"{t.month}/{t.day} {t:%H:%M}"


def source_links(sources, root, observed=None, year=None):
    """Short file:line links; the full path stays in the link target and tooltip."""
    parts = []
    for s in sources:
        full = (Path(root) / s["path"]).resolve()
        date = short_date(s["source_date"], year) or "未注明日期"
        checked = "" if s["observed_at"] == observed else f"，核对于 {e(s['observed_at'])}"
        parts.append(f'<a href="{html.escape(full.as_uri(), quote=True)}#L{s["line"]}" title="{html.escape(str(full), quote=True)}:{s["line"]}">'
                     f'{e(Path(s["path"]).name)}:{s["line"]}</a>（{e(date)}{checked}）')
    return f'<span class="src">{" · ".join(parts)}</span>' if parts else ""


def check_sources(sources, root):
    if not isinstance(sources, list) or not sources:
        raise ValueError("Each decision needs at least one dated source")
    for s in sources:
        if not isinstance(s, dict):
            raise ValueError("Each source must be an object")
        rel = s.get("path")
        if not isinstance(rel, str) or not rel or Path(rel).is_absolute() or ".." in Path(rel).parts or ":" in rel:
            raise ValueError("Source must be a project-relative file path")
        path = (Path(root) / rel).resolve()
        if not path.is_relative_to(Path(root).resolve()) or not path.is_file():
            raise ValueError("Source must exist inside its allowlisted project")
        if type(s.get("line")) is not int or s["line"] < 1:
            raise ValueError("Source line must be a positive integer")
        if "source_date" not in s:
            raise ValueError("Source date is required; use null when unknown")
        if s["source_date"] is not None:
            dt.date.fromisoformat(s["source_date"])
        observed = dt.datetime.fromisoformat(s["observed_at"])
        if observed.tzinfo is None:
            raise ValueError("Source observation time needs a timezone")


def prepare_brief(brief, scan):
    """Join narrative to scan facts; reject omissions and hand-copied fact fields."""
    by_alias = {}
    for p in scan["projects"]:
        if not p.get("alias") or p["alias"] in by_alias:
            raise ValueError("Duplicate or missing scan alias")
        by_alias[p["alias"]] = p
    aliases = [p["alias"] for p in brief["projects"]]
    if len(aliases) != len(set(aliases)) or set(aliases) != set(by_alias):
        raise ValueError("Brief must cover every scan alias exactly once, without extra projects")
    b = copy.deepcopy(brief)
    for p in b["projects"]:
        if set(p) - {"alias", "workstreams", "unknowns", "today"}:
            raise ValueError("Do not copy Git/count/date/domain facts into the brief; they come from SCAN.json")
        observed = by_alias[p["alias"]]
        p.update({key: copy.deepcopy(observed.get(key)) for key in ("path", "domain", "git", "backlog", "backlog_tasks")})
        p["observed_at"] = scan["observed_at"]
        p.setdefault("unknowns", [])
        if p.get("today") is not None:
            today = p["today"]
            if not isinstance(today, dict) or today.get("mode") not in MODES:
                raise ValueError("Today's result needs a supported mode")
            if any(not isinstance(today.get(key), str) or not today[key].strip()
                   for key in ("outcome", "reason")):
                raise ValueError("Today's result needs an outcome and its reason")
        if not observed["exists"]:
            p["unknowns"].append("白名单路径不存在；项目状态未知")
        for w in p.get("workstreams", []):
            if w.get("sources"):
                check_sources(w["sources"], p["path"])
    if b.get("capacity") not in (None, *CAPACITY):
        raise ValueError("capacity must be abundant, scarce or null (as the user stated it)")
    for section_name in ("decisions", "advisory", "risks", "feedback", "parked"):
        for item in b.get(section_name, []):
            if item.get("project") not in by_alias:
                raise ValueError(f"{section_name}: project is outside this scan")
            if section_name in ("decisions", "feedback", "parked") or item.get("sources"):
                check_sources(item.get("sources"), by_alias[item["project"]]["path"])
            if section_name in ("decisions", "feedback", "parked") and has_tasks(by_alias[item["project"]]) and any(
                    Path(src["path"]).parts[:2] == ("backlog", "tasks") for src in item["sources"]):
                raise ValueError(f"{section_name}: Backlog tasks are classified from the scan; do not restate them in the brief")
            fields = {"feedback": ("question", "when"), "parked": ("item", "default")}.get(section_name, ())
            if any(not isinstance(item.get(key), str) or not item[key].strip() for key in fields):
                raise ValueError(f"{section_name}: missing description or timing/default")
            if section_name == "decisions" and item.get("attn") not in (None, *DECISION_ATTN):
                raise ValueError("decisions: attn must be light, read, focus or omitted")
    for p in b["projects"]:
        for t in (p.get("backlog_tasks") or {}).get("tasks") or []:
            t["sources"] = [{"path": t["path"], "line": 1, "observed_at": scan["observed_at"],
                             "source_date": (t.get("updatedAt") or "")[:10] or None}] if t.get("path") else []
            if t["sources"]:
                check_sources(t["sources"], p["path"])
    b["observed_at"] = scan["observed_at"]
    b["generated_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    return b


def has_tasks(p):
    return bool(p.get("backlog_tasks") and p["backlog_tasks"].get("tasks") is not None)


def task_views(b):
    """Classify Backlog tasks by status and labels (Attune convention v0 §9); no inference.

    `scarce` is the work an agent can do on the mainline now (In Progress, or a
    ready To Do). Waiting mainline tasks are already in `needs` or `feedback`:
    under scarce capacity the next step there is the user's, not a model run.
    """
    v = {"needs": [], "feedback": [], "parked": [], "abundant": [], "gpu": [], "scarce": [], "in_flight": {}, "conflicts": []}
    for p in b["projects"]:
        tasks = (p.get("backlog_tasks") or {}).get("tasks") or []
        for t in tasks:
            t["project"] = p["alias"]
            labels = set(t.get("labels") or [])
            if t["status"] == "Waiting":
                if "needs-human:feedback" in labels:
                    v["feedback"].append(t)
                else:
                    v["needs"].append(t)
            elif t["status"] == "Parked":
                v["parked"].append(t)
            elif t["status"] == "To Do" and "agent-ready" in labels and t.get("isReady"):
                if "irreversible" in labels:
                    v["conflicts"].append(t)
                else:
                    v["gpu" if "gpu" in labels else "abundant"].append(t)
            if t["status"] == "In Progress" and labels & set(ATTN):
                v["in_flight"][p["alias"]] = v["in_flight"].get(p["alias"], 0) + 1
        mainline = [t for t in tasks if "mainline" in (t.get("labels") or []) and "irreversible" not in t["labels"]
                    and (t["status"] == "In Progress" or (t["status"] == "To Do" and t.get("isReady")))]
        mainline.sort(key=lambda t: (t["status"] != "In Progress", size_rank(t)))
        v["scarce"] += mainline[:2]
    v["needs"].sort(key=lambda t: (attn_rank(t), "mainline" not in t["labels"], t["project"]))
    for key in ("abundant", "gpu"):
        v[key].sort(key=lambda t: ("mainline" not in t["labels"], bool(set(t["labels"]) & set(ATTN)), size_rank(t)))
    return v


def attn_rank(t):
    return min([list(ATTN).index(x) for x in t.get("labels") or [] if x in ATTN] or [len(ATTN)])


def size_rank(t):
    return min([SIZE_ORDER[x] for x in t.get("labels") or [] if x in SIZE_ORDER] or [len(SIZE_ORDER)])


def task_tags(t):
    """Plain-language tags; attention on unfinished work is what delivery will need."""
    labels = t.get("labels") or []
    later = t["status"] in ("To Do", "In Progress")
    tags = [NEEDS[x] for x in labels if x in NEEDS]
    tags += [("交付后" if later else "") + ATTN[x] for x in labels if x in ATTN]
    tags += [LABELS[x] for x in labels if x in LABELS]
    if t["status"] == "Waiting" and not set(labels) & set(NEEDS):
        tags.append("缺少 needs-human 标签，按待判断处理")
    return tags


def plain(text):
    return " ".join((text or "").replace("**", "").replace("`", "").split())


def lead(text, limit=160):
    """The opening sentences of a description, for a glance; the rest stays one click away."""
    text = plain(text)
    if len(text) <= limit:
        return text, ""
    cut = max(text.rfind(mark, 0, limit) for mark in "。；！？")
    cut = cut + 1 if cut > 40 else limit
    return text[:cut], text[cut:].strip()


def asks(b, v):
    """One batched list of what needs the user: Backlog Waiting tasks and document decisions."""
    items = []
    for t in v["needs"]:
        items.append({"project": t["project"], "question": t["title"], "why": plain(t.get("description")),
                      "attn": attn_rank(t), "mainline": "mainline" in t["labels"], "task": t,
                      "irreversible": "irreversible" in t["labels"],
                      "tags": [x for x in task_tags(t) if x not in LABELS.values()]})
    for d in b.get("decisions", []):
        rank = list(DECISION_ATTN).index(d["attn"]) if d.get("attn") else len(ATTN)
        why = "；".join(x for x in (d.get("why_now") and f'为什么现在：{d["why_now"]}',
                                    d.get("if_wait") and f'不处理会怎样：{d["if_wait"]}') if x)
        items.append({"project": d["project"], "question": d.get("question"), "why": why, "attn": rank,
                      "mainline": False, "sources": d["sources"], "irreversible": False,
                      "tags": ["决定"] + ([ATTN[DECISION_ATTN[d["attn"]]]] if d.get("attn") else [])})
    order = [p["alias"] for p in b["projects"]]
    return sorted(items, key=lambda i: (i["attn"], not i["mainline"], order.index(i["project"])))


def project_warnings(p):
    git = p.get("git") or {}
    backlog = p.get("backlog") or {}
    warnings = list(git.get("errors", []))
    warnings += (p.get("backlog_tasks") or {}).get("errors", [])
    if backlog.get("error"):
        warnings.append(backlog["error"])
    if backlog.get("truncated"):
        warnings.append(f'Backlog 清单不完整：仅展示 {backlog["displayed_chars"]} / {backlog["total_chars"]} 字符；不能据此判断没有其他待办或待决定事项')
    out = []
    for w in warnings:
        out.append(next((zh for en, zh in SCAN_ERRORS.items() if w.startswith(en)), w))
    return out


def label(p):
    return f'{p["alias"]} · {Path(p["path"]).name}'


class Context:
    """Everything a project row needs, computed once from the prepared brief."""

    def __init__(self, b):
        self.b = b
        self.v = task_views(b)
        self.asks = asks(b, self.v)
        self.year = dt.datetime.fromisoformat(b["observed_at"]).year
        self.observed = b["observed_at"]
        self.roots = {p["alias"]: p["path"] for p in b["projects"]}

    def of(self, key, alias):
        return [i for i in self.b.get(key, []) if i.get("project") == alias]

    def tasks(self, key, alias):
        return [t for t in self.v[key] if t["project"] == alias]

    def group(self, p):
        if any(a["project"] == p["alias"] for a in self.asks):
            return "decide"
        return p["today"]["mode"] if p.get("today") else "unknown"

    def counts(self, alias):
        return {"决定": sum(a["project"] == alias for a in self.asks),
                "顺便反馈": len(self.of("feedback", alias)) + len(self.tasks("feedback", alias)),
                "停放": len(self.of("parked", alias)) + len(self.tasks("parked", alias))}

    def latest(self, p):
        dates = [s["source_date"] for w in p.get("workstreams", []) for s in w.get("sources", [])]
        dates += [s["source_date"] for key in ("decisions", "feedback", "parked")
                  for i in self.of(key, p["alias"]) for s in i["sources"]]
        dates += [s["source_date"] for t in (p.get("backlog_tasks") or {}).get("tasks") or [] for s in t["sources"]]
        dates = [d for d in dates if d]
        return short_date(max(dates), self.year) if dates else None

    def other_tasks(self, alias, p):
        shown = {t["id"] for key in ("needs", "feedback", "parked", "scarce", "abundant", "gpu", "conflicts")
                 for t in self.tasks(key, alias)}
        return [t for t in (p.get("backlog_tasks") or {}).get("tasks") or [] if t["id"] not in shown]


# ---------- HTML ----------

def chips(tags, cls=""):
    return "".join(f'<span class="chip {cls}">{e(x)}</span>' for x in tags)


def task_li(t, ctx, detail=False):
    warn = '<span class="chip warn">不可逆</span>' if "irreversible" in (t.get("labels") or []) else ""
    desc = f'<div class="why">{e(plain(t.get("description")))}</div>' if detail and t.get("description") else ""
    src = task_link(t, ctx) if t["sources"] else '<span class="src">任务文件未知</span>'
    return f'<li>{e(t["title"])} {warn}{chips(task_tags(t))}{src}{desc}</li>'


def task_link(t, ctx):
    s = t["sources"][0]
    full = (Path(ctx.roots[t["project"]]) / s["path"]).resolve()
    date = short_date(s["source_date"], ctx.year) or "未注明日期"
    return (f'<span class="src"><a href="{html.escape(full.as_uri(), quote=True)}#L1" title="{html.escape(str(full), quote=True)}">'
            f'{e(t["id"])}</a>（{e(date)}）</span>')


def ask_li(a, ctx, roots):
    """One compact line per ask; the full material is one click away, never dropped."""
    tags = chips([a["project"]], "accent") + (chips(["不可逆"], "warn") if a["irreversible"] else "")
    tags += chips(a["tags"] + (["主线"] if a["mainline"] and "主线" not in a["tags"] else []))
    src = task_link(a["task"], ctx) if a.get("task") else source_links(a["sources"], roots[a["project"]], ctx.observed, ctx.year)
    why = f'<div class="why clamp">{e(a["why"])}</div>' if a["why"] else ""
    full = f'<div class="why">{e(a["why"])}</div>' if a["why"] else ""
    return (f'<li><details><summary><span class="q">{e(a["question"])}</span> {tags}{why}</summary>'
            f'{full}<div>{src}</div></details></li>')


def bullet_list(title, items):
    return f'<h3>{title}</h3><ul>{"".join(items)}</ul>' if items else ""


def project_detail(p, ctx):
    a = p["alias"]
    year, obs = ctx.year, ctx.observed
    parts = []
    if p.get("today"):
        parts.append(f'<h3>为什么是这一步</h3><div>{e(p["today"]["reason"])}</div>')
    ws = "".join(
        f"<tr><td>{e(w.get('name'))}</td><td>{e(w.get('state'))}</td><td>{e(w.get('next'))}</td>"
        f"<td>{source_links(w.get('sources', []), p['path'], obs, year)}</td></tr>"
        for w in p.get("workstreams", []))
    parts.append(f'<h3>工作线</h3><table><tr><th>工作线</th><th>现在怎样</th><th>下一步</th><th>依据</th></tr>{ws}</table>'
                 if ws else '<h3>工作线</h3><div class="muted">没有识别出工作线；没有记录不等于没有工作</div>')
    if has_tasks(p):
        abundant_only = [t for t in ctx.tasks("abundant", a) if t not in ctx.tasks("scarce", a)]
        parts.append(bullet_list("任务 · 主线下一步（额度紧张时只做这些）", [task_li(t, ctx) for t in ctx.tasks("scarce", a)]))
        parts.append(bullet_list("任务 · 额度多时再加（不需要你）", [task_li(t, ctx) for t in abundant_only]))
        parts.append(bullet_list("任务 · 依赖本地 GPU", [task_li(t, ctx) for t in ctx.tasks("gpu", a)]))
        parts.append(bullet_list("任务 · 标签冲突（同时标了 agent-ready 和 irreversible，未列入可推进）",
                                 [task_li(t, ctx) for t in ctx.tasks("conflicts", a)]))
        parts.append(bullet_list("任务 · 其他待办（未就绪或未标为可直接做）", [task_li(t, ctx) for t in ctx.other_tasks(a, p)]))
    fb = [f'<li>{e(f["question"])} <span class="muted">· {e(f["when"])}</span> {source_links(f["sources"], p["path"], obs, year)}</li>'
          for f in ctx.of("feedback", a)] + [task_li(t, ctx) for t in ctx.tasks("feedback", a)]
    parts.append(bullet_list("用的时候顺便看（不催）", fb))
    adv = [f'<li>{e(x.get("work"))}<div class="why">{e(x.get("why_no_human"))}</div></li>' for x in ctx.of("advisory", a)]
    parts.append(bullet_list("不需要你也能做（建议，未启动）", adv))
    parked = [f'<li>{e(x["item"])} <span class="muted">· 默认：{e(x["default"])}</span> {source_links(x["sources"], p["path"], obs, year)}</li>'
              for x in ctx.of("parked", a)] + [task_li(t, ctx, detail=True) for t in ctx.tasks("parked", a)]
    parts.append(bullet_list("停放（附重启条件）", parked))
    parts.append(bullet_list("风险", [f'<li><span class="chip warn">{e(r.get("kind"))}</span>{e(r.get("detail"))}</li>' for r in ctx.of("risks", a)]))
    parts.append(bullet_list("不确定", [f"<li>{e(u)}</li>" for u in p.get("unknowns", [])]))
    git = p.get("git") or {}
    warnings = "".join(f'<li>{e(w)}</li>' for w in project_warnings(p))
    parts.append(f'<h3>Git 与证据</h3><div class="small">分支 {e(git.get("branch"))} · 最近提交 {e(git.get("head"))}'
                 f'（{e(short_date(git.get("last_commit_at"), year))}，{e(git.get("last_commit_subject"))}）'
                 f' · 已跟踪改动 {e(git.get("uncommitted_tracked"))} · 未跟踪文件 {e(git.get("untracked"))}'
                 f' · 领先 {e(git.get("ahead"))} / 落后 {e(git.get("behind"))}</div>'
                 + (f'<ul class="small muted">{warnings}</ul>' if warnings else ""))
    return "".join(parts)


def project_row(p, ctx):
    a = p["alias"]
    today = p.get("today")
    today_html = (f'<span class="chip {"ok" if today["mode"] == "proceed" else ""}">{e(MODES[today["mode"]])}</span>{e(today["outcome"])}'
                  if today else '<span class="muted">今天的目标没能确定</span>')
    c = ctx.counts(a)
    need = (chips([f"决定 {c['决定']}"], "accent") if c["决定"] else "") + chips([f"{k} {n}" for k, n in c.items() if n and k != "决定"])
    risks = chips([r.get("kind") for r in ctx.of("risks", a)], "warn")
    if any(not w.startswith("没有可比较的 upstream") for w in project_warnings(p)):
        risks += chips(["证据不全"], "warn")
    latest = ctx.latest(p)
    return (f'<details class="row" id="{e(a)}"><summary class="grid">'
            f'<div class="c proj"><span class="caret">▸</span><b>{e(label(p))}</b><div class="muted small" style="padding-left:14px">{e(p.get("domain"))}</div></div>'
            f'<div class="c" data-label="今天">{today_html}</div>'
            f'<div class="c" data-label="需要你">{need or "<span class=muted>—</span>"}</div>'
            f'<div class="c small" data-label="最新依据">{e(latest) if latest else "<span class=muted>未注明</span>"}</div>'
            f'<div class="c" data-label="提醒">{risks or "<span class=muted>—</span>"}</div>'
            f'</summary><div class="detail">{project_detail(p, ctx)}</div></details>')


def summary_line(ctx):
    n = len(ctx.asks)
    light = sum(a["attn"] == 0 for a in ctx.asks)
    fb = len(ctx.b.get("feedback", [])) + len(ctx.v["feedback"])
    cap = ctx.b.get("capacity")
    parts = [f"需要你决定 <b>{n}</b> 件" + (f"，其中 {light} 件看一眼就能定" if light else "") if n else "没有发现需要你决定的事",
             f"{fb} 处等你用的时候顺便看",
             f"远端额度{CAPACITY[cap]}（你说明的）" if cap else "远端额度未说明，按紧张处理"]
    return " · ".join(parts)


def capacity_panel(ctx):
    v, cap = ctx.v, ctx.b.get("capacity")
    li = lambda t: f'<li>{chips([t["project"]], "accent")}{e(t["title"])} {chips(task_tags(t))}{task_link(t, ctx) if t["sources"] else ""}</li>'
    scarce = "".join(li(t) for t in v["scarce"]) or '<li class="muted">没有标为主线、可以直接做的任务</li>'
    waiting = [t for t in v["needs"] if "mainline" in t["labels"]]
    waiting_html = (f'<div class="small muted">主线上在等你的：{"、".join(e(t["project"] + " " + t["title"]) for t in waiting)}（见上）</div>'
                    if waiting else "")
    extra = [t for t in v["abundant"] if t not in v["scarce"]]
    more = "".join(li(t) for t in extra)
    more += "".join(f'<li>{chips([x["project"]], "accent")}{e(x.get("work"))} <span class="chip">来自文档</span></li>'
                    for x in ctx.b.get("advisory", []))
    more = more or '<li class="muted">没有</li>'
    gpu = "".join(li(t) for t in v["gpu"]) or '<li class="muted">没有</li>'
    conflicts = "".join(f'<li>{e(t["project"])} {e(t["id"])}：同时标了 agent-ready 和 irreversible，未列入可推进</li>' for t in v["conflicts"])
    covered = "、".join(p["alias"] for p in ctx.b["projects"] if has_tasks(p)) or "无"
    in_flight = "、".join(f"{k} {n} 条" for k, n in v["in_flight"].items()) or "无"
    return f"""<h2>模型额度</h2>
<div class="panel"><div class="box{' now' if cap != 'abundant' else ''}"><h3>额度紧张时只做这些{'（当前）' if cap != 'abundant' else ''}</h3><ul>{scarce}</ul>{waiting_html}</div>
<div class="box{' now' if cap == 'abundant' else ''}"><h3>额度多时再加（不需要你）{'（当前）' if cap == 'abundant' else ''}</h3><ul>{more}</ul></div></div>
<div class="box" style="margin-top:12px"><h3>依赖本地 GPU（看 GPU 是否空闲，与远端额度无关）</h3><ul>{gpu}</ul>{f'<ul>{conflicts}</ul>' if conflicts else ''}
<div class="small muted">按任务标签分类的项目：{e(covered)}；其他项目的可推进工作见各自详情。在途（进行中、交付后要你）：{e(in_flight)}</div></div>"""


def render_page(b):
    ctx = Context(b)
    roots = {p["alias"]: p["path"] for p in b["projects"]}
    asks_html = "".join(ask_li(a, ctx, roots) for a in ctx.asks)
    rows = ""
    for key, title in GROUPS.items():
        members = [p for p in b["projects"] if ctx.group(p) == key]
        if members:
            rows += f'<div class="group">{title} · {len(members)}</div>' + "".join(project_row(p, ctx) for p in members)
    return f"""<!doctype html><html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>项目汇报</title><style>{CSS}</style></head><body><main>
<h1>项目汇报 <span class="muted" style="font-size:15px">{e(local_time(ctx.observed))}</span></h1>
<p class="lede">{summary_line(ctx)}</p>
<h2>需要你决定</h2>{f'<ol class="asks">{asks_html}</ol>' if asks_html else '<p class="muted">没有发现需要你决定的事（只代表来源里没看到）</p>'}
<h2>项目一览 <span class="muted small">点开一行看详情</span></h2>
<div class="board"><div class="grid head"><div>项目</div><div>今天做什么</div><div>需要你</div><div>最新依据</div><div>提醒</div></div>{rows}</div>
{capacity_panel(ctx)}
<h2>说明</h2><div class="notes"><ul>
<li>只读汇总：没有改动任何项目，也没有派单；要执行，请在对应项目里发起。</li>
<li>扫描于 {e(ctx.observed)}；Git 未联网刷新。依据后的日期是来源里写明的事实日期，未注明的标为"未注明日期"。</li>
<li>有 Backlog 的项目按任务状态和标签直接分类；其他项目来自阅读状态文档，覆盖和判断还没经你确认。</li>
</ul></div>
</main></body></html>"""


# ---------- Markdown ----------

def md(value):
    """Keep source prose from becoming Markdown structure or active HTML."""
    if value is None or value == "":
        return "未知"
    value = str(value).replace("\\", "\\\\").replace("\n", " ")
    for char in "`*_[]|":
        value = value.replace(char, "\\" + char)
    return value.replace("<", "&lt;").replace(">", "&gt;")


def markdown_sources(sources, root, observed=None, year=None):
    return "；".join(
        f'[{md(Path(s["path"]).name)}:{s["line"]}](<{quote(str((Path(root) / s["path"]).resolve()), safe="/")}:{s["line"]}>)'
        f'（{md(short_date(s["source_date"], year) or "未注明日期")}{"" if s["observed_at"] == observed else "，核对于 " + md(s["observed_at"])}）'
        for s in sources)


def markdown_task_link(t, ctx):
    if not t["sources"]:
        return "任务文件未知"
    s = t["sources"][0]
    return (f'[{md(t["id"])}](<{quote(str((Path(ctx.roots[t["project"]]) / s["path"]).resolve()), safe="/")}:1>)'
            f'（{md(short_date(s["source_date"], ctx.year) or "未注明日期")}）')


def markdown_task(t, ctx, detail=False):
    warn = "【不可逆】" if "irreversible" in (t.get("labels") or []) else ""
    tags = "、".join(task_tags(t))
    src = markdown_task_link(t, ctx)
    line = f'- {md(t["title"])}{warn}{"（" + md(tags) + "）" if tags else ""} {src}'
    if detail and t.get("description"):
        line += f' — {md(plain(t["description"]))}'
    return line


def render_markdown(b):
    """A usable report, not just artifact counts; shares prepared facts with HTML."""
    ctx = Context(b)
    roots = {p["alias"]: p["path"] for p in b["projects"]}
    out = [f"# 项目汇报 · {local_time(ctx.observed)}", "", summary_line(ctx).replace("<b>", "**").replace("</b>", "**") + "。", "",
           "## 需要你决定", ""]
    for n, a in enumerate(ctx.asks, 1):
        tags = "、".join((["不可逆"] if a["irreversible"] else []) + a["tags"] + (["主线"] if a["mainline"] and "主线" not in a["tags"] else []))
        src = (markdown_task_link(a["task"], ctx) if a.get("task")
               else markdown_sources(a["sources"], roots[a["project"]], ctx.observed, ctx.year))
        out.append(f'{n}. **{md(a["project"])} · {md(a["question"])}**（{md(tags)}）')
        if a["why"]:
            head, rest = lead(a["why"])
            out.append(f'   {md(head)}{"…" if rest else ""}')
        out.append(f'   {src}')
    if not ctx.asks:
        out.append("没有发现需要你决定的事；来源覆盖有限，不等于证明没有。")
    out += ["", "## 项目一览", "", "| 项目 | 轮到 | 今天做什么 | 需要你 | 最新依据 | 提醒 |", "|---|---|---|---|---|---|"]
    for key, title in GROUPS.items():
        for p in [p for p in b["projects"] if ctx.group(p) == key]:
            t = p.get("today")
            c = ctx.counts(p["alias"])
            need = "、".join(f"{k} {n}" for k, n in c.items() if n) or "—"
            risks = "、".join(md(r.get("kind")) for r in ctx.of("risks", p["alias"])) or "—"
            today = f'{MODES[t["mode"]]}：{md(t["outcome"])}' if t else "今天的目标没能确定"
            out.append(f'| {md(label(p))} | {title} | {today} | {need} | {md(ctx.latest(p) or "未注明")} | {risks} |')
    v = ctx.v
    cap = b.get("capacity")
    out += ["", "## 模型额度", "", f'远端额度：{CAPACITY[cap] + "（你说明的）" if cap else "未说明，按紧张处理"}。', "",
            "**额度紧张时只做这些**", ""]
    out += [markdown_task(t, ctx) for t in v["scarce"]] or ["没有标为主线、可以直接做的任务。"]
    waiting = [t for t in v["needs"] if "mainline" in t["labels"]]
    if waiting:
        out.append("主线上在等你的：" + "、".join(md(t["project"] + " " + t["title"]) for t in waiting) + "（见上）。")
    out += ["", "**额度多时再加（不需要你）**", ""]
    extra = [markdown_task(t, ctx) for t in v["abundant"] if t not in v["scarce"]]
    extra += [f'- {md(x["project"])}：{md(x.get("work"))}（来自文档）' for x in b.get("advisory", [])]
    out += extra or ["没有。"]
    out += ["", "**依赖本地 GPU**", ""]
    out += [markdown_task(t, ctx) for t in v["gpu"]] or ["没有。"]
    out += [f'- 标签冲突：{md(t["project"])} {md(t["id"])} 同时标了 agent-ready 和 irreversible，未列入可推进' for t in v["conflicts"]]
    out += ["", "## 各项目详情", ""]
    for p in b["projects"]:
        a = p["alias"]
        out += [f'### {md(label(p))}', ""]
        if p.get("today"):
            t = p["today"]
            out += [f'**今天（{MODES[t["mode"]]}）：{md(t["outcome"])}** {md(t["reason"])}', ""]
        if p.get("workstreams"):
            out += ["| 工作线 | 现在怎样 | 下一步 | 依据 |", "|---|---|---|---|"]
            out += [f'| {md(w.get("name"))} | {md(w.get("state"))} | {md(w.get("next"))} | '
                    f'{markdown_sources(w.get("sources", []), p["path"], ctx.observed, ctx.year) or "—"} |'
                    for w in p["workstreams"]]
            out.append("")
        else:
            out += ["当前工作线未知；没有记录不等于没有工作。", ""]
        if has_tasks(p):
            groups = [("主线下一步", ctx.tasks("scarce", a)),
                      ("额度多时再加", [t for t in ctx.tasks("abundant", a) if t not in ctx.tasks("scarce", a)]),
                      ("依赖本地 GPU", ctx.tasks("gpu", a)), ("其他待办", ctx.other_tasks(a, p))]
            for title, tasks in groups:
                if tasks:
                    out += [f"任务 · {title}：", *[markdown_task(t, ctx) for t in tasks], ""]
        fb = [f'- {md(f["question"])}。{md(f["when"])} {markdown_sources(f["sources"], p["path"], ctx.observed, ctx.year)}'
              for f in ctx.of("feedback", a)] + [markdown_task(t, ctx) for t in ctx.tasks("feedback", a)]
        adv = [f'- {md(x.get("work"))}。{md(x.get("why_no_human"))}' for x in ctx.of("advisory", a)]
        parked = [f'- {md(x["item"])}。默认：{md(x["default"])} {markdown_sources(x["sources"], p["path"], ctx.observed, ctx.year)}'
                  for x in ctx.of("parked", a)] + [markdown_task(t, ctx, detail=True) for t in ctx.tasks("parked", a)]
        risks = [f'- {md(r.get("kind"))}：{md(r.get("detail"))}' for r in ctx.of("risks", a)]
        unknowns = [f'- {md(u)}' for u in p.get("unknowns", [])]
        for title, lines in [("用的时候顺便看", fb), ("不需要你也能做（建议，未启动）", adv), ("停放", parked),
                             ("风险", risks), ("不确定", unknowns)]:
            if lines:
                out += [f"{title}：", *lines, ""]
        g = p.get("git") or {}
        out.append(f'Git：分支 {md(g.get("branch"))}，已跟踪改动 {md(g.get("uncommitted_tracked"))}，未跟踪文件 {md(g.get("untracked"))}，'
                   f'领先 {md(g.get("ahead"))} / 落后 {md(g.get("behind"))}。')
        out += [f'- 证据限制：{md(w)}' for w in project_warnings(p)]
        out.append("")
    out += ["## 说明", "", "- 只读汇总：没有改动任何项目，也没有派单；要执行，请在对应项目里发起。",
            f'- 扫描于 {md(ctx.observed)}；Git 未联网刷新。依据后的日期是来源里写明的事实日期。',
            "- 有 Backlog 的项目按任务状态和标签直接分类；其他项目来自阅读状态文档，覆盖和判断还没经你确认。"]
    return "\n".join(out).rstrip() + "\n"


def main():
    if len(sys.argv) != 3:
        sys.exit("Usage: python3 -I render_brief.py BRIEF.json SCAN.json")
    try:
        with open(sys.argv[1]) as f:
            brief = json.load(f)
        with open(sys.argv[2]) as f:
            scan = json.load(f)
        prepared = prepare_brief(brief, scan)
        page = render_page(prepared)
        report = render_markdown(prepared)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        sys.exit(f"Brief validation failed: {exc}")
    out_dir = os.path.join(tempfile.gettempdir(), "portfolio-brief")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"brief-{dt.datetime.now():%Y%m%d-%H%M%S-%f}.html")
    with open(path, "w") as f:
        f.write(page)
    Path(path).with_suffix(".md").write_text(report)
    print(path)


if __name__ == "__main__":
    main()
