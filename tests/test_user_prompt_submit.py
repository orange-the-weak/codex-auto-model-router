import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_HOOK = ROOT / "scripts" / "user_prompt_submit.py"


class UserPromptSubmitTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.codex_home = self.base / "codex home"
        self.skill = self.codex_home / "skills" / "codex-auto-model-router"
        self.scripts = self.skill / "scripts"
        self.scripts.mkdir(parents=True)
        for source in (ROOT / "scripts").glob("*.py"):
            shutil.copy2(source, self.scripts / source.name)
        shutil.copy2(ROOT / "SKILL.md", self.skill / "SKILL.md")
        self.project = self.base / "project"
        self.project.mkdir()
        (self.project / ".git").mkdir()

    def tearDown(self):
        self.temp_dir.cleanup()

    def invoke(self, payload):
        return subprocess.run(
            [sys.executable, str(self.scripts / SOURCE_HOOK.name)],
            input=payload,
            text=True,
            capture_output=True,
            cwd=self.project,
            env=os.environ | {"CODEX_HOME": str(self.codex_home)},
            check=False,
        )

    def event(self, **extra):
        return {"hook_event_name": "UserPromptSubmit", "cwd": str(self.project), **extra}

    def test_enabled_project_gets_context_without_prompt_content(self):
        secret = "private prompt marker 8f0b"
        result = self.invoke(json.dumps(self.event(prompt=secret)))
        self.assertEqual(result.returncode, 0)
        output = json.loads(result.stdout)
        context = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("codex-auto-model-router", context)
        self.assertNotIn(secret, result.stdout)
        self.assertEqual(result.stderr, "")

    def test_disabled_project_gets_no_router_context(self):
        project_config = self.project / ".codex" / "config.toml"
        project_config.parent.mkdir()
        project_config.write_text(
            "[[skills.config]]\n"
            f"path = '{self.skill / 'SKILL.md'}'\n"
            "enabled = false\n",
            encoding="utf-8",
        )
        result = self.invoke(json.dumps(self.event()))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_wrong_event_and_invalid_json_fail_open_silently(self):
        wrong_event = self.invoke(json.dumps({"hook_event_name": "SessionStart", "cwd": str(self.project)}))
        malformed = self.invoke("private malformed prompt payload")
        for result in (wrong_event, malformed):
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
            self.assertEqual(result.stderr, "")

    def test_missing_skill_and_invalid_project_config_fail_open_silently(self):
        (self.skill / "SKILL.md").unlink()
        missing_skill = self.invoke(json.dumps(self.event()))
        self.assertEqual(missing_skill.returncode, 0)
        self.assertEqual(missing_skill.stdout, "")

        shutil.copy2(ROOT / "SKILL.md", self.skill / "SKILL.md")
        router = self.scripts / "router_lite.py"
        router.unlink()
        missing_router = self.invoke(json.dumps(self.event()))
        self.assertEqual(missing_router.returncode, 0)
        self.assertEqual(missing_router.stdout, "")
        shutil.copy2(ROOT / "scripts" / "router_lite.py", router)

        project_config = self.project / ".codex" / "config.toml"
        project_config.parent.mkdir(parents=True, exist_ok=True)
        project_config.write_text("not valid = [toml", encoding="utf-8")
        invalid_config = self.invoke(json.dumps(self.event()))
        self.assertEqual(invalid_config.returncode, 0)
        self.assertEqual(invalid_config.stdout, "")
        self.assertEqual(invalid_config.stderr, "")

    def test_configurator_preserves_malformed_target(self):
        hooks_path = self.codex_home / "hooks.json"
        hooks_path.write_text("not json", encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "configure_user_hook.py"), "--codex-home", str(self.codex_home)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(hooks_path.read_text(encoding="utf-8"), "not json")
        self.assertEqual(list(self.codex_home.glob(".hooks.json.*")), [])


if __name__ == "__main__":
    unittest.main()
