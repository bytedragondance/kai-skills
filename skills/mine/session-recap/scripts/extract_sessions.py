#!/usr/bin/env python3
"""Extract one work-day of AI coding-session evidence as Markdown.

Local sources:
  - Cursor
  - Claude Code
  - Trae CLI
  - Codex CLI

TMates is opt-in through --tmates-agent or --tmates-run because managed-agent
IDs are user-specific. The script is read-only and writes only to stdout.
"""

import argparse
import datetime
import glob
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple


HOME = Path.home()
CURSOR_DB = Path(
    os.environ.get(
        "SESSION_RECAP_CURSOR_DB",
        str(
            HOME
            / "Library/Application Support/Cursor/User/globalStorage/state.vscdb"
        ),
    )
)
CLAUDE_ROOT = Path(
    os.environ.get("SESSION_RECAP_CLAUDE_ROOT", str(HOME / ".claude/projects"))
)
TRAE_ROOT = Path(
    os.environ.get("SESSION_RECAP_TRAE_ROOT", str(HOME / ".trae/cli/sessions"))
)
CODEX_ROOT = Path(
    os.environ.get("SESSION_RECAP_CODEX_ROOT", str(HOME / ".codex/sessions"))
)

MAX_USER_MESSAGES = 10
SNIPPET_LENGTH = 200
CLAUDE_SCAN_MARGIN_DAYS = 3
TMATES_MESSAGE_LIMIT = 40
TMATES_LIST_PAGE_SIZE = 50
TMATES_LIST_MAX_PAGES = 20
AUTO_DISCOVERED_RUN_LIMIT = 15
TMATES_SITE = os.environ.get("SESSION_RECAP_TMATES_SITE", "i18n-tt")


def env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as error:
        raise SystemExit(f"{name} must be an integer, got {value!r}") from error


DAY_START_HOUR = env_int("SESSION_RECAP_DAY_START_HOUR", 4)
if not 0 <= DAY_START_HOUR <= 23:
    raise SystemExit("SESSION_RECAP_DAY_START_HOUR must be between 0 and 23")

RUN_ID_RE = re.compile(
    r"(?:task/share/|run[-_ ]?id\s*[=: ]\s*|--run-id\s+)(\d{2,})",
    re.IGNORECASE,
)
ROLLOUT_NOISE_PREFIXES = (
    "the following is the codex agent history",
    "# agents.md",
    "<permissions instructions>",
    "<turn_aborted>",
    "<skill>",
    "base directory for this skill",
)


def split_ids(value: str) -> List[str]:
    return [item for item in re.split(r"[,\s]+", (value or "").strip()) if item]


def unique(values: Iterable[str]) -> List[str]:
    seen: Set[str] = set()
    result: List[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def default_work_day(now: Optional[datetime.datetime] = None) -> str:
    local_now = now or datetime.datetime.now().astimezone()
    shifted = local_now - datetime.timedelta(hours=DAY_START_HOUR)
    return (shifted.date() - datetime.timedelta(days=1)).isoformat()


def valid_date(value: str) -> str:
    try:
        return datetime.date.fromisoformat(value).isoformat()
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            f"expected YYYY-MM-DD, got {value!r}"
        ) from error


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract one work-day of AI coding-session evidence."
    )
    parser.add_argument(
        "date",
        nargs="?",
        type=valid_date,
        default=default_work_day(),
        help="work-day in YYYY-MM-DD form (default: previous work-day)",
    )
    parser.add_argument(
        "--tmates-agent",
        "--tmates-agents",
        action="append",
        default=[],
        metavar="ID[,ID...]",
        help="managed-agent IDs to sweep; repeat or comma-separate",
    )
    parser.add_argument(
        "--tmates-run",
        "--tmates",
        action="append",
        default=[],
        metavar="ID[,ID...]",
        help="specific TMates run IDs to fetch; repeat or comma-separate",
    )
    parser.add_argument(
        "--note",
        type=Path,
        help="existing note to scan for TMates task/share or run IDs",
    )
    args = parser.parse_args(argv[1:])
    env_agents = split_ids(os.environ.get("SESSION_RECAP_TMATES_AGENTS", ""))
    env_runs = split_ids(os.environ.get("SESSION_RECAP_TMATES_RUNS", ""))
    args.tmates_agents = unique(
        env_agents
        + [
            item
            for value in args.tmates_agent
            for item in split_ids(value)
        ]
    )
    args.tmates_runs = unique(
        env_runs
        + [
            item
            for value in args.tmates_run
            for item in split_ids(value)
        ]
    )
    return args


