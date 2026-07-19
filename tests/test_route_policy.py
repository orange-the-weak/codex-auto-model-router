import importlib.util
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("route_policy", ROOT / "scripts" / "route_policy.py")
POLICY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(POLICY)


def current(model="gpt-5.6-sol", effort="ultra"):
    return {
        "status": "verified",
        "thread_id": "019f6001-95ae-7411-a5ba-7895a1897e49",
        "model": model,
        "effort": effort,
        "source": "test",
        "reason": None,
    }


class RoutePolicyTests(unittest.TestCase):
    def segment(self, segment_id, task_kind="ordinary", risk="normal", size="normal", **extra):
        value = {
            "segment_id": segment_id,
            "goal": f"Complete {segment_id}",
            "task_kind": task_kind,
            "risk": risk,
            "size": size,
            "acceptance": [f"{segment_id} accepted"],
            "validation_budget": f"Validate {segment_id}",
        }
        value.update(extra)
        return value

    def validate_cursor(self, plan, cursor, segment_id, completed_ids, **overrides):
        original = plan["original"]
        segment = plan["segments"][cursor]
        values = {
            "route_id": plan["route_id"],
            "attempt_id": segment["attempt_id"],
            "original_model": original["model"],
            "original_effort": original["effort"],
            "protocol": plan["protocol"],
            "restore_required": plan["restore_required"],
            "segment_budget": plan["segment_budget"],
            "switch_budget": plan["switch_budget"],
            "budget_source": plan["budget_source"],
        }
        values.update(overrides)
        return POLICY.validate_segment_cursor(
            plan, cursor, segment_id, completed_ids,
            values["route_id"], values["attempt_id"],
            values["original_model"], values["original_effort"],
            values["protocol"], values["restore_required"],
            values["segment_budget"], values["switch_budget"], values["budget_source"],
        )

    def linear_plan(self, current_route=None):
        return POLICY.plan_apply_segments([
            self.segment("analyze", task_kind="complex"),
            self.segment("implement"),
        ], current=current_route or current())

    def adaptive_parallel_segments(self, count=6):
        return [
            self.segment(
                f"task-{index}",
                size="large" if index == 0 else "normal",
                work_estimate="long" if index == 0 else "normal",
                access_mode="read",
            )
            for index in range(count)
        ]

    def test_fallback_keeps_sol_target_inside_gpt56_family(self):
        result = POLICY.resolve_family_fallback(
            "Sol", "high", ["gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.5"]
        )
        self.assertEqual(result["execution"]["model"], "gpt-5.6-terra")
        self.assertEqual(result["reason"], "gpt56-family-fallback")
        self.assertTrue(result["gpt56_family_available"])

    def test_fallback_keeps_terra_target_inside_gpt56_family(self):
        result = POLICY.resolve_family_fallback(
            "Terra", "medium", ["gpt-5.6-luna", "gpt-5.5"]
        )
        self.assertEqual(result["execution"]["model"], "gpt-5.6-luna")
        self.assertNotEqual(result["execution"]["model"], "gpt-5.5")

    def test_fallback_keeps_luna_target_inside_gpt56_family(self):
        result = POLICY.resolve_family_fallback(
            "Luna", "low", ["gpt-5.6-terra", "gpt-5.5"]
        )
        self.assertEqual(result["execution"]["model"], "gpt-5.6-terra")

    def test_gpt55_is_allowed_only_when_all_gpt56_models_are_unavailable(self):
        result = POLICY.resolve_family_fallback(
            "Terra", "medium", ["gpt-5.5", "gpt-5.4", "gpt-5.4-mini"]
        )
        self.assertEqual(result["execution"]["model"], "gpt-5.5")
        self.assertFalse(result["gpt56_family_available"])
        self.assertEqual(result["reason"], "gpt56-family-unavailable")

    def test_unknown_availability_retries_gpt56_target_instead_of_assuming_gpt55(self):
        result = POLICY.resolve_family_fallback("Terra", "medium")
        self.assertEqual(result["execution"]["model"], "gpt-5.6-terra")
        self.assertIsNone(result["gpt56_family_available"])
        self.assertEqual(result["reason"], "availability-unknown-try-gpt56-target-first")

    def test_empty_availability_never_invents_gpt55(self):
        result = POLICY.resolve_family_fallback("Luna", "low", [])
        self.assertIsNone(result["execution"]["model"])
        self.assertEqual(result["reason"], "no-supported-model-available")

    def test_single_route_does_not_restore_from_gpt56_to_original_gpt55(self):
        route = POLICY.select_route(
            "apply", current=current("gpt-5.5", "medium")
        )
        self.assertEqual(route["execution"]["dispatch"], "same-task-switch")
        self.assertEqual(route["execution"]["model"], "gpt-5.6-terra")
        self.assertFalse(route["restore_required"])

    def test_segment_plan_does_not_restore_to_original_gpt55(self):
        plan = POLICY.plan_apply_segments(
            [self.segment("implement")], current=current("gpt-5.5", "medium")
        )
        self.assertEqual(plan["segments"][0]["dispatch"], "same-task-switch")
        self.assertFalse(plan["restore_required"])
        self.assertEqual(plan["switch_count"], 1)
        self.assertEqual(plan["original"]["model"], "gpt-5.5")

    def test_segment_plan_still_restores_original_gpt56(self):
        plan = POLICY.plan_apply_segments(
            [self.segment("implement")], current=current("gpt-5.6-sol", "medium")
        )
        self.assertTrue(plan["restore_required"])
        self.assertEqual(plan["switch_count"], 2)

    def test_envelope_rejects_restore_to_original_gpt55(self):
        plan = self.linear_plan(current("gpt-5.5", "medium"))
        plan["restore_required"] = True
        plan["switch_count"] += 1
        plan["plan_hash"] = POLICY.plan_hash(
            plan["segments"], plan["route_id"], plan["original"], True,
            plan["segment_budget"], plan["switch_budget"], plan["budget_source"],
            plan["routing_evidence"], POLICY.SEGMENTED_PROTOCOL,
        )
        for segment in plan["segments"]:
            segment["attempt_id"] = POLICY.hashlib.sha256(
                f"{plan['route_id']}:{plan['plan_hash']}:{segment['segment_id']}".encode()
            ).hexdigest()
        with self.assertRaisesRegex(ValueError, "non-GPT-5.6 original"):
            self.validate_cursor(plan, 1, "implement", ["analyze"])

    def test_detects_latest_current_route_for_exact_thread(self):
        with tempfile.TemporaryDirectory() as directory:
            thread_id = "019f6001-95ae-7411-a5ba-7895a1897e49"
            session = Path(directory) / f"rollout-{thread_id}.jsonl"
            rows = [
                {"type": "session_meta", "payload": {"id": thread_id}},
                {"type": "event_msg", "payload": {"type": "thread_settings_applied", "thread_settings": {"model": "gpt-5.6-luna", "reasoning_effort": "low"}}},
                {"type": "event_msg", "payload": {"type": "thread_settings_applied", "thread_settings": {"model": "gpt-5.6-sol", "reasoning_effort": "ultra"}}},
            ]
            session.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            detected = POLICY.detect_current_route(directory, {"CODEX_THREAD_ID": thread_id})
            self.assertEqual((detected["model"], detected["effort"]), ("gpt-5.6-sol", "ultra"))
            self.assertEqual(detected["status"], "verified")

    def test_detects_turn_context_when_settings_event_is_absent(self):
        with tempfile.TemporaryDirectory() as directory:
            thread_id = "019f6001-95ae-7411-a5ba-7895a1897e49"
            session = Path(directory) / f"rollout-{thread_id}.jsonl"
            row = {
                "type": "turn_context",
                "payload": {
                    "model": "gpt-5.6-terra",
                    "effort": "high",
                    "collaboration_mode": {
                        "settings": {"model": "gpt-5.6-terra", "reasoning_effort": "high"}
                    },
                },
            }
            metadata = {"type": "session_meta", "payload": {"session_id": thread_id}}
            session.write_text(json.dumps(metadata) + "\n" + json.dumps(row) + "\n")
            detected = POLICY.detect_current_route(directory, {"CODEX_THREAD_ID": thread_id})
            self.assertEqual((detected["model"], detected["effort"]), ("gpt-5.6-terra", "high"))
            self.assertEqual(detected["source"], "local-session-metadata:turn_context")

    def test_rejects_filename_match_with_wrong_session_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            thread_id = "019f6001-95ae-7411-a5ba-7895a1897e49"
            session = Path(directory) / f"backup-{thread_id}.jsonl"
            rows = [
                {"type": "session_meta", "payload": {"id": "019f6002-95ae-7411-a5ba-7895a1897e49"}},
                {"type": "turn_context", "payload": {"model": "gpt-5.6-luna", "effort": "low"}},
            ]
            session.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            detected = POLICY.detect_current_route(directory, {"CODEX_THREAD_ID": thread_id})
            self.assertEqual(detected["status"], "unavailable")
            self.assertEqual(detected["reason"], "verified-settings-not-found")

    def test_ordinary_apply_uses_terra_medium_and_restores(self):
        route = POLICY.select_route("apply", current=current())
        self.assertEqual(route["recommended"]["model"], "gpt-5.6-terra")
        self.assertEqual(route["recommended"]["effort"], "medium")
        self.assertEqual(route["execution"]["dispatch"], "same-task-switch")
        self.assertTrue(route["restore_required"])

    def test_tiny_mechanical_apply_switches_from_previous_sol_to_luna_low(self):
        route = POLICY.select_route(
            "apply", task_kind="mechanical", risk="low", size="tiny",
            current=current("gpt-5.6-sol", "high"),
        )
        self.assertEqual(route["recommended"]["model"], "gpt-5.6-luna")
        self.assertEqual(route["recommended"]["effort"], "low")
        self.assertEqual(route["execution"]["model"], "gpt-5.6-luna")
        self.assertEqual(route["execution"]["effort"], "low")
        self.assertEqual(route["execution"]["dispatch"], "same-task-switch")
        self.assertTrue(route["restore_required"])

    def test_explicit_override_still_controls_tiny_task(self):
        route = POLICY.select_route(
            "apply", task_kind="mechanical", risk="low", size="tiny",
            model_override="luna", effort_override="low", current=current(),
        )
        self.assertEqual(route["execution"]["dispatch"], "same-task-switch")
        self.assertTrue(route["explicit_override"])

    def test_tiny_low_risk_ordinary_apply_switches_to_terra_low(self):
        route = POLICY.select_route(
            "apply", task_kind="ordinary", risk="low", size="tiny",
            current=current("gpt-5.6-sol", "medium"),
        )
        self.assertEqual(
            (route["recommended"]["model"], route["recommended"]["effort"]),
            ("gpt-5.6-terra", "low"),
        )
        self.assertEqual(route["execution"]["dispatch"], "same-task-switch")

    def test_current_target_route_stays_local_without_keep_placeholder(self):
        route = POLICY.select_route(
            "apply", task_kind="mechanical", risk="low", size="tiny",
            current=current("gpt-5.6-luna", "low"),
        )
        self.assertEqual(route["execution"]["dispatch"], "local")
        self.assertEqual(route["execution"]["reason"], "route-already-matched")
        self.assertEqual(
            (route["execution"]["model"], route["execution"]["effort"]),
            ("gpt-5.6-luna", "low"),
        )

    def test_complex_tiny_task_still_uses_sol(self):
        route = POLICY.select_route("apply", task_kind="complex", risk="normal", size="tiny", current=current())
        self.assertEqual(route["recommended"]["model"], "gpt-5.6-sol")
        self.assertEqual(route["execution"]["dispatch"], "same-task-switch")

    def test_spaced_sol_alias_is_supported(self):
        route = POLICY.select_route("assess", model_override="GPT-5.6 Sol", current=current())
        self.assertEqual(route["recommended"]["model"], "gpt-5.6-sol")

    def test_spaced_terra_and_very_high_aliases_are_supported(self):
        route = POLICY.select_route(
            "apply", model_override="GPT-5.6 Terra", effort_override="very high", current=current()
        )
        self.assertEqual(
            (route["recommended"]["model"], route["recommended"]["effort"]),
            ("gpt-5.6-terra", "xhigh"),
        )

    def test_unknown_original_never_uses_persistent_same_task_switch(self):
        route = POLICY.select_route("assess", current=POLICY.unavailable_current())
        self.assertEqual(route["execution"]["dispatch"], "selectable-subagent-or-local")
        self.assertFalse(route["restore_required"])

    def test_high_risk_apply_uses_sol_high(self):
        route = POLICY.select_route("apply", risk="high", current=current("gpt-5.6-terra", "medium"))
        self.assertEqual((route["recommended"]["model"], route["recommended"]["effort"]), ("gpt-5.6-sol", "high"))

    def test_bounded_complex_apply_switches_from_previous_luna_to_sol_medium(self):
        route = POLICY.select_route(
            "apply", task_kind="complex", risk="normal", size="normal",
            current=current("gpt-5.6-luna", "low"),
        )
        self.assertEqual(
            (route["recommended"]["model"], route["recommended"]["effort"]),
            ("gpt-5.6-sol", "medium"),
        )
        self.assertEqual(route["execution"]["dispatch"], "same-task-switch")
        self.assertTrue(route["restore_required"])

    def test_high_ambiguity_complex_uses_sol_high(self):
        route = POLICY.select_route(
            "apply", task_kind="complex", ambiguity="high",
            current=current("gpt-5.6-luna", "low"),
        )
        self.assertEqual(
            (route["recommended"]["model"], route["recommended"]["effort"]),
            ("gpt-5.6-sol", "high"),
        )
        self.assertEqual(
            route["recommended"]["source"],
            "benchmark-prior:complex_uncertain_or_high_consequence",
        )

    def test_failed_complex_attempt_is_the_only_automatic_xhigh_escalation(self):
        route = POLICY.select_route(
            "apply", task_kind="complex", prior_failure=True,
            current=current("gpt-5.6-sol", "medium"),
        )
        self.assertEqual(
            (route["recommended"]["model"], route["recommended"]["effort"]),
            ("gpt-5.6-sol", "xhigh"),
        )

    def test_active_evidence_snapshot_is_exposed_for_audit(self):
        route = POLICY.select_route("apply", current=current())
        self.assertEqual(route["routing_evidence"]["status"], "active")
        self.assertEqual(
            route["routing_evidence"]["snapshot_id"],
            "gpt56-routing-evidence-2026-07-15",
        )

    def test_stale_evidence_falls_back_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            data = json.loads(POLICY.DEFAULT_EVIDENCE_PATH.read_text())
            data["observed_at"] = "2020-01-01"
            path.write_text(json.dumps(data))
            route = POLICY.select_route(
                "apply", task_kind="complex", current=current(), evidence_path=path
            )
            self.assertEqual(route["routing_evidence"]["status"], "stale")
            self.assertEqual(
                (route["recommended"]["model"], route["recommended"]["effort"]),
                ("gpt-5.6-sol", "high"),
            )
            self.assertEqual(route["recommended"]["source"], "deterministic-fallback")

    def test_invalid_evidence_falls_back_without_crashing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            path.write_text("{not-json")
            route = POLICY.select_route("apply", current=current(), evidence_path=path)
            self.assertEqual(route["routing_evidence"]["status"], "invalid")
            self.assertEqual(route["recommended"]["source"], "deterministic-fallback")

    def test_evidence_without_required_independent_source_is_invalid(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            data = json.loads(POLICY.DEFAULT_EVIDENCE_PATH.read_text())
            data["sources"] = [
                item for item in data["sources"]
                if item["id"] != "aa-coding-agent-index-v1.1"
            ]
            path.write_text(json.dumps(data))
            route = POLICY.select_route("apply", current=current(), evidence_path=path)
            self.assertEqual(route["routing_evidence"]["status"], "invalid")
            self.assertIn("required-sources-missing", route["routing_evidence"]["reason"])

    def test_incomplete_gpt56_effort_matrix_is_invalid(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            data = json.loads(POLICY.DEFAULT_EVIDENCE_PATH.read_text())
            data["effort_profiles"]["metrics"] = [
                item for item in data["effort_profiles"]["metrics"]
                if (item["model"], item["effort"]) != ("gpt-5.6-luna", "xhigh")
            ]
            path.write_text(json.dumps(data))
            route = POLICY.select_route("apply", current=current(), evidence_path=path)
            self.assertEqual(route["routing_evidence"]["status"], "invalid")
            self.assertIn("matrix-incomplete", route["routing_evidence"]["reason"])

    def test_segment_plan_routes_and_restores_in_one_thread(self):
        segments = [
            self.segment("analyze", task_kind="complex"),
            self.segment("implement", task_kind="ordinary"),
            self.segment("verify", task_kind="mechanical", size="normal"),
        ]
        plan = POLICY.plan_apply_segments(segments, current=current("gpt-5.6-sol", "medium"))
        self.assertEqual(plan["protocol"], "segmented-v1")
        self.assertEqual(
            [(item["model"], item["effort"]) for item in plan["segments"]],
            [
                ("gpt-5.6-sol", "medium"),
                ("gpt-5.6-terra", "medium"),
                ("gpt-5.6-luna", "low"),
            ],
        )
        self.assertEqual(plan["switch_count"], 3)
        self.assertEqual((plan["segment_budget"], plan["switch_budget"]), (4, 4))
        self.assertEqual(plan["budget_source"], "standard")
        self.assertTrue(plan["restore_required"])
        self.assertEqual(len(plan["plan_hash"]), 64)

    def test_cursor_validation_accepts_only_exact_next_segment(self):
        plan = POLICY.plan_apply_segments([
            self.segment("analyze", task_kind="complex"),
            self.segment("implement"),
        ], current=current())
        selected = self.validate_cursor(plan, 1, "implement", ["analyze"])
        self.assertEqual(selected["segment_id"], "implement")
        with self.assertRaisesRegex(ValueError, "does not match cursor"):
            self.validate_cursor(plan, 1, "analyze", ["analyze"])

    def test_cursor_validation_rejects_mutated_plan(self):
        plan = self.linear_plan()
        plan["segments"][1]["goal"] = "mutated"
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            self.validate_cursor(plan, 1, "implement", ["analyze"])

    def test_cursor_validation_rejects_evidence_snapshot_mutation(self):
        plan = self.linear_plan()
        plan["routing_evidence"]["snapshot_id"] = "forged"
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            self.validate_cursor(plan, 1, "implement", ["analyze"])

    def test_legacy_plan_without_evidence_still_validates(self):
        plan = self.linear_plan()
        plan.pop("routing_evidence")
        plan["plan_hash"] = POLICY.plan_hash(
            plan["segments"], plan["route_id"], plan["original"],
            plan["restore_required"], plan["segment_budget"],
            plan["switch_budget"], plan["budget_source"],
        )
        for segment in plan["segments"]:
            segment["attempt_id"] = POLICY.hashlib.sha256(
                f"{plan['route_id']}:{plan['plan_hash']}:{segment['segment_id']}".encode()
            ).hexdigest()
        selected = self.validate_cursor(plan, 1, "implement", ["analyze"])
        self.assertEqual(selected["segment_id"], "implement")

    def test_cursor_validation_rejects_budget_mutation(self):
        plan = self.linear_plan()
        plan["segment_budget"] = 5
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            self.validate_cursor(plan, 1, "implement", ["analyze"])

    def test_cursor_validation_rejects_outer_budget_mismatch(self):
        plan = self.linear_plan()
        with self.assertRaisesRegex(ValueError, "budget mismatch"):
            self.validate_cursor(plan, 1, "implement", ["analyze"], segment_budget=5)

    def test_segment_attempt_ids_are_unique_per_invocation(self):
        first = POLICY.plan_apply_segments([self.segment("implement")], current=current())
        second = POLICY.plan_apply_segments([self.segment("implement")], current=current())
        self.assertNotEqual(first["plan_hash"], second["plan_hash"])
        self.assertNotEqual(first["segments"][0]["attempt_id"], second["segments"][0]["attempt_id"])

    def test_cursor_validation_rejects_forged_envelope_identity(self):
        plan = self.linear_plan()
        with self.assertRaisesRegex(ValueError, "route_id mismatch"):
            self.validate_cursor(plan, 1, "implement", ["analyze"], route_id="forged")
        with self.assertRaisesRegex(ValueError, "attempt_id mismatch"):
            self.validate_cursor(plan, 1, "implement", ["analyze"], attempt_id="forged")
        with self.assertRaisesRegex(ValueError, "original route mismatch"):
            self.validate_cursor(plan, 1, "implement", ["analyze"], original_model="gpt-5.6-luna")
        with self.assertRaisesRegex(ValueError, "protocol mismatch"):
            self.validate_cursor(plan, 1, "implement", ["analyze"], protocol="forged")
        with self.assertRaisesRegex(ValueError, "Restore decision mismatch"):
            self.validate_cursor(plan, 1, "implement", ["analyze"], restore_required=not plan["restore_required"])

    def test_single_segment_uses_compact_fast_protocol(self):
        plan = POLICY.plan_apply_segments([
            self.segment("docs", task_kind="mechanical", risk="low", size="tiny")
        ], current=current("gpt-5.6-luna", "low"))
        self.assertEqual(plan["protocol"], POLICY.FAST_PROTOCOL)
        self.assertFalse(plan["fast_path"]["claim_required"])
        self.assertFalse(plan["fast_path"]["continuation_required"])
        selected = POLICY.validate_fast_envelope(
            plan, plan["route_id"], "docs", plan["segments"][0]["attempt_id"]
        )
        self.assertEqual(selected["dispatch"], "local")

    def test_fast_switch_requires_claim_and_compact_continuation(self):
        plan = POLICY.plan_apply_segments([
            self.segment("docs", task_kind="mechanical", risk="low", size="tiny")
        ], current=current("gpt-5.6-sol", "high"))
        self.assertTrue(plan["fast_path"]["claim_required"])
        self.assertTrue(plan["fast_path"]["continuation_required"])
        self.assertFalse(plan["fast_path"]["full_plan_continuation_required"])

    def test_report_route_is_supported_for_one_segment(self):
        plan = POLICY.plan_apply_segments(
            [self.segment("docs")], current=current(), report_model="Luna", report_effort="low"
        )

    def test_partial_segment_report_route_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "report route requires both model and effort"):
            POLICY.plan_apply_segments([
                self.segment("docs", model="Luna", route_source="report")
            ], current=current())

    def test_segment_report_route_is_not_user_override(self):
        plan = POLICY.plan_apply_segments([
            self.segment("docs", model="Luna", effort="low", route_source="report")
        ], current=current())
        self.assertFalse(plan["explicit_override"])
        self.assertEqual(plan["segments"][0]["reason"], "report")
        self.assertEqual(
            (plan["segments"][0]["model"], plan["segments"][0]["effort"], plan["segments"][0]["reason"]),
            ("gpt-5.6-luna", "low", "report"),
        )

    def test_multi_segment_global_report_route_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "per-segment report routes"):
            POLICY.plan_apply_segments(
                [self.segment("one"), self.segment("two")], current=current(),
                report_model="Luna", report_effort="low",
            )

    def test_global_user_override_wins_over_segment_report_route(self):
        plan = POLICY.plan_apply_segments([
            self.segment("review", model="Luna", effort="low", route_source="report")
        ], current=current(), model_override="Sol", effort_override="high")
        self.assertEqual(
            (plan["segments"][0]["model"], plan["segments"][0]["effort"], plan["segments"][0]["reason"]),
            ("gpt-5.6-sol", "high", "user-override"),
        )

    def test_adjacent_segments_with_same_route_are_merged(self):
        segments = [
            self.segment("implement"),
            self.segment("tests"),
        ]
        plan = POLICY.plan_apply_segments(segments, current=current("gpt-5.6-sol", "medium"))
        self.assertEqual(plan["segment_count"], 1)
        self.assertEqual(plan["segments"][0]["source_ids"], ["implement", "tests"])
        self.assertIn("Then:", plan["segments"][0]["goal"])

    def test_tiny_segment_is_routed_independently_from_previous_strong_segment(self):
        segments = [
            self.segment("analyze", task_kind="complex"),
            self.segment("rename", task_kind="mechanical", risk="low", size="tiny"),
        ]
        plan = POLICY.plan_apply_segments(segments, current=current("gpt-5.6-sol", "medium"))
        self.assertEqual(plan["segment_count"], 2)
        self.assertEqual(
            [(item["model"], item["effort"]) for item in plan["segments"]],
            [("gpt-5.6-sol", "medium"), ("gpt-5.6-luna", "low")],
        )

    def test_unknown_original_uses_non_persistent_segment_fallback(self):
        plan = POLICY.plan_apply_segments(
            [self.segment("implement")], current=POLICY.unavailable_current()
        )
        self.assertEqual(plan["segments"][0]["dispatch"], "selectable-subagent-or-local")
        self.assertFalse(plan["restore_required"])
        self.assertEqual(plan["switch_count"], 0)

    def test_parallel_plan_uses_dependency_protocol_and_runtime_cap(self):
        plan = POLICY.plan_parallel_segments([
            self.segment("long", work_estimate="long", access_mode="read"),
            self.segment("short", work_estimate="short", access_mode="read"),
            self.segment("join", depends_on=["long", "short"], access_mode="read"),
        ], current=current(), runtime_max_threads=2)
        self.assertEqual(plan["protocol"], "dependency-parallel-v1")
        self.assertEqual(plan["parallel"]["effective_max_parallelism"], 2)
        self.assertEqual(plan["parallel"]["runtime_max_threads_source"], "runtime-config")
        self.assertEqual(plan["parallel"]["scheduler"], "critical-path-priority-wait-any")
        self.assertEqual(plan["parallel"]["initial_frontier"], ["long", "short"])
        self.assertEqual(plan["parallel"]["failure_policy"], "stop-dispatch-drain-running")
        self.assertFalse(plan["parallel"]["workers_may_delegate"])

    def test_parallel_default_is_smart_reduced_by_runtime_threads(self):
        plan = POLICY.plan_parallel_segments([
            self.segment("one", access_mode="read"),
            self.segment("two", access_mode="read"),
            self.segment("three", access_mode="read"),
        ], current=current(), runtime_max_threads=2)
        self.assertEqual(plan["parallel"]["requested_max_parallelism"], 4)
        self.assertEqual(plan["parallel"]["effective_max_parallelism"], 2)
        self.assertEqual(plan["parallel"]["parallelism_source"], "smart-reduced")
        self.assertIn("runtime-capacity", plan["parallel"]["reduction_reasons"])

    def test_parallel_default_cap_is_four_and_invalid_caps_are_rejected(self):
        plan = POLICY.plan_parallel_segments([
            self.segment(
                f"task-{index}", access_mode="read",
                size="large" if index == 0 else "normal",
            )
            for index in range(5)
        ], current=current(), runtime_max_threads=6)
        self.assertEqual(plan["parallel"]["requested_max_parallelism"], 4)
        self.assertEqual(plan["parallel"]["effective_max_parallelism"], 4)
        for invalid_cap in (0, 17):
            with self.assertRaisesRegex(ValueError, "max_parallelism"):
                POLICY.plan_parallel_segments(
                    [self.segment("one", access_mode="read")], current=current(),
                    max_parallelism=invalid_cap,
                )

    def test_parallel_standard_cap_with_four_useful_tasks(self):
        plan = POLICY.plan_parallel_segments(
            self.adaptive_parallel_segments(4), current=current(), runtime_max_threads=6
        )
        self.assertEqual(plan["parallel"]["parallelism_source"], "standard")
        self.assertEqual(plan["parallel"]["requested_max_parallelism"], 4)
        self.assertEqual(plan["parallel"]["effective_max_parallelism"], 4)
        self.assertEqual(plan["parallel"]["capacity_evaluation"]["useful_parallelism"], 4)
        self.assertEqual(plan["parallel"]["reduction_reasons"], [])

    def test_parallel_never_auto_extends_above_four(self):
        plan = POLICY.plan_parallel_segments(
            self.adaptive_parallel_segments(), current=current(), runtime_max_threads=8
        )
        parallel = plan["parallel"]
        self.assertEqual(parallel["parallelism_source"], "standard")
        self.assertEqual(parallel["requested_max_parallelism"], 4)
        self.assertEqual(parallel["effective_max_parallelism"], 4)
        self.assertEqual(parallel["capacity_evaluation"]["useful_parallelism"], 6)

    def test_parallel_high_risk_alone_does_not_extend(self):
        plan = POLICY.plan_parallel_segments([
            self.segment(
                f"risk-{index}", risk="high", work_estimate="normal", access_mode="read"
            )
            for index in range(6)
        ], current=current(), runtime_max_threads=8, max_segments=6)
        self.assertEqual(plan["parallel"]["parallelism_source"], "standard")
        self.assertEqual(plan["parallel"]["requested_max_parallelism"], 4)
        self.assertEqual(plan["parallel"]["capacity_evaluation"]["useful_parallelism"], 6)

    def test_parallel_tiny_siblings_merge_without_extension(self):
        plan = POLICY.plan_parallel_segments([
            self.segment(
                f"tiny-{index}", size="tiny", work_estimate="short", access_mode="read"
            )
            for index in range(6)
        ], current=current(), runtime_max_threads=8)
        self.assertEqual(plan["segment_count"], 2)
        self.assertEqual(plan["parallel"]["parallelism_source"], "smart-reduced")
        self.assertEqual(plan["parallel"]["effective_max_parallelism"], 2)

    def test_parallel_conflicts_prevent_adaptive_extension(self):
        segments = self.adaptive_parallel_segments()
        for segment in segments:
            segment["conflict_keys"] = ["shared-simulator"]
        plan = POLICY.plan_parallel_segments(
            segments, current=current(), runtime_max_threads=8
        )
        self.assertEqual(plan["parallel"]["parallelism_source"], "smart-reduced")
        self.assertEqual(plan["parallel"]["capacity_evaluation"]["useful_parallelism"], 1)
        self.assertEqual(plan["parallel"]["effective_max_parallelism"], 1)

    def test_parallel_user_override_can_be_smaller_or_confirmed_larger(self):
        segments = self.adaptive_parallel_segments()
        smaller = POLICY.plan_parallel_segments(
            segments, current=current(), max_parallelism=2, runtime_max_threads=8
        )
        larger = POLICY.plan_parallel_segments(
            segments, current=current(), max_parallelism=6, runtime_max_threads=6
        )
        self.assertEqual(smaller["parallel"]["parallelism_source"], "user-override")
        self.assertEqual(smaller["parallel"]["requested_max_parallelism"], 2)
        self.assertEqual(smaller["parallel"]["effective_max_parallelism"], 2)
        self.assertEqual(larger["parallel"]["parallelism_source"], "user-override")
        self.assertEqual(larger["parallel"]["requested_max_parallelism"], 6)
        self.assertEqual(larger["parallel"]["effective_max_parallelism"], 6)

    def test_parallel_override_above_four_requires_confirmed_capacity(self):
        segments = self.adaptive_parallel_segments()
        with self.assertRaisesRegex(ValueError, "observed free worker capacity"):
            POLICY.plan_parallel_segments(
                segments, current=current(), max_parallelism=6
            )
        with self.assertRaisesRegex(ValueError, "confirmed runtime capacity"):
            POLICY.plan_parallel_segments(
                segments, current=current(), max_parallelism=6, runtime_max_threads=3
            )
        with self.assertRaisesRegex(ValueError, "independent ready-task capacity"):
            POLICY.plan_parallel_segments(
                segments[:5], current=current(), max_parallelism=6,
                runtime_max_threads=6,
            )

    def test_parallel_runtime_smart_reduces_default_cap(self):
        plan = POLICY.plan_parallel_segments(
            self.adaptive_parallel_segments(), current=current(), runtime_max_threads=3
        )
        self.assertEqual(plan["parallel"]["parallelism_source"], "smart-reduced")
        self.assertEqual(plan["parallel"]["requested_max_parallelism"], 4)
        self.assertEqual(plan["parallel"]["effective_max_parallelism"], 3)

    def test_observed_total_slots_reserve_coordinator_and_running_workers(self):
        plan = POLICY.plan_parallel_segments(
            self.adaptive_parallel_segments(), current=current(),
            runtime_total_slots=4, runtime_running_workers=1,
        )
        parallel = plan["parallel"]
        self.assertEqual(parallel["coordinator_reserved_slots"], 1)
        self.assertEqual(parallel["available_worker_slots"], 2)
        self.assertEqual(parallel["effective_max_parallelism"], 2)
        self.assertEqual(parallel["capacity_source"], "observed-total-slots")

    def test_unverified_capacity_does_not_create_a_worker_queue(self):
        plan = POLICY.plan_parallel_segments(
            self.adaptive_parallel_segments(4), current=current()
        )
        self.assertEqual(plan["parallel"]["effective_max_parallelism"], 1)
        self.assertEqual(plan["parallel"]["capacity_source"], "unverified-dispatch-probe")

    def test_context_capsule_excludes_full_plan_and_future_segments(self):
        segments = self.adaptive_parallel_segments(4)
        segments[0]["decisions"] = ["Preserve the accepted baseline"]
        segments[0]["prohibited_actions"] = ["Do not run a full build"]
        plan = POLICY.plan_parallel_segments(
            segments, current=current(), runtime_total_slots=4
        )
        capsule = POLICY.context_capsule(plan, "task-0")
        self.assertNotIn("segments", capsule)
        self.assertNotIn("current", capsule)
        self.assertEqual(capsule["segment_id"], "task-0")
        self.assertEqual(capsule["decisions"], ["Preserve the accepted baseline"])
        self.assertEqual(capsule["prohibited_actions"], ["Do not run a full build"])

    def test_parallel_rejects_unknown_duplicate_and_cyclic_dependencies(self):
        invalid_plans = [
            [self.segment("one", depends_on=["missing"], access_mode="read")],
            [
                self.segment("one", access_mode="read"),
                self.segment("two", depends_on=["one", "one"], access_mode="read"),
            ],
            [
                self.segment("one", depends_on=["two"], access_mode="read"),
                self.segment("two", depends_on=["one"], access_mode="read"),
            ],
        ]
        for invalid_plan in invalid_plans:
            with self.assertRaises(ValueError):
                POLICY.plan_parallel_segments(invalid_plan, current=current())

    def test_parallel_write_requires_concrete_scope(self):
        with self.assertRaisesRegex(ValueError, "requires non-empty write_scopes"):
            POLICY.plan_parallel_segments([
                self.segment("write", access_mode="write")
            ], current=current())
        with self.assertRaisesRegex(ValueError, "concrete repository-relative"):
            POLICY.plan_parallel_segments([
                self.segment("write", access_mode="write", write_scopes=["src/*"])
            ], current=current())

    def test_overlapping_write_scopes_degrade_to_serial(self):
        plan = POLICY.plan_parallel_segments([
            self.segment("one", access_mode="write", write_scopes=["src"]),
            self.segment("two", access_mode="write", write_scopes=["src/api.py"]),
        ], current=current())
        second = next(item for item in plan["segments"] if item["segment_id"] == "two")
        self.assertEqual(second["depends_on"], ["one"])
        self.assertEqual(
            plan["parallel"]["serialized_conflicts"][0]["reason"],
            "overlapping-write-scope",
        )

    def test_conflict_keys_serialize_shared_mutable_resources(self):
        plan = POLICY.plan_parallel_segments([
            self.segment("one", access_mode="read", conflict_keys=["git-index"]),
            self.segment("two", access_mode="read", conflict_keys=["git-index"]),
        ], current=current())
        second = next(item for item in plan["segments"] if item["segment_id"] == "two")
        self.assertEqual(second["depends_on"], ["one"])
        self.assertEqual(plan["parallel"]["serialized_conflicts"][0]["conflict_keys"], ["git-index"])

    def test_compatible_short_siblings_are_merged(self):
        plan = POLICY.plan_parallel_segments([
            self.segment("one", work_estimate="short", access_mode="read"),
            self.segment("two", work_estimate="short", access_mode="read"),
            self.segment("join", depends_on=["one", "two"], access_mode="read"),
        ], current=current())
        self.assertEqual(plan["segment_count"], 2)
        first = plan["segments"][0]
        self.assertEqual(first["source_ids"], ["one", "two"])
        self.assertEqual(plan["segments"][1]["depends_on"], ["one"])

    def test_short_siblings_with_different_successors_stay_separate(self):
        plan = POLICY.plan_parallel_segments([
            self.segment("one", work_estimate="short", access_mode="read"),
            self.segment("two", work_estimate="short", access_mode="read"),
            self.segment("after-one", depends_on=["one"], access_mode="read"),
            self.segment("after-two", depends_on=["two"], access_mode="read"),
        ], current=current())
        self.assertEqual(plan["segment_count"], 4)

    def test_parallel_envelope_validates_frontier_and_capacity(self):
        plan = POLICY.plan_parallel_segments([
            self.segment("one", access_mode="read"),
            self.segment("two", access_mode="read"),
            self.segment("join", depends_on=["one", "two"], access_mode="read"),
        ], current=current(), max_parallelism=2, runtime_total_slots=3)
        one = next(item for item in plan["segments"] if item["segment_id"] == "one")
        selected = POLICY.validate_parallel_envelope(
            plan, "one", [], [], plan["route_id"], one["attempt_id"]
        )
        self.assertEqual(selected["segment_id"], "one")
        join = next(item for item in plan["segments"] if item["segment_id"] == "join")
        with self.assertRaisesRegex(ValueError, "dependencies are incomplete"):
            POLICY.validate_parallel_envelope(
                plan, "join", ["one"], [], plan["route_id"], join["attempt_id"]
            )
        two = next(item for item in plan["segments"] if item["segment_id"] == "two")
        with self.assertRaisesRegex(ValueError, "deterministic frontier priority"):
            POLICY.validate_parallel_envelope(
                plan, "two", [], [], plan["route_id"], two["attempt_id"]
            )
        with self.assertRaisesRegex(ValueError, "no available worker slot"):
            POLICY.validate_parallel_envelope(
                plan, "one", [], ["two", "join"],
                plan["route_id"], one["attempt_id"],
            )

    def test_parallel_envelope_rejects_forged_completed_descendant(self):
        plan = POLICY.plan_parallel_segments([
            self.segment("root", access_mode="read"),
            self.segment("child", depends_on=["root"], access_mode="read"),
            self.segment("other", access_mode="read"),
        ], current=current())
        other = next(item for item in plan["segments"] if item["segment_id"] == "other")
        with self.assertRaisesRegex(ValueError, "completed state has incomplete dependencies"):
            POLICY.validate_parallel_envelope(
                plan, "other", ["child"], [], plan["route_id"], other["attempt_id"]
            )

    def test_parallel_envelope_refills_frontier_after_any_worker_completes(self):
        plan = POLICY.plan_parallel_segments([
            self.segment("long", work_estimate="long", access_mode="read"),
            self.segment("short", work_estimate="short", access_mode="read"),
            self.segment("after-short", depends_on=["short"], access_mode="read"),
        ], current=current(), max_parallelism=2, runtime_total_slots=3)
        after_short = next(
            item for item in plan["segments"] if item["segment_id"] == "after-short"
        )
        selected = POLICY.validate_parallel_envelope(
            plan, "after-short", ["short"], ["long"],
            plan["route_id"], after_short["attempt_id"],
        )
        self.assertEqual(selected["segment_id"], "after-short")

    def test_parallel_envelope_rejects_plan_hash_tampering(self):
        plan = POLICY.plan_parallel_segments([
            self.segment("one", access_mode="read"),
        ], current=current())
        plan["segments"][0]["goal"] = "tampered"
        segment = plan["segments"][0]
        with self.assertRaisesRegex(ValueError, "plan hash mismatch"):
            POLICY.validate_parallel_envelope(
                plan, "one", [], [], plan["route_id"], segment["attempt_id"]
            )

    def test_parallel_envelope_rejects_parallelism_source_hash_tampering(self):
        plan = POLICY.plan_parallel_segments(
            self.adaptive_parallel_segments(), current=current(), runtime_max_threads=3
        )
        plan["parallel"]["parallelism_source"] = "standard"
        segment = plan["segments"][0]
        with self.assertRaises(ValueError):
            POLICY.validate_parallel_envelope(
                plan, segment["segment_id"], [], [], plan["route_id"],
                segment["attempt_id"], {
                    "parallelism_source": "standard",
                    "requested_max_parallelism": 4,
                    "effective_max_parallelism": 3,
                },
            )

    def test_parallel_envelope_requires_matching_concurrency_metadata(self):
        plan = POLICY.plan_parallel_segments([
            self.segment("one", access_mode="read"),
        ], current=current())
        segment = plan["segments"][0]
        with self.assertRaisesRegex(ValueError, "concurrency metadata mismatch"):
            POLICY.validate_parallel_envelope(
                plan, "one", [], [], plan["route_id"], segment["attempt_id"],
                {
                    "parallelism_source": "standard",
                    "requested_max_parallelism": 4,
                    "effective_max_parallelism": 2,
                },
            )

    def test_parallel_legacy_plan_without_source_still_validates(self):
        plan = POLICY.plan_parallel_segments([
            self.segment("one", access_mode="read"),
        ], current=current())
        plan["parallel"].pop("parallelism_source")
        plan["plan_hash"] = POLICY.plan_hash(
            plan["segments"], plan["route_id"], plan["original"], False,
            plan["segment_budget"], plan["switch_budget"], plan["budget_source"],
            plan["routing_evidence"], POLICY.PARALLEL_PROTOCOL, plan["parallel"],
        )
        segment = plan["segments"][0]
        segment["attempt_id"] = POLICY.hashlib.sha256(
            f"{plan['route_id']}:{plan['plan_hash']}:one".encode("utf-8")
        ).hexdigest()
        selected = POLICY.validate_parallel_envelope(
            plan, "one", [], [], plan["route_id"], segment["attempt_id"]
        )
        self.assertEqual(selected["segment_id"], "one")

    def test_segment_override_wins_when_global_is_absent(self):
        plan = POLICY.plan_apply_segments([
            self.segment("review", model="GPT-5.6 Sol", effort="xhigh")
        ], current=current())
        self.assertEqual(
            (plan["segments"][0]["model"], plan["segments"][0]["effort"]),
            ("gpt-5.6-sol", "xhigh"),
        )

    def test_conflicting_global_and_segment_override_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "conflicting model overrides"):
            POLICY.plan_apply_segments(
                [self.segment("review", model="Sol")],
                current=current(),
                model_override="Terra",
            )

    def test_non_linear_dependencies_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "must depend only on the previous segment"):
            POLICY.plan_apply_segments([
                self.segment("one"),
                self.segment("two", depends_on=[]),
            ], current=current())

    def test_standard_budget_rejects_route_thrashing_without_extension_basis(self):
        segments = [
            self.segment("one", model="Luna", effort="low"),
            self.segment("two", model="Terra", effort="medium"),
            self.segment("three", model="Sol", effort="high"),
            self.segment("four", model="Luna", effort="high"),
        ]
        with self.assertRaisesRegex(ValueError, "standard 4/4 budget"):
            POLICY.plan_apply_segments(segments, current=current("gpt-5.6-sol", "medium"))

    def test_complex_plan_automatically_extends_to_six(self):
        segments = [
            self.segment("one", task_kind="complex", model="Luna", effort="low"),
            self.segment("two", model="Terra", effort="medium"),
            self.segment("three", model="Sol", effort="high"),
            self.segment("four", model="Luna", effort="high"),
            self.segment("five", model="Terra", effort="low"),
        ]
        plan = POLICY.plan_apply_segments(
            segments, current=current("gpt-5.6-sol", "medium")
        )
        self.assertEqual(plan["segment_count"], 5)
        self.assertEqual(plan["switch_count"], 6)
        self.assertEqual((plan["segment_budget"], plan["switch_budget"]), (6, 6))
        self.assertEqual(plan["budget_source"], "adaptive-extended")

    def test_high_risk_alone_does_not_trigger_automatic_extension(self):
        segments = [
            self.segment("one", risk="high", model="Luna", effort="low"),
            self.segment("two", model="Terra", effort="medium"),
            self.segment("three", model="Sol", effort="high"),
            self.segment("four", model="Luna", effort="high"),
            self.segment("five", model="Terra", effort="low"),
        ]
        with self.assertRaisesRegex(ValueError, "complex or large Segment"):
            POLICY.plan_apply_segments(segments, current=current("gpt-5.6-sol", "medium"))

    def test_user_can_override_budgets_up_to_hard_limit(self):
        routes = [
            ("Luna", "low"), ("Terra", "medium"), ("Sol", "high"),
            ("Luna", "high"), ("Terra", "low"), ("Sol", "xhigh"),
            ("Luna", "medium"),
        ]
        segments = [
            self.segment(str(index), model=model, effort=effort)
            for index, (model, effort) in enumerate(routes, 1)
        ]
        plan = POLICY.plan_apply_segments(
            segments,
            current=current("gpt-5.6-sol", "medium"),
            max_segments=8,
            max_switches=8,
        )
        self.assertEqual(plan["segment_count"], 7)
        self.assertEqual(plan["switch_count"], 8)
        self.assertEqual(plan["budget_source"], "user-override")
        self.assertTrue(plan["explicit_override"])
        self.assertEqual((plan["hard_max_segments"], plan["hard_max_switches"]), (8, 8))

    def test_synthetic_current_exercises_switch_and_restore_budget(self):
        synthetic = current("gpt-5.6-sol", "medium")
        synthetic["status"] = "synthetic"
        segments = [
            self.segment("one", model="Luna", effort="low"),
            self.segment("two", model="Terra", effort="medium"),
            self.segment("three", model="Sol", effort="high"),
        ]
        plan = POLICY.plan_apply_segments(segments, current=synthetic)
        self.assertEqual(plan["switch_count"], 4)
        self.assertTrue(plan["restore_required"])
        self.assertEqual(plan["original"], {
            "model": "gpt-5.6-sol", "effort": "medium"
        })

    def test_single_user_budget_applies_to_both_dimensions(self):
        plan = POLICY.plan_apply_segments(
            [self.segment("one")], current=current(), max_segments=3
        )
        self.assertEqual((plan["segment_budget"], plan["switch_budget"]), (3, 3))
        self.assertEqual(plan["budget_source"], "user-override")

    def test_user_smaller_budget_is_enforced(self):
        with self.assertRaisesRegex(ValueError, "budget is 1"):
            POLICY.plan_apply_segments(
                [
                    self.segment("one", model="Luna", effort="low"),
                    self.segment("two", model="Terra", effort="medium"),
                ],
                current=current("gpt-5.6-sol", "medium"),
                max_segments=1,
            )

    def test_budget_above_hard_limit_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "1 to 8"):
            POLICY.plan_apply_segments(
                [self.segment("one")], current=current(), max_segments=9
            )

    def test_adjacent_merge_is_counted_before_budget(self):
        plan = POLICY.plan_apply_segments(
            [self.segment("one"), self.segment("two")],
            current=current(),
            max_segments=1,
            max_switches=2,
        )
        self.assertEqual(plan["segment_count"], 1)
        self.assertEqual(plan["segment_budget"], 1)

if __name__ == "__main__":
    unittest.main()
