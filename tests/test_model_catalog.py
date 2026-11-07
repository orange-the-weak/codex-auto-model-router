import io
import json
import unittest
from contextlib import redirect_stdout
import test_router_lite as legacy_tests
LITE = legacy_tests.LITE
reusable_candidate = legacy_tests.reusable_candidate


class CatalogTests(unittest.TestCase):
    def args(self, **kwargs):
        return legacy_tests.RouterLiteTests().args(model_policy="current", **kwargs)

    def run_plan(self, available, tasks=None):
        tasks = tasks or [{"task_name": name, "estimated_seconds": 600} for name in ("alpha", "beta")]
        args = self.args(available_model=available, tasks_json=json.dumps(tasks), no_runtime_detection=True)
        out = io.StringIO()
        with redirect_stdout(out):
            LITE.plan(args)
        return json.loads(out.getvalue())

    def test_astra_all_efforts_explicit(self):
        for effort in LITE.EFFORT_RANK:
            result = LITE._decision(self.args(model="gpt-6-astra", effort=effort), current={})
            self.assertEqual(result["model"], "gpt-6-astra")
            self.assertEqual(result["agent_type"], f"codex_auto_model_executor_gpt6_astra_{effort}")

    def test_sol_first_with_astra_reserved_for_reasoning_failure(self):
        result = LITE._decision(self.args(task_kind="complex", risk="high"), current={})
        self.assertEqual(result["recommended_route"], {"model": "gpt-6.1-sol", "effort": "high"})
        result = LITE._decision(self.args(task_kind="complex", prior_failure=True,
            prior_failure_kind="reasoning"), current={})
        self.assertEqual(result["recommended_route"], {"model": "gpt-6-astra", "effort": "medium"})

    def test_explicit_astra_is_not_silently_replaced(self):
        result = LITE._decision(self.args(model="astra", available_model=["gpt-6.1-sol"]), current={})
        self.assertEqual(result["action"], "local")
        self.assertIsNone(result["execution_route"]["model"])
        self.assertEqual(result["reason"], "explicit-model-unavailable")

    def test_astra_cost_guard_including_fallback(self):
        for model in ("astra", "gpt-6-astra"):
            result = LITE._decision(self.args(model=model, risk="high"), current={})
            self.assertEqual(result["execution_route"]["effort"], "low")
        result = LITE._decision(self.args(task_kind="complex", prior_failure=True,
            prior_failure_kind="reasoning"), current={})
        self.assertEqual(result["execution_route"]["effort"], "medium")
        result = LITE.catalog.resolve("gpt-6.1-sol", "max", ["gpt-6-astra"])
        self.assertEqual(result["execution"]["effort"], "low")
        result = LITE.catalog.resolve("gpt-6.1-sol", "max", ["gpt-6-astra"], explicit_effort=True)
        self.assertEqual(result["execution"]["effort"], "max")

    def test_automatic_astra_fallback_discloses_downgrade(self):
        result = LITE._decision(self.args(task_kind="complex", prior_failure=True,
            prior_failure_kind="verification", available_model=["gpt-6.1-sol"]), current={})
        self.assertEqual(result["execution_route"]["model"], "gpt-6.1-sol")
        self.assertTrue(result["fallback"]["quality_degraded"])

    def test_astra_parallel_lanes_obey_cost_guard(self):
        result = self.run_plan(["gpt-6-astra"], [
            {"task_name": name, "risk": "high", "estimated_seconds": 600}
            for name in ("alpha", "beta")])
        self.assertTrue(result["parallel"])
        for lane in result["executor_lanes"]:
            self.assertEqual(lane["route"], ["gpt-6-astra", "low"])

    def test_high_effort_astra_candidate_not_implicitly_reused(self):
        args = self.args(model="astra", no_runtime_detection=True,
            reuse_candidates_json=json.dumps([reusable_candidate("astra_leaf", model="gpt-6-astra", effort="high")]))
        out = io.StringIO()
        with redirect_stdout(out):
            LITE.decide(args)
        result = json.loads(out.getvalue())
        self.assertNotEqual(result["action"], "reuse")
        self.assertEqual(result["execution_route"]["effort"], "low")

    def test_plan_uses_resolved_route(self):
        result = self.run_plan(["gpt-6.1-sol"])
        self.assertEqual(result["action"], "parallel")
        for task in result["tasks"]:
            self.assertEqual(task["leaf_agent_type"], "codex_auto_model_executor_gpt61_sol_medium")
        for lane in result["executor_lanes"]:
            self.assertEqual(lane["route"], ["gpt-6.1-sol", "medium"])

    def test_plan_no_models_no_dispatch(self):
        result = self.run_plan([])
        self.assertFalse(result["parallel"])
        self.assertFalse(result.get("dispatch_now"))
        self.assertTrue(all(t["leaf_agent_type"] is None for t in result["tasks"]))

    def test_mixed_availability_never_dispatches_unavailable_task(self):
        tasks = [{"task_name": "blocked", "estimated_seconds": 600, "available_models": []},
                 {"task_name": "ready", "estimated_seconds": 600}]
        result = self.run_plan(["gpt-6-luna"], tasks)
        self.assertNotIn("blocked", result.get("dispatch_now", []))

    def test_reuse_uses_resolved_model(self):
        candidate = reusable_candidate("sol_leaf", model="gpt-6.1-sol", effort="medium")
        args = self.args(available_model=["gpt-6.1-sol"], no_runtime_detection=True,
                         reuse_candidates_json=json.dumps([candidate]))
        out = io.StringIO()
        with redirect_stdout(out):
            LITE.decide(args)
        result = json.loads(out.getvalue())
        self.assertEqual(result["action"], "reuse")
        self.assertEqual(result["reuse_target"], "sol_leaf")

    def test_surface_changes_are_advisory(self):
        result = LITE.catalog.check_surface(["gpt-new"], ["gpt-6-astra"])
        self.assertTrue(result["update_suggested"])
        self.assertEqual(result["unknown_models"], ["gpt-new"])
        self.assertFalse(result["routing_changed"])
        self.assertFalse(LITE.catalog.check_surface(["gpt-6-astra"], ["gpt-6-astra"])["update_suggested"])

    def test_presets_match_catalog(self):
        import tomllib
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        for model, entry in LITE.catalog.MODELS.items():
            for effort in entry["efforts"]:
                name = f"{entry['preset_stem']}_{effort}"
                preset = tomllib.loads((root / "codex-agents" / (name.replace("_", "-") + ".toml")).read_text())
                self.assertEqual((preset["model"], preset["model_reasoning_effort"]), (model, effort))

    def test_invalid_surface_rejected(self):
        with self.assertRaises(ValueError):
            LITE.catalog.resolve("gpt-6-astra", "high", "gpt-6-astra")
        with self.assertRaises(ValueError):
            LITE.catalog.check_surface(["gpt-6-astra"], "not-a-list")

    def test_unknown_availability_does_not_downgrade(self):
        result = LITE.catalog.resolve("gpt-6-astra", "high")
        self.assertEqual(result["execution"]["model"], "gpt-6-astra")
        self.assertFalse(result["availability_complete"])

    def test_sol_fallback_prefers_compatible_sol_before_astra(self):
        for available, expected in ((["gpt-6-sol", "gpt-5.6-sol", "gpt-6-astra"], "gpt-6-sol"),
                                    (["gpt-5.6-sol", "gpt-6-astra"], "gpt-5.6-sol"),
                                    (["gpt-6-astra"], "gpt-6-astra")):
            result = LITE.catalog.resolve("gpt-6.1-sol", "high", available)
            self.assertEqual(result["execution"]["model"], expected)
            if expected == "gpt-6-astra":
                self.assertEqual(result["execution"]["effort"], "low")

    def test_current_policy_is_cli_default(self):
        args = LITE.parser().parse_args(["decide", "--no-runtime-detection", "--risk", "high"])
        self.assertEqual(LITE._decision(args)["recommended_route"]["model"], "gpt-6.1-sol")

    def test_explicit_legacy_still_supported(self):
        result = LITE._decision(self.args(model="gpt-5.6-sol", effort="high"), current={})
        self.assertEqual(result["recommended_route"]["model"], "gpt-5.6-sol")

    def test_invalid_catalog_fails_open(self):
        from unittest.mock import patch
        out = io.StringIO()
        with patch.object(LITE.catalog, "LOAD_ERROR", "invalid catalog"), redirect_stdout(out):
            LITE.main(["decide", "--no-runtime-detection"])
        self.assertEqual(json.loads(out.getvalue())["action"], "local")