def work_day(datetime_value: datetime.datetime) -> str:
    return (
        datetime_value - datetime.timedelta(hours=DAY_START_HOUR)
    ).strftime("%Y-%m-%d")


def local_datetime_from_milliseconds(
    milliseconds: object,
) -> Optional[datetime.datetime]:
    try:
        return datetime.datetime.fromtimestamp(
            int(milliseconds) / 1000
        ).astimezone()
    except (TypeError, ValueError, OSError):
        return None


def local_datetime_from_iso(value: object) -> Optional[datetime.datetime]:
    try:
        return datetime.datetime.fromisoformat(
            str(value or "").replace("Z", "+00:00")
        ).astimezone()
    except (TypeError, ValueError):
        return None


def day_and_time_from_iso(value: object) -> Tuple[str, str]:
    parsed = local_datetime_from_iso(value)
    if parsed is None:
        return "", "?"
    return work_day(parsed), parsed.strftime("%H:%M")


def day_from_milliseconds(milliseconds: object) -> str:
    parsed = local_datetime_from_milliseconds(milliseconds)
    return work_day(parsed) if parsed else ""


def time_from_milliseconds(milliseconds: object) -> str:
    parsed = local_datetime_from_milliseconds(milliseconds)
    return parsed.strftime("%H:%M") if parsed else "?"


def clean(text: object, limit: int = SNIPPET_LENGTH) -> str:
    return " ".join(str(text or "").split())[:limit]


def harvest_run_ids(text: object, destination: Set[str]) -> None:
    for match in RUN_ID_RE.finditer(str(text or "")):
        destination.add(match.group(1))


def print_coverage(status: str, detail: str = "") -> None:
    suffix = f" — {detail}" if detail else ""
    print(f"  (coverage: {status}{suffix})")


def cursor_sessions(date: str, harvested_ids: Set[str]) -> str:
    if not CURSOR_DB.exists():
        print_coverage("unavailable", f"database not found: {CURSOR_DB}")
        return "unavailable"

    try:
        connection = sqlite3.connect(f"file:{CURSOR_DB}?mode=ro", uri=True)
        rows = connection.execute(
            "SELECT key, value FROM cursorDiskKV "
            "WHERE key LIKE 'composerData:%'"
        ).fetchall()
    except sqlite3.Error as error:
        print_coverage("unavailable", clean(error))
        return "unavailable"

    sessions = []
    try:
        for _, value in rows:
            try:
                data = json.loads(value)
            except (TypeError, json.JSONDecodeError):
                continue
            created = data.get("createdAt")
            updated = data.get("lastUpdatedAt") or created
            if (
                day_from_milliseconds(created) != date
                and day_from_milliseconds(updated) != date
            ):
                continue
            headers = data.get("fullConversationHeadersOnly") or []
            composer_id = data.get("composerId")
            if headers and composer_id:
                sessions.append(
                    (
                        int(created or 0),
                        str(composer_id),
                        data.get("name") or "",
                        headers,
                    )
                )

        if not sessions:
            print_coverage("no activity")
            return "no activity"

        for created, composer_id, name, headers in sorted(sessions):
            print(
                f"\n  [{time_from_milliseconds(created)}] "
                f"{name or '(untitled)'} · {len(headers)} msgs · "
                f"{composer_id[:8]}"
            )
            count = 0
            for header in headers:
                if header.get("type") != 1:
                    continue
                bubble_id = header.get("bubbleId")
                row = connection.execute(
                    "SELECT value FROM cursorDiskKV WHERE key=?",
                    (f"bubbleId:{composer_id}:{bubble_id}",),
                ).fetchone()
                if not row:
                    continue
                try:
                    text = clean(json.loads(row[0]).get("text"))
                except (TypeError, json.JSONDecodeError):
                    text = ""
                if not text:
                    continue
                harvest_run_ids(text, harvested_ids)
                print(f"      U> {text}")
                count += 1
                if count >= MAX_USER_MESSAGES:
                    print("      …(more omitted)")
                    break
    finally:
        connection.close()

    return "complete"


