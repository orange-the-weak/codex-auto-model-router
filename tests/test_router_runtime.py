import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "router_runtime", ROOT / "scripts" / "router_runtime.py"
)
RUNTIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNTIME)


def current(model, effort):
    return {
        "status": "verified", "thread_id": "019f6001-95ae-7411-a5ba-7895a1897e49",
        "model": model, "effort": effort, "source": "test", "reason": None,
    }


def segment():
    return {
        "segment_id": "docs", "goal": "Update docs", "task_kind": "mechanical",
        "risk": "low", "size": "tiny", "acceptance": ["Docs updated"],
        "validation_budget": "Diff check",
    }


def named_segment(name):
    value = segment()
    value["segment_id"] = name
    return value


class RouterRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.ledger = Path(self.temp.name) / "ledger.jsonl"

    def tearDown(self):
        self.temp.cleanup()

    def args(self, **values):
        return SimpleNamespace(
            ledger=self.ledger, sessions_root=None, no_runtime_detection=True, **values
        )

    def envelope(self, plan):
        selected = plan["segments"][0]
        return {
            "plan": plan, "route_id": plan["route_id"],
            "segment_id": selected["segment_id"], "attempt_id": selected["attempt_id"],
        }

    def parallel_plan(self):
        return RUNTIME.policy.plan_parallel_segments(
            [named_segment("one"), named_segment("two")],
            current=current("gpt-5.6-luna", "low"),
            runtime_total_slots=3,
        )

    def parallel_result(self, plan, **overrides):
        result = {
            "plan": plan, "segment_id": "two", "completed_ids": ["one"],
            "outcome": "completed",
        }
        result.update(overrides)
        return result

    def capture_trace(self, plan, spans):
        for identifier, start, end, outcome in spans:
            for event_type, monotonic_ns, timestamp in (
                ("parallel_worker_start", start, "2026-07-20T00:00:00+00:00"),
                ("parallel_worker_finish", end, "2026-07-20T00:00:12.5+00:00"),
            ):
                event = {
                    "event": event_type,
                    "route_id": plan["route_id"],
                    "segment_id": identifier,
                    "monotonic_ns": monotonic_ns,
                    "clock_source": RUNTIME.ledger.PARALLEL_CLOCK_SOURCE,
                    "capture_source": "router-runtime",
                    "timestamp": timestamp,
                }
                if event_type == "parallel_worker_finish":
                    event["outcome"] = outcome
                self.assertTrue(RUNTIME.ledger.append_event(self.ledger, event))

    def test_fast_local_begin_skips_claim_and_returns_capsule(self):
        plan = RUNTIME.policy.plan_apply_segments(
            [segment()], current=current("gpt-5.6-luna", "low")
        )
        output = io.StringIO()
        with redirect_stdout(output):
            RUNTIME.begin(self.args(envelope_json=json.dumps(self.envelope(plan))))
        result = json.loads(output.getvalue())
        self.assertFalse(result["claim_required"])
        self.assertIsNone(result["claimed"])
        self.assertNotIn("segments", result["context_capsule"])
        self.assertFalse(self.ledger.exists())

    def test_fast_switch_claims_once_and_blocks_replay(self):
        plan = RUNTIME.policy.plan_apply_segments(
            [segment()], current=current("gpt-5.6-sol", "high")
        )
        encoded = json.dumps(self.envelope(plan))
        with redirect_stdout(io.StringIO()):
            RUNTIME.begin(self.args(envelope_json=encoded))
        with self.assertRaisesRegex(SystemExit, "already claimed"):
            RUNTIME.begin(self.args(envelope_json=encoded))
        events, warnings = RUNTIME.ledger.read_events(self.ledger)
        self.assertEqual(warnings, [])
        self.assertEqual([item["event"] for item in events], [
            "segment_claim", "routing_efficiency",
        ])
        self.assertEqual(events[-1]["state_gate"], "stopped")

    def test_finish_records_verified_result_metrics_and_restore(self):
        plan = RUNTIME.policy.plan_apply_segments(
            [segment()], current=current("gpt-5.6-sol", "medium")
        )
        result = {
            "plan": plan, "segment_id": "docs", "outcome": "completed",
            "task_class": "docs", "verification": "deterministic",
            "source": "user-confirmed", "actual_model": "gpt-5.6-luna",
            "actual_effort": "low",
            "metrics": {
                "source": "task-metadata", "routing_seconds": 0.5,
                "tool_round_trips": 2, "state_gate": "passed",
            },
        }
        output = io.StringIO()
        with redirect_stdout(output):
            RUNTIME.finish(self.args(result_json=json.dumps(result)))
        finished = json.loads(output.getvalue())
        self.assertTrue(finished["execution_recorded"])
        self.assertTrue(finished["metrics_recorded"])
        self.assertEqual(finished["next"]["action"], "restore")
        events, warnings = RUNTIME.ledger.read_events(self.ledger)
        self.assertEqual(warnings, [])
        self.assertEqual([item["event"] for item in events], [
            "execution", "routing_efficiency",
        ])

    def test_finish_rejects_mutated_plan_before_recording(self):
        plan = RUNTIME.policy.plan_apply_segments(
            [segment()], current=current("gpt-5.6-sol", "medium")
        )
        plan["segments"][0]["goal"] = "Forged"
        result = {
            "plan": plan, "segment_id": "docs", "outcome": "completed",
            "source": "user-confirmed", "actual_model": "gpt-5.6-luna",
            "actual_effort": "low",
        }
        with self.assertRaisesRegex(SystemExit, "hash mismatch"):
            RUNTIME.finish(self.args(result_json=json.dumps(result)))
        self.assertFalse(self.ledger.exists())

    def test_parallel_finish_records_canonical_current_run_once(self):
        plan = self.parallel_plan()
        self.capture_trace(plan, [
            ("one", 100_000_000_000, 110_000_000_000, "completed"),
            ("two", 102_500_000_000, 112_500_000_000, "completed"),
        ])
        output = io.StringIO()
        with redirect_stdout(output):
            RUNTIME.finish(self.args(result_json=json.dumps(
                self.parallel_result(plan)
            )))
        finished = json.loads(output.getvalue())
        self.assertEqual(finished["next"]["action"], "return")
        self.assertTrue(finished["parallel_execution_recorded"])
        self.assertEqual(finished["parallel_execution_state"], "recorded")
        self.assertEqual(
            finished["parallel_execution_brief"],
            "并发：峰值 2｜墙钟：12.5s｜累计 worker：20s｜有效并发倍率：1.6x｜并发利用率：80%",
        )
        events, warnings = RUNTIME.ledger.read_events(self.ledger)
        self.assertEqual(warnings, [])
        self.assertEqual(len(events), 5)
        measured = events[-1]
        self.assertEqual(measured["event"], "parallel_execution")
        self.assertEqual(measured["wall_clock_seconds"], 12.5)
        self.assertEqual(measured["schema_version"], 2)
        self.assertEqual(
            measured["measurement_boundary"],
            "dispatch-confirmed-to-result-received",
        )
        self.assertEqual(
            measured["timing_provenance"], "coordinator-monotonic-v1"
        )
        self.assertEqual(len(measured["worker_intervals"]), 2)
        summary = RUNTIME.ledger.build_summary(
            events, warnings, current_route_id=plan["route_id"]
        )
        current_run = summary["parallel_execution"]["current_run"]
        self.assertEqual(current_run["route_id"], plan["route_id"])
        self.assertEqual(current_run["effective_parallel_factor"], 1.6)
        self.assertEqual(current_run["parallel_utilization_percent"], 80.0)

    def test_parallel_finish_keeps_missing_timing_pending(self):
        plan = self.parallel_plan()
        output = io.StringIO()
        with redirect_stdout(output):
            RUNTIME.finish(self.args(result_json=json.dumps(self.parallel_result(plan))))
        finished = json.loads(output.getvalue())
        self.assertFalse(finished["parallel_execution_recorded"])
        self.assertEqual(finished["parallel_execution_state"], "pending")
        self.assertEqual(
            finished["parallel_execution_pending_reason"],
            "missing-worker-start-events",
        )
        self.assertEqual(
            finished["parallel_execution_missing_fields"],
            ["one", "two"],
        )
        self.assertEqual(
            finished["parallel_execution_brief"],
            "并发：2/4｜测量：待记录",
        )
        self.assertFalse(self.ledger.exists())

    def test_parallel_finish_keeps_running_worker_pending(self):
        plan = self.parallel_plan()
        RUNTIME.ledger.append_event(self.ledger, {
            "event": "parallel_worker_start",
            "route_id": plan["route_id"],
            "segment_id": "one",
            "monotonic_ns": 100,
            "clock_source": RUNTIME.ledger.PARALLEL_CLOCK_SOURCE,
            "capture_source": "router-runtime",
        })
        output = io.StringIO()
        result = self.parallel_result(plan, outcome="failed", segment_id="one")
        with redirect_stdout(output):
            RUNTIME.finish(self.args(result_json=json.dumps(result)))
        finished = json.loads(output.getvalue())
        self.assertEqual(finished["parallel_execution_state"], "pending")
        self.assertEqual(
            finished["parallel_execution_pending_reason"],
            "worker-results-still-pending",
        )

    def test_parallel_finish_is_idempotent_for_duplicate_route(self):
        plan = self.parallel_plan()
        self.capture_trace(plan, [
            ("one", 100_000_000_000, 110_000_000_000, "completed"),
            ("two", 102_500_000_000, 112_500_000_000, "completed"),
        ])
        encoded = json.dumps(self.parallel_result(plan))
        with redirect_stdout(io.StringIO()):
            RUNTIME.finish(self.args(result_json=encoded))
        output = io.StringIO()
        with redirect_stdout(output):
            RUNTIME.finish(self.args(result_json=encoded))
        finished = json.loads(output.getvalue())
        self.assertFalse(finished["parallel_execution_recorded"])
        self.assertEqual(finished["parallel_execution_state"], "already-recorded")
        events, warnings = RUNTIME.ledger.read_events(self.ledger)
        self.assertEqual(warnings, [])
        self.assertEqual(len(events), 5)

    def test_parallel_finish_records_failed_aggregate(self):
        plan = self.parallel_plan()
        self.capture_trace(plan, [
            ("one", 100_000_000_000, 106_000_000_000, "failed"),
        ])
        result = self.parallel_result(
            plan, segment_id="one", completed_ids=[], outcome="failed",
        )
        output = io.StringIO()
        with redirect_stdout(output):
            RUNTIME.finish(self.args(result_json=json.dumps(result)))
        finished = json.loads(output.getvalue())
        self.assertFalse(finished["ok"])
        self.assertEqual(finished["next"]["action"], "stop")
        self.assertTrue(finished["parallel_execution_recorded"])
        events, warnings = RUNTIME.ledger.read_events(self.ledger)
        self.assertEqual(warnings, [])
        self.assertEqual(events[-1]["outcome"], "failed")

    def test_worker_capture_uses_runtime_clock_and_rejects_finish_without_start(self):
        plan = self.parallel_plan()
        with self.assertRaisesRegex(SystemExit, "requires a captured start"):
            RUNTIME.worker_finish(self.args(
                route_id=plan["route_id"], segment_id="one", outcome="completed"
            ))
        original_clock = RUNTIME.time.monotonic_ns
        try:
            RUNTIME.time.monotonic_ns = lambda: 123456789
            with redirect_stdout(io.StringIO()):
                RUNTIME.worker_start(self.args(
                    route_id=plan["route_id"], segment_id="one"
                ))
            RUNTIME.time.monotonic_ns = lambda: 223456789
            with redirect_stdout(io.StringIO()):
                RUNTIME.worker_finish(self.args(
                    route_id=plan["route_id"], segment_id="one", outcome="completed"
                ))
        finally:
            RUNTIME.time.monotonic_ns = original_clock
        events, warnings = RUNTIME.ledger.read_events(self.ledger)
        self.assertEqual(warnings, [])
        self.assertEqual([item["monotonic_ns"] for item in events], [123456789, 223456789])


if __name__ == "__main__":
    unittest.main()
