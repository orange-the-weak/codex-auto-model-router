import importlib.util
import json
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

    def test_complex_apply_switches_from_previous_luna_to_sol_high(self):
        route = POLICY.select_route(
            "apply", task_kind="complex", risk="normal", size="normal",
            current=current("gpt-5.6-luna", "low"),
        )
        self.assertEqual(
            (route["recommended"]["model"], route["recommended"]["effort"]),
            ("gpt-5.6-sol", "high"),
        )
        self.assertEqual(route["execution"]["dispatch"], "same-task-switch")
        self.assertTrue(route["restore_required"])

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
                ("gpt-5.6-sol", "high"),
                ("gpt-5.6-terra", "medium"),
                ("gpt-5.6-luna", "low"),
            ],
        )
        self.assertEqual(plan["switch_count"], 4)
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
        plan = POLICY.plan_apply_segments([self.segment("implement")], current=current())
        plan["segments"][0]["goal"] = "mutated"
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            self.validate_cursor(plan, 0, "implement", [])

    def test_cursor_validation_rejects_budget_mutation(self):
        plan = POLICY.plan_apply_segments([self.segment("implement")], current=current())
        plan["segment_budget"] = 5
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            self.validate_cursor(plan, 0, "implement", [])

    def test_cursor_validation_rejects_outer_budget_mismatch(self):
        plan = POLICY.plan_apply_segments([self.segment("implement")], current=current())
        with self.assertRaisesRegex(ValueError, "budget mismatch"):
            self.validate_cursor(plan, 0, "implement", [], segment_budget=5)

    def test_segment_attempt_ids_are_unique_per_invocation(self):
        first = POLICY.plan_apply_segments([self.segment("implement")], current=current())
        second = POLICY.plan_apply_segments([self.segment("implement")], current=current())
        self.assertNotEqual(first["plan_hash"], second["plan_hash"])
        self.assertNotEqual(first["segments"][0]["attempt_id"], second["segments"][0]["attempt_id"])

    def test_cursor_validation_rejects_forged_envelope_identity(self):
        plan = POLICY.plan_apply_segments([self.segment("implement")], current=current())
        with self.assertRaisesRegex(ValueError, "route_id mismatch"):
            self.validate_cursor(plan, 0, "implement", [], route_id="forged")
        with self.assertRaisesRegex(ValueError, "attempt_id mismatch"):
            self.validate_cursor(plan, 0, "implement", [], attempt_id="forged")
        with self.assertRaisesRegex(ValueError, "original route mismatch"):
            self.validate_cursor(plan, 0, "implement", [], original_model="gpt-5.6-luna")
        with self.assertRaisesRegex(ValueError, "protocol mismatch"):
            self.validate_cursor(plan, 0, "implement", [], protocol="forged")
        with self.assertRaisesRegex(ValueError, "Restore decision mismatch"):
            self.validate_cursor(plan, 0, "implement", [], restore_required=not plan["restore_required"])

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
            [("gpt-5.6-sol", "high"), ("gpt-5.6-luna", "low")],
        )

    def test_unknown_original_uses_non_persistent_segment_fallback(self):
        plan = POLICY.plan_apply_segments(
            [self.segment("implement")], current=POLICY.unavailable_current()
        )
        self.assertEqual(plan["segments"][0]["dispatch"], "selectable-subagent-or-local")
        self.assertFalse(plan["restore_required"])
        self.assertEqual(plan["switch_count"], 0)

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
