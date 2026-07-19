import json
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def fail(message):
    raise SystemExit(message)


skill_text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
if not skill_text.startswith("---\n"):
    fail("SKILL.md frontmatter is missing")
frontmatter = skill_text.split("---", 2)[1]
if "\nname: codex-auto-model-router\n" not in "\n" + frontmatter or "\ndescription: " not in "\n" + frontmatter:
    fail("SKILL.md frontmatter is invalid")

ui_text = (ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
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
if "## Capability check and Dispatch" not in skill_text or "Never create a new top-level Codex task" not in skill_text:
    fail("same-task routing contract is missing")
if "A task/agent name alone is not proof of model selection" not in skill_text:
    fail("generic subagent model-safety guard is missing")
for distribution_text, label in (
    (skill_text, "SKILL.md"),
    ((ROOT / "README.md").read_text(encoding="utf-8"), "README.md"),
    ((ROOT / "README.zh-CN.md").read_text(encoding="utf-8"), "README.zh-CN.md"),
    ((ROOT / "references" / "parallel-execution.md").read_text(encoding="utf-8"), "parallel-execution.md"),
):
    if "worker_time_compression_percent" in distribution_text:
        fail(f"obsolete compression wording is exposed in {label}")
for stable_phrase in (
    "并发：峰值 <n>｜墙钟：<wall>｜累计 worker：<worker>｜有效并发倍率：<factor>x｜并发利用率：<util>%",
    "并发：<effective>/<requested>｜测量：待记录",
    "coordinator's monotonic clock",
    "historical aggregate",
    "Print the returned `parallel_execution_brief` verbatim",
):
    if stable_phrase not in skill_text and stable_phrase not in (ROOT / "references" / "parallel-execution.md").read_text(encoding="utf-8"):
        fail(f"stable distribution contract is missing: {stable_phrase}")
if "A normal successful completion needs no separate model-identity or runtime-verification warning" not in skill_text:
    fail("normal completion suppression rule is missing")
if "Use this order once for the complete plan" not in skill_text or "explicitly model-selectable executor presets" not in skill_text:
    fail("switch-to-subagent fallback order is missing")
for family_guard in (
    "Never accept `available-default`, the current model, or GPT-5.5 while any GPT-5.6 route remains selectable",
    "Use GPT-5.5 only after the capability surface explicitly exposes no GPT-5.6 model",
    "fallback_reason=gpt56-family-unavailable",
    "Do not restore to an original GPT-5.5 setting after a GPT-5.6 Segment succeeds",
):
    if family_guard not in skill_text:
        fail(f"GPT-5.6 family fallback guard is missing: {family_guard}")
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
if "Never inherit the previous request's strength" not in skill_text or "never show `current-route` or `keep` placeholders" not in skill_text:
    fail("per-request dynamic routing contract is missing")
if "Never make a persistent same-task switch when the original model or effort is unknown" not in skill_text:
    fail("safe-restore rule is missing")
if "A failed segment stops the chain" not in skill_text or "Never re-plan after execution begins" not in skill_text:
    fail("segment failure or recursion guard is missing")
for parallel_contract in (
    "## Dependency-aware parallel planning",
    "dependency-parallel-v1",
    "critical-path",
    "wait-any",
    "stop-dispatch-drain-running",
    "write_scopes",
    "conflict_keys",
    "Workers receive only a bounded context capsule",
    "parallelism_source=standard|smart-reduced|user-override",
    "Automatic planning requests at most 4",
    "Create an executor only after confirming a free slot",
    "End every Apply chat summary with one concise concurrency line",
):
    if parallel_contract not in skill_text:
        fail(f"parallel routing contract is missing: {parallel_contract}")
state_machine = (ROOT / "references" / "execution-state-machine.md").read_text(encoding="utf-8")
for invariant in (
    "one immutable `route_id`",
    "standard budget is 4/4",
    "absolute 8/8 hard limit",
    "A failed segment stops the plan",
    "`RETURN` is terminal",
    "GPT-5.5 is legal only after the capability check proves the complete GPT-5.6 family unavailable",
    "A non-5.6 original is audit-only after verified GPT-5.6 execution",
    "`apply-fast-v1` has no cursor",
    "observed total slots - coordinator - running workers",
    "scripts/router_runtime.py begin",
    "context capsule",
):
    if invariant not in state_machine:
        fail(f"state-machine invariant is missing: {invariant}")

ledger_text = (ROOT / "scripts" / "model_usage_ledger.py").read_text(encoding="utf-8")
if 'MODES = ("assess", "apply", "query", "record", "retune")' not in ledger_text:
    fail("Apply ledger mode is missing")
if "import msvcrt" not in ledger_text or "import fcntl" not in ledger_text:
    fail("cross-platform ledger locking is missing")
if 'commands.add_parser("claim")' not in ledger_text or '"segment_claim"' not in ledger_text:
    fail("atomic Segment replay claim is missing")
for parallel_ledger_contract in (
    'commands.add_parser("parallel-plan")',
    'commands.add_parser("parallel-execution")',
    'commands.add_parser("resolve-ledger")',
    '"model_concurrency_usage"',
    '"cumulative_worker_seconds"',
    '"parallelism_source"',
    '"requested_max_parallelism"',
    '"effective_parallel_factor"',
    '"parallel_utilization_percent"',
    '"current_run"',
    '"historical_summary"',
    'parallel_run_brief',
    'pending_parallel_brief',
    '"parallel_worker_start"',
    '"parallel_worker_finish"',
    'PARALLEL_SCHEMA_VERSION = 2',
    '"worker_intervals"',
    '"legacy_unverified"',
    'commands.add_parser("efficiency")',
    '"routing_efficiency"',
    '"queue_wait_seconds"',
):
    if parallel_ledger_contract not in ledger_text:
        fail(f"parallel ledger contract is missing: {parallel_ledger_contract}")
if '"worker_time_compression_percent"' in ledger_text:
    fail("obsolete worker time compression metric remains in the public ledger output")
policy_text = (ROOT / "scripts" / "route_policy.py").read_text(encoding="utf-8")
for contract in ("CODEX_THREAD_ID", "thread_settings_applied", "turn_context", "route-already-matched", "selectable-subagent-or-local", "apply-fast-v1", "segmented-v1", "dependency-parallel-v1", "DEFAULT_AUTO_PARALLELISM", "HARD_MAX_PARALLELISM", "parallelism_source", "capacity_evaluation", "smart-reduced", "runtime_total_slots", "coordinator_reserved_slots", "available_worker_slots", "context_capsule", "critical-path-priority-wait-any", "write_scopes", "conflict_keys", "stop-dispatch-drain-running", "validate_fast_envelope", "validate_parallel_envelope", "DEFAULT_MAX_SEGMENTS", "EXTENDED_MAX_SEGMENTS", "HARD_MAX_SEGMENTS", "HARD_MAX_SWITCHES", "budget_source", "plan_hash", "attempt_id", "validate_segment_cursor", "synthetic-test-input", "load_benchmark_evidence", "evidence-snapshot-expired", "prior_failure", "resolve_family_fallback", "gpt56-family-unavailable"):
    if contract not in policy_text:
        fail(f"route policy contract is missing: {contract}")

install_text = (ROOT / "install.sh").read_text(encoding="utf-8")
if 'cp "$ROOT/scripts/"*.py' not in install_text:
    fail("installer does not copy every bundled policy script")
if 'cp "$ROOT/references/benchmark-evidence.json"' not in install_text:
    fail("installer does not copy the benchmark evidence snapshot")
if 'SKILL_TARGET="$CODEX_HOME/skills/codex-auto-model-router"' not in install_text:
    fail("installer target does not match the renamed skill")
if 'LEGACY_SKILL_TARGET="$CODEX_HOME/skills/codex-model-router"' not in install_text:
    fail("installer does not migrate the legacy skill name")
if 'project-model-router*.toml' in install_text or 'project-model-executor*.toml' in install_text:
    fail("installer uses an unsafe broad legacy-agent cleanup glob")

preset_mapping = (ROOT / "references" / "preset-mapping.md").read_text(encoding="utf-8")
parallel_reference = (ROOT / "references" / "parallel-execution.md").read_text(encoding="utf-8")
for contract in ("dependency-parallel-v1", "wait-any", "stop-dispatch-drain-running", "write_scopes", "conflict_keys", "parallelism_source=standard|smart-reduced|user-override", "observed_total_slots", "coordinator_slots", "bounded context capsule", "parallel_utilization", "without requiring a serial baseline"):
    if contract not in parallel_reference:
        fail(f"parallel execution reference is missing: {contract}")
runtime_text = (ROOT / "scripts" / "router_runtime.py").read_text(encoding="utf-8")
for contract in (
    "def begin", "def finish", "def worker_start", "def worker_finish",
    "validate_fast_envelope", "segment_claim", "routing_efficiency", "context_capsule",
):
    if contract not in runtime_text:
        fail(f"combined Router runtime contract is missing: {contract}")
evidence = json.loads(
    (ROOT / "references" / "benchmark-evidence.json").read_text(encoding="utf-8")
)
if evidence.get("schema_version") != 1 or not evidence.get("snapshot_id"):
    fail("benchmark evidence metadata is invalid")
if evidence.get("runtime_network_required") is not False:
    fail("benchmark evidence must remain offline at runtime")
if evidence.get("policy", {}).get("gpt55_fallback_requires_gpt56_family_unavailable") is not True:
    fail("benchmark evidence does not protect the GPT-5.6 family fallback rule")
if len(evidence.get("sources", [])) < 6:
    fail("benchmark evidence does not contain enough attributable sources")
if len(evidence.get("effort_profiles", {}).get("metrics", [])) < 15:
    fail("benchmark evidence effort matrix is incomplete")
if "GPT-5.5" not in (ROOT / "references" / "benchmark-evidence.md").read_text(encoding="utf-8"):
    fail("benchmark evidence report is missing the GPT-5.5 comparison")

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
        data = tomllib.loads((ROOT / "codex-agents" / name).read_text(encoding="utf-8"))
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
        executor = tomllib.loads(
            (ROOT / "codex-agents" / executor_name).read_text(encoding="utf-8")
        )
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

readme_text = (ROOT / "README.md").read_text(encoding="utf-8")
if "https://github.com/orange-the-weak/codex-auto-model-router" not in readme_text:
    fail("README install URL does not match the current repository remote")

for forbidden in ("s" + "k-" + "live", "BEGIN " + "PRIVATE KEY", "api" + "_key"):
    for path in ROOT.rglob("*"):
        if (
            path.is_file()
            and ".git" not in path.parts
            and "__pycache__" not in path.parts
            and path.suffix != ".pyc"
            and forbidden in path.read_text(encoding="utf-8", errors="ignore")
        ):
            fail(f"possible secret marker {forbidden!r} in {path}")

print("distribution OK: skill metadata, UI metadata, 12 router presets, 12 executor presets, no obvious secrets")
