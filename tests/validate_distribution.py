import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def fail(message):
    raise SystemExit(message)


skill_text = (ROOT / "SKILL.md").read_text()
if not skill_text.startswith("---\n"):
    fail("SKILL.md frontmatter is missing")
frontmatter = skill_text.split("---", 2)[1]
if "\nname: codex-auto-model-router\n" not in "\n" + frontmatter or "\ndescription: " not in "\n" + frontmatter:
    fail("SKILL.md frontmatter is invalid")

ui_text = (ROOT / "agents" / "openai.yaml").read_text()
values = {}
for line in ui_text.splitlines():
    stripped = line.strip()
    if ": " in stripped:
        key, value = stripped.split(": ", 1)
        values[key] = value.strip().strip('"')
if not 25 <= len(values.get("short_description", "")) <= 64:
    fail("openai.yaml short_description length is invalid")
if "$codex-auto-model-router" not in values.get("default_prompt", ""):
    fail("openai.yaml default prompt does not invoke the skill")
if "## Visible routing protocol" not in skill_text or "Codex 自动路由｜Segment <index>/<total>：<task segment>" not in skill_text:
    fail("visible routing protocol is missing")
if "## Path dispatch" not in skill_text or "ROUTE_PROJECT_MODELS_EXECUTOR=1`" not in skill_text:
    fail("coordinator/router/executor path dispatch is missing")
if "## Capability check and Dispatch" not in skill_text or "Never call a thread/task creation capability" not in skill_text:
    fail("same-task routing contract is missing")
if "A task/agent name alone is not proof of model selection" not in skill_text:
    fail("generic subagent model-safety guard is missing")
if "A normal successful completion needs no separate model-identity or runtime-verification warning" not in skill_text:
    fail("normal completion suppression rule is missing")
if "Use this order once for the complete plan" not in skill_text or "explicitly model-selectable executor presets" not in skill_text:
    fail("switch-to-subagent fallback order is missing")
if "ROUTED_MODE=APPLY_SEGMENT" not in skill_text or "ROUTED_MODE=APPLY_ONESHOT" not in skill_text or "## Restore and Return" not in skill_text:
    fail("segmented Apply, compatibility, or restore contract is missing")
for budget_contract in (
    "standard budget of four routed segments and four switches",
    "Expand automatically to six segments and six switches",
    "Eight segments and eight switches are absolute hard limits",
    "budget_source=standard|adaptive-extended|user-override",
):
    if budget_contract not in skill_text:
        fail(f"adaptive budget contract is missing: {budget_contract}")
if "tiny mechanical segment" not in skill_text or "Never make a persistent same-task switch when the original model or effort is unknown" not in skill_text:
    fail("switch-cost or safe-restore rule is missing")
if "A failed segment stops the chain" not in skill_text or "Never re-plan after execution begins" not in skill_text:
    fail("segment failure or recursion guard is missing")

state_machine = (ROOT / "references" / "execution-state-machine.md").read_text()
for invariant in (
    "one immutable `route_id`",
    "immutable adaptive budget",
    "absolute 8/8 hard limit",
    "A failed segment stops the plan",
    "`RETURN` is terminal",
):
    if invariant not in state_machine:
        fail(f"state-machine invariant is missing: {invariant}")

ledger_text = (ROOT / "scripts" / "model_usage_ledger.py").read_text()
if 'MODES = ("assess", "apply", "query", "record", "retune")' not in ledger_text:
    fail("Apply ledger mode is missing")
if "import msvcrt" not in ledger_text or "import fcntl" not in ledger_text:
    fail("cross-platform ledger locking is missing")
if 'commands.add_parser("claim")' not in ledger_text or '"segment_claim"' not in ledger_text:
    fail("atomic Segment replay claim is missing")

policy_text = (ROOT / "scripts" / "route_policy.py").read_text()
for contract in ("CODEX_THREAD_ID", "thread_settings_applied", "turn_context", "tiny-segment-switch-cost", "selectable-subagent-or-local", "segmented-v1", "DEFAULT_MAX_SEGMENTS", "EXTENDED_MAX_SEGMENTS", "HARD_MAX_SEGMENTS", "HARD_MAX_SWITCHES", "budget_source", "plan_hash", "attempt_id", "validate_segment_cursor", "synthetic-test-input"):
    if contract not in policy_text:
        fail(f"route policy contract is missing: {contract}")

