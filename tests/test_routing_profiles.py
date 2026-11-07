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

    def test_three_complete_profiles_and_astra_budget(self):
        self.assertEqual(set(PROFILES.ROUTING_PROFILES), {"economy", "balanced", "quality"})
        for table in PROFILES.ROUTING_PROFILES.values():
            self.assertEqual(set(table), set(PROFILES.TASK_LANES))
            for route in table.values():
                if route["model"] == "gpt-6-astra":
                    self.assertIn(route["effort"], ("low", "medium"))

    def test_sol_first_matrix_and_profile_boundaries(self):
        expected = {
            "economy": (("gpt-6-luna", "high"), "medium", "high"),
            "balanced": (("gpt-6.1-sol", "medium"), "medium", "high"),
            "quality": (("gpt-6.1-sol", "high"), "high", "xhigh"),
        }
        for profile, (ordinary, bounded, uncertain) in expected.items():
            routes = self.config(profile)["routes"]
            with self.subTest(profile=profile):
                self.assertEqual(routes["ordinary_default"], dict(zip(("model", "effort"), ordinary)))
                self.assertEqual(routes["complex_bounded"], {"model": "gpt-6.1-sol", "effort": bounded})
                for lane in ("complex_uncertain", "high_consequence"):
                    self.assertEqual(routes[lane], {"model": "gpt-6.1-sol", "effort": uncertain})
                self.assertEqual(routes["complex_failed_escalation"], {"model": "gpt-6-astra", "effort": "medium"})

    def test_shared_policy_matches_lite_across_profiles_and_lanes(self):
        cases = ({"task_kind": "mechanical"}, {}, {"size": "large"},
                 {"size": "large", "verification": "deterministic"},
                 {"latency_priority": "high"}, {"task_kind": "complex"},
                 {"ambiguity": "high"}, {"risk": "high"},
                 {"task_kind": "complex", "prior_failure": True, "prior_failure_kind": "reasoning"},
                 {"task_kind": "complex", "prior_failure": True, "prior_failure_kind": "infrastructure"})
        for profile in PROFILES.ROUTING_PROFILES:
            config = self.config(profile)
            for signals in cases:
                with self.subTest(profile=profile, signals=signals):
                    lite = LITE._decision(self.args(routing_config=config, **signals), current={})
                    strict = POLICY.select_route("apply", routing_config=config, **signals)
                    self.assertEqual(lite["recommended_route"], {k: strict["recommended"][k] for k in ("model", "effort")})
                    if signals.get("prior_failure_kind") == "infrastructure":
                        self.assertNotEqual(lite["recommended_route"]["model"], "gpt-6-astra")

    def test_configured_analysis_prefers_sol_61_without_changing_legacy(self):
        for mode in ("assess", "retune"):
            current = POLICY.select_route(mode, routing_config=self.config())
            legacy = POLICY.select_route(mode)
            self.assertEqual((current["recommended"]["model"], current["recommended"]["effort"]), ("gpt-6.1-sol", "high"))
            self.assertEqual(legacy["recommended"]["model"], "gpt-5.6-sol")

    def test_shared_policy_preserves_explicit_efforts_and_astra_model_only_guard(self):
        for profile in PROFILES.ROUTING_PROFILES:
            config = self.config(profile)
            for model in ("gpt-6.1-sol", "astra"):
                for effort in (None, *PROFILES.ROUTED_EFFORTS):
                    with self.subTest(profile=profile, model=model, effort=effort):
                        lite = LITE._decision(self.args(routing_config=config, model=model, effort=effort), current={})
                        strict = POLICY.select_route("apply", routing_config=config, model_override=model, effort_override=effort)
                        self.assertEqual(lite["recommended_route"], {k: strict["recommended"][k] for k in ("model", "effort")})
                        if model == "astra" and effort is None:
                            self.assertEqual(lite["execution_route"]["effort"], "low")

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
        self.assertEqual(result["recommended_route"], {"model": "gpt-6.1-sol", "effort": "medium"})
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
        self.assertEqual((linear["segments"][0]["model"], linear["segments"][0]["effort"]), ("gpt-6.1-sol", "xhigh"))
        self.assertEqual(parallel["segments"][0]["effort"], "xhigh")
        self.write(self.project_file, 'schema_version=1\nprofile="economy"\n')
        self.assertEqual(linear["segments"][0]["model"], "gpt-6.1-sol")

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
