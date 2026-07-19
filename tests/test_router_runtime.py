import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


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

    def begin_result(self, envelope, runtime_current):
        output = io.StringIO()
        trusted_capacity = envelope.get("dispatch_capacity")
        with patch.object(RUNTIME, "_current", return_value=runtime_current):
            with redirect_stdout(output):
                RUNTIME.begin(self.args(
                    envelope_json=json.dumps(envelope),
                    trusted_dispatch_capacity_json=(
                        json.dumps(trusted_capacity) if trusted_capacity else None
                    ),
                ))
        return json.loads(output.getvalue())

    def parallel_plan(self):
        return RUNTIME.policy.plan_parallel_segments(
            [named_segment("one"), named_segment("two")],
            current=current("gpt-5.6-luna", "low"),
            runtime_total_slots=3,
        )

    def parallel_envelope(self, plan, identifier="one"):
        selected = next(
            item for item in plan["segments"] if item["segment_id"] == identifier
        )
        return {
            "plan": plan, "route_id": plan["route_id"],
            "segment_id": identifier, "attempt_id": selected["attempt_id"],
            "completed_ids": [], "running_ids": [],
            "agent_task_name": identifier,
            "dispatch_capacity": {
                "schema_version": 1, "observation_source": "task-metadata",
                "capacity_source": "observed-total-slots",
                "snapshot_scope": "immediate-pre-dispatch",
                "coordinator_reserved_slots": 1,
                "runtime_total_slots": 3, "runtime_running_workers": 0,
            },
        }

    def parallel_result(self, plan, **overrides):
        identifier = overrides.pop("segment_id", "two")
        selected = next(
            item for item in plan["segments"] if item["segment_id"] == identifier
        )
        result = {
            "plan": plan, "route_id": plan["route_id"],
            "plan_hash": plan["plan_hash"], "segment_id": identifier,
            "attempt_id": selected["attempt_id"], "outcome": "completed",
            "task_metadata": {
                "trusted": True, "source": "task-metadata",
                "route_id": plan["route_id"], "plan_hash": plan["plan_hash"],
                "segment_id": identifier, "attempt_id": selected["attempt_id"],
                "actual_model": selected["model"],
                "actual_effort": selected["effort"],
            },
        }
        result.update(overrides)
        return result

    def claim(self, plan, identifier):
        selected = next(
            item for item in plan["segments"] if item["segment_id"] == identifier
        )
        self.assertTrue(RUNTIME.ledger.append_event(self.ledger, {
            "event": "segment_claim", "route_id": plan["route_id"],
            "plan_hash": plan["plan_hash"], "segment_id": identifier,
            "attempt_id": selected["attempt_id"],
            "claim_state": "prepared",
        }))

    def identity_args(self, plan, identifier, **values):
        selected = next(
            item for item in plan["segments"] if item["segment_id"] == identifier
        )
        return self.args(
            route_id=plan["route_id"], plan_hash=plan["plan_hash"],
            segment_id=identifier, attempt_id=selected["attempt_id"], **values,
        )

    def capability_decision(self, plan, identifier, execution_model="gpt-5.5"):
        selected = next(
            item for item in plan["segments"] if item["segment_id"] == identifier
        )
        return {
            "schema_version": 1, "verified": True,
            "source": RUNTIME.ledger.CAPABILITY_DECISION_SOURCE,
            "route_id": plan["route_id"], "plan_hash": plan["plan_hash"],
            "segment_id": identifier, "attempt_id": selected["attempt_id"],
            "target_model": selected["model"], "target_effort": selected["effort"],
            "execution_model": execution_model,
            "execution_effort": selected["effort"],
            "reason": "gpt56-family-unavailable",
            "availability_complete": True, "available_models": ["gpt-5.5"],
        }

    def finish_result(self, result):
        output = io.StringIO()
        with redirect_stdout(output):
            RUNTIME.finish(self.args(result_json=json.dumps(result)))
        return json.loads(output.getvalue())

    def capture_trace(self, plan, spans):
        for identifier, start, end, outcome in spans:
            for event_type, monotonic_ns, timestamp in (
                ("parallel_worker_start", start, "2026-07-20T00:00:00+00:00"),
                ("parallel_worker_finish", end, "2026-07-20T00:00:12.5+00:00"),
            ):
                event = {
                    "event": event_type,
                    "route_id": plan["route_id"],
                    "plan_hash": plan["plan_hash"],
                    "segment_id": identifier,
                    "attempt_id": next(
                        item["attempt_id"] for item in plan["segments"]
                        if item["segment_id"] == identifier
                    ),
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
        result = self.begin_result(
            self.envelope(plan), current("gpt-5.6-luna", "low")
        )
        self.assertFalse(result["claim_required"])
        self.assertIsNone(result["claimed"])
        self.assertNotIn("segments", result["context_capsule"])
        self.assertFalse(self.ledger.exists())

    def test_fast_switch_claims_once_and_blocks_replay(self):
        plan = RUNTIME.policy.plan_apply_segments(
            [segment()], current=current("gpt-5.6-sol", "high")
        )
        encoded = json.dumps(self.envelope(plan))
        with patch.object(
            RUNTIME, "_current", return_value=current("gpt-5.6-luna", "low")
        ):
            with redirect_stdout(io.StringIO()):
                RUNTIME.begin(self.args(envelope_json=encoded))
        with self.assertRaisesRegex(SystemExit, "already claimed"):
            with patch.object(
                RUNTIME, "_current", return_value=current("gpt-5.6-luna", "low")
            ):
                RUNTIME.begin(self.args(envelope_json=encoded))
        events, warnings = RUNTIME.ledger.read_events(self.ledger)
        self.assertEqual(warnings, [])
        self.assertEqual([item["event"] for item in events], [
            "segment_claim", "routing_efficiency",
        ])
        self.assertEqual(events[-1]["state_gate"], "stopped")

    def test_begin_rejects_unknown_or_mismatched_runtime_before_claim(self):
        plan = RUNTIME.policy.plan_apply_segments(
            [segment()], current=current("gpt-5.6-luna", "low")
        )
        envelope = self.envelope(plan)
        for runtime_current, message in (
            (RUNTIME.policy.unavailable_current(), "unverified"),
            (current("gpt-5.6-sol", "high"), "does not match Segment route"),
        ):
            ledger_path = Path(self.temp.name) / f"{message[:3]}.jsonl"
            with self.assertRaisesRegex(SystemExit, message):
                with patch.object(RUNTIME, "_current", return_value=runtime_current):
                    RUNTIME.begin(SimpleNamespace(
                        ledger=ledger_path, sessions_root=None,
                        no_runtime_detection=False,
                        envelope_json=json.dumps(envelope),
                    ))
            events, _ = RUNTIME.ledger.read_events(ledger_path)
            self.assertNotIn("segment_claim", [item["event"] for item in events])

    def test_begin_binds_verified_gpt55_capability_fallback_to_claim(self):
        plan = RUNTIME.policy.plan_apply_segments(
            [segment()], current=current("gpt-5.6-luna", "low")
        )
        decision = self.capability_decision(plan, "docs")
        envelope = {**self.envelope(plan), "capability_decision": decision}
        started = self.begin_result(envelope, current("gpt-5.5", "low"))
        self.assertTrue(started["claim_required"])
        self.assertEqual(started["claim_state"], "prepared")
        events, warnings = RUNTIME.ledger.read_events(self.ledger)
        self.assertEqual(warnings, [])
        self.assertEqual(events[0]["capability_decision_hash"], (
            RUNTIME.ledger.capability_decision_hash(decision)
        ))

    def test_parallel_prepared_claim_recovers_until_dispatch_confirmed(self):
        plan = self.parallel_plan()
        envelope = self.parallel_envelope(plan)
        runtime_current = current(
            plan["segments"][0]["model"], plan["segments"][0]["effort"]
        )
        first = self.begin_result(envelope, runtime_current)
        self.assertEqual(first["claim_state"], "prepared")
        recovered = self.begin_result(envelope, runtime_current)
        self.assertEqual(recovered["claim_state"], "recovered")
        self.assertTrue(recovered["prepared_recovery"])
        with redirect_stdout(io.StringIO()):
            RUNTIME.worker_start(self.identity_args(plan, "one"))
        with self.assertRaisesRegex(SystemExit, "already dispatched"):
            self.begin_result(envelope, runtime_current)

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
        self.claim(plan, "docs")
        finished = self.finish_result(result)
        self.assertTrue(finished["execution_recorded"])
        self.assertTrue(finished["metrics_recorded"])
        self.assertEqual(finished["next"]["action"], "restore")
        events, warnings = RUNTIME.ledger.read_events(self.ledger)
        self.assertEqual(warnings, [])
        self.assertEqual([item["event"] for item in events], [
            "segment_claim", "segment_result", "execution", "routing_efficiency",
        ])

    def test_finish_requires_matching_unconsumed_claim_except_fast_local(self):
        switched = RUNTIME.policy.plan_apply_segments(
            [segment()], current=current("gpt-5.6-sol", "medium")
        )
        result = {
            "plan": switched, "segment_id": "docs", "outcome": "completed",
            "source": "user-confirmed", "actual_model": "gpt-5.6-luna",
            "actual_effort": "low",
        }
        with self.assertRaisesRegex(SystemExit, "matching segment claim"):
            RUNTIME.finish(self.args(result_json=json.dumps(result)))
        self.claim(switched, "docs")
        finished = self.finish_result(result)
        self.assertTrue(finished["claim_consumed"])
        recovered = self.finish_result(result)
        self.assertTrue(recovered["finish_recovered"])
        self.assertFalse(recovered["execution_recorded"])

        local_ledger = Path(self.temp.name) / "local.jsonl"
        local = RUNTIME.policy.plan_apply_segments(
            [segment()], current=current("gpt-5.6-luna", "low")
        )
        local_result = {
            "plan": local, "segment_id": "docs", "outcome": "completed",
            "source": "user-confirmed", "actual_model": "gpt-5.6-luna",
            "actual_effort": "low",
        }
        output = io.StringIO()
        with redirect_stdout(output):
            RUNTIME.finish(SimpleNamespace(
                ledger=local_ledger, sessions_root=None,
                no_runtime_detection=True, result_json=json.dumps(local_result),
            ))
        self.assertTrue(json.loads(output.getvalue())["claim_consumed"])

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

    def test_sequential_finish_derives_cursor_from_consumed_results(self):
        first = named_segment("one")
        first.update({"model": "Luna", "effort": "low"})
        second = named_segment("two")
        second.update({
            "task_kind": "complex", "risk": "high", "size": "normal",
            "model": "Sol", "effort": "high", "depends_on": ["one"],
        })
        plan = RUNTIME.policy.plan_apply_segments(
            [first, second], current=current("gpt-5.6-luna", "low")
        )
        self.claim(plan, "one")
        self.claim(plan, "two")
        forged_second = {
            "plan": plan, "segment_id": "two", "cursor": 1,
            "completed_ids": ["one"], "outcome": "completed",
        }
        with self.assertRaisesRegex(SystemExit, "authoritative cursor"):
            RUNTIME.finish(self.args(result_json=json.dumps(forged_second)))
        first_result = {
            "plan": plan, "segment_id": "one", "cursor": 99,
            "completed_ids": ["forged"], "outcome": "completed",
        }
        finished = self.finish_result(first_result)
        self.assertEqual(finished["next"], {"action": "advance", "cursor": 1})
        second_finished = self.finish_result(forged_second)
        self.assertNotEqual(second_finished["next"]["action"], "advance")

    def test_finish_rejects_explicit_identity_mismatch(self):
        plan = RUNTIME.policy.plan_apply_segments(
            [segment()], current=current("gpt-5.6-sol", "medium")
        )
        self.claim(plan, "docs")
        result = {
            "plan": plan, "route_id": "forged", "segment_id": "docs",
            "outcome": "completed",
        }
        with self.assertRaisesRegex(SystemExit, "route_id mismatch"):
            RUNTIME.finish(self.args(result_json=json.dumps(result)))

    def test_finish_requires_gpt55_family_unavailable_reason_before_consuming_claim(self):
        plan = RUNTIME.policy.plan_apply_segments(
            [segment()], current=current("gpt-5.6-sol", "medium")
        )
        decision = self.capability_decision(plan, "docs")
        selected = plan["segments"][0]
        self.assertTrue(RUNTIME.ledger.append_event(self.ledger, {
            "event": "segment_claim", "route_id": plan["route_id"],
            "plan_hash": plan["plan_hash"], "segment_id": "docs",
            "attempt_id": selected["attempt_id"], "claim_state": "prepared",
            "capability_decision_hash": RUNTIME.ledger.capability_decision_hash(decision),
        }))
        result = {
            "plan": plan, "segment_id": "docs", "outcome": "completed",
            "source": "user-confirmed", "actual_model": "gpt-5.5",
            "actual_effort": selected["effort"],
        }
        with self.assertRaisesRegex(SystemExit, "capability_decision"):
            RUNTIME.finish(self.args(result_json=json.dumps(result)))
        events, _ = RUNTIME.ledger.read_events(self.ledger)
        self.assertNotIn("segment_result", [item["event"] for item in events])
        result["fallback_reason"] = "gpt56-family-unavailable"
        with self.assertRaisesRegex(SystemExit, "capability_decision"):
            RUNTIME.finish(self.args(result_json=json.dumps(result)))
        result["capability_decision"] = decision
        finished = self.finish_result(result)
        self.assertTrue(finished["execution_recorded"])

    def test_parallel_execution_accepts_only_identity_bound_trusted_metadata(self):
        plan = self.parallel_plan()
        self.claim(plan, "one")
        self.capture_trace(plan, [
            ("one", 100, 200, "completed"),
        ])
        untrusted = self.parallel_result(plan, segment_id="one")
        untrusted.pop("task_metadata")
        untrusted.update({
            "source": "task-metadata", "actual_model": "gpt-5.6-sol",
            "actual_effort": "high",
        })
        finished = self.finish_result(untrusted)
        self.assertFalse(finished["execution_recorded"])
        self.assertIsNone(finished["execution_runtime_metadata"])

        second_ledger = Path(self.temp.name) / "trusted.jsonl"
        original_ledger = self.ledger
        self.ledger = second_ledger
        try:
            plan = self.parallel_plan()
            self.claim(plan, "one")
            self.capture_trace(plan, [("one", 100, 200, "completed")])
            finished = self.finish_result(self.parallel_result(plan, segment_id="one"))
            self.assertTrue(finished["execution_recorded"])
            events, _ = RUNTIME.ledger.read_events(self.ledger)
            execution = next(item for item in events if item["event"] == "execution")
            self.assertEqual(execution["model"], plan["segments"][0]["model"])
            self.assertEqual(execution["concurrency"], 1)
        finally:
            self.ledger = original_ledger

    def test_malformed_history_warns_without_blocking_complete_parallel_trace(self):
        self.ledger.write_text("{malformed}\n", encoding="utf-8")
        plan = self.parallel_plan()
        self.claim(plan, "one")
        self.capture_trace(plan, [("one", 100, 200, "failed")])
        finished = self.finish_result(self.parallel_result(
            plan, segment_id="one", outcome="failed",
        ))
        self.assertTrue(finished["parallel_execution_recorded"])
        self.assertEqual(finished["ledger_warning_count"], 1)

    def test_parallel_finish_records_canonical_current_run_once(self):
        plan = self.parallel_plan()
        self.claim(plan, "one")
        self.claim(plan, "two")
        self.capture_trace(plan, [
            ("one", 100_000_000_000, 110_000_000_000, "completed"),
            ("two", 102_500_000_000, 112_500_000_000, "completed"),
        ])
        first = self.finish_result(self.parallel_result(plan, segment_id="one"))
        self.assertEqual(first["next"]["action"], "await-result-recording")
        finished = self.finish_result(self.parallel_result(plan, segment_id="two"))
        self.assertEqual(finished["next"]["action"], "return")
        self.assertTrue(finished["parallel_execution_recorded"])
        self.assertEqual(finished["parallel_execution_state"], "recorded")
        self.assertEqual(
            finished["parallel_execution_brief"],
            "并发：峰值 3（含主任务）｜实际用时：13秒｜并行任务累计用时：20秒｜并行省时估算：38%｜槽位利用：87%",
        )
        events, warnings = RUNTIME.ledger.read_events(self.ledger)
        self.assertEqual(warnings, [])
        self.assertEqual(len(events), 12)
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
        self.assertEqual(measured["dispatched_ids"], ["one", "two"])
        self.assertEqual(measured["skipped_ids"], [])
        executions = [item for item in events if item["event"] == "execution"]
        self.assertEqual([item["concurrency"] for item in executions], [2, 2])
        summary = RUNTIME.ledger.build_summary(
            events, warnings, current_route_id=plan["route_id"]
        )
        current_run = summary["parallel_execution"]["current_run"]
        self.assertEqual(current_run["route_id"], plan["route_id"])
        self.assertEqual(current_run["effective_parallel_factor"], 1.6)
        self.assertEqual(current_run["visible_peak_concurrency"], 3)
        self.assertEqual(current_run["leaf_parallel_utilization_percent"], 80.0)
        self.assertEqual(current_run["parallel_utilization_percent"], 86.7)

    def test_parallel_finish_requires_canonical_worker_interval(self):
        plan = self.parallel_plan()
        self.claim(plan, "two")
        with self.assertRaisesRegex(SystemExit, "captured worker start"):
            RUNTIME.finish(self.args(result_json=json.dumps(self.parallel_result(plan))))

    def test_parallel_failure_latch_drains_workers_before_terminal_aggregate(self):
        plan = self.parallel_plan()
        self.claim(plan, "one")
        self.claim(plan, "two")
        for identifier, tick in (("one", 100), ("two", 150)):
            selected = next(
                item for item in plan["segments"] if item["segment_id"] == identifier
            )
            RUNTIME.ledger.append_event(self.ledger, {
                "event": "parallel_worker_start", "route_id": plan["route_id"],
                "plan_hash": plan["plan_hash"], "segment_id": identifier,
                "attempt_id": selected["attempt_id"], "monotonic_ns": tick,
                "clock_source": RUNTIME.ledger.PARALLEL_CLOCK_SOURCE,
                "capture_source": "router-runtime",
            })
        RUNTIME.ledger.append_event(self.ledger, {
            "event": "parallel_worker_finish", "route_id": plan["route_id"],
            "plan_hash": plan["plan_hash"], "segment_id": "one",
            "attempt_id": plan["segments"][0]["attempt_id"], "monotonic_ns": 200,
            "clock_source": RUNTIME.ledger.PARALLEL_CLOCK_SOURCE,
            "capture_source": "router-runtime", "outcome": "failed",
        })
        failed = self.finish_result(self.parallel_result(
            plan, outcome="failed", segment_id="one",
        ))
        self.assertEqual(failed["next"]["action"], "drain-running")
        self.assertEqual(failed["parallel_execution_state"], "pending")
        before, _ = RUNTIME.ledger.read_events(self.ledger)
        with self.assertRaisesRegex(SystemExit, "matching prepared claim"):
            RUNTIME.worker_start(self.args(
                route_id=plan["route_id"], plan_hash=plan["plan_hash"],
                segment_id="typo", attempt_id="typo-attempt",
            ))
        after, _ = RUNTIME.ledger.read_events(self.ledger)
        self.assertEqual(before, after)
        RUNTIME.ledger.append_event(self.ledger, {
            "event": "parallel_worker_finish", "route_id": plan["route_id"],
            "plan_hash": plan["plan_hash"], "segment_id": "two",
            "attempt_id": plan["segments"][1]["attempt_id"], "monotonic_ns": 300,
            "clock_source": RUNTIME.ledger.PARALLEL_CLOCK_SOURCE,
            "capture_source": "router-runtime", "outcome": "completed",
        })
        drained = self.finish_result(self.parallel_result(plan, segment_id="two"))
        self.assertEqual(drained["next"]["action"], "stop")
        self.assertTrue(drained["parallel_execution_recorded"])

    def test_parallel_finish_consumes_each_claim_once(self):
        plan = self.parallel_plan()
        self.claim(plan, "one")
        self.claim(plan, "two")
        self.capture_trace(plan, [
            ("one", 100_000_000_000, 110_000_000_000, "completed"),
            ("two", 102_500_000_000, 112_500_000_000, "completed"),
        ])
        self.finish_result(self.parallel_result(plan, segment_id="one"))
        encoded = json.dumps(self.parallel_result(plan, segment_id="two"))
        self.finish_result(json.loads(encoded))
        recovered = self.finish_result(json.loads(encoded))
        self.assertTrue(recovered["finish_recovered"])
        self.assertFalse(recovered["execution_recorded"])

    def test_parallel_finish_records_failed_aggregate(self):
        plan = self.parallel_plan()
        self.claim(plan, "one")
        self.capture_trace(plan, [
            ("one", 100_000_000_000, 106_000_000_000, "failed"),
        ])
        result = self.parallel_result(
            plan, segment_id="one", completed_ids=["forged"], outcome="failed",
        )
        finished = self.finish_result(result)
        self.assertFalse(finished["ok"])
        self.assertEqual(finished["next"]["action"], "stop")
        self.assertTrue(finished["parallel_execution_recorded"])
        events, warnings = RUNTIME.ledger.read_events(self.ledger)
        self.assertEqual(warnings, [])
        self.assertEqual(events[-1]["outcome"], "failed")
        self.assertEqual(events[-1]["dispatched_ids"], ["one"])
        self.assertEqual(events[-1]["skipped_ids"], ["two"])

    def test_worker_capture_uses_runtime_clock_and_rejects_finish_without_start(self):
        plan = self.parallel_plan()
        self.claim(plan, "one")
        with self.assertRaisesRegex(SystemExit, "dispatch-confirmed start"):
            RUNTIME.worker_finish(self.identity_args(
                plan, "one", outcome="completed"
            ))
        original_clock = RUNTIME.time.monotonic_ns
        try:
            RUNTIME.time.monotonic_ns = lambda: 123456789
            with redirect_stdout(io.StringIO()):
                RUNTIME.worker_start(self.identity_args(plan, "one"))
            RUNTIME.time.monotonic_ns = lambda: 223456789
            with redirect_stdout(io.StringIO()):
                RUNTIME.worker_finish(self.identity_args(
                    plan, "one", outcome="completed"
                ))
        finally:
            RUNTIME.time.monotonic_ns = original_clock
        events, warnings = RUNTIME.ledger.read_events(self.ledger)
        self.assertEqual(warnings, [])
        worker_events = [item for item in events if item["event"].startswith("parallel_worker")]
        self.assertEqual([item["monotonic_ns"] for item in worker_events], [123456789, 223456789])


if __name__ == "__main__":
    unittest.main()
