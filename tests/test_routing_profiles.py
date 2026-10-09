"""Profile acceptance coverage, adapted from David Soff's PR #6."""
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
import test_router_lite as helpers

LITE = helpers.LITE
PROFILES = LITE.profiles
POLICY = LITE.policy


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        (self.project / ".git").mkdir()
        self.env = {"CODEX_HOME": str(self.root / "home")}
        self.global_file = self.root / "home/router.toml"
        self.project_file = self.project / ".codex/router.toml"

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def config(self, profile=None):
        return PROFILES.resolve_routing_config(self.project, profile, self.env)

    def args(self, **overrides):
        return helpers.RouterLiteTests().args(model_policy="current", repository=self.project, **overrides)

    def test_complete_profiles_and_opt_in_astra_budget(self):
        self.assertEqual(set(PROFILES.ROUTING_PROFILES), {"economy", "balanced", "quality", "plus", "pro"})
        for profile, table in PROFILES.ROUTING_PROFILES.items():
            self.assertEqual(set(table), set(PROFILES.TASK_LANES))
            for route in table.values():
                if route["model"] == "gpt-6-astra":
                    self.assertIn(route["effort"], ("xhigh",) if profile == "pro" else ("low", "medium"))

    def assert_route(self, profile, expected, **signals):
        config = self.config(profile)
        lite = LITE._decision(self.args(routing_config=config, **signals), current={})
        strict = POLICY.select_route("apply", routing_config=config, **signals)
        self.assertEqual(lite["recommended_route"], dict(zip(("model", "effort"), expected)))
        self.assertEqual((strict["recommended"]["model"], strict["recommended"]["effort"]), expected)
        return lite

    def test_plus_ladder_and_no_automatic_astra(self):
        cases = [
            ({"task_kind": "mechanical"}, ("gpt-6-luna", "high")),
            ({}, ("gpt-6-luna", "xhigh")),
            ({"size": "large", "verification": "deterministic"}, ("gpt-6-luna", "xhigh")),
            ({"latency_priority": "high"}, ("gpt-6-luna", "xhigh")),
            ({"task_kind": "complex"}, ("gpt-6.1-sol", "high")),
            ({"task_kind": "complex", "ambiguity": "high"}, ("gpt-6.1-sol", "xhigh")),
            ({"risk": "high"}, ("gpt-6.1-sol", "xhigh")),
            ({"task_subtype": "extreme"}, ("gpt-6.1-sol", "xhigh")),
            ({"prior_failure": True, "prior_failure_kind": "reasoning", "prior_failure_model": "gpt-6.1-sol"}, ("gpt-6.1-sol", "xhigh")),
        ]
        for signals, expected in cases:
            with self.subTest(signals=signals):
                self.assert_route("plus", expected, **signals)

    def test_pro_default_and_task_type_split(self):
        self.assert_route("pro", ("gpt-6-luna", "high"), task_kind="mechanical")
        self.assert_route("pro", ("gpt-6-luna", "xhigh"))
        self.assert_route("pro", ("gpt-5.6-sol", "xhigh"), task_kind="complex")
        self.assert_route("pro", ("gpt-6.1-sol", "xhigh"), task_kind="complex", size="large")
        for subtype in PROFILES.SCOPED_TASK_SUBTYPES:
            self.assert_route("pro", ("gpt-5.6-sol", "xhigh"), task_kind="complex", task_subtype=subtype)
            self.assert_route("pro", ("gpt-6-luna", "xhigh"), task_subtype=subtype)
        for subtype in PROFILES.DEEP_TASK_SUBTYPES:
            self.assert_route("pro", ("gpt-6.1-sol", "xhigh"), task_subtype=subtype)

    def test_pro_substantive_corresponding_sol_failure_only(self):
        for subtype, corresponding in (("ui", "gpt-5.6-sol"), ("large_repo", "gpt-6.1-sol")):
            for kind in ("reasoning", "verification", "infrastructure", "unknown"):
                for failed in (None, "gpt-6-luna", "gpt-5.6-sol", "gpt-6.1-sol"):
                    expected = "gpt-6-astra" if kind in ("reasoning", "verification") and failed == corresponding else corresponding
                    with self.subTest(subtype=subtype, kind=kind, failed=failed):
                        self.assert_route("pro", (expected, "xhigh"), task_kind="complex", task_subtype=subtype,
                                          prior_failure=True, prior_failure_kind=kind, prior_failure_model=failed,
                                          prior_failure_effort="xhigh")

    def test_pro_failure_requires_observed_xhigh_effort(self):
        for subtype, corresponding in (("ui", "gpt-5.6-sol"), ("large_repo", "gpt-6.1-sol")):
            for effort in (None, "low", "medium", "high", "xhigh", "max"):
                expected = "gpt-6-astra" if effort == "xhigh" else corresponding
                self.assert_route("pro", (expected, "xhigh"), task_kind="complex", task_subtype=subtype,
                    prior_failure=True, prior_failure_kind="reasoning", prior_failure_model=corresponding,
                    prior_failure_effort=effort)

    def test_pro_extreme_and_high_consequence_skip_intermediate_astra(self):
        for signals in ({"task_subtype": "extreme"}, {"consequence": "high"}, {"risk": "high"}):
            result = self.assert_route("pro", ("gpt-6-astra", "xhigh"), **signals)
            self.assertIn("budget", result["budget_warning"])

    def test_luna_failure_promotes_to_sol_and_infrastructure_does_not(self):
        for profile, sol in (("plus", ("gpt-6.1-sol", "high")), ("pro", ("gpt-5.6-sol", "xhigh"))):
            self.assert_route(profile, sol, prior_failure=True, prior_failure_kind="reasoning", prior_failure_model="gpt-6-luna")
            self.assert_route(profile, ("gpt-6-luna", "xhigh"), prior_failure=True,
                              prior_failure_kind="infrastructure", prior_failure_model="gpt-6-luna")

    def test_plan_profile_selection_persists_until_explicit_switch(self):
        PROFILES.set_routing_profile("plus", "global", self.project, self.env)
        PROFILES.set_routing_profile("pro", "project", self.project, self.env)
        before = self.project_file.read_bytes()
        for _ in range(3):
            self.assertEqual(self.config()["profile"], "pro")
            self.assertEqual(self.config("quality")["profile"], "quality")
            self.assertEqual(self.project_file.read_bytes(), before)
        PROFILES.set_routing_profile("balanced", "project", self.project, self.env)
        self.assertEqual(self.config()["profile"], "balanced")
        self.assertEqual(self.global_file.read_text().count('profile = "plus"'), 1)

    def test_account_entitlement_environment_and_model_surface_never_select_profile(self):
        env = dict(self.env, CHATGPT_PLAN="pro", OPENAI_PLAN="plus", ACCOUNT_TYPE="pro", SUBSCRIPTION_TIER="pro")
        self.assertEqual(PROFILES.resolve_routing_config(self.project, environ=env)["profile"], "balanced")
        with patch.dict(os.environ, env):
            result = LITE._decision(self.args(available_model=["gpt-6-astra"]), current={"model": "gpt-6-astra", "effort": "xhigh"})
        self.assertEqual(result["routing_profile"], "balanced")

    def test_plan_fallback_cannot_promote_sol_to_astra(self):
        for profile in PROFILES.PLAN_PROFILES:
            config = self.config(profile)
            result = LITE._decision(self.args(routing_config=config, task_kind="complex",
                task_subtype="large_repo", available_model=["gpt-6-astra"]), current={})
            self.assertIsNone(result["execution_route"]["model"])
            self.assertEqual(result["action"], "local")
            strict = POLICY.resolve_family_fallback("gpt-6.1-sol", "xhigh", ["gpt-6-astra"], routing_profile=profile)
            self.assertIsNone(strict["execution"]["model"])
            result = LITE._decision(self.args(routing_config=config, task_subtype="large_repo",
                available_model=["gpt-6-astra", "gpt-5.6-sol"]), current={})
            self.assertEqual(result["execution_route"], {"model": "gpt-5.6-sol", "effort": "xhigh"})

    def test_pro_astra_fallback_discloses_degradation_and_retains_xhigh(self):
        result = LITE._decision(self.args(routing_config=self.config("pro"), consequence="high",
            available_model=["gpt-6.1-sol"]), current={})
        self.assertEqual(result["execution_route"], {"model": "gpt-6.1-sol", "effort": "xhigh"})
        self.assertTrue(result["fallback"]["quality_degraded"])

    def test_plan_explicit_model_effort_and_lane_preferences_win(self):
        for profile in PROFILES.PLAN_PROFILES:
            config = self.config(profile)
            explicit = LITE._decision(self.args(routing_config=config, model="astra", effort="max"), current={})
            self.assertEqual(explicit["recommended_route"], {"model": "gpt-6-astra", "effort": "max"})
            model_only = LITE._decision(self.args(routing_config=config, model="astra"), current={})
            self.assertEqual(model_only["recommended_route"]["effort"], "low")
            missing = LITE._decision(self.args(routing_config=config, model="astra", effort="xhigh",
                available_model=["gpt-6.1-sol"]), current={})
            self.assertEqual(missing["reason"], "explicit-model-unavailable")
            effort_only = LITE._decision(self.args(routing_config=config, effort="high"), current={})
            self.assertEqual(effort_only["recommended_route"], {"model": "gpt-6-luna", "effort": "high"})
        self.write(self.project_file, 'schema_version=1\nprofile="plus"\n[profiles.plus.routes.ordinary_default]\nmodel="astra"\neffort="xhigh"\n')
        self.assert_route("plus", ("gpt-6-astra", "xhigh"))

    def test_strict_plan_evidence_and_profile_are_frozen(self):
        segment = {"segment_id": "scoped-change", "goal": "change", "task_kind": "complex",
            "task_subtype": "ui", "prior_failure": True, "prior_failure_kind": "verification",
            "prior_failure_model": "gpt-5.6-sol", "prior_failure_effort": "xhigh",
            "acceptance": ["verified"], "validation_budget": "one check"}
        config = self.config("pro")
        for planner in (POLICY.plan_apply_segments, POLICY.plan_parallel_segments):
            result = planner([segment], routing_config=config)
            routed = result["segments"][0]
            self.assertEqual((routed["model"], routed["effort"]), ("gpt-6-astra", "xhigh"))
            self.assertEqual(routed["routing_profile"], "pro")
            self.assertEqual(routed["prior_failure_model"], "gpt-5.6-sol")
            self.assertEqual(routed["prior_failure_effort"], "xhigh")
            self.assertEqual(routed["task_subtype"], "ui")

    def test_new_evidence_is_validated(self):
        for signals in ({"task_subtype": "guess"}, {"prior_failure_model": "gpt-5.6-sol"},
                        {"prior_failure": True, "prior_failure_model": "made-up-model"},
                        {"prior_failure_effort": "xhigh"}, {"prior_failure": True, "prior_failure_effort": "ultra"}):
            with self.assertRaises(ValueError):
                POLICY.select_route("apply", routing_config=self.config("pro"), **signals)

    def test_decide_refreshes_stale_profile_snapshot_before_reuse(self):
        candidate = helpers.reusable_candidate("old_astra", "gpt-6-astra", "xhigh",
            repository_realpath=str(self.project.resolve()))
        args = self.args(routing_config=self.config("pro"), task_kind="complex",
            task_subtype="large_repo", no_runtime_detection=True, estimated_seconds=180,
            reuse_candidates_json=json.dumps([candidate]))
        self.write(self.project_file, 'schema_version=1\nprofile="plus"\n')
        with patch.dict(os.environ, self.env):
            result = helpers.RouterLiteTests().output(LITE.decide, args)
        self.assertEqual(result["routing_profile"], "plus")
        self.assertEqual(result["recommended_route"], {"model": "gpt-6.1-sol", "effort": "xhigh"})
        self.assertNotEqual(result["action"], "reuse")
        self.assertIsNone(result["reuse_target"])

    def test_lite_plan_retains_subtype_and_blocks_cached_astra_reuse(self):
        tasks = [{"task_name": "scoped_change", "task_kind": "complex", "task_subtype": "ui", "estimated_seconds": 180},
                 {"task_name": "deep_review", "task_kind": "complex", "task_subtype": "large_repo", "estimated_seconds": 180}]
        candidate = helpers.reusable_candidate("old_astra", "gpt-6-astra", "xhigh",
            repository_realpath=str(self.project.resolve()))
        args = self.args(profile="pro", tasks_json=json.dumps(tasks), no_runtime_detection=True,
            reuse_candidates_json=json.dumps([candidate]))
        with patch.dict(os.environ, self.env):
            result = helpers.RouterLiteTests().output(LITE.plan, args)
        self.assertEqual([task["route"]["recommended_route"] for task in result["tasks"]],
                         [{"model": "gpt-5.6-sol", "effort": "xhigh"}, {"model": "gpt-6.1-sol", "effort": "xhigh"}])
        self.assertNotIn('"reuse_target": "old_astra"', json.dumps(result))

    def test_extreme_task_cannot_reuse_cached_executor(self):
        candidate = helpers.reusable_candidate("old_astra", "gpt-6-astra", "xhigh",
            repository_realpath=str(self.project.resolve()))
        args = self.args(profile="pro", task_subtype="extreme", no_runtime_detection=True,
            reuse_candidates_json=json.dumps([candidate]))
        with patch.dict(os.environ, self.env):
            result = helpers.RouterLiteTests().output(LITE.decide, args)
        self.assertNotEqual(result["action"], "reuse")
        self.assertIn("high_consequence", result["reuse_policy"]["task_exclusions"])

    def test_strict_runtime_rejects_astra_availability_bypass(self):
        from test_router_runtime import RUNTIME
        config = self.config("plus")
        plan = POLICY.plan_apply_segments([{"segment_id": "deep-review", "goal": "review", "task_kind": "complex",
            "task_subtype": "large_repo", "acceptance": ["verified"], "validation_budget": "one check"}], routing_config=config)
        segment = plan["segments"][0]
        capsule = POLICY.context_capsule(plan, segment["segment_id"])
        self.assertEqual(capsule["routing_profile"], "plus")
        self.assertEqual(capsule["task_subtype"], "large_repo")
        decision = {"schema_version": 1, "verified": True, "source": RUNTIME.ledger.CAPABILITY_DECISION_SOURCE,
            **RUNTIME._decision_identity(plan, segment), "target_model": "gpt-6.1-sol", "target_effort": "xhigh",
            "execution_model": "gpt-6-astra", "execution_effort": "xhigh", "available_models": ["gpt-6-astra"],
            "availability_complete": True, "reason": "resolved"}
        with self.assertRaisesRegex(ValueError, "deterministic family fallback"):
            RUNTIME._validated_capability_decision(decision, plan, segment, ("gpt-6-astra", "xhigh"))

    def test_generated_report_cannot_override_plan_profile_policy(self):
        base = {"segment_id": "ordinary-change", "goal": "change", "acceptance": ["verified"], "validation_budget": "one check"}
        for profile in PROFILES.PLAN_PROFILES:
            config = self.config(profile)
            selected = POLICY.select_route("apply", routing_config=config, report_model="astra", report_effort="xhigh")
            self.assertEqual((selected["recommended"]["model"], selected["recommended"]["effort"]), ("gpt-6-luna", "xhigh"))
            explicit = POLICY.select_route("apply", routing_config=config, model_override="astra",
                report_model="astra", report_effort="xhigh")
            self.assertEqual(explicit["recommended"]["effort"], "low")
            for planner in (POLICY.plan_apply_segments, POLICY.plan_parallel_segments):
                for local_report in (False, True):
                    raw = dict(base, model="astra", effort="xhigh", route_source="report") if local_report else base
                    options = {} if local_report else {"report_model": "astra", "report_effort": "xhigh"}
                    result = planner([raw], routing_config=config, **options)
                    self.assertEqual((result["segments"][0]["model"], result["segments"][0]["effort"]), ("gpt-6-luna", "xhigh"))
                pinned = planner([dict(base, model="astra", effort="xhigh")], routing_config=config)
                self.assertEqual((pinned["segments"][0]["model"], pinned["segments"][0]["effort"]), ("gpt-6-astra", "xhigh"))
                explicit = planner([dict(base, model="astra", effort="xhigh", route_source="report")],
                    routing_config=config, model_override="astra")
                self.assertEqual(explicit["segments"][0]["effort"], "low")

    def test_current_catalog_fallback_rejects_ultra(self):
        with self.assertRaises(ValueError):
            POLICY.resolve_family_fallback("astra", "ultra")
        self.assertEqual(POLICY.normalize_available_model("gpt-6.1-sol"), "gpt-6.1-sol")

    def test_global_project_and_command_precedence(self):
        self.write(self.global_file, 'schema_version=1\nprofile="economy"\n[profiles.economy.routes.complex_bounded]\nmodel="gpt-6.1-sol"\neffort="high"\n')
        self.write(self.project_file, 'schema_version=1\nprofile="quality"\n[profiles.quality.routes.complex_bounded]\nmodel="astra"\neffort="medium"\n')
        self.assertEqual(self.config()["selected_from"], "project")
        self.assertEqual(self.config()["routes"]["complex_bounded"], {"model": "gpt-6-astra", "effort": "medium"})
        self.assertEqual(self.config("economy")["route_sources"]["complex_bounded"], "global")
        self.assertEqual(self.config("economy")["routes"]["complex_bounded"]["effort"], "high")

    def test_set_preserves_comments_and_overrides(self):
        self.write(self.project_file, '# personal settings\nschema_version=0x1 # version\nprofile="economy" # selected\n[profiles.quality.routes.complex_uncertain]\nmodel="gpt-6-astra"\neffort="high"\n')
        PROFILES.set_routing_profile("quality", "project", self.project, self.env)
        text = self.project_file.read_text(encoding="utf-8")
        self.assertIn("# personal settings", text)
        self.assertIn("# selected", text)
        self.assertIn("# version", text)
        self.assertIn('effort="high"', text)
        self.assertEqual(self.config()["profile"], "quality")
        self.assertFalse(PROFILES.set_routing_profile("quality", "project", self.project, self.env)["changed"])

    def test_invalid_config_is_not_rewritten(self):
        for body in ('schema_version=2', 'schema_version=1\nprofile="unknown"',
                     'schema_version=1\n[profiles.quality.routes.unknown]\nmodel="astra"\neffort="low"',
                     'schema_version=1\n[profiles.quality.routes.complex_uncertain]\nmodel="astra"\neffort="ultra"'):
            self.write(self.project_file, body)
            with self.assertRaises(ValueError):
                PROFILES.set_routing_profile("quality", "project", self.project, self.env)
            self.assertEqual(self.project_file.read_text(encoding="utf-8"), body)

    def test_lite_and_strict_agree_and_explicit_override_wins(self):
        config = self.config("quality")
        args = self.args(routing_config=config, task_kind="ordinary")
        lite = LITE._decision(args, current={})
        strict = POLICY.select_route("apply", routing_config=config)
        self.assertEqual(lite["recommended_route"], {k: strict["recommended"][k] for k in ("model", "effort")})
        explicit = LITE._decision(self.args(routing_config=config, model="gpt-6-luna", effort="low"), current={})
        self.assertEqual(explicit["recommended_route"], {"model": "gpt-6-luna", "effort": "low"})

    def test_configured_astra_effort_is_explicit(self):
        self.write(self.project_file, 'schema_version=1\n[profiles.balanced.routes.high_consequence]\nmodel="gpt-6-astra"\neffort="high"\n')
        config = self.config()
        lite = LITE._decision(self.args(routing_config=config, risk="high"), current={})
        strict = POLICY.select_route("apply", risk="high", routing_config=config)
        self.assertEqual(lite["recommended_route"]["effort"], "high")
        self.assertEqual(strict["recommended"]["effort"], "high")

    def test_effort_only_keeps_profile_model_and_astra_model_only_stays_low(self):
        config = self.config("economy")
        result = LITE._decision(self.args(routing_config=config, task_kind="complex", effort="medium"), current={})
        self.assertEqual(result["recommended_route"], {"model": "gpt-6-luna", "effort": "medium"})
        result = LITE._decision(self.args(routing_config=config, model="astra"), current={})
        self.assertEqual(result["recommended_route"]["effort"], "low")

    def test_strict_disabled_skips_invalid_profile(self):
        self.write(self.project_file, 'invalid = [')
        self.write(self.project / ".codex/config.toml", '[[skills.config]]\npath=' + json.dumps(str(Path(LITE.__file__).resolve().parents[1] / "SKILL.md")) + '\nenabled=false\n')
        out = io.StringIO()
        with patch.dict(os.environ, self.env), patch("sys.argv", ["route_policy.py", "--mode", "apply", "--repository", str(self.project), "--no-runtime-detection"]), redirect_stdout(out):
            POLICY.main()
        self.assertEqual(json.loads(out.getvalue())["action"], "disabled")

    def test_strict_plans_freeze_resolved_routes(self):
        segment = {"segment_id": "critical-change", "goal": "change", "risk": "high",
                   "acceptance": ["verified"], "validation_budget": "one check"}
        config = self.config("quality")
        linear = POLICY.plan_apply_segments([segment], routing_config=config)
        parallel = POLICY.plan_parallel_segments([dict(segment, depends_on=[])], routing_config=config)
        self.assertEqual((linear["segments"][0]["model"], linear["segments"][0]["effort"]), ("gpt-6-astra", "low"))
        self.assertEqual(parallel["segments"][0]["effort"], "low")
        self.write(self.project_file, 'schema_version=1\nprofile="economy"\n')
        self.assertEqual(linear["segments"][0]["model"], "gpt-6-astra")

    def test_invalid_config_fails_open_and_disabled_skips_config(self):
        self.write(self.project_file, 'invalid = [')
        out = io.StringIO()
        with patch.dict(os.environ, self.env), redirect_stdout(out):
            LITE.main(["decide", "--repository", str(self.project), "--no-runtime-detection"])
        self.assertEqual(json.loads(out.getvalue())["action"], "local")
        self.write(self.project / ".codex/config.toml", '[[skills.config]]\npath=' + json.dumps(str(Path(LITE.__file__).resolve().parents[1] / "SKILL.md")) + '\nenabled=false\n')
        out = io.StringIO()
        with patch.dict(os.environ, self.env), redirect_stdout(out):
            LITE.main(["decide", "--repository", str(self.project), "--no-runtime-detection"])
        self.assertEqual(json.loads(out.getvalue())["action"], "disabled")
