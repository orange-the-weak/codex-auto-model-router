import filecmp
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRESETS = tuple(sorted(path.name for path in (ROOT / "codex-agents").glob("*.toml")))
LEGACY_PRESETS = (
    "project-model-router.toml",
    "project-model-router-luna-high.toml",
    "project-model-executor.toml",
    "project-model-executor-xhigh.toml",
    "project-model-executor-terra-xhigh.toml",
)


def payload_files(root):
    return sorted(path.relative_to(root) for path in root.rglob("*") if path.is_file())


def expected_payload_files():
    return sorted(
        [Path("SKILL.md"), Path("agents/openai.yaml")]
        + [Path("references") / path.name for path in (ROOT / "references").glob("*.md")]
        + [Path("references/benchmark-evidence.json")]
        + [Path("scripts") / path.name for path in (ROOT / "scripts").glob("*.py")]
    )


class InstallationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.codex_home = Path(self.temp_dir.name) / "codex-home"

    def tearDown(self):
        self.temp_dir.cleanup()

    def install(self, extra_environment=None, check=True, installer_root=ROOT):
        environment = os.environ | {"CODEX_HOME": str(self.codex_home)}
        if extra_environment:
            environment.update(extra_environment)
        if sys.platform == "win32":
            command = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(installer_root / "install.ps1")]
        else:
            command = ["sh", str(installer_root / "install.sh")]
        result = subprocess.run(
            command,
            cwd=installer_root,
            env=environment,
            check=False,
            text=True,
            capture_output=True,
        )
        if check and result.returncode != 0:
            self.fail(
                f"installer exited with {result.returncode}\n"
                f"stdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}"
            )
        return result

    def isolated_installer_copy(self):
        replica = Path(self.temp_dir.name) / "installer-replica"
        replica.mkdir()
        for source in (ROOT / "install.sh", ROOT / "install.ps1", ROOT / "SKILL.md"):
            shutil.copy2(source, replica / source.name)
        shutil.copytree(ROOT / "agents", replica / "agents")
        shutil.copytree(ROOT / "references", replica / "references")
        shutil.copytree(ROOT / "scripts", replica / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(ROOT / "codex-agents", replica / "codex-agents")
        return replica

    def assert_no_install_residue(self):
        skills_root = self.codex_home / "skills"
        self.assertEqual(list(skills_root.glob(".codex-auto-model-router.stage.*")), [])
        self.assertEqual(list(skills_root.glob(".codex-auto-model-router.backup.*")), [])

    def assert_failed_install_keeps_old_state(
        self,
        command_environment=None,
        install_first=True,
        installer_root=ROOT,
        with_legacy_state=False,
    ):
        if install_first:
            self.install()
        skill = self.codex_home / "skills" / "codex-auto-model-router"
        old_only = skill / "old-only.txt"
        old_only.write_text("keep", encoding="utf-8")
        agents = self.codex_home / "agents"
        old_preset = agents / "codex-auto-model-router-old.toml"
        old_preset.write_text("keep", encoding="utf-8")
        legacy = self.codex_home / "skills" / "codex-model-router"
        legacy_payload = None
        if with_legacy_state:
            legacy.mkdir(parents=True)
            (legacy / "legacy-only.txt").write_text("keep", encoding="utf-8")
            for name in LEGACY_PRESETS:
                (agents / name).write_text(f"keep:{name}", encoding="utf-8")
            legacy_payload = {
                path.relative_to(legacy): path.read_bytes()
                for path in legacy.rglob("*")
                if path.is_file()
            }
        old_agents = {
            path.name: path.read_bytes()
            for path in agents.glob("*.toml")
        }
        old_payload = {path.relative_to(skill): path.read_bytes() for path in skill.rglob("*") if path.is_file()}
        result = self.install(command_environment, check=False, installer_root=installer_root)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(old_only.exists())
        self.assertEqual(old_preset.read_text(encoding="utf-8"), "keep")
        self.assertEqual(
            {path.relative_to(skill): path.read_bytes() for path in skill.rglob("*") if path.is_file()},
            old_payload,
        )
        self.assertEqual(
            {path.name: path.read_bytes() for path in agents.glob("*.toml")},
            old_agents,
        )
        if with_legacy_state:
            self.assertEqual(
                {
                    path.relative_to(legacy): path.read_bytes()
                    for path in legacy.rglob("*")
                    if path.is_file()
                },
                legacy_payload,
            )
        self.assert_no_install_residue()

    def assert_exact_payload(self):
        target = self.codex_home / "skills" / "codex-auto-model-router"
        expected_files = expected_payload_files()
        self.assertEqual(payload_files(target), sorted(expected_files))
        for relative_path in expected_files:
            self.assertTrue(filecmp.cmp(ROOT / relative_path, target / relative_path, shallow=False), relative_path)

    def test_clean_and_repeated_install_has_exact_payload_and_all_presets(self):
        self.install()
        self.assert_exact_payload()
        agents = self.codex_home / "agents"
        self.assertEqual(sorted(path.name for path in agents.glob("codex-auto-model-*.toml")), list(PRESETS))
        self.assert_no_install_residue()
        self.install()
        self.assert_exact_payload()
        self.assertEqual(sorted(path.name for path in agents.glob("codex-auto-model-*.toml")), list(PRESETS))

    def test_stale_owned_files_are_removed_without_touching_unrelated_agent(self):
        skill = self.codex_home / "skills" / "codex-auto-model-router"
        stale_skill = skill / "scripts" / "removed-upstream.py"
        stale_skill.parent.mkdir(parents=True)
        stale_skill.write_bytes(b"stale")
        agents = self.codex_home / "agents"
        agents.mkdir(parents=True)
        (agents / "codex-auto-model-router-renamed.toml").write_text("stale", encoding="utf-8")
        unrelated = agents / "another-project-agent.toml"
        unrelated.write_text("keep", encoding="utf-8")
        self.install()
        self.assertFalse(stale_skill.exists())
        self.assertFalse((agents / "codex-auto-model-router-renamed.toml").exists())
        self.assertEqual(unrelated.read_text(encoding="utf-8"), "keep")
        self.assert_no_install_residue()

    def test_legacy_skill_and_presets_are_migrated(self):
        legacy = self.codex_home / "skills" / "codex-model-router"
        legacy.mkdir(parents=True)
        (legacy / "old.txt").write_text("old", encoding="utf-8")
        agents = self.codex_home / "agents"
        agents.mkdir(parents=True)
        for name in LEGACY_PRESETS:
            (agents / name).write_text("old", encoding="utf-8")
        self.install()
        self.assertFalse(legacy.exists())
        for name in LEGACY_PRESETS:
            self.assertFalse((agents / name).exists(), name)
        self.assert_exact_payload()
        self.assertEqual(
            sorted(path.name for path in agents.glob("codex-auto-model-*.toml")),
            list(PRESETS),
        )
        self.assert_no_install_residue()

    def test_missing_source_file_keeps_existing_install_intact(self):
        self.install()
        replica = self.isolated_installer_copy()
        (replica / "SKILL.md").unlink()
        self.assert_failed_install_keeps_old_state(install_first=False, installer_root=replica)

    def test_non_directory_skill_target_is_rejected_without_mutation(self):
        skill_target = self.codex_home / "skills" / "codex-auto-model-router"
        skill_target.parent.mkdir(parents=True)
        skill_target.write_text("keep", encoding="utf-8")
        result = self.install(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(skill_target.is_file())
        self.assertEqual(skill_target.read_text(encoding="utf-8"), "keep")
        self.assert_no_install_residue()

    @unittest.skipIf(sys.platform == "win32", "POSIX relative symlink semantics")
    def test_injected_failure_restores_relative_skill_and_preset_symlinks(self):
        skills = self.codex_home / "skills"
        actual_skill = skills / "actual-skill"
        actual_skill.mkdir(parents=True)
        (actual_skill / "keep.txt").write_text("keep", encoding="utf-8")
        skill_link = skills / "codex-auto-model-router"
        skill_link.symlink_to("actual-skill", target_is_directory=True)

        agents = self.codex_home / "agents"
        agents.mkdir(parents=True)
        unrelated = agents / "another-project-agent.toml"
        unrelated.write_text("keep", encoding="utf-8")
        preset_link = agents / "codex-auto-model-router-old.toml"
        preset_link.symlink_to(unrelated.name)

        result = self.install(
            {"CODEX_AUTO_MODEL_ROUTER_INSTALL_FAIL_AT": "after-agent-swap"},
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(skill_link.is_symlink())
        self.assertEqual(os.readlink(skill_link), "actual-skill")
        self.assertEqual((skill_link / "keep.txt").read_text(encoding="utf-8"), "keep")
        self.assertTrue(preset_link.is_symlink())
        self.assertEqual(os.readlink(preset_link), unrelated.name)
        self.assertEqual(preset_link.read_text(encoding="utf-8"), "keep")
        self.assert_no_install_residue()

    def test_injected_failure_after_skill_swap_keeps_existing_install_intact(self):
        self.assert_failed_install_keeps_old_state(
            {"CODEX_AUTO_MODEL_ROUTER_INSTALL_FAIL_AT": "after-skill-swap"}
        )

    def test_injected_failure_during_agent_backup_keeps_existing_install_intact(self):
        self.assert_failed_install_keeps_old_state(
            {"CODEX_AUTO_MODEL_ROUTER_INSTALL_FAIL_AT": "during-agent-backup"},
            with_legacy_state=True,
        )

    def test_injected_failure_after_agent_swap_restores_legacy_state(self):
        self.assert_failed_install_keeps_old_state(
            {"CODEX_AUTO_MODEL_ROUTER_INSTALL_FAIL_AT": "after-agent-swap"},
            with_legacy_state=True,
        )

    def test_powershell_installer_exposes_the_same_owned_cleanup_contract(self):
        installer = (ROOT / "install.ps1").read_text(encoding="utf-8")
        for required in (
            "codex-auto-model-router*.toml",
            "codex-auto-model-executor*.toml",
            "project-model-router.toml",
            "project-model-executor.toml",
            "$stagedSkill",
            "$skillBackup",
            "Restore-OwnedAgents",
            "Move-Item -LiteralPath $skillTarget -Destination $skillBackup",
            "CODEX_AUTO_MODEL_ROUTER_INSTALL_FAIL_AT",
            "during-agent-backup",
            "$legacySkillBackup",
            "Test-FileContentEqual",
            "[IO.File]::ReadAllBytes",
        ):
            self.assertIn(required, installer)
        self.assertNotIn("project-model-*.toml", installer)
        self.assertNotIn("Get-FileHash", installer)
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if powershell:
            escaped_installer = str(ROOT / "install.ps1").replace("'", "''")
            subprocess.run(
                [
                    powershell,
                    "-NoProfile",
                    "-Command",
                    f"[scriptblock]::Create((Get-Content -Raw -LiteralPath '{escaped_installer}')) | Out-Null",
                ],
                check=True,
                text=True,
                capture_output=True,
            )


if __name__ == "__main__":
    unittest.main()
