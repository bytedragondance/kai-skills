"""Read-only scan of the allowlisted projects. Prints JSON to stdout.

Never writes to a project: git runs with GIT_OPTIONAL_LOCKS=0 so status
does not refresh the index, and Backlog.md is only listed and read
through its CLI (`task list --json`, `task <id> --json`).
"""
import datetime as dt
import json
import os
import re
import subprocess
import sys

CONFIG = os.path.expanduser("~/.config/portfolio-brief/projects.json")
BACKLOG_LIMIT = 4000
TASK_LIMIT = 80
DESCRIPTION_LIMIT = 400
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
    info = {key: None for key in (
        "branch", "head", "last_commit_at", "last_commit_subject", "days_since_commit",
        "uncommitted_tracked", "untracked", "ahead", "behind")}
    info["errors"] = []
    if run(["git", "rev-parse", "--is-inside-work-tree"], path) != "true":
        info["errors"].append("Git repository could not be established; Git facts are unknown")
        return info
    log = run(["git", "log", "-1", "--format=%h%x1f%cI%x1f%s"], path)
    if log and len(log.split("\x1f", 2)) == 3:
        head, when, subject = log.split("\x1f", 2)
        info.update(head=head, last_commit_at=when, last_commit_subject=subject)
        try:
            info["days_since_commit"] = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(when)).days
        except (ValueError, TypeError):
            info["errors"].append("Last commit date could not be parsed")
    else:
        info["errors"].append("Last commit unavailable (including repositories with no commits)")
    status = run(["git", "status", "--porcelain=v1", "-uall"], path)
    if status is None:
        info["errors"].append("git status failed; uncommitted counts are unknown")
    else:
        lines = [line for line in status.splitlines() if line]
        info["uncommitted_tracked"] = sum(not line.startswith("??") for line in lines)
        info["untracked"] = sum(line.startswith("??") for line in lines)
    counts = run(["git", "rev-list", "--left-right", "--count", "@{upstream}...HEAD"], path)
    try:
        behind, ahead = (int(n) for n in counts.split())
        if min(behind, ahead) < 0:
            raise ValueError("negative count")
        info.update(behind=behind, ahead=ahead)
    except (AttributeError, ValueError):
        info["errors"].append("Upstream comparison unavailable; ahead/behind unknown (no fetch performed)")
    branch = run(["git", "branch", "--show-current"], path)
    if branch is None:
        info["errors"].append("Current branch could not be read")
    else:
        info["branch"] = branch or "(detached HEAD)"
    return info


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
    if out is None:
        return {"text": None, "truncated": False, "total_chars": None,
                "displayed_chars": 0, "error": "Backlog CLI listing failed; task state unknown"}
    return {"text": out[:BACKLOG_LIMIT], "truncated": len(out) > BACKLOG_LIMIT,
            "total_chars": len(out), "displayed_chars": min(len(out), BACKLOG_LIMIT), "error": None}


def backlog_tasks(path):
    """Open Backlog tasks with status and labels, via the CLI's JSON output (read-only).

    None when the project has no Backlog. Failures stay explicit: tasks is None
    when the listing fails; a task whose detail fails keeps its listing fields.
    """
    if not os.path.isdir(os.path.join(path, "backlog")):
        return None
    out = run(["backlog", "task", "list", "--json"], path)
    try:
        listed = json.loads(out)["tasks"]
    except (TypeError, ValueError, KeyError):
        return {"tasks": None, "truncated": False, "errors": ["Backlog JSON listing failed; task state unknown"]}
    open_tasks = [t for t in listed if t.get("status") != "Done"]
    result = {"tasks": [], "truncated": len(open_tasks) > TASK_LIMIT, "errors": []}
    for t in open_tasks[:TASK_LIMIT]:
        task = {key: t.get(key) for key in ("id", "title", "status", "priority", "labels", "isReady", "updatedAt")}
        task.update(dependencies=None, description=None, path=None)
        try:
            detail = json.loads(run(["backlog", "task", t["id"], "--json"], path))["task"]
            task.update(dependencies=detail.get("dependencies"), path=detail.get("path"),
                        description=(detail.get("description") or "")[:DESCRIPTION_LIMIT] or None)
        except (TypeError, ValueError, KeyError):
            result["errors"].append(f"{t.get('id')}: task detail unavailable; dependencies and source unknown")
        result["tasks"].append(task)
    if result["truncated"]:
        result["errors"].append(f"Only the first {TASK_LIMIT} of {len(open_tasks)} open tasks were read")
    return result


def main():
    if not os.path.exists(CONFIG):
        sys.exit(f"Missing allowlist: {CONFIG}. See the skill's 'Allowlist' section.")
    with open(CONFIG) as f:
        projects = json.load(f)["projects"]
    out = {"observed_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "projects": []}
    for p in projects:
        path = os.path.expanduser(p["path"])
        entry = {"alias": p["alias"], "domain": p.get("domain"), "path": path, "exists": os.path.isdir(path)}
        if entry["exists"]:
            entry["instruction_files"] = [n for n in ("AGENTS.md", "CLAUDE.md") if os.path.exists(os.path.join(path, n))]
            entry["git"] = git_info(path)
            entry["state_docs"] = state_docs(path)
            entry["backlog"] = backlog(path)
            entry["backlog_tasks"] = backlog_tasks(path)
        out["projects"].append(entry)
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
