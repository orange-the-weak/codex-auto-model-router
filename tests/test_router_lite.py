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
            "max_total_tasks": LITE.DEFAULT_MAX_TOTAL_TASKS,
            "available_worker_slots": 3,
            "min_parallel_seconds": LITE.DEFAULT_MIN_PARALLEL_SECONDS,
            "executor_startup_seconds": LITE.DEFAULT_EXECUTOR_STARTUP_SECONDS,
            "reused_executor_seconds": LITE.DEFAULT_REUSED_EXECUTOR_SECONDS,
            "max_executor_reuses": LITE.DEFAULT_MAX_REUSES_PER_EXECUTOR,
            "reuse_candidates_json": "[]",
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

    def test_mismatched_route_uses_explicit_agent_without_switch_or_hash(self):
        current = {"status": "verified", "thread_id": "t", "model": "gpt-5.6-sol", "effort": "high"}
        with patch.object(LITE.policy, "detect_current_route", return_value=current):
            result = self.output(LITE.decide, self.args(task_kind="mechanical"))
        self.assertEqual(result["action"], "delegate")
        self.assertEqual(result["agent_type"], "codex_auto_model_executor_luna")
        self.assertNotIn("plan_hash", result)
        self.assertNotIn("route_id", result)

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
            {"agent_task_name": "prior_one", "model": "gpt-5.6-luna", "effort": "high"},
            {"agent_task_name": "prior_two", "model": "gpt-5.6-luna", "effort": "high"},
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
            {"agent_task_name": "sol_agent", "model": "gpt-5.6-sol", "effort": "high"},
        ]
        args = self.plan_args(tasks, reuse_candidates_json=json.dumps(candidates))
        with patch.object(LITE.policy, "detect_current_route", return_value=LITE.policy.unavailable_current()):
            result = self.output(LITE.plan, args)
        self.assertFalse(result["parallel"])
        self.assertEqual(result["planning_estimate"]["reused_activations"], 0)

    def test_reuse_limit_forces_a_fresh_executor_after_one_followup(self):
        tasks = [
            {"task_name": f"task_{index}", "estimated_seconds": 180}
            for index in range(5)
        ]
        args = self.plan_args(tasks, max_total_tasks=3, available_worker_slots=2)
        with patch.object(LITE.policy, "detect_current_route", return_value=LITE.policy.unavailable_current()):
            result = self.output(LITE.plan, args)
        self.assertTrue(result["parallel"])
        self.assertEqual(result["planning_estimate"]["fresh_activations"], 3)
        self.assertEqual(result["planning_estimate"]["reused_activations"], 2)

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


if __name__ == "__main__":
    unittest.main()