install_text = (ROOT / "install.sh").read_text()
if 'cp "$ROOT/scripts/"*.py' not in install_text:
    fail("installer does not copy every bundled policy script")
if 'SKILL_TARGET="$CODEX_HOME/skills/codex-auto-model-router"' not in install_text:
    fail("installer target does not match the renamed skill")
if 'LEGACY_SKILL_TARGET="$CODEX_HOME/skills/codex-model-router"' not in install_text:
    fail("installer does not migrate the legacy skill name")
if 'project-model-router*.toml' in install_text or 'project-model-executor*.toml' in install_text:
    fail("installer uses an unsafe broad legacy-agent cleanup glob")

preset_mapping = (ROOT / "references" / "preset-mapping.md").read_text()

models = {"sol": "gpt-5.6-sol", "terra": "gpt-5.6-terra", "luna": "gpt-5.6-luna"}
router_count = 0
executor_count = 0
for tier, model in models.items():
    for effort in ("low", "medium", "high", "xhigh"):
        if tier == "sol" and effort == "medium":
            name = "codex-auto-model-router.toml"
        elif effort == "medium":
            name = f"codex-auto-model-router-{tier}.toml"
        elif tier == "sol":
            name = f"codex-auto-model-router-{effort}.toml"
        else:
            name = f"codex-auto-model-router-{tier}-{effort}.toml"
        data = tomllib.loads((ROOT / "codex-agents" / name).read_text())
        if data.get("name") != Path(name).stem.replace("-", "_"):
            fail(f"incorrect preset name: {name}")
        if data.get("model") != model or data.get("model_reasoning_effort") != effort:
            fail(f"incorrect preset: {name}")
        if data.get("sandbox_mode") != "read-only":
            fail(f"agent must be read-only: {name}")
        if "ROUTE_PROJECT_MODELS_SUBAGENT=1" not in data.get("developer_instructions", ""):
            fail(f"router subagent recursion guard is missing: {name}")
        if f"`{data.get('name')}`" not in preset_mapping:
            fail(f"router preset mapping is missing: {name}")
        router_count += 1

        if tier == "sol" and effort == "medium":
            executor_name = "codex-auto-model-executor.toml"
        elif effort == "medium":
            executor_name = f"codex-auto-model-executor-{tier}.toml"
        elif tier == "sol":
            executor_name = f"codex-auto-model-executor-{effort}.toml"
        else:
            executor_name = f"codex-auto-model-executor-{tier}-{effort}.toml"
        executor = tomllib.loads((ROOT / "codex-agents" / executor_name).read_text())
        if executor.get("name") != Path(executor_name).stem.replace("-", "_"):
            fail(f"incorrect executor name: {executor_name}")
        if executor.get("model") != model or executor.get("model_reasoning_effort") != effort:
            fail(f"incorrect executor preset: {executor_name}")
        if executor.get("sandbox_mode") != "workspace-write":
            fail(f"executor must be workspace-write: {executor_name}")
        if "ROUTE_PROJECT_MODELS_EXECUTOR=1" not in executor.get("developer_instructions", ""):
            fail(f"executor recursion guard is missing: {executor_name}")
        if "route_id and segment_id" not in executor.get("developer_instructions", "") or "do not plan, route, advance" not in executor.get("developer_instructions", ""):
            fail(f"executor segment guard is missing: {executor_name}")
        if f"`{executor.get('name')}`" not in preset_mapping:
            fail(f"executor preset mapping is missing: {executor_name}")
        executor_count += 1

if router_count != 12 or executor_count != 12:
    fail(f"expected 12 router and 12 executor presets, found {router_count} and {executor_count}")

legacy_presets = list((ROOT / "codex-agents").glob("project-model-*.toml"))
if legacy_presets:
    fail(f"legacy preset files remain: {legacy_presets}")

readme_text = (ROOT / "README.md").read_text()
if "https://github.com/orange-the-weak/codex-auto-model-router" not in readme_text:
    fail("README install URL does not match the current repository remote")

for forbidden in ("s" + "k-" + "live", "BEGIN " + "PRIVATE KEY", "api" + "_key"):
    for path in ROOT.rglob("*"):
        if path.is_file() and ".git" not in path.parts and forbidden in path.read_text(errors="ignore"):
            fail(f"possible secret marker {forbidden!r} in {path}")

print("distribution OK: skill metadata, UI metadata, 12 router presets, 12 executor presets, no obvious secrets")
