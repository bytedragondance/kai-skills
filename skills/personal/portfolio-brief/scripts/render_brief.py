"""Render a brief JSON file into one self-contained local HTML page.

Usage: python3 -I render_brief.py BRIEF.json
Prints the output path. Writes only under $TMPDIR/portfolio-brief/.
"""
import datetime as dt
import html
import json
import os
import sys
import tempfile

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


def project_card(p):
    ws = "".join(
        f"<tr><td>{e(w.get('name'))}</td><td>{e(w.get('state'))}</td><td>{e(w.get('next'))}</td></tr>"
        for w in p.get("workstreams", []))
    unknowns = "".join(f"<li>{e(u)}</li>" for u in p.get("unknowns", []))
    return f"""<div class="card"><div><b>{e(p.get('alias'))}</b> <span class="tag">{e(p.get('domain'))}</span>
<span class="muted">最近提交 {e(p.get('last_commit'))} · 未提交 {e(p.get('uncommitted'))} · 观察于 {e(p.get('observed_at'))}</span></div>
{f'<table><tr><th>工作线</th><th>现在怎样</th><th>下一步</th></tr>{ws}</table>' if ws else '<p class="muted">没有识别出工作线</p>'}
{f'<div class="muted" style="margin-top:6px">不确定：</div><ul>{unknowns}</ul>' if unknowns else ''}</div>"""


def section(title, items, row, empty):
    body = "".join(row(i) for i in items) if items else f'<p class="muted">{empty}</p>'
    return f"<h2>{title}</h2>{body}"


def main():
    with open(sys.argv[1]) as f:
        b = json.load(f)
    decisions = sorted(b.get("decisions", []), key=lambda d: (d.get("group") or "", d.get("project") or ""))
    page = f"""<!doctype html><html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Portfolio brief</title><style>{CSS}</style></head><body><main>
<h1>项目总览</h1><div class="muted">生成于 {e(b.get('generated_at'))} · 只读汇总，未改动任何项目 · 建议项需要你自己去对应项目触发</div>
{section("需要你判断的事", decisions, lambda d: f'<div class="card"><span class="tag">{e(d.get("project"))}</span>{f"<span class=tag>{e(d.get('group'))}</span>" if d.get("group") else ""}<b>{e(d.get("question"))}</b><div class="muted">为什么现在：{e(d.get("why_now"))} · 不处理会怎样：{e(d.get("if_wait"))}</div></div>', "没有发现需要你判断的事（不代表没有，只是来源里没看到）")}
{section("不需要你也能推进的事（建议）", b.get("advisory", []), lambda a: f'<div class="card"><span class="tag">{e(a.get("project"))}</span>{e(a.get("work"))}<div class="muted">{e(a.get("why_no_human"))}</div></div>', "没有")}
{section("风险提示", b.get("risks", []), lambda r: f'<div class="card"><span class="tag warn">{e(r.get("kind"))}</span><span class="tag">{e(r.get("project"))}</span>{e(r.get("detail"))}</div>', "没有")}
<h2>各项目</h2>{"".join(project_card(p) for p in b.get("projects", []))}
</main></body></html>"""
    out_dir = os.path.join(tempfile.gettempdir(), "portfolio-brief")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"brief-{dt.datetime.now():%Y%m%d-%H%M}.html")
    with open(path, "w") as f:
        f.write(page)
    print(path)


if __name__ == "__main__":
    main()