def claude_user_messages(
    path: Path, harvested_ids: Set[str]
) -> List[Tuple[str, str, str]]:
    result: List[Tuple[str, str, str]] = []
    try:
        file_handle = path.open(encoding="utf-8")
    except OSError:
        return result

    with file_handle:
        for line in file_handle:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("type") != "user":
                continue
            content = record.get("message", {}).get("content")
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                text = " ".join(
                    part.get("text", "")
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                )
            else:
                text = ""
            text = text.strip()
            if (
                not text
                or text.startswith("<")
                or "command-name" in text
                or "command-message" in text
            ):
                continue
            item_day, item_time = day_and_time_from_iso(record.get("timestamp"))
            snippet = clean(text)
            harvest_run_ids(snippet, harvested_ids)
            result.append((item_day, item_time, snippet))
    return result


def claude_candidate_files(date: str) -> List[Path]:
    upper_date = (
        datetime.date.fromisoformat(date)
        + datetime.timedelta(days=CLAUDE_SCAN_MARGIN_DAYS + 1)
    ).isoformat()
    try:
        process = subprocess.run(
            [
                "find",
                str(CLAUDE_ROOT),
                "-name",
                "*.jsonl",
                "-newermt",
                f"{date} 00:00",
                "!",
                "-newermt",
                f"{upper_date} 00:00",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if process.returncode == 0:
            return [Path(line) for line in process.stdout.splitlines() if line]
    except (OSError, subprocess.SubprocessError):
        pass
    return list(CLAUDE_ROOT.glob("**/*.jsonl"))


def claude_sessions(date: str, harvested_ids: Set[str]) -> str:
    if not CLAUDE_ROOT.exists():
        print_coverage("unavailable", f"root not found: {CLAUDE_ROOT}")
        return "unavailable"

    files = claude_candidate_files(date)
    main_files = [path for path in files if "subagents" not in path.parts]
    subagent_files = [path for path in files if "subagents" in path.parts]
    shown = False

    for path in sorted(main_files):
        messages = [
            (item_time, text)
            for item_day, item_time, text in claude_user_messages(
                path, harvested_ids
            )
            if item_day == date
        ]
        if not messages:
            continue
        shown = True
        try:
            project = path.parts[path.parts.index("projects") + 1]
        except (ValueError, IndexError):
            project = path.parent.name
        print(f"\n  [main] {project} · start {messages[0][0]}")
        for item_time, text in messages[:MAX_USER_MESSAGES]:
            print(f"      {item_time} U> {text}")
        if len(messages) > MAX_USER_MESSAGES:
            print(
                f"      …(+{len(messages) - MAX_USER_MESSAGES} more omitted)"
            )

    subagent_items = []
    for path in subagent_files:
        messages = [
            (item_time, text)
            for item_day, item_time, text in claude_user_messages(
                path, harvested_ids
            )
            if item_day == date
        ]
        if messages:
            subagent_items.append((path, messages[0][1]))

    if subagent_items:
        shown = True
        print(f"\n  [subagents/workflows] {len(subagent_items)} files:")
        seen: Set[str] = set()
        for path, task in sorted(subagent_items):
            key = task[:60]
            if key in seen:
                continue
            seen.add(key)
            try:
                project = path.parts[path.parts.index("projects") + 1]
            except (ValueError, IndexError):
                project = path.parent.name
            print(f"      ({project}) {task[:160]}")
            if len(seen) >= 12:
                break

    if not shown:
        print_coverage("no activity")
        return "no activity"
    return "complete"


def rollout_user_turns(
    path: Path, harvested_ids: Set[str]
) -> List[Tuple[str, str, str]]:
    result: List[Tuple[str, str, str]] = []
    try:
        file_handle = path.open(encoding="utf-8")
    except OSError:
        return result

    with file_handle:
        for line in file_handle:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("type") != "response_item":
                continue
            payload = record.get("payload", {})
            if (
                payload.get("type") != "message"
                or payload.get("role") != "user"
            ):
                continue
            text = " ".join(
                item.get("text", "")
                for item in payload.get("content", [])
                if isinstance(item, dict)
                and item.get("type") in ("input_text", "text")
            ).strip()
            if not text:
                continue
            lower_prefix = text[:60].lower()
            if any(
                lower_prefix.startswith(prefix)
                for prefix in ROLLOUT_NOISE_PREFIXES
            ):
                continue
            item_day, item_time = day_and_time_from_iso(record.get("timestamp"))
            snippet = clean(text)
            harvest_run_ids(snippet, harvested_ids)
            result.append((item_day, item_time, snippet))
    return result


def rollout_cwd(path: Path) -> str:
    try:
        with path.open(encoding="utf-8") as file_handle:
            for line in file_handle:
                record = json.loads(line)
                if record.get("type") == "session_meta":
                    return str(record.get("payload", {}).get("cwd", ""))
    except (OSError, json.JSONDecodeError):
        return ""
    return ""


def rollout_files(root: Path, date: str) -> List[Path]:
    target = datetime.date.fromisoformat(date)
    files: List[Path] = []
    for offset in (-1, 0, 1):
        directory_date = target + datetime.timedelta(days=offset)
        files.extend(
            Path(path)
            for path in glob.glob(
                str(
                    root
                    / f"{directory_date:%Y}"
                    / f"{directory_date:%m}"
                    / f"{directory_date:%d}"
                    / "rollout-*.jsonl"
                )
            )
        )
    return sorted(set(files))


def rollout_sessions(
    root: Path, date: str, label: str, harvested_ids: Set[str]
) -> str:
    if not root.exists():
        print_coverage("unavailable", f"root not found: {root}")
        return "unavailable"

    shown = False
    for path in rollout_files(root, date):
        turns = [
            (item_time, text)
            for item_day, item_time, text in rollout_user_turns(
                path, harvested_ids
            )
            if item_day == date
        ]
        if not turns:
            continue
        shown = True
        cwd = rollout_cwd(path)
        project = Path(cwd).name if cwd else "(unknown)"
        print(f"\n  [{turns[0][0]}] {project} · {len(turns)} user turns")
        for item_time, text in turns[:MAX_USER_MESSAGES]:
            print(f"      {item_time} U> {text}")
        if len(turns) > MAX_USER_MESSAGES:
            print(f"      …(+{len(turns) - MAX_USER_MESSAGES} more omitted)")

    if not shown:
        print_coverage("no activity", label)
        return "no activity"
    return "complete"


def parse_bytedcli_json(output: str) -> Optional[Dict[str, object]]:
    start = output.find("{")
    if start < 0:
        return None
    try:
        parsed = json.loads(output[start:])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def bytedcli_error(payload: Dict[str, object]) -> str:
    error = payload.get("error")
    if isinstance(error, dict):
        return clean(
            error.get("message") or error.get("msg") or json.dumps(error)
        )
    return clean(error or "unknown error")


def tmates_run_list(agent_id: str) -> Tuple[Optional[List[dict]], str]:
    runs: List[dict] = []
    page = 1
    total: Optional[int] = None
    while page <= TMATES_LIST_MAX_PAGES:
        try:
            process = subprocess.run(
                [
                    "bytedcli",
                    "--json",
                    "--site",
                    TMATES_SITE,
                    "tmates",
                    "run",
                    "list",
                    "--managed-agent-id",
                    agent_id,
                    "--page",
                    str(page),
                    "--page-size",
                    str(TMATES_LIST_PAGE_SIZE),
                ],
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
            )
        except FileNotFoundError:
            return None, "bytedcli command not found"
        except (OSError, subprocess.SubprocessError) as error:
            return None, clean(error)

        payload = parse_bytedcli_json(process.stdout or "")
        if payload is None:
            return None, "response did not contain JSON"
        if payload.get("status") != "success":
            return None, bytedcli_error(payload)
        data = payload.get("data") or {}
        if not isinstance(data, dict):
            return None, "response data was not an object"
        batch = data.get("runs") or []
        if not isinstance(batch, list):
            return None, "response runs was not a list"
        runs.extend(item for item in batch if isinstance(item, dict))
        try:
            total = int(data.get("total", len(runs)))
        except (TypeError, ValueError):
            total = len(runs)
        if not batch or len(runs) >= total:
            break
        page += 1
    return runs, ""


def tmates_run_get(run_id: str) -> Tuple[Optional[dict], str]:
    try:
        process = subprocess.run(
            [
                "bytedcli",
                "--json",
                "--site",
                TMATES_SITE,
                "tmates",
                "run",
                "get",
                "--run-id",
                run_id,
                "--message-limit",
                str(TMATES_MESSAGE_LIMIT),
            ],
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
    except FileNotFoundError:
        return None, "bytedcli command not found"
    except (OSError, subprocess.SubprocessError) as error:
        return None, clean(error)

    payload = parse_bytedcli_json(process.stdout or "")
    if payload is None:
        return None, "response did not contain JSON"
    if payload.get("status") != "success":
        return None, bytedcli_error(payload)
    data = payload.get("data") or {}
    if not isinstance(data, dict) or not isinstance(data.get("run"), dict):
        return None, "response did not contain a run"
    return data["run"], ""


def day_window(date: str) -> Tuple[datetime.datetime, datetime.datetime]:
    target = datetime.date.fromisoformat(date)
    start = datetime.datetime.combine(
        target, datetime.time(DAY_START_HOUR)
    ).astimezone()
    return start, start + datetime.timedelta(days=1)


def run_overlaps_day(
    run: dict, start: datetime.datetime, end: datetime.datetime
) -> bool:
    created = local_datetime_from_iso(run.get("createdAt"))
    if created is None:
        return False
    updated = local_datetime_from_iso(run.get("updatedAt")) or created
    return created < end and updated >= start


def note_run_ids(path: Optional[Path]) -> Tuple[List[str], str]:
    if path is None:
        return [], ""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        return [], clean(error)
    return RUN_ID_RE.findall(text), ""


def tmates_sessions(
    date: str,
    agent_ids: Sequence[str],
    run_ids: Sequence[str],
    note: Optional[Path],
    harvested_ids: Set[str],
) -> Tuple[str, bool]:
    if not agent_ids and not run_ids and note is None:
        print_coverage(
            "not configured",
            "use --tmates-agent, --tmates-run, or --note",
        )
        return "not configured", False

    candidates: List[str] = list(run_ids)
    errors: List[str] = []
    start, end = day_window(date)

    for agent_id in agent_ids:
        runs, error = tmates_run_list(agent_id)
        if error:
            errors.append(f"agent {agent_id}: {error}")
            continue
        for run in runs or []:
            if run_overlaps_day(run, start, end):
                candidates.append(str(run.get("id") or ""))

    discovered_ids, note_error = note_run_ids(note)
    if note_error:
        errors.append(f"note {note}: {note_error}")
    auto_discovered = unique(discovered_ids + sorted(harvested_ids))
    candidates.extend(auto_discovered[:AUTO_DISCOVERED_RUN_LIMIT])
    candidates = unique(candidates)

    shown = False
    for run_id in candidates:
        run, error = tmates_run_get(run_id)
        if error:
            errors.append(f"run {run_id}: {error}")
            continue
        if run is None:
            errors.append(f"run {run_id}: empty response")
            continue

        messages = run.get("messages") or []
        if not isinstance(messages, list):
            messages = []
        day_messages = [
            message
            for message in messages
            if isinstance(message, dict)
            and day_from_milliseconds(message.get("createdAt")) == date
        ]
        created_day, created_time = day_and_time_from_iso(run.get("createdAt"))
        if not day_messages and created_day != date:
            continue

        shown = True
        status = "/".join(
            str(value)
            for value in (run.get("status"), run.get("displayStatus"))
            if value
        )
        title = run.get("promptSummary")
        if not title and isinstance(run.get("prompt"), dict):
            title = run.get("prompt", {}).get("text", "")
        head_time = (
            time_from_milliseconds(day_messages[0].get("createdAt"))
            if day_messages
            else created_time
        )
        identifiers = " ".join(
            f"{key}={value}"
            for key, value in (
                ("agent", run.get("managedAgentId")),
                ("project", run.get("projectId")),
                ("space", run.get("spaceId")),
                ("branch", run.get("branch")),
            )
            if value not in (None, "")
        )
        print(
            f"\n  [{head_time}] run {run_id} · {status or '?'} · "
            f"{run.get('messageCount', len(messages))} msgs"
        )
        if identifiers:
            print(f"      ids: {identifiers}")
        if title:
            print(f"      « {clean(title)} »")
        if day_messages:
            for message in day_messages[: MAX_USER_MESSAGES + 4]:
                content = message.get("content") or {}
                text = clean(
                    content.get("text", "") if isinstance(content, dict) else ""
                )
                if not text:
                    continue
                sender = str(message.get("from") or "")
                tag = (
                    "U>"
                    if sender == "USER"
                    else ("AGENT>" if sender.endswith("AGENT") else sender)
                )
                print(
                    f"      "
                    f"{time_from_milliseconds(message.get('createdAt'))} "
                    f"{tag} {text}"
                )
        else:
            print(
                f"      (started at {created_time}; the fetched message window "
                "contains only later activity)"
            )

    if errors:
        print("\n  ⚠ TMates coverage incomplete:")
        for error in errors:
            print(f"    - {error}")
        return "incomplete", True
    if not shown:
        print_coverage("no activity")
        return "no activity", False
    return "complete", False


def main(argv: Sequence[str] = sys.argv) -> int:
    args = parse_args(argv)
    harvested_ids: Set[str] = set()

    print(f"# AI coding session recap · {args.date}")
    print(
        f"\nWork-day boundary: {DAY_START_HOUR:02d}:00 local → "
        f"next day {DAY_START_HOUR:02d}:00 local."
    )

    print("\n## Cursor")
    cursor_sessions(args.date, harvested_ids)

    print("\n## Claude Code")
    claude_sessions(args.date, harvested_ids)

    print("\n## Trae CLI")
    rollout_sessions(TRAE_ROOT, args.date, "Trae CLI", harvested_ids)

    print("\n## Codex CLI")
    rollout_sessions(CODEX_ROOT, args.date, "Codex CLI", harvested_ids)

    print("\n## TMates")
    _, tmates_incomplete = tmates_sessions(
        args.date,
        args.tmates_agents,
        args.tmates_runs,
        args.note,
        harvested_ids,
    )

    print(
        "\n---\n"
        "Local sections contain user turns only; they prove activity and intent, "
        "not completion. Verify delivered outcomes against authoritative artifacts."
    )
    if tmates_incomplete:
        print(
            "\n⚠ This recap has incomplete TMates coverage. "
            "Do not interpret the missing cloud evidence as no activity."
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
