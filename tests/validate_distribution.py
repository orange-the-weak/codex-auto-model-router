import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def fail(message):
    raise SystemExit(message)


skill_text = (ROOT / "SKILL.md").read_text()
if not skill_text.startswith("---\n"):
    fail("SKILL.md frontmatter is missing")
frontmatter = skill_text.split("---", 2)[1]
if "\nname: codex-model-router\n" not in "\n" + frontmatter or "\ndescription: " not in "\n" + frontmatter:
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
if "$codex-model-router" not in values.get("default_prompt", ""):
    fail("openai.yaml default prompt does not invoke the skill")
if "## Visible routing protocol" not in skill_text or "Codex 自动路由｜任务段：<task segment>" not in skill_text:
    fail("visible routing protocol is missing")
if "## Path dispatch" not in skill_text or "ROUTE_PROJECT_MODELS_EXECUTOR=1`" not in skill_text:
    fail("coordinator/router/executor path dispatch is missing")
if "## Native same-task routing" not in skill_text or "Never use the thread-creation capability" not in skill_text:
    fail("native same-task routing contract is missing")
if "Never assume a generic subagent's task name changes its model" not in skill_text:
    fail("generic subagent model-safety guard is missing")

models = {"sol": "gpt-5.6-sol", "terra": "gpt-5.6-terra", "luna": "gpt-5.6-luna"}
router_count = 0
executor_count = 0
for tier, model in models.items():
    for effort in ("low", "medium", "high", "xhigh"):
        if tier == "sol" and effort == "medium":
            name = "project-model-router.toml"
        elif effort == "medium":
            name = f"project-model-router-{tier}.toml"
        elif tier == "sol":
            name = f"project-model-router-{effort}.toml"
        else:
            name = f"project-model-router-{tier}-{effort}.toml"
        data = tomllib.loads((ROOT / "codex-agents" / name).read_text())
        if data.get("model") != model or data.get("model_reasoning_effort") != effort:
            fail(f"incorrect preset: {name}")
        if data.get("sandbox_mode") != "read-only":
            fail(f"agent must be read-only: {name}")
        router_count += 1

        if tier == "sol" and effort == "medium":
            executor_name = "project-model-executor.toml"
        elif effort == "medium":
            executor_name = f"project-model-executor-{tier}.toml"
        elif tier == "sol":
            executor_name = f"project-model-executor-{effort}.toml"
        else:
            executor_name = f"project-model-executor-{tier}-{effort}.toml"
        executor = tomllib.loads((ROOT / "codex-agents" / executor_name).read_text())
        if executor.get("model") != model or executor.get("model_reasoning_effort") != effort:
            fail(f"incorrect executor preset: {executor_name}")
        if executor.get("sandbox_mode") != "workspace-write":
            fail(f"executor must be workspace-write: {executor_name}")
        if "ROUTE_PROJECT_MODELS_EXECUTOR=1" not in executor.get("developer_instructions", ""):
            fail(f"executor recursion guard is missing: {executor_name}")
        executor_count += 1

if router_count != 12 or executor_count != 12:
    fail(f"expected 12 router and 12 executor presets, found {router_count} and {executor_count}")

for forbidden in ("s" + "k-" + "live", "BEGIN " + "PRIVATE KEY", "api" + "_key"):
    for path in ROOT.rglob("*"):
        if path.is_file() and ".git" not in path.parts and forbidden in path.read_text(errors="ignore"):
            fail(f"possible secret marker {forbidden!r} in {path}")

print("distribution OK: skill metadata, UI metadata, 12 router presets, 12 executor presets, no obvious secrets")
