"""Focused regression checks using synthetic sources, never the real allowlist."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


def load(name):
    path = Path(__file__).resolve().parents[1] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scan = load("portfolio_scan")
render = load("render_brief")
WHEN = "2026-10-17T12:00:00+00:00"


class ScanTests(unittest.TestCase):
    def git(self, **overrides):
        values = {"rev-parse": "true", "log": f"abcdef\x1f{WHEN}\x1fA commit",
                  "status": "", "rev-list": "0\t0", "branch": "main"}
        values.update(overrides)
        with patch.object(scan, "run", side_effect=lambda cmd, cwd: values[cmd[1]]):
            return scan.git_info("/synthetic")

    def test_failed_status_preserves_other_facts(self):
        result = self.git(status=None)
        self.assertIsNone(result["uncommitted_tracked"])
        self.assertIsNone(result["untracked"])
        self.assertEqual(result["head"], "abcdef")
        self.assertTrue(result["errors"])

    def test_clean_status_is_zero(self):
        result = self.git()
        self.assertEqual((result["uncommitted_tracked"], result["untracked"]), (0, 0))

    def test_dirty_counts_are_separate(self):
        result = self.git(status=' M tracked.txt\n?? new.txt\n M "a\\nb.txt"')
        self.assertEqual((result["uncommitted_tracked"], result["untracked"]), (2, 1))

    def test_missing_upstream_is_unknown(self):
        result = self.git(**{"rev-list": None})
        self.assertIsNone(result["ahead"])
        self.assertIsNone(result["behind"])
        self.assertEqual(result["untracked"], 0)

    def test_empty_repo_keeps_status_but_no_commit(self):
        result = self.git(log=None, **{"rev-list": None})
        self.assertIsNone(result["head"])
        self.assertIsNone(result["days_since_commit"])
        self.assertEqual(result["untracked"], 0)

    def test_git_unavailable_is_not_clean(self):
        result = self.git(**{"rev-parse": None})
        self.assertIsNone(result["uncommitted_tracked"])
        self.assertIsNone(result["head"])
        self.assertTrue(result["errors"])

    def test_backlog_boundaries_empty_and_failure(self):
        with patch.object(scan.os.path, "isdir", return_value=True):
            for value, truncated in [("文" * 4000, False), ("文" * 4001, True), ("", False), (None, False)]:
                with self.subTest(length=None if value is None else len(value)), patch.object(scan, "run", return_value=value):
                    result = scan.backlog("/synthetic")
                    self.assertEqual(result["truncated"], truncated)
                    self.assertEqual(result["total_chars"], None if value is None else len(value))
                    self.assertEqual(result["displayed_chars"], min(len(value or ""), 4000))
                    self.assertEqual(bool(result["error"]), value is None)

    def test_subprocess_failure_and_timeout_stay_unknown(self):
        failures = [OSError("missing executable"), subprocess.TimeoutExpired("git", 20)]
        for error in failures:
            with self.subTest(error=type(error).__name__), patch.object(scan.subprocess, "run", side_effect=error):
                self.assertIsNone(scan.run(["git", "status"], "/synthetic"))
        with patch.object(scan.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", "private error")) as proc:
            self.assertIsNone(scan.run(["git", "status"], "/synthetic"))
            self.assertEqual(proc.call_args.kwargs["env"]["GIT_OPTIONAL_LOCKS"], "0")


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "source 空 #.md").write_text("# Synthetic source\nPending decision\n")
        self.source = {"path": "source 空 #.md", "line": 2, "source_date": None, "observed_at": WHEN}
        self.scan = {"observed_at": WHEN, "projects": [
            {"alias": "P1", "path": str(self.root), "exists": True, "domain": "dev",
             "git": {"head": "abc123", "last_commit_at": WHEN, "uncommitted_tracked": 59,
                     "untracked": 0, "ahead": None, "behind": None, "errors": ["upstream unavailable"]},
             "backlog": {"text": "x" * 4000, "truncated": True, "displayed_chars": 4000, "total_chars": 4001, "error": None}}
        ]}
        self.brief = {"projects": [{"alias": "P1", "workstreams": [], "unknowns": []}],
                      "decisions": [{"project": "P1", "question": "<script>choose</script>", "sources": [self.source]}]}

    def test_facts_from_scan_and_input_not_mutated(self):
        old = copy.deepcopy(self.brief)
        prepared = render.prepare_brief(self.brief, self.scan)
        self.assertEqual(prepared["projects"][0]["git"]["uncommitted_tracked"], 59)
        self.assertEqual(self.brief, old)
        page = render.render_page(prepared)
        self.assertIn("已跟踪改动 59", page)
        self.assertIn("未跟踪文件 0", page)
        self.assertIn("upstream unavailable", page)
        self.assertIn("4000 / 4001", page)
        self.assertIn("&lt;script&gt;choose&lt;/script&gt;", page)
        self.assertIn("source%20%E7%A9%BA%20%23.md#L2", page)
        self.assertIn(WHEN, page)

    def test_hand_copied_count_is_rejected(self):
        self.brief["projects"][0]["uncommitted"] = 159
        with self.assertRaises(ValueError):
            render.prepare_brief(self.brief, self.scan)

    def test_failed_counts_and_backlog_error_reach_page(self):
        p = self.scan["projects"][0]
        p["git"]["uncommitted_tracked"] = None
        p["git"]["untracked"] = None
        p["backlog"] = {"error": "Backlog unavailable"}
        page = render.render_page(render.prepare_brief(self.brief, self.scan))
        self.assertIn('已跟踪改动 <span class="muted">未知</span>', page)
        self.assertIn("Backlog unavailable", page)

    def test_alias_coverage_duplicate_missing_and_extra_rejected(self):
        for projects in [[], [{"alias": "P1"}, {"alias": "P1"}], [{"alias": "P1"}, {"alias": "P2"}]]:
            with self.subTest(projects=projects), self.assertRaises(ValueError):
                render.prepare_brief({**self.brief, "projects": projects}, self.scan)

    def test_alias_order_can_differ(self):
        self.scan["projects"].append({**self.scan["projects"][0], "alias": "P2"})
        self.brief["projects"].insert(0, {"alias": "P2"})
        result = render.prepare_brief(self.brief, self.scan)
        self.assertEqual([p["alias"] for p in result["projects"]], ["P2", "P1"])

    def test_feedback_and_parked_are_separate_from_decisions_in_both_outputs(self):
        self.brief['projects'][0]['today'] = {'outcome': 'Use existing dashboard', 'mode': 'feedback', 'reason': 'Installed; real use remains unknown'}
        self.brief['feedback'] = [{'project': 'P1', 'question': 'Observe charging at next use', 'when': 'Natural use only', 'sources': [self.source]}]
        self.brief['parked'] = [{'project': 'P1', 'item': 'Optional inventory', 'default': 'Keep inactive', 'sources': [self.source]}]
        prepared = render.prepare_brief(self.brief, self.scan)
        page, report = render.render_page(prepared), render.render_markdown(prepared)
        self.assertEqual(len(prepared['decisions']), 1)
        self.assertIn('1 条待决定事项 · 1 条自然使用反馈 · 1 条默认停放事项', page)
        decision_text = report.split('## 需要你决定', 1)[1].split('## 自然使用反馈', 1)[0]
        self.assertNotIn('Observe charging', decision_text)
        self.assertNotIn('Optional inventory', decision_text)
        self.assertIn('Observe charging', report)
        self.assertIn('Optional inventory', report)
        self.assertIn('Use existing dashboard', page)
        self.assertIn('Use existing dashboard', report)
        self.assertIn('已跟踪改动 59', report)
        self.assertIn('4000 / 4001', report)
        self.assertIn('事实/来源日期 未知', report)
        self.assertNotIn('<script>', report)

    def test_feedback_and_parked_need_in_scope_provenance_and_descriptions(self):
        for section, item in [('feedback', {'question': 'Observe', 'when': 'Next use'}),
                              ('parked', {'item': 'Option', 'default': 'Inactive'})]:
            for change in [{'sources': []}, {'project': 'P2'}, {next(iter(item)): ''}]:
                brief = copy.deepcopy(self.brief)
                brief[section] = [{'project': 'P1', 'sources': [self.source], **item, **change}]
                with self.subTest(section=section, change=change), self.assertRaises(ValueError):
                    render.prepare_brief(brief, self.scan)

    def test_today_result_requires_a_real_mode_and_reason(self):
        for today in [{'outcome': 'Result', 'mode': 'done', 'reason': 'Claim'},
                      {'outcome': '', 'mode': 'proceed', 'reason': 'Ready'},
                      {'outcome': 'Result', 'mode': 'paused', 'reason': ''}]:
            self.brief['projects'][0]['today'] = today
            with self.subTest(today=today), self.assertRaises(ValueError):
                render.prepare_brief(self.brief, self.scan)

    def test_decision_without_source_or_outside_project_is_rejected(self):
        for updates in [{"sources": []}, {"project": "P2"}]:
            brief = copy.deepcopy(self.brief)
            brief["decisions"][0].update(updates)
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                render.prepare_brief(brief, self.scan)

    def test_source_boundary_and_dates(self):
        for changes in [{"path": "/etc/passwd"}, {"path": "../outside.md"}, {"path": "https://example.org"},
                        {"path": "missing.md"}, {"line": 0}, {"line": True}, {"source_date": "unknown"},
                        {"observed_at": "2026-10-17T12:00:00"}]:
            with self.subTest(changes=changes), self.assertRaises((ValueError, KeyError)):
                render.check_sources([{**self.source, **changes}], str(self.root))
        render.check_sources([self.source], str(self.root))
        render.check_sources([{**self.source, "source_date": "2026-10-16"}], str(self.root))

    def test_symlink_outside_project_is_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "outside.md"
            target.write_text("synthetic")
            (self.root / "link.md").symlink_to(target)
            with self.assertRaises(ValueError):
                render.check_sources([{**self.source, "path": "link.md"}], str(self.root))

    def test_cli_validates_before_writing(self):
        brief_path, scan_path = self.root / "brief.json", self.root / "scan.json"
        scan_path.write_text(json.dumps(self.scan))
        self.brief["projects"][0]["uncommitted"] = 159
        brief_path.write_text(json.dumps(self.brief))
        cmd = [sys.executable, "-I", render.__file__, str(brief_path), str(scan_path)]
        env = {**os.environ, "TMPDIR": str(self.root)}
        result = subprocess.run(cmd, capture_output=True, text=True, env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / "portfolio-brief").exists())
        del self.brief["projects"][0]["uncommitted"]
        brief_path.write_text(json.dumps(self.brief))
        result = subprocess.run(cmd, capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        html_path = Path(result.stdout.strip())
        self.assertTrue(html_path.is_file())
        text_path = html_path.with_suffix('.md')
        self.assertTrue(text_path.is_file())
        self.assertIn('Attune 项目汇报', text_path.read_text())
        self.assertIn(WHEN, text_path.read_text())


if __name__ == "__main__":
    unittest.main()
