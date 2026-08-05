import importlib.util
import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("router_lite", ROOT / "scripts" / "router_lite.py")
LITE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LITE)


def reusable_candidate(name, model="gpt-5.6-luna", effort="high", **overrides):
    candidate = {
        "agent_task_name": name,
        "model": model,
        "effort": effort,
        "idle": True,
        "accepted": True,
        "ownership_released": True,
        "pending_tool_call": False,
        "external_action": False,
        "sensitive_data": False,
        "interrupted": False,
        "failed": False,
        "prior_failure": False,
        "fresh_context_required": False,
        "deployment": False,
        "authentication": False,
        "high_consequence": False,
        "request_id": "request-1",
        "repository_realpath": str(ROOT.resolve()),
        "permissions_fingerprint": "workspace-write",
        "sandbox_fingerprint": "default-sandbox",
        "followups_used": 0,
    }
    candidate.update(overrides)
    return candidate


class RouterLiteTests(unittest.TestCase):
    def args(self, **overrides):
        values = {
            "task_kind": "ordinary", "risk": "normal", "size": "normal",
            "ambiguity": None, "coupling": None, "verification": None,
            "consequence": None, "latency_priority": None,
            "prior_failure": False, "prior_failure_kind": None,
            "tool_bound": False,
            "estimated_seconds": None,
            "min_delegate_seconds": LITE.DEFAULT_MIN_DELEGATE_SECONDS,
            "model": None, "effort": None, "sessions_root": None,
            "no_runtime_detection": False,
            "no_subagents": False,
            # Compatibility flag for older wrappers; it is no longer permission.
            "allow_subagents": False,
            "max_total_tasks": LITE.DEFAULT_MAX_TOTAL_TASKS,
            "available_worker_slots": 3,
            "min_parallel_seconds": LITE.DEFAULT_MIN_PARALLEL_SECONDS,
            "executor_startup_seconds": LITE.DEFAULT_EXECUTOR_STARTUP_SECONDS,
            "reused_executor_seconds": LITE.DEFAULT_REUSED_EXECUTOR_SECONDS,
            "max_executor_reuses": LITE.DEFAULT_MAX_REUSES_PER_EXECUTOR,
            "reuse_candidates_json": "[]",
            "request_id": "request-1",
            "repository": ROOT,
            "permissions_fingerprint": "workspace-write",
            "sandbox_fingerprint": "default-sandbox",
            "fresh_context_required": False,
            "external_action": False,
            "sensitive_data": False,
            "executor_wait_poll_seconds": LITE.DEFAULT_EXECUTOR_WAIT_POLL_SECONDS,
            "executor_stalled_after_seconds": (
                LITE.DEFAULT_EXECUTOR_STALLED_AFTER_SECONDS
            ),
            "coordination_seconds": LITE.DEFAULT_COORDINATION_SECONDS,
            "spawn_stagger_seconds": LITE.DEFAULT_SPAWN_STAGGER_SECONDS,
            "aggregation_seconds": LITE.DEFAULT_AGGREGATION_SECONDS,
            "min_parallel_savings_seconds": LITE.DEFAULT_MIN_PARALLEL_SAVINGS_SECONDS,
            "min_parallel_savings_ratio": LITE.DEFAULT_MIN_PARALLEL_SAVINGS_RATIO,
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def plan_args(self, tasks, **overrides):
        return self.args(tasks_json=json.dumps(tasks), **overrides)

    def output(self, function, args):
        stream = io.StringIO()
        with redirect_stdout(stream):
            function(args)
        return json.loads(stream.getvalue())

    def test_matching_route_runs_locally_without_restore(self):
        current = {"status": "verified", "thread_id": "t", "model": "gpt-5.6-luna", "effort": "medium"}
        with patch.object(LITE.policy, "detect_current_route", return_value=current):
            result = self.output(LITE.decide, self.args(task_kind="mechanical"))
        self.assertEqual(result["action"], "local")
        self.assertFalse(result["restore_required"])

    def test_mismatched_route_automatically_uses_agent_without_switch_or_hash(self):
        current = {"status": "verified", "thread_id": "t", "model": "gpt-5.6-sol", "effort": "high"}
        with patch.object(LITE.policy, "detect_current_route", return_value=current):
            result = self.output(LITE.decide, self.args(task_kind="mechanical"))
        self.assertEqual(result["action"], "delegate")
        self.assertEqual(result["agent_type"], "codex_auto_model_executor_luna")
        self.assertEqual(result["spawn_contract"]["fork_turns"], "none")
        self.assertFalse(result["spawn_contract"]["retry_on_contract_error"])
        self.assertTrue(result["record_contract"]["required_after_execution"])
        self.assertEqual(result["subagent_policy"]["mode"], "automatic-benefit-gated")
        self.assertFalse(result["subagent_policy"]["user_permission_required"])
        self.assertTrue(result["delegation_gate"]["benefit_clear"])
        self.assertNotIn("plan_hash", result)
        self.assertNotIn("route_id", result)

    def test_mismatched_route_stays_local_when_user_disables_subagents(self):
        current = {
            "status": "verified", "thread_id": "t",
            "model": "gpt-5.6-sol", "effort": "high",
        }
        with patch.object(LITE.policy, "detect_current_route", return_value=current):
            result = self.output(
                LITE.decide,
                self.args(task_kind="mechanical", no_subagents=True),
            )
        self.assertEqual(result["action"], "local")
        self.assertEqual(result["reason"], "subagents-disabled-by-user")
        self.assertEqual((result["model"], result["effort"]), ("gpt-5.6-sol", "high"))
        self.assertEqual(
            result["recommended_route"],
            {"model": "gpt-5.6-luna", "effort": "medium"},
        )
        self.assertIsNone(result["agent_type"])
        self.assertIsNone(result["spawn_contract"])
        self.assertFalse(result["subagent_policy"]["allowed"])
        self.assertFalse(result["subagent_policy"]["automatic_creation"])
        self.assertFalse(result["subagent_policy"]["automatic_reuse"])
        self.assertFalse(result["subagent_policy"]["user_permission_required"])
        self.assertTrue(result["subagent_policy"]["disabled_by_user"])
        self.assertTrue(result["tool_concurrency"]["allowed"])
        self.assertFalse(result["tool_concurrency"]["creates_child_agents"])
        self.assertTrue(result["tool_concurrency"]["same_model_and_effort"])
        self.assertFalse(result["record_contract"]["required_after_execution"])
        self.assertFalse(result["reuse_policy"]["enabled"])
        self.assertEqual(result["reuse_policy"]["max_followups_per_executor"], 0)
        self.assertEqual(result["reuse_policy"]["eligible_candidates"], [])
        self.assertIn(
            "subagents_disabled_by_user",
            result["reuse_policy"]["task_exclusions"],
        )

    def test_no_subagents_plan_never_creates_or_reuses_subagents(self):
        tasks = [
            {"task_name": "one", "task_kind": "ordinary", "estimated_seconds": 180},
            {"task_name": "two", "task_kind": "ordinary", "estimated_seconds": 180},
        ]
        current = {
            "status": "verified", "thread_id": "t",
            "model": "gpt-5.6-sol", "effort": "high",
        }
        with patch.object(LITE.policy, "detect_current_route", return_value=current):
            result = self.output(
                LITE.plan,
                self.plan_args(tasks, no_subagents=True),
            )
        self.assertEqual(result["action"], "local")
        self.assertFalse(result["parallel"])
        self.assertEqual(result["parallel_kind"], "none")
        self.assertFalse(result["subagent_policy"]["allowed"])
        self.assertTrue(result["tool_concurrency"]["allowed"])
        self.assertEqual(result["tool_concurrency"]["planning"], "coordinator-direct")
        self.assertTrue(all(item["leaf_agent_type"] is None for item in result["tasks"]))
        self.assertTrue(all(not item["reuse_eligible"] for item in result["tasks"]))

    def test_cli_automatically_delegates_and_supports_explicit_opt_out(self):
        command = [
            "python3", str(ROOT / "scripts" / "router_lite.py"), "decide",
            "--no-runtime-detection", "--task-kind", "mechanical",
        ]
        default = subprocess.run(command, text=True, capture_output=True, check=False)
        opted_out = subprocess.run(
            command + ["--no-subagents"],
            text=True, capture_output=True, check=False,
        )
        default_payload = json.loads(default.stdout)
        self.assertEqual(default_payload["action"], "delegate")
        self.assertFalse(default_payload["subagent_policy"]["user_permission_required"])
        opted_out_payload = json.loads(opted_out.stdout)
        self.assertEqual(opted_out_payload["action"], "local")
        self.assertEqual(opted_out_payload["reason"], "subagents-disabled-by-user")

    def test_short_unverified_route_stays_local_when_benefit_is_not_proven(self):
        result = self.output(
            LITE.decide,
            self.args(
                no_runtime_detection=True,
                task_kind="mechanical",
                estimated_seconds=20,
            ),
        )
        self.assertEqual(result["action"], "local")
        self.assertEqual(result["reason"], "route-benefit-not-proven")
        self.assertFalse(result["delegation_gate"]["benefit_clear"])

    def test_executor_permission_and_immediate_final_contract(self):
        current = {
            "status": "verified", "thread_id": "t",
            "model": "gpt-5.6-sol", "effort": "high",
        }
        with patch.object(LITE.policy, "detect_current_route", return_value=current):
            result = self.output(LITE.decide, self.args(task_kind="mechanical"))
        self.assertFalse(result["spawn_contract"]["request_escalated_permissions"])
        self.assertTrue(
            result["spawn_contract"]["return_limited_result_on_permission_boundary"]
        )
        executor = result["lifecycle_contract"]["executor"]
        self.assertEqual(executor["permission_boundary_result"], "limited")
        self.assertTrue(executor["finalize_immediately_after_acceptance"])
        self.assertTrue(
            executor["no_post_acceptance_validation_commentary_or_parent_wait"]
        )

    def test_completed_executor_is_terminal_and_never_interrupted(self):
        decision = LITE.executor_lifecycle_decision(
            "completed",
            now_seconds=10_000,
            last_activity_seconds=0,
            stalled_after_seconds=600,
        )
        self.assertEqual(decision["decision"], "accept-completed")
        self.assertFalse(decision["should_interrupt"])
        self.assertEqual(decision["same_request_reuse"], "prequalify")

        contract = LITE._lifecycle_contract(self.args())["coordinator"]
        self.assertIn("completed", contract["terminal_states"])
        self.assertEqual(
            contract["on_completed"],
            "accept-result-and-reuse-only-before-parent-finalization",
        )
        self.assertTrue(contract["clear_reuse_registry_on_new_request"])
        self.assertFalse(contract["delete_or_interrupt_completed_on_new_request"])

    def test_child_task_complete_reconciles_stale_parent_running_state(self):
        decision = LITE.executor_lifecycle_decision(
            "running",
            now_seconds=10_000,
            last_activity_seconds=0,
            task_complete_observed=True,
            stalled_after_seconds=600,
        )
        self.assertEqual(decision["reported_state"], "running")
        self.assertEqual(decision["state"], "completed")
        self.assertEqual(decision["decision"], "reconcile-completed")
        self.assertFalse(decision["should_interrupt"])
        self.assertEqual(decision["same_request_reuse"], "prequalify")

        contract = LITE._lifecycle_contract(self.args())["coordinator"]
        self.assertIn("child-task-complete", contract["completion_authority"])
        self.assertTrue(contract["refresh_status_after_wait_update"])
        self.assertTrue(contract["refresh_status_before_parent_final"])
        self.assertFalse(contract["wait_timeout_is_stall"])
        self.assertTrue(
            contract["parent_final_requires_no_required_running_executors"]
        )
        self.assertTrue(contract["parent_final_requires_all_owned_children_terminal"])
        self.assertTrue(contract["parent_final_stops_new_dispatch"])
        self.assertTrue(contract["parent_final_disables_reuse"])
        self.assertTrue(contract["parent_final_clears_reuse_registry"])
        self.assertTrue(contract["parent_final_interrupts_unneeded_running_children"])
        self.assertTrue(contract["parent_final_interrupts_optional_stragglers"])
        self.assertTrue(contract["parent_final_rechecks_status_after_interrupt"])
        self.assertEqual(contract["parent_final_scope"], "current-task-tree-only")
        self.assertFalse(contract["delete_child_agent_ui_history_supported"])

    def test_running_activity_refreshes_stall_timer(self):
        first = LITE.executor_lifecycle_decision(
            "running",
            now_seconds=600,
            last_activity_seconds=0,
            activity_at_seconds=599,
            stalled_after_seconds=100,
        )
        self.assertEqual(first["decision"], "continue-waiting")
        self.assertEqual(first["last_activity_seconds"], 599)
        self.assertEqual(first["stalled_for_seconds"], 1)
        self.assertFalse(first["should_interrupt"])

        continued = LITE.executor_lifecycle_decision(
            "running",
            now_seconds=700,
            last_activity_seconds=first["last_activity_seconds"],
            activity_at_seconds=699,
            stalled_after_seconds=100,
        )
        self.assertEqual(continued["decision"], "continue-waiting")
        self.assertEqual(continued["last_activity_seconds"], 699)

    def test_only_stalled_running_executor_suggests_interrupt(self):
        stalled = LITE.executor_lifecycle_decision(
            "running",
            now_seconds=601,
            last_activity_seconds=0,
            stalled_after_seconds=600,
        )
        self.assertEqual(stalled["decision"], "suggest-interrupt")
        self.assertTrue(stalled["should_interrupt"])
        self.assertEqual(stalled["stalled_for_seconds"], 601)

        idle = LITE.executor_lifecycle_decision(
            "idle",
            now_seconds=10_000,
            last_activity_seconds=0,
            stalled_after_seconds=600,
        )
        self.assertEqual(idle["decision"], "observe")
        self.assertFalse(idle["should_interrupt"])

    def test_short_ordinary_work_stays_local_on_sufficient_current_route(self):
        current = {"status": "verified", "thread_id": "t", "model": "gpt-5.6-sol", "effort": "high"}
        with patch.object(LITE.policy, "detect_current_route", return_value=current):
            result = self.output(
                LITE.decide,
                self.args(
                    task_kind="ordinary", risk="low", ambiguity="low", coupling="low",
                    verification="deterministic", consequence="low", estimated_seconds=60,
                ),
            )
        self.assertEqual(result["action"], "local")
        self.assertEqual(result["reason"], "startup-aware-local-fast-path")
        self.assertEqual(result["delegate_break_even_seconds"], 90)

    def test_short_work_delegates_when_current_route_is_not_sufficient(self):
        current = {"status": "verified", "thread_id": "t", "model": "gpt-5.6-luna", "effort": "medium"}
        with patch.object(LITE.policy, "detect_current_route", return_value=current):
            result = self.output(
                LITE.decide,
                self.args(task_kind="complex", estimated_seconds=60),
            )
        self.assertEqual(result["action"], "delegate")
        self.assertEqual(result["model"], "gpt-5.6-sol")

    def test_tiny_mechanical_work_uses_current_gpt56_locally(self):
        current = {"status": "verified", "thread_id": "t", "model": "gpt-5.6-sol", "effort": "high"}
        with patch.object(LITE.policy, "detect_current_route", return_value=current):
            result = self.output(LITE.decide, self.args(task_kind="mechanical", size="tiny", risk="low"))
        self.assertEqual(result["action"], "local")
        self.assertEqual((result["model"], result["effort"]), ("gpt-5.6-sol", "high"))
        self.assertEqual(result["recommended_route"], {"model": "gpt-5.6-luna", "effort": "medium"})
        self.assertEqual(result["reason"], "tiny-local-fast-path")

    def test_weaker_current_route_cannot_bypass_tiny_or_tool_bound_recommendation(self):
        weak = {
            "status": "verified", "thread_id": "t",
            "model": "gpt-5.6-luna", "effort": "low",
        }
        with patch.object(LITE.policy, "detect_current_route", return_value=weak):
            tiny = self.output(
                LITE.decide,
                self.args(task_kind="mechanical", size="tiny", risk="low"),
            )
            tool_bound = self.output(
                LITE.decide,
                self.args(
                    task_kind="complex", tool_bound=True,
                    verification="deterministic", estimated_seconds=30,
                ),
            )
        self.assertEqual(tiny["action"], "delegate")
        self.assertEqual(tiny["recommended_route"]["effort"], "medium")
        self.assertEqual(tool_bound["action"], "delegate")
        self.assertEqual(tool_bound["recommended_route"]["model"], "gpt-5.6-sol")

    def test_sequential_decide_reuses_exact_route_with_bound_identity(self):
        current = {
            "status": "verified", "thread_id": "t",
            "model": "gpt-5.6-sol", "effort": "high",
        }
        candidates = [reusable_candidate("bounded_worker")]
        with patch.object(LITE.policy, "detect_current_route", return_value=current):
            result = self.output(
                LITE.decide,
                self.args(
                    task_kind="ordinary", risk="low", ambiguity="low",
                    coupling="medium", verification="deterministic",
                    consequence="low", estimated_seconds=60,
                    reuse_candidates_json=json.dumps(candidates),
                ),
            )
        self.assertEqual(result["action"], "reuse")
        self.assertEqual(result["reuse_target"], "bounded_worker")
        self.assertEqual(result["reason"], "safe-same-request-reuse")

    def test_sequential_reuse_rejects_identity_mismatch_and_review(self):
        current = {
            "status": "verified", "thread_id": "t",
            "model": "gpt-5.6-sol", "effort": "high",
        }
        mismatched = reusable_candidate("wrong_repo", repository_realpath="/tmp/other")
        with patch.object(LITE.policy, "detect_current_route", return_value=current):
            identity_result = self.output(
                LITE.decide,
                self.args(
                    task_kind="ordinary", risk="low", ambiguity="low",
                    coupling="medium", verification="deterministic",
                    consequence="low", reuse_candidates_json=json.dumps([mismatched]),
                ),
            )
            review_result = self.output(
                LITE.decide,
                self.args(
                    task_kind="ordinary", risk="low", ambiguity="low",
                    coupling="medium", verification="deterministic",
                    consequence="low", fresh_context_required=True,
                    reuse_candidates_json=json.dumps([reusable_candidate("reviewer")]),
                ),
            )
        self.assertEqual(identity_result["action"], "delegate")
        self.assertIn(
            "repository_realpath",
            identity_result["reuse_policy"]["rejected_candidates"][0]["reasons"],
        )
        self.assertEqual(review_result["action"], "delegate")
        self.assertIn("fresh_context_required", review_result["reuse_policy"]["task_exclusions"])

    def test_tool_bound_work_uses_current_gpt56_locally(self):
        current = {"status": "verified", "thread_id": "t", "model": "gpt-5.6-sol", "effort": "medium"}
        with patch.object(LITE.policy, "detect_current_route", return_value=current):
            result = self.output(
                LITE.decide,
                self.args(task_kind="mechanical", size="normal", tool_bound=True, verification="deterministic"),
            )
        self.assertEqual(result["action"], "local")
        self.assertEqual(result["reason"], "tool-bound-local-fast-path")

    def test_explicit_route_bypasses_local_cost_fast_path(self):
        current = {"status": "verified", "thread_id": "t", "model": "gpt-5.6-sol", "effort": "high"}
        with patch.object(LITE.policy, "detect_current_route", return_value=current):
            result = self.output(
                LITE.decide,
                self.args(task_kind="mechanical", size="tiny", risk="low", model="gpt-5.6-luna", effort="medium"),
            )
        self.assertEqual(result["action"], "delegate")

    def test_parallel_requires_duration_independence_and_capacity(self):
        tasks = [
            {"task_name": "one", "task_kind": "ordinary", "estimated_seconds": 100, "write_scopes": ["Sources/A"]},
            {"task_name": "two", "task_kind": "ordinary", "estimated_seconds": 100, "write_scopes": ["Sources/B"]},
        ]
        args = self.args(
            tasks_json=json.dumps(tasks), max_total_tasks=4, available_worker_slots=3,
            min_parallel_seconds=LITE.DEFAULT_MIN_PARALLEL_SECONDS,
            executor_startup_seconds=LITE.DEFAULT_EXECUTOR_STARTUP_SECONDS,
            coordination_seconds=LITE.DEFAULT_COORDINATION_SECONDS,
            spawn_stagger_seconds=LITE.DEFAULT_SPAWN_STAGGER_SECONDS,
            aggregation_seconds=LITE.DEFAULT_AGGREGATION_SECONDS,
            min_parallel_savings_seconds=LITE.DEFAULT_MIN_PARALLEL_SAVINGS_SECONDS,
            min_parallel_savings_ratio=LITE.DEFAULT_MIN_PARALLEL_SAVINGS_RATIO,
        )
        with patch.object(LITE.policy, "detect_current_route", return_value=LITE.policy.unavailable_current()):
            result = self.output(LITE.plan, args)
        self.assertTrue(result["parallel"])
        self.assertEqual(result["max_parallelism"], 2)
        self.assertEqual(result["planning_estimate"]["savings_seconds"], 32)
        self.assertEqual(result["planning_estimate"]["fresh_executor_seconds"], 40)

    def test_parallel_leaf_keeps_explicit_agent_type_when_coordinator_route_matches(self):
        tasks = [
            {"task_name": "one", "task_kind": "ordinary", "estimated_seconds": 120},
            {"task_name": "two", "task_kind": "ordinary", "estimated_seconds": 120},
        ]
        current = {
            "status": "verified", "thread_id": "t",
            "model": "gpt-5.6-luna", "effort": "high",
        }
        with patch.object(LITE.policy, "detect_current_route", return_value=current):
            result = self.output(LITE.plan, self.plan_args(tasks))
        self.assertTrue(result["parallel"])
        self.assertTrue(all(
            item["leaf_agent_type"] == "codex_auto_model_executor_luna_high"
            for item in result["tasks"]
        ))

    def test_two_ninety_second_tasks_are_only_candidates_after_spawn_stagger(self):
        tasks = [
            {"task_name": "one", "estimated_seconds": 90},
            {"task_name": "two", "estimated_seconds": 90},
        ]
        args = self.plan_args(tasks)
        with patch.object(LITE.policy, "detect_current_route", return_value=LITE.policy.unavailable_current()):
            result = self.output(LITE.plan, args)
        self.assertFalse(result["parallel"])
        self.assertEqual(result["planning_estimate"]["dispatch_seconds"], 18)
        self.assertEqual(result["planning_estimate"]["savings_seconds"], 22)

    def test_parallel_rejects_imbalanced_plan_with_low_relative_benefit(self):
        tasks = [
            {"task_name": "long", "estimated_seconds": 240},
            {"task_name": "short", "estimated_seconds": 90},
        ]
        args = self.plan_args(tasks)
        with patch.object(LITE.policy, "detect_current_route", return_value=LITE.policy.unavailable_current()):
            result = self.output(LITE.plan, args)
        self.assertFalse(result["parallel"])
        self.assertEqual(result["planning_estimate"]["savings_seconds"], 30)
        self.assertLess(result["planning_estimate"]["savings_ratio"], 0.15)

    def test_same_route_refill_reuses_completed_executor(self):
        tasks = [
            {"task_name": "one", "estimated_seconds": 140},
            {"task_name": "two", "estimated_seconds": 130},
            {"task_name": "three", "estimated_seconds": 120},
        ]
        args = self.plan_args(tasks, max_total_tasks=3, available_worker_slots=2)
        with patch.object(LITE.policy, "detect_current_route", return_value=LITE.policy.unavailable_current()):
            result = self.output(LITE.plan, args)
        self.assertTrue(result["parallel"])
        self.assertEqual(result["planning_estimate"]["fresh_activations"], 2)
        self.assertEqual(result["planning_estimate"]["reused_activations"], 1)
        self.assertIn(
            "reused",
            [task["activation"] for lane in result["executor_lanes"] for task in lane["tasks"]],
        )
        self.assertEqual(result["reuse_policy"]["scope"], "same-request-only")
        self.assertFalse(result["reuse_policy"]["cross_request_reuse"])

    def test_prequalified_reused_executors_make_ninety_second_pair_worthwhile(self):
        tasks = [
            {"task_name": "one", "estimated_seconds": 90},
            {"task_name": "two", "estimated_seconds": 90},
        ]
        candidates = [
            reusable_candidate("prior_one"),
            reusable_candidate("prior_two"),
        ]
        args = self.plan_args(tasks, reuse_candidates_json=json.dumps(candidates))
        with patch.object(LITE.policy, "detect_current_route", return_value=LITE.policy.unavailable_current()):
            result = self.output(LITE.plan, args)
        self.assertTrue(result["parallel"])
        self.assertEqual(result["planning_estimate"]["fresh_activations"], 0)
        self.assertEqual(result["planning_estimate"]["reused_activations"], 2)
        self.assertEqual(
            {task["reuse_target"] for lane in result["executor_lanes"] for task in lane["tasks"]},
            {"prior_one", "prior_two"},
        )

    def test_mismatched_reuse_candidate_is_treated_as_fresh(self):
        tasks = [
            {"task_name": "one", "estimated_seconds": 90},
            {"task_name": "two", "estimated_seconds": 90},
        ]
        candidates = [
            reusable_candidate("sol_agent", model="gpt-5.6-sol", effort="high"),
        ]
        args = self.plan_args(tasks, reuse_candidates_json=json.dumps(candidates))
        with patch.object(LITE.policy, "detect_current_route", return_value=LITE.policy.unavailable_current()):
            result = self.output(LITE.plan, args)
        self.assertFalse(result["parallel"])
        self.assertEqual(result["planning_estimate"]["reused_activations"], 0)

    def test_default_allows_two_followups_per_executor(self):
        tasks = [
            {"task_name": f"task_{index}", "estimated_seconds": 180}
            for index in range(5)
        ]
        args = self.plan_args(tasks, max_total_tasks=3, available_worker_slots=2)
        with patch.object(LITE.policy, "detect_current_route", return_value=LITE.policy.unavailable_current()):
            result = self.output(LITE.plan, args)
        self.assertTrue(result["parallel"])
        self.assertEqual(result["planning_estimate"]["fresh_activations"], 2)
        self.assertEqual(result["planning_estimate"]["reused_activations"], 3)
        self.assertEqual(result["reuse_policy"]["max_followups_per_executor"], 2)

    def test_incomplete_candidate_attestation_is_rejected_not_reused(self):
        tasks = [
            {"task_name": "one", "estimated_seconds": 120},
            {"task_name": "two", "estimated_seconds": 120},
        ]
        candidates = [
            {"agent_task_name": "prior", "model": "gpt-5.6-luna", "effort": "high"},
        ]
        args = self.plan_args(tasks, reuse_candidates_json=json.dumps(candidates))
        with patch.object(LITE.policy, "detect_current_route", return_value=LITE.policy.unavailable_current()):
            result = self.output(LITE.plan, args)
        self.assertEqual(result["planning_estimate"]["reused_activations"], 0)
        self.assertEqual(result["reuse_policy"]["eligible_candidates"], [])
        self.assertIn(
            "request_id",
            result["reuse_policy"]["rejected_candidates"][0]["reasons"],
        )

    def test_candidate_reuse_count_is_honored(self):
        tasks = [
            {"task_name": "one", "estimated_seconds": 120},
            {"task_name": "two", "estimated_seconds": 120},
        ]
        candidates = [reusable_candidate("spent", followups_used=2)]
        args = self.plan_args(tasks, reuse_candidates_json=json.dumps(candidates))
        with patch.object(LITE.policy, "detect_current_route", return_value=LITE.policy.unavailable_current()):
            result = self.output(LITE.plan, args)
        self.assertEqual(result["planning_estimate"]["reused_activations"], 0)
        self.assertIn(
            "reuse_limit",
            result["reuse_policy"]["rejected_candidates"][0]["reasons"],
        )

    def test_candidate_origin_exclusions_are_all_enforced(self):
        tasks = [
            {"task_name": "one", "estimated_seconds": 120},
            {"task_name": "two", "estimated_seconds": 120},
        ]
        for field in (
            "pending_tool_call", "external_action", "sensitive_data", "interrupted",
            "failed", "prior_failure", "fresh_context_required", "deployment",
            "authentication", "high_consequence",
        ):
            with self.subTest(field=field):
                candidate = reusable_candidate("unsafe", **{field: True})
                args = self.plan_args(
                    tasks, reuse_candidates_json=json.dumps([candidate])
                )
                with patch.object(
                    LITE.policy, "detect_current_route",
                    return_value=LITE.policy.unavailable_current(),
                ):
                    result = self.output(LITE.plan, args)
                self.assertEqual(result["planning_estimate"]["reused_activations"], 0)
                self.assertIn(
                    field,
                    result["reuse_policy"]["rejected_candidates"][0]["reasons"],
                )

    def test_fresh_context_and_high_consequence_tasks_are_never_reused(self):
        tasks = [
            {
                "task_name": "independent_review", "estimated_seconds": 180,
                "fresh_context_required": True,
            },
            {
                "task_name": "sensitive_change", "estimated_seconds": 180,
                "risk": "high", "consequence": "high",
            },
            {"task_name": "normal_followup", "estimated_seconds": 180},
        ]
        args = self.plan_args(tasks, max_total_tasks=2, available_worker_slots=1)
        with patch.object(LITE.policy, "detect_current_route", return_value=LITE.policy.unavailable_current()):
            result = self.output(LITE.plan, args)
        self.assertTrue(result["tasks"][0]["fresh_context_required"])
        self.assertFalse(result["tasks"][0]["reuse_eligible"])
        self.assertFalse(result["tasks"][1]["reuse_eligible"])
        self.assertIn("high_consequence", result["tasks"][1]["reuse_exclusions"])

    def test_route_change_uses_fresh_executor_instead_of_reuse(self):
        tasks = [
            {"task_name": "luna", "estimated_seconds": 200, "model": "gpt-5.6-luna", "effort": "high"},
            {"task_name": "sol", "estimated_seconds": 190, "model": "gpt-5.6-sol", "effort": "high"},
            {"task_name": "terra", "estimated_seconds": 180, "model": "gpt-5.6-terra", "effort": "high"},
        ]
        args = self.plan_args(tasks, max_total_tasks=3, available_worker_slots=2)
        with patch.object(LITE.policy, "detect_current_route", return_value=LITE.policy.unavailable_current()):
            result = self.output(LITE.plan, args)
        self.assertTrue(result["parallel"])
        self.assertEqual(result["planning_estimate"]["fresh_activations"], 3)
        self.assertEqual(result["planning_estimate"]["reused_activations"], 0)

    def test_parallel_dispatches_longest_tasks_first(self):
        tasks = [
            {"task_name": "quick", "estimated_seconds": 100},
            {"task_name": "long", "estimated_seconds": 180},
            {"task_name": "middle", "estimated_seconds": 120},
        ]
        args = self.plan_args(tasks, max_total_tasks=3, available_worker_slots=2)
        with patch.object(LITE.policy, "detect_current_route", return_value=LITE.policy.unavailable_current()):
            result = self.output(LITE.plan, args)
        self.assertTrue(result["parallel"])
        self.assertEqual(result["priority_order"], ["long", "middle", "quick"])
        self.assertEqual(result["dispatch_now"], ["long", "middle"])
        self.assertEqual(result["local_or_deferred"], ["quick"])

    def test_invalid_parallel_cost_assumption_fails_open(self):
        result = subprocess.run(
            [
                "python3", str(ROOT / "scripts" / "router_lite.py"), "plan",
                "--no-runtime-detection", "--tasks-json",
                '[{"task_name":"one","estimated_seconds":90},{"task_name":"two","estimated_seconds":90}]',
                "--executor-startup-seconds", "-1",
            ],
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["action"], "local")

    def test_short_tasks_do_not_force_parallelism(self):
        tasks = [
            {"task_name": "one", "estimated_seconds": 20},
            {"task_name": "two", "estimated_seconds": 20},
        ]
        args = self.args(tasks_json=json.dumps(tasks), max_total_tasks=4, available_worker_slots=3, min_parallel_seconds=60)
        with patch.object(LITE.policy, "detect_current_route", return_value=LITE.policy.unavailable_current()):
            result = self.output(LITE.plan, args)
        self.assertFalse(result["parallel"])

    def test_default_threshold_rejects_seventy_five_second_tasks(self):
        tasks = [
            {"task_name": "one", "estimated_seconds": 75},
            {"task_name": "two", "estimated_seconds": 75},
        ]
        args = self.args(
            tasks_json=json.dumps(tasks), max_total_tasks=4, available_worker_slots=3,
            min_parallel_seconds=LITE.DEFAULT_MIN_PARALLEL_SECONDS,
        )
        with patch.object(LITE.policy, "detect_current_route", return_value=LITE.policy.unavailable_current()):
            result = self.output(LITE.plan, args)
        self.assertFalse(result["parallel"])

    def test_nested_write_scopes_prevent_parallelism(self):
        tasks = [
            {"task_name": "source_tree", "estimated_seconds": 90, "write_scopes": ["Sources"]},
            {"task_name": "source_file", "estimated_seconds": 90, "write_scopes": ["Sources/App"]},
        ]
        args = self.args(tasks_json=json.dumps(tasks), max_total_tasks=4, available_worker_slots=3, min_parallel_seconds=60)
        with patch.object(LITE.policy, "detect_current_route", return_value=LITE.policy.unavailable_current()):
            result = self.output(LITE.plan, args)
        self.assertFalse(result["parallel"])

    def test_shared_conflict_key_prevents_parallelism(self):
        tasks = [
            {"task_name": "build_one", "estimated_seconds": 90, "conflict_keys": ["simulator"]},
            {"task_name": "build_two", "estimated_seconds": 90, "conflict_keys": ["simulator"]},
        ]
        args = self.args(tasks_json=json.dumps(tasks), max_total_tasks=4, available_worker_slots=3, min_parallel_seconds=60)
        with patch.object(LITE.policy, "detect_current_route", return_value=LITE.policy.unavailable_current()):
            result = self.output(LITE.plan, args)
        self.assertFalse(result["parallel"])

    def test_optional_straggler_policy_and_recovery_budget(self):
        tasks = [
            {"task_name": "primary", "estimated_seconds": 90, "required": True},
            {
                "task_name": "secondary", "estimated_seconds": 90,
                "required": False, "max_recovery_attempts": 0,
            },
        ]
        args = self.args(tasks_json=json.dumps(tasks), max_total_tasks=4, available_worker_slots=3, min_parallel_seconds=60)
        with patch.object(LITE.policy, "detect_current_route", return_value=LITE.policy.unavailable_current()):
            result = self.output(LITE.plan, args)
        self.assertEqual(result["result_policy"]["required_tasks"], ["primary"])
        self.assertEqual(result["result_policy"]["optional_tasks"], ["secondary"])
        self.assertEqual(result["tasks"][1]["max_recovery_attempts"], 0)

    def test_recovery_budget_is_bounded(self):
        tasks = [{"task_name": "source", "estimated_seconds": 90, "max_recovery_attempts": 4}]
        args = self.args(tasks_json=json.dumps(tasks), max_total_tasks=4, available_worker_slots=3, min_parallel_seconds=60)
        with patch.object(LITE.policy, "detect_current_route", return_value=LITE.policy.unavailable_current()):
            with self.assertRaisesRegex(ValueError, "max recovery attempts"):
                LITE.plan(args)

    def test_ledger_failure_is_non_blocking(self):
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(
                ledger=Path(directory) / "ledger.jsonl", event_id=None,
                model="gpt-5.6-luna", effort="medium", task_class="mechanical",
                outcome="completed", source="task-metadata", duration_seconds=1.0,
                concurrency=1,
            )
            with patch.object(LITE.ledger, "append_event", side_effect=PermissionError):
                result = self.output(LITE.record, args)
        self.assertFalse(result["recorded"])
        self.assertEqual(result["warning"], "ledger-best-effort:PermissionError")

    def test_cli_invalid_plan_fails_open_with_success_exit(self):
        result = subprocess.run(
            [
                "python3", str(ROOT / "scripts" / "router_lite.py"), "plan",
                "--no-runtime-detection", "--tasks-json", "not-json",
            ],
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["action"], "local")
        self.assertTrue(payload["fail_open"])

    def test_cli_legacy_route_values_and_context_flags_are_accepted(self):
        result = subprocess.run(
            [
                "python3", str(ROOT / "scripts" / "router_lite.py"), "decide",
                "--no-runtime-detection", "--task-kind", "ordinary",
                "--risk", "medium", "--size", "small",
                "--responsibility", "release_git_publish",
                "--signals", "bounded deterministic release check",
            ],
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertNotIn("warning", payload)
        self.assertEqual(payload["recommended_route"]["model"], "gpt-5.6-luna")

    def test_cli_unknown_argument_fails_open_with_success_exit(self):
        result = subprocess.run(
            [
                "python3", str(ROOT / "scripts" / "router_lite.py"), "decide",
                "--no-runtime-detection", "--unknown-caller-flag", "value",
            ],
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["action"], "local")
        self.assertEqual(payload["warning"], "router-lite-fallback:RouterArgumentError")


if __name__ == "__main__":
    unittest.main()
