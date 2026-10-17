"""Read-only scan of the allowlisted projects. Prints JSON to stdout.

Never writes to a project: git runs with GIT_OPTIONAL_LOCKS=0 so status
does not refresh the index, and Backlog.md is only listed.
"""
import datetime as dt
import json
import os
import re
import subprocess
import sys

CONFIG = os.path.expanduser("~/.config/portfolio-brief/projects.json")
STATE_DOC = re.compile(r"(status|state|roadmap|plan|decision|adr|next|orientation|direction|handoff)", re.I)
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "build", "dist", "DerivedData", "__pycache__", ".build"}
ENV = {**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"}


def run(cmd, cwd, timeout=20):
    try:
        r = subprocess.run(cmd, cwd=cwd, env=ENV, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def git_info(path):
    if run(["git", "rev-parse", "--is-inside-work-tree"], path) != "true":
        return None
    log = run(["git", "log", "-1", "--format=%h%x1f%cI%x1f%s"], path)
    head, when, subject = (log.split("\x1f") + ["", "", ""])[:3] if log else ("", "", "")
    status = run(["git", "status", "--porcelain=v1", "-uall"], path) or ""
    lines = [l for l in status.splitlines() if l]
    counts = run(["git", "rev-list", "--left-right", "--count", "@{upstream}...HEAD"], path)
    behind, ahead = (counts.split() if counts else (None, None))
    days = None
    if when:
        days = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(when)).days
    return {
        "branch": run(["git", "branch", "--show-current"], path),
        "head": head,
        "last_commit_at": when or None,
        "last_commit_subject": subject or None,
        "days_since_commit": days,
        "uncommitted_tracked": sum(1 for l in lines if not l.startswith("??")),
        "untracked": sum(1 for l in lines if l.startswith("??")),
        "ahead": int(ahead) if ahead is not None else None,
        "behind": int(behind) if behind is not None else None,
    }


def state_docs(path, limit=8):
    found = []
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        if root[len(path):].count(os.sep) > 3:
            dirs[:] = []
            continue
        for f in files:
            if f.endswith(".md") and STATE_DOC.search(f):
                p = os.path.join(root, f)
                found.append((os.path.getmtime(p), os.path.relpath(p, path)))
    found.sort(reverse=True)
    return [{"path": rel, "modified_at": dt.datetime.fromtimestamp(m).isoformat(timespec="minutes")}
            for m, rel in found[:limit]]


def backlog(path):
    if not os.path.isdir(os.path.join(path, "backlog")):
        return None
    out = run(["backlog", "task", "list", "--plain"], path)
    return out[:4000] if out else "backlog/ present but the CLI listing failed"


def main():
    if not os.path.exists(CONFIG):
        sys.exit(f"Missing allowlist: {CONFIG}. See the skill's 'Allowlist' section.")
    with open(CONFIG) as f:
        projects = json.load(f)["projects"]
    out = {"observed_at": dt.datetime.now().isoformat(timespec="minutes"), "projects": []}
    for p in projects:
        path = os.path.expanduser(p["path"])
        entry = {"alias": p["alias"], "domain": p.get("domain"), "path": path, "exists": os.path.isdir(path)}
        if entry["exists"]:
            entry["instruction_files"] = [n for n in ("AGENTS.md", "CLAUDE.md") if os.path.exists(os.path.join(path, n))]
            entry["git"] = git_info(path)
            entry["state_docs"] = state_docs(path)
            entry["backlog"] = backlog(path)
        out["projects"].append(entry)
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
