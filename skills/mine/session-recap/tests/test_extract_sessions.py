import datetime
import importlib.util
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "extract_sessions.py"
)
SPEC = importlib.util.spec_from_file_location("session_recap_extract", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
extract = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(extract)


class SessionRecapExtractorTest(unittest.TestCase):
    def test_default_work_day_respects_four_am_boundary(self):
        timezone = datetime.timezone(datetime.timedelta(hours=-7))

        before_boundary = datetime.datetime(2026, 7, 28, 2, 0, tzinfo=timezone)
        after_boundary = datetime.datetime(2026, 7, 28, 10, 0, tzinfo=timezone)

        self.assertEqual(extract.default_work_day(before_boundary), "2026-07-26")
        self.assertEqual(extract.default_work_day(after_boundary), "2026-07-27")

    def test_parse_args_keeps_tmates_opt_in(self):
        with mock.patch.dict(
            os.environ,
            {
                "SESSION_RECAP_TMATES_AGENTS": "",
                "SESSION_RECAP_TMATES_RUNS": "",
            },
            clear=False,
        ):
            args = extract.parse_args(["extract_sessions.py", "2026-07-27"])

        self.assertEqual(args.tmates_agents, [])
        self.assertEqual(args.tmates_runs, [])
        self.assertIsNone(args.note)

    def test_rollout_parser_drops_injected_noise_and_harvests_run_id(self):
        timestamp = datetime.datetime.now().astimezone().replace(
            hour=12, minute=0, second=0, microsecond=0
        )
        records = [
            {
                "timestamp": timestamp.isoformat(),
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "<permissions instructions>hidden",
                        }
                    ],
                },
            },
            {
                "timestamp": timestamp.isoformat(),
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "Review task/share/92352 and summarize it",
                        }
                    ],
                },
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rollout-test.jsonl"
            path.write_text(
                "\n".join(json.dumps(record) for record in records) + "\n",
                encoding="utf-8",
            )
            harvested_ids = set()
            turns = extract.rollout_user_turns(path, harvested_ids)

        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0][2], "Review task/share/92352 and summarize it")
        self.assertEqual(harvested_ids, {"92352"})

    def test_tmates_is_not_configured_without_explicit_scope(self):
        output = io.StringIO()
        with redirect_stdout(output):
            status, incomplete = extract.tmates_sessions(
                "2026-07-27", [], [], None, set()
            )

        self.assertEqual(status, "not configured")
        self.assertFalse(incomplete)
        self.assertIn("use --tmates-agent", output.getvalue())

    def test_configured_tmates_failure_is_incomplete(self):
        output = io.StringIO()
        with mock.patch.object(
            extract,
            "tmates_run_list",
            return_value=(None, "unauthorized"),
        ), redirect_stdout(output):
            status, incomplete = extract.tmates_sessions(
                "2026-07-27", ["531"], [], None, set()
            )

        self.assertEqual(status, "incomplete")
        self.assertTrue(incomplete)
        self.assertIn("agent 531: unauthorized", output.getvalue())


if __name__ == "__main__":
    unittest.main()
