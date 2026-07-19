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

    def test_reports_only_verified_model_concurrency(self):
        LEDGER.append_event(self.ledger, {
            "event": "execution", "model": "GPT-5.6 Terra", "effort": "low",
            "task_class": "ui", "outcome": "completed", "source": "task-metadata",
            "route_id": "route-1", "segment_id": "one", "concurrency": 3,
        })
        LEDGER.append_event(self.ledger, {
            "event": "execution", "model": "GPT-5.6 Luna", "effort": "low",
            "task_class": "docs", "outcome": "completed", "source": "task-metadata",
            "route_id": "route-1", "segment_id": "two",
        })
        summary = LEDGER.build_summary(*LEDGER.read_events(self.ledger))
        self.assertEqual(summary["model_concurrency_usage"]["total"], 1)
        self.assertEqual(
            summary["model_concurrency_usage"]["items"]["GPT-5.6 Terra | 3"]["percent"],
            100.0,
        )

    def test_parallel_plan_and_verified_execution_are_separate(self):
        plan = {
            "event": "parallel_plan", "route_id": "route-1",
            "protocol": "dependency-parallel-v1", "effective_max_parallelism": 4,
            "planned_worker_count": 3,
            "model_plan": {"gpt-5.6-sol": 1, "gpt-5.6-terra": 2},
        }
        measured = {
            "event": "parallel_execution", "route_id": "route-1",
            "wall_clock_seconds": 12.5, "cumulative_worker_seconds": 29.0,
            "peak_concurrency": 3, "worker_count": 3,
            "outcome": "completed", "source": "task-metadata",
        }
        self.assertTrue(LEDGER.append_event(self.ledger, plan))
        self.assertTrue(LEDGER.append_event(self.ledger, measured))
        self.assertFalse(LEDGER.append_event(self.ledger, measured.copy()))
        summary = LEDGER.build_summary(*LEDGER.read_events(self.ledger))
        self.assertEqual(summary["parallel_plans"]["count"], 1)
        self.assertEqual(summary["parallel_execution"]["wall_clock_seconds"], 12.5)
        self.assertEqual(summary["parallel_execution"]["cumulative_worker_seconds"], 29.0)
        self.assertEqual(summary["parallel_execution"]["effective_parallel_factor"], 2.32)
        self.assertEqual(summary["parallel_execution"]["parallel_utilization_percent"], 77.3)
        self.assertEqual(summary["parallel_execution"]["worker_time_compression_percent"], 56.9)
        self.assertEqual(summary["parallel_execution"]["latest"], {
            "route_id": "route-1", "wall_clock_seconds": 12.5,
            "cumulative_worker_seconds": 29.0, "peak_concurrency": 3,
            "effective_parallel_factor": 2.32,
            "parallel_utilization_percent": 77.3,
            "worker_time_compression_percent": 56.9,
        })
        rendered = LEDGER.render_markdown(summary)
        self.assertIn("effective parallel factor: 2.32x", rendered)
        self.assertIn("parallel utilization: 77.3%", rendered)
        self.assertIn("not serial/parallel speedup", rendered)

    def test_parallel_plan_records_adaptive_concurrency_intent(self):
        plan = {
            "event": "parallel_plan", "route_id": "route-adaptive",
            "protocol": "dependency-parallel-v1",
            "parallelism_source": "adaptive-extended",
            "requested_max_parallelism": 6,
            "effective_max_parallelism": 5,
            "planned_worker_count": 5,
            "model_plan": {"gpt-5.6-sol": 1, "gpt-5.6-terra": 4},
        }
        self.assertTrue(LEDGER.append_event(self.ledger, plan))
        latest = LEDGER.build_summary(
            *LEDGER.read_events(self.ledger)
        )["parallel_plans"]["latest"]
        self.assertEqual(latest["parallelism_source"], "adaptive-extended")
        self.assertEqual(latest["requested_max_parallelism"], 6)
        self.assertEqual(latest["effective_max_parallelism"], 5)

    def test_parallel_plan_rejects_inconsistent_concurrency_intent(self):
        with self.assertRaisesRegex(ValueError, "adaptive parallel plan must request six"):
            LEDGER.validate_event({
                "event": "parallel_plan", "route_id": "route-invalid",
                "protocol": "dependency-parallel-v1",
                "parallelism_source": "adaptive-extended",
                "requested_max_parallelism": 4,
                "effective_max_parallelism": 4,
                "planned_worker_count": 4,
                "model_plan": {"gpt-5.6-terra": 4},
            })

    def test_parallel_plan_cli_writes_requested_effective_and_source(self):
        args = LEDGER.parser().parse_args([
            "parallel-plan", "--ledger", str(self.ledger),
            "--route-id", "route-cli",
            "--requested-max-parallelism", "4",
            "--effective-max-parallelism", "3",
            "--parallelism-source", "smart-reduced",
            "--planned-worker-count", "3",
            "--model-plan", '{"gpt-5.6-terra":3}',
        ])
        with redirect_stdout(io.StringIO()):
            args.func(args)
        event = LEDGER.read_events(self.ledger)[0][0]
        self.assertEqual(event["requested_max_parallelism"], 4)
        self.assertEqual(event["effective_max_parallelism"], 3)
        self.assertEqual(event["parallelism_source"], "smart-reduced")

    def test_parallel_plan_accepts_smart_reduced_concurrency_intent(self):
        event = LEDGER.validate_event({
            "event": "parallel_plan", "route_id": "route-smart-reduced",
            "protocol": "dependency-parallel-v1",
            "parallelism_source": "smart-reduced",
            "requested_max_parallelism": 4,
            "effective_max_parallelism": 2,
            "planned_worker_count": 3,
            "model_plan": {"gpt-5.6-sol": 1, "gpt-5.6-terra": 2},
        })
        self.assertEqual(event["parallelism_source"], "smart-reduced")

    def test_parallel_execution_rejects_unverified_timing(self):
        with self.assertRaisesRegex(ValueError, "verified outcome and source"):
            LEDGER.validate_event({
                "event": "parallel_execution", "route_id": "route-1",
                "wall_clock_seconds": 1, "cumulative_worker_seconds": 1,
                "peak_concurrency": 1, "worker_count": 1,
                "outcome": "completed", "source": "configured-only",
            })

    def test_parallel_execution_rejects_impossible_worker_overlap(self):
        with self.assertRaisesRegex(ValueError, "exceeds observed concurrency capacity"):
            LEDGER.validate_event({
                "event": "parallel_execution", "route_id": "route-1",
                "wall_clock_seconds": 10, "cumulative_worker_seconds": 31,
                "peak_concurrency": 3, "worker_count": 3,
                "outcome": "completed", "source": "task-metadata",
            })

    def test_routing_efficiency_records_only_observed_fields(self):
        event = {
            "event": "routing_efficiency", "route_id": "route-1",
            "segment_id": "implement", "source": "task-metadata",
            "routing_seconds": 1.2, "queue_wait_seconds": 0.4,
            "model_round_trips": 2, "tool_round_trips": 3,
            "state_gate": "passed",
        }
        self.assertTrue(LEDGER.append_event(self.ledger, event))
        self.assertFalse(LEDGER.append_event(self.ledger, event.copy()))
        summary = LEDGER.build_summary(*LEDGER.read_events(self.ledger))
        self.assertEqual(summary["routing_efficiency"]["count"], 1)
        self.assertEqual(summary["routing_efficiency"]["durations"]["routing_seconds"], 1.2)
        self.assertEqual(summary["routing_efficiency"]["round_trips"]["tool_round_trips"], 3)
        self.assertIsNone(summary["routing_efficiency"]["durations"]["restore_seconds"])
        self.assertEqual(summary["routing_efficiency"]["round_trips"]["model_round_trips"], 2)
        self.assertIsNone(summary["routing_efficiency"]["durations"]["useful_execution_seconds"])
        self.assertEqual(summary["routing_efficiency"]["state_gates"]["passed"], 1)

    def test_routing_efficiency_rejects_guessed_or_empty_metrics(self):
        with self.assertRaisesRegex(ValueError, "task metadata or user confirmation"):
            LEDGER.validate_event({
                "event": "routing_efficiency", "route_id": "route-1",
                "source": "estimated", "routing_seconds": 1,
            })
        with self.assertRaisesRegex(ValueError, "at least one observed metric"):
            LEDGER.validate_event({
                "event": "routing_efficiency", "route_id": "route-1",
                "source": "task-metadata",
            })

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
