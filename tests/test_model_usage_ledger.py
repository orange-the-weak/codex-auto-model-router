import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("model_usage_ledger", ROOT / "scripts" / "model_usage_ledger.py")
LEDGER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LEDGER)


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.ledger = self.root / "history.jsonl"

    def tearDown(self):
        self.temp.cleanup()

    def test_deduplicates_event_ids(self):
        event = {"event": "skill_run", "event_id": "same", "mode": "query", "analysis_model": "local-script", "effort": "none"}
        self.assertTrue(LEDGER.append_event(self.ledger, event.copy()))
        self.assertFalse(LEDGER.append_event(self.ledger, event.copy()))

    def test_apply_is_a_valid_skill_run_mode(self):
        parser = LEDGER.parser()
        args = parser.parse_args([
            "record", "--ledger", str(self.ledger), "--event", "skill_run",
            "--mode", "apply", "--analysis-model", "gpt-5.6-terra", "--effort", "medium",
        ])
        with redirect_stdout(io.StringIO()):
            args.func(args)
        events, warnings = LEDGER.read_events(self.ledger)
        self.assertEqual(warnings, [])
        self.assertEqual(events[0]["mode"], "apply")

    def test_reports_model_and_effort_usage(self):
        LEDGER.append_event(self.ledger, {
            "event": "execution", "model": "GPT-5.6 Terra", "effort": "low",
            "task_class": "ui", "outcome": "completed", "source": "user-confirmed",
            "route_id": "route-1", "segment_id": "implement",
        })
        events, warnings = LEDGER.read_events(self.ledger)
        summary = LEDGER.build_summary(events, warnings)
        self.assertEqual(summary["actual_execution"]["items"]["GPT-5.6 Terra"]["percent"], 100.0)
        self.assertEqual(summary["model_effort_usage"]["items"]["GPT-5.6 Terra | low"]["count"], 1)

    def test_records_segment_identifiers(self):
        parser = LEDGER.parser()
        args = parser.parse_args([
            "record", "--ledger", str(self.ledger), "--event", "execution",
            "--route-id", "route-1", "--segment-id", "verify", "--model", "gpt-5.6-luna",
            "--effort", "low", "--task-class", "tests", "--outcome", "completed",
            "--source", "task-metadata", "--verification", "deterministic",
        ])
        with redirect_stdout(io.StringIO()):
            args.func(args)
        events, warnings = LEDGER.read_events(self.ledger)
        self.assertEqual(warnings, [])
        self.assertEqual(events[0]["route_id"], "route-1")
        self.assertEqual(events[0]["segment_id"], "verify")

    def test_segment_replay_is_idempotent_by_route_and_segment(self):
        event = {
            "event": "execution", "route_id": "route-1", "segment_id": "implement",
            "model": "Terra", "effort": "medium", "task_class": "code",
            "outcome": "completed", "source": "task-metadata", "verification": "deterministic",
        }
        self.assertTrue(LEDGER.append_event(self.ledger, event.copy()))
        self.assertFalse(LEDGER.append_event(self.ledger, event.copy()))
        events, _ = LEDGER.read_events(self.ledger)
        self.assertEqual(len(events), 1)

    def test_segment_claim_blocks_replay_before_execution(self):
        parser = LEDGER.parser()
        command = [
            "claim", "--ledger", str(self.ledger), "--route-id", "route-1",
            "--segment-id", "implement", "--attempt-id", "attempt-1",
        ]
        outputs = []
        for _ in range(2):
            args = parser.parse_args(command)
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                args.func(args)
            outputs.append(json.loads(buffer.getvalue()))
        self.assertTrue(outputs[0]["claimed"])
        self.assertFalse(outputs[1]["claimed"])
        events, warnings = LEDGER.read_events(self.ledger)
        self.assertEqual(warnings, [])
        self.assertEqual([item["event"] for item in events], ["segment_claim"])

    def test_rejects_empty_segment_identifier(self):
        event = {
            "event": "execution", "model": "Terra", "effort": "medium",
            "task_class": "docs", "outcome": "completed", "source": "task-metadata",
            "segment_id": "",
        }
        with self.assertRaisesRegex(ValueError, "segment_id must be a non-empty string"):
            LEDGER.validate_event(event)

    def test_requires_route_and_segment_identifiers_together(self):
        event = {
            "event": "execution", "route_id": "route-1", "model": "Terra",
            "effort": "medium", "task_class": "docs", "outcome": "completed",
            "source": "task-metadata",
        }
        with self.assertRaisesRegex(ValueError, "requires both route_id and segment_id"):
            LEDGER.validate_event(event)

    def test_legacy_whole_task_records_do_not_distort_segment_ratio(self):
        events = [
            {"event": "execution", "model": "Sol", "effort": "high", "task_class": "legacy", "outcome": "completed", "source": "user-confirmed"},
            {"event": "execution", "route_id": "route-1", "segment_id": "verify", "model": "Luna", "effort": "low", "task_class": "tests", "outcome": "completed", "source": "task-metadata"},
        ]
        summary = LEDGER.build_summary(events, [])
        self.assertEqual(summary["actual_execution"]["items"]["Luna"]["percent"], 100.0)
        self.assertEqual(summary["legacy_execution"]["items"]["Sol"]["count"], 1)

    def test_segment_without_reliable_source_is_not_counted(self):
        summary = LEDGER.build_summary([{
            "event": "execution", "route_id": "route-1", "segment_id": "configured-only",
            "model": "Sol", "effort": "high", "task_class": "code", "outcome": "completed",
        }], [])
        self.assertEqual(summary["actual_execution"]["total"], 0)
        self.assertEqual(summary["route_performance"], {})

    def test_retune_signals_use_thresholds(self):
        events = []
        for index, outcome in enumerate(("failed", "escalated", "reworked", "completed", "completed")):
            events.append({"event": "execution", "route_id": "auth-route", "segment_id": f"auth-{index}", "model": "Luna", "effort": "low", "task_class": "auth", "outcome": outcome, "source": "task-metadata"})
        for index in range(10):
            events.append({
                "event": "execution", "route_id": "docs-route", "segment_id": f"docs-{index}", "model": "Terra", "effort": "medium",
                "task_class": "docs", "outcome": "completed", "verification": "deterministic", "source": "task-metadata",
            })
        summary = LEDGER.build_summary(events, [])
        self.assertEqual(summary["route_performance"]["auth | Luna | low"]["retune_signal"], "raise_candidate")
        self.assertEqual(summary["route_performance"]["docs | Terra | medium"]["retune_signal"], "lower_candidate")

    def test_skips_malformed_lines(self):
        valid = {"event": "skill_run", "mode": "query", "analysis_model": "local-script", "effort": "none"}
        self.ledger.write_text('{bad json}\n' + json.dumps(valid) + "\n")
        events, warnings = LEDGER.read_events(self.ledger)
        self.assertEqual(len(events), 1)
        self.assertEqual(len(warnings), 1)

    def test_skips_schema_invalid_events(self):
        invalid = {"event": "execution", "model": "Terra", "effort": "turbo", "task_class": "docs", "outcome": "completed", "source": "task-metadata"}
        self.ledger.write_text(json.dumps(invalid) + "\n")
        events, warnings = LEDGER.read_events(self.ledger)
        self.assertEqual(events, [])
        self.assertEqual(len(warnings), 1)

    def test_lowering_requires_deterministic_verification(self):
        events = [
            {
                "event": "execution", "route_id": "docs-route", "segment_id": f"docs-{index}", "model": "Terra", "effort": "medium",
                "task_class": "docs", "outcome": "completed", "verification": "manual", "source": "task-metadata",
            }
            for index in range(10)
        ]
        summary = LEDGER.build_summary(events, [])
        self.assertEqual(summary["route_performance"]["docs | Terra | medium"]["retune_signal"], "hold")

    def test_cancelled_duration_is_excluded(self):
        events = [
            {"event": "execution", "route_id": "route", "segment_id": "done", "model": "Terra", "effort": "medium", "task_class": "docs", "outcome": "completed", "duration_seconds": 10, "source": "task-metadata"},
            {"event": "execution", "route_id": "route", "segment_id": "cancelled", "model": "Terra", "effort": "medium", "task_class": "docs", "outcome": "cancelled", "duration_seconds": 1000, "source": "task-metadata"},
        ]
        summary = LEDGER.build_summary(events, [])
        performance = summary["route_performance"]["docs | Terra | medium"]
        self.assertEqual(performance["duration_median_seconds"], 10)
        self.assertEqual(performance["duration_p75_seconds"], 10)

    def test_report_markers_preserve_surrounding_content(self):
        report = self.root / "report.md"
        report.write_text("before\n\n<!-- MODEL_USAGE_START -->\nstale\n<!-- MODEL_USAGE_END -->\n\nafter\n")
        LEDGER.update_report(report, "<!-- MODEL_USAGE_START -->\nnew\n<!-- MODEL_USAGE_END -->")
        text = report.read_text()
        self.assertIn("before", text)
        self.assertIn("after", text)
        self.assertIn("new", text)
        self.assertNotIn("stale", text)


if __name__ == "__main__":
    unittest.main()
