"""Render a brief JSON file into one self-contained local HTML page.

Usage: python3 -I render_brief.py BRIEF.json SCAN.json
Prints the output path. Writes only under $TMPDIR/portfolio-brief/.
"""
import datetime as dt
import copy
import html
import json
import os
import sys
import tempfile
from pathlib import Path

CSS = """
:root{--bg:#fbfaf7;--card:#fff;--text:#2c2c2a;--muted:#6b6a65;--line:#e3e1d9;--accent:#534ab7;--warn:#854f0b;--warnbg:#faeeda}
@media (prefers-color-scheme:dark){:root{--bg:#1f1f1d;--card:#2a2a28;--text:#ecebe6;--muted:#a3a29b;--line:#3d3d3a;--accent:#afa9ec;--warn:#fac775;--warnbg:#412402}}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.6 -apple-system,"PingFang SC",sans-serif}
main{max-width:960px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:22px;font-weight:500;margin:0 0 4px}h2{font-size:17px;font-weight:500;margin:28px 0 10px}
.muted{color:var(--muted);font-size:13px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 16px;margin:8px 0}
.tag{display:inline-block;font-size:12px;padding:0 8px;border-radius:6px;border:1px solid var(--line);color:var(--muted);margin-right:6px}
.warn{background:var(--warnbg);color:var(--warn);border-color:transparent}
table{border-collapse:collapse;width:100%}td,th{text-align:left;vertical-align:top;padding:6px 8px;border-top:1px solid var(--line);font-size:14px}
th{font-weight:500;color:var(--muted);font-size:13px}
ul{margin:4px 0;padding-left:20px}
"""


def e(x):
    return html.escape(str(x)) if x not in (None, "") else '<span class="muted">未知</span>'


