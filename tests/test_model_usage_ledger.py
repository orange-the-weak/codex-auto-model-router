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

    def verified_run(self, route_id, spans, outcome="completed"):
        intervals = [
            {
                "segment_id": f"worker-{index}",
                "started_monotonic_ns": int(start * 1_000_000_000),
                "result_received_monotonic_ns": int(end * 1_000_000_000),
                "started_at": "2026-07-20T00:00:00+00:00",
                "result_received_at": "2026-07-20T00:00:20+00:00",
                "outcome": outcome,
            }
            for index, (start, end) in enumerate(spans, 1)
        ]
        return {
            "event": "parallel_execution",
            "schema_version": 2,
            "route_id": route_id,
            **LEDGER.parallel_metrics_from_intervals(intervals),
            "worker_intervals": intervals,
            "outcome": outcome,
            "source": "task-metadata",
            "measurement_boundary": "dispatch-confirmed-to-result-received",
            "timing_provenance": LEDGER.PARALLEL_TIMING_PROVENANCE,
            "clock_source": LEDGER.PARALLEL_CLOCK_SOURCE,
        }

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

    def test_resolves_ledger_to_nearest_git_root(self):
        parent = self.root / "workspace"
        child_repo = parent / "nested"
        deep_path = child_repo / "src" / "feature"
        (parent / ".git").mkdir(parents=True)
        (child_repo / ".git").mkdir(parents=True)
        deep_path.mkdir(parents=True)
        self.assertEqual(
            LEDGER.resolve_ledger_path(deep_path),
            child_repo.resolve() / ".codex" / "model-routing-history.jsonl",
        )
        self.assertEqual(
            LEDGER.resolve_ledger_path(parent),
            parent.resolve() / ".codex" / "model-routing-history.jsonl",
        )

    def test_parallel_briefs_have_one_stable_shape(self):
        self.assertEqual(
            LEDGER.parallel_run_brief({
                "wall_clock_seconds": 120,
                "cumulative_worker_seconds": 288,
                "peak_concurrency": 3,
            }),
            "并发：峰值 3｜墙钟：120s｜累计 worker：288s｜有效并发倍率：2.4x｜并发利用率：80%",
        )
        self.assertEqual(
            LEDGER.pending_parallel_brief(3, 4),
            "并发：3/4｜测量：待记录",
        )

    def test_replays_anonymized_codex_task_events_into_auditable_intervals(self):
        fixture = ROOT / "tests" / "fixtures" / "codex-parallel-task-events.jsonl"
        starts = {}
        intervals = []
        for line in fixture.read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            payload = event["payload"]
            identifier = event["router_fixture"]["segment_id"]
            if payload["type"] == "task_started":
                starts[identifier] = payload["started_at"]
            elif payload["type"] == "task_complete":
                self.assertEqual(payload["started_at"], starts[identifier])
                self.assertEqual(
                    payload["duration_ms"],
                    int((payload["completed_at"] - payload["started_at"]) * 1000),
                )
                intervals.append({
                    "segment_id": identifier,
                    "started_monotonic_ns": int(payload["started_at"] * 1_000_000_000),
                    "result_received_monotonic_ns": int(payload["completed_at"] * 1_000_000_000),
                    "started_at": event["timestamp"],
                    "result_received_at": event["timestamp"],
                    "outcome": event["router_fixture"]["outcome"],
                })
        metrics = LEDGER.parallel_metrics_from_intervals(intervals)
        self.assertEqual(metrics, {
            "wall_clock_seconds": 15.0,
            "cumulative_worker_seconds": 25.0,
            "peak_concurrency": 2,
            "worker_count": 3,
        })

    def test_interval_metrics_handle_refill_boundary_and_slow_tail(self):
        adjacent = self.verified_run("adjacent", [(0, 5), (5, 10)])
        self.assertEqual(adjacent["peak_concurrency"], 1)
        self.assertEqual(adjacent["wall_clock_seconds"], 10)
        slow_tail = self.verified_run("slow-tail", [(0, 20), (0, 5), (5, 10)])
        self.assertEqual(slow_tail["peak_concurrency"], 2)
        self.assertEqual(slow_tail["cumulative_worker_seconds"], 30)
        self.assertEqual(
            LEDGER.parallel_run_brief(slow_tail),
            "并发：峰值 2｜墙钟：20s｜累计 worker：30s｜有效并发倍率：1.5x｜并发利用率：75%",
        )

    def test_interval_metrics_reject_reversed_or_zero_duration(self):
        for start, end in ((2, 1), (1, 1)):
            with self.assertRaisesRegex(ValueError, "positive duration"):
                LEDGER.parallel_metrics_from_intervals([{
                    "started_monotonic_ns": start,
                    "result_received_monotonic_ns": end,
                }])

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
        summary = LEDGER.build_summary(*LEDGER.read_events(self.ledger), current_route_id="route-1")
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
        measured = self.verified_run("route-1", [(0, 12.5), (0, 10), (0, 6.5)])
        self.assertTrue(LEDGER.append_event(self.ledger, plan))
        self.assertTrue(LEDGER.append_event(self.ledger, measured))
        self.assertFalse(LEDGER.append_event(self.ledger, measured.copy()))
        summary = LEDGER.build_summary(*LEDGER.read_events(self.ledger), current_route_id="route-1")
        self.assertEqual(summary["parallel_plans"]["count"], 1)
        self.assertEqual(summary["parallel_execution"]["historical_summary"], {
            "count": 1, "wall_clock_seconds": 12.5,
            "cumulative_worker_seconds": 29.0, "peak_concurrency": 3,
            "effective_parallel_factor": 2.32,
            "parallel_utilization_percent": 77.3,
        })
        self.assertEqual(summary["parallel_execution"]["current_run"], {
            "route_id": "route-1", "schema_version": 2,
            "clock_source": "python-monotonic-ns", "wall_clock_seconds": 12.5,
            "cumulative_worker_seconds": 29.0, "peak_concurrency": 3, "worker_count": 3,
            "outcome": "completed",
            "measurement_boundary": "dispatch-confirmed-to-result-received",
            "timing_provenance": "coordinator-monotonic-v1",
            "effective_parallel_factor": 2.32,
            "parallel_utilization_percent": 77.3,
        })
        self.assertNotIn("worker_time_compression_percent", json.dumps(summary))
        rendered = LEDGER.render_markdown(summary)
        self.assertIn("effective parallel factor: 2.32x", rendered)
        self.assertIn("parallel utilization: 77.3%", rendered)
        self.assertIn("Historical verified parallel execution", rendered)
        self.assertIn("Current verified parallel run", rendered)
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

    def test_verified_parallel_execution_rejects_tampered_aggregate_or_provenance(self):
        base = self.verified_run("route-1", [(0, 10), (0, 10)])
        with self.assertRaisesRegex(ValueError, "timing provenance"):
            LEDGER.validate_event({**base, "timing_provenance": "task-metadata"})
        with self.assertRaisesRegex(ValueError, "does not match intervals"):
            LEDGER.validate_event({**base, "wall_clock_seconds": 11})
        failed_interval = {**base["worker_intervals"][0], "outcome": "failed"}
        with self.assertRaisesRegex(ValueError, "contains failed worker"):
            LEDGER.validate_event({
                **base,
                "worker_intervals": [failed_interval, base["worker_intervals"][1]],
            })

    def test_legacy_parallel_execution_is_readable_but_excluded_from_verified_metrics(self):
        legacy = {
            "event": "parallel_execution", "route_id": "legacy-route",
            "wall_clock_seconds": 8, "cumulative_worker_seconds": 12,
            "peak_concurrency": 2, "worker_count": 2,
            "outcome": "completed", "source": "user-confirmed",
        }
        summary = LEDGER.build_summary([legacy], [], current_route_id="legacy-route")
        self.assertIsNone(summary["parallel_execution"]["current_run"])
        self.assertEqual(summary["parallel_execution"]["historical_summary"]["count"], 0)
        self.assertEqual(summary["parallel_execution"]["legacy_unverified"], {
            "count": 1, "route_ids": ["legacy-route"],
        })
        self.assertIn("Excluded from verified metrics: 1", LEDGER.render_markdown(summary))

    def test_parallel_current_run_is_latest_while_historical_summary_aggregates_all_runs(self):
        events = [
            self.verified_run("route-first", [(0, 10), (0, 5)]),
            self.verified_run("route-latest", [(0, 4), (0, 4)]),
        ]
        summary = LEDGER.build_summary(events, [])
        self.assertIsNone(summary["parallel_execution"]["current_run"])
        self.assertNotIn("Current verified parallel run", LEDGER.render_markdown(summary))
        summary = LEDGER.build_summary(events, [], current_route_id="route-first")
        self.assertEqual(summary["parallel_execution"]["current_run"]["route_id"], "route-first")
        self.assertEqual(summary["parallel_execution"]["historical_summary"], {
            "count": 2, "wall_clock_seconds": 14,
            "cumulative_worker_seconds": 23, "peak_concurrency": 2,
            "effective_parallel_factor": 1.64,
            "parallel_utilization_percent": 82.1,
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
