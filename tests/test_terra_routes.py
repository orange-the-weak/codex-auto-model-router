"""Terra is an explicit bounded focus, not a replacement for Sol-first work."""
import unittest
import test_router_lite as helpers
import test_routing_profiles as profile_helpers

LITE = helpers.LITE
POLICY = LITE.policy


class TerraRouteTests(unittest.TestCase):
    def setUp(self):
        self.fixture = profile_helpers.ProfileTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)

    def route(self, focus=None, profile="balanced", **signals):
        config = self.fixture.config(profile)
        args = self.fixture.args(routing_config=config, task_focus=focus, **signals)
        return LITE._decision(args, current={})

    def test_bounded_focus_selects_terra_in_all_profiles(self):
        for profile in LITE.profiles.ROUTING_PROFILES:
            effort = "high" if profile == "quality" else "medium"
            for focus in LITE.profiles.TASK_FOCUSES[1:]:
                with self.subTest(profile=profile, focus=focus):
                    result = self.route(focus, profile)
                    self.assertEqual(result["recommended_route"], {"model": "gpt-6.1-terra", "effort": effort})
                    self.assertEqual(result["agent_type"], f"codex_auto_model_executor_gpt61_terra_{effort}")
                    strict = POLICY.select_route("apply", routing_config=self.fixture.config(profile), task_focus=focus)
                    self.assertEqual(result["recommended_route"], {k: strict["recommended"][k] for k in ("model", "effort")})

    def test_sol_first_and_risk_boundaries(self):
        self.assertEqual(self.route()["recommended_route"]["model"], "gpt-6.1-sol")
        for signals in ({"task_kind": "complex"}, {"risk": "high"},
                        {"ambiguity": "high"}, {"coupling": "high"},
                        {"consequence": "high"}, {"prior_failure": True}):
            with self.subTest(signals=signals):
                self.assertNotEqual(self.route("computer_use", **signals)["recommended_route"]["model"], "gpt-6.1-terra")

    def test_explicit_pins_efforts_and_availability(self):
        pinned = self.route("writing", model="gpt-6.1-sol", effort="high")
        self.assertEqual(pinned["execution_route"], {"model": "gpt-6.1-sol", "effort": "high"})
        for effort in LITE.profiles.ROUTED_EFFORTS:
            result = self.route(model="gpt-6.1-terra", effort=effort)
            self.assertEqual(result["execution_route"], {"model": "gpt-6.1-terra", "effort": effort})
        missing_pin = self.route(model="gpt-6.1-terra", available_model=["gpt-6.1-sol"])
        self.assertEqual(missing_pin["reason"], "explicit-model-unavailable")
        fallback = self.route("visual", available_model=["gpt-6.1-sol"])
        self.assertEqual(fallback["execution_route"], {"model": "gpt-6.1-sol", "effort": "medium"})
        self.assertEqual(fallback["agent_type"], "codex_auto_model_executor_gpt61_sol_medium")
        self.assertEqual(self.route("visual", available_model=[])["action"], "local")

    def test_legacy_policy_is_not_changed_by_focus(self):
        result = POLICY.select_route("apply", task_focus="writing")
        self.assertEqual(result["recommended"]["model"], "gpt-5.6-luna")
        for invalid in ("anything", "extreme"):
            with self.assertRaises(ValueError):
                self.route(invalid)
        for effort in ("none", "ultra"):
            with self.assertRaises(ValueError):
                self.route(model="gpt-6.1-terra", effort=effort)

    def test_strict_plans_freeze_focus_and_do_not_merge_different_work(self):
        config = self.fixture.config()
        segments = [{"segment_id": focus, "goal": focus, "task_focus": focus,
                     "merge_group": "bounded-work", "work_estimate": "short", "acceptance": ["saved result checked"],
                     "validation_budget": "one check"} for focus in ("visual", "writing")]
        for planner in (POLICY.plan_apply_segments, POLICY.plan_parallel_segments):
            plan = planner(segments, routing_config=config)
            self.assertEqual(len(plan["segments"]), 2)
            for segment in plan["segments"]:
                self.assertEqual(segment["model"], "gpt-6.1-terra")
                capsule = POLICY.context_capsule(plan, segment["segment_id"])
                self.assertEqual(capsule["task_focus"], segment["task_focus"])

    def test_old_three_role_catalog_is_still_accepted(self):
        import json
        data = json.loads(LITE.catalog.PATH.read_text(encoding="utf-8"))
        data["roles"].pop("specialist")
        path = self.fixture.root / "old-catalog.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(set(LITE.catalog.load(path)["roles"]), {"efficient", "strong", "frontier"})