def source_links(sources, root):
    return " · ".join(
        f'<a href="{html.escape((Path(root) / s["path"]).resolve().as_uri(), quote=True)}#L{s["line"]}">{e(s["path"])}:{s["line"]}</a>'
        f'（来源日期 {e(s["source_date"])}；核对于 {e(s["observed_at"])}）'
        for s in sources)


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
        if set(p) - {"alias", "workstreams", "unknowns"}:
            raise ValueError("Do not copy Git/count/date/domain facts into the brief; they come from SCAN.json")
        observed = by_alias[p["alias"]]
        p.update({key: observed.get(key) for key in ("path", "domain", "git", "backlog")})
        p["observed_at"] = scan["observed_at"]
        p.setdefault("unknowns", [])
        if not observed["exists"]:
            p["unknowns"].append("白名单路径不存在；项目状态未知")
        for w in p.get("workstreams", []):
            if w.get("sources"):
                check_sources(w["sources"], p["path"])
    for section_name in ("decisions", "advisory", "risks"):
        for item in b.get(section_name, []):
            if item.get("project") not in by_alias:
                raise ValueError(f"{section_name}: project is outside this scan")
            if section_name == "decisions" or item.get("sources"):
                check_sources(item.get("sources"), by_alias[item["project"]]["path"])
    b["generated_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    return b


def project_card(p):
    git = p.get("git") or {}
    backlog = p.get("backlog") or {}
    warnings = list(git.get("errors", []))
    if backlog.get("error"):
        warnings.append(backlog["error"])
    if backlog.get("truncated"):
        warnings.append(f'Backlog 清单不完整：仅展示 {backlog["displayed_chars"]} / {backlog["total_chars"]} 字符；不能据此判断没有其他待办或待决定事项')
    ws = "".join(
        f"<tr><td>{e(w.get('name'))}</td><td>{e(w.get('state'))}<div class='muted'>{source_links(w.get('sources', []), p['path'])}</div></td><td>{e(w.get('next'))}</td></tr>"
        for w in p.get("workstreams", []))
    unknowns = "".join(f"<li>{e(u)}</li>" for u in p.get("unknowns", []))
    return f"""<div class="card"><div><b>{e(p.get('alias'))}</b> <span class="tag">{e(p.get('domain'))}</span>
<span class="muted">最近提交 {e(git.get('head'))}（{e(git.get('last_commit_at'))}） · 已跟踪改动 {e(git.get('uncommitted_tracked'))} · 未跟踪文件 {e(git.get('untracked'))} · 观察于 {e(p.get('observed_at'))}</span></div>
<div class="muted">分支 {e(git.get('branch'))} · 相对本地 upstream：领先 {e(git.get('ahead'))} / 落后 {e(git.get('behind'))}（未联网刷新）</div>
{''.join(f'<div class="warn">{e(warning)}</div>' for warning in warnings)}
{f'<table><tr><th>工作线</th><th>现在怎样</th><th>下一步</th></tr>{ws}</table>' if ws else '<p class="muted">没有识别出工作线</p>'}
{f'<div class="muted" style="margin-top:6px">不确定：</div><ul>{unknowns}</ul>' if unknowns else ''}</div>"""


def section(title, items, row, empty):
    body = "".join(row(i) for i in items) if items else f'<p class="muted">{empty}</p>'
    return f"<h2>{title}</h2>{body}"


def render_page(b):
    roots = {p["alias"]: p["path"] for p in b["projects"]}
    decisions = sorted(b.get("decisions", []), key=lambda d: (d.get("group") or "", d.get("project") or ""))
    page = f"""<!doctype html><html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Portfolio brief</title><style>{CSS}</style></head><body><main>
<h1>项目总览</h1><div class="muted">生成于 {e(b.get('generated_at'))} · 只读汇总，未改动任何项目 · 建议项需要你自己去对应项目触发</div>
<div class="muted">{len(b['projects'])} 个项目 · {len(decisions)} 条待判断事项 · {len(b.get('advisory', []))} 条建议 · {len(b.get('risks', []))} 条风险；清单尚需用户判断是否有重要遗漏。</div>
{section("需要你判断的事", decisions, lambda d: f'<div class="card"><span class="tag">{e(d.get("project"))}</span>{f"<span class=tag>{e(d.get('group'))}</span>" if d.get("group") else ""}<b>{e(d.get("question"))}</b><div class="muted">为什么现在：{e(d.get("why_now"))} · 不处理会怎样：{e(d.get("if_wait"))}</div><div class="muted">{source_links(d["sources"], roots[d["project"]])}</div></div>', "没有发现需要你判断的事（不代表没有，只是来源里没看到）")}
{section("不需要你也能推进的事（建议）", b.get("advisory", []), lambda a: f'<div class="card"><span class="tag">{e(a.get("project"))}</span>{e(a.get("work"))}<div class="muted">{e(a.get("why_no_human"))}</div></div>', "没有")}
{section("风险提示", b.get("risks", []), lambda r: f'<div class="card"><span class="tag warn">{e(r.get("kind"))}</span><span class="tag">{e(r.get("project"))}</span>{e(r.get("detail"))}</div>', "没有")}
<h2>各项目</h2>{"".join(project_card(p) for p in b.get("projects", []))}
</main></body></html>"""
    return page


def main():
    if len(sys.argv) != 3:
        sys.exit("Usage: python3 -I render_brief.py BRIEF.json SCAN.json")
    try:
        with open(sys.argv[1]) as f:
            brief = json.load(f)
        with open(sys.argv[2]) as f:
            scan = json.load(f)
        page = render_page(prepare_brief(brief, scan))
    except (ValueError, KeyError, TypeError, OSError) as exc:
        sys.exit(f"Brief validation failed: {exc}")
    out_dir = os.path.join(tempfile.gettempdir(), "portfolio-brief")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"brief-{dt.datetime.now():%Y%m%d-%H%M%S-%f}.html")
    with open(path, "w") as f:
        f.write(page)
    print(path)


if __name__ == "__main__":
    main()
