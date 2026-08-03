import json
import subprocess
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def fail(message):
    raise SystemExit(message)


gitignore_text = (ROOT / ".gitignore").read_text(encoding="utf-8")
for ignored_private_output in (
    ".codex/model-routing-runtime/",
    "benchmarks/gpt56-matrix/",
    "docs/xiaohongshu-launch-post/",
    "README 2.md",
    "README.zh-CN 2.md",
):
    if ignored_private_output not in gitignore_text:
        fail(f"private or duplicate output is not excluded: {ignored_private_output}")

community_files = {
    ".github/ISSUE_TEMPLATE/routing-feedback.yml": (
        "Routing feedback",
        "I removed prompts, source code, credentials, personal paths, and private project data.",
    ),
    ".github/ISSUE_TEMPLATE/bug-report.yml": (
        "Bug report",
        "For security issues, use GitHub private vulnerability reporting instead.",
    ),
    ".github/pull_request_template.md": (
        "## Evidence and compatibility",
        "No prompts, source code, credentials, paths, or private project data were added",
    ),
    "docs/community-launch-kit.md": (
        "## GitHub settings",
        "This is my first open-source project.",
    ),
}
for relative_path, required_phrases in community_files.items():
    path = ROOT / relative_path
    if not path.is_file():
        fail(f"missing community release file: {relative_path}")
    text = path.read_text(encoding="utf-8")
    for phrase in required_phrases:
        if phrase not in text:
            fail(f"community release contract is missing from {relative_path}: {phrase}")


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
if "## Visible routing protocol" not in skill_text or "Codex 自动路由｜任务段：<task segment>" not in skill_text:
    fail("visible routing protocol is missing")
for obsolete_segment_counter in (
    "Segment <index>/<total>",
    "Segment 1/1",
    "Segment 1/3",
):
    for path in (ROOT / "SKILL.md", ROOT / "README.md", ROOT / "README.zh-CN.md"):
        if obsolete_segment_counter in path.read_text(encoding="utf-8"):
            fail(f"visible Segment counter remains in {path.name}: {obsolete_segment_counter}")
if "含主任务，先派发" in skill_text:
    fail("unknown-capacity prompt does not use the unified concurrency plan shape")
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
    "并发：峰值 <leaf peak + 1>（含主任务）｜实际用时：<h时m分s秒>｜子任务累计：<h时m分s秒>｜任务重叠：<h时m分s秒>｜编排空档：<h时m分s秒>",
    "并发计划：<leaf cap + 1> 个任务（含主任务）｜测量：待记录",
    "coordinator's monotonic clock",
    "historical aggregate",
    "Print the returned `parallel_execution_brief` verbatim",
):
    if stable_phrase not in skill_text and stable_phrase not in (ROOT / "references" / "parallel-execution.md").read_text(encoding="utf-8"):
        fail(f"stable distribution contract is missing: {stable_phrase}")
if "A normal successful completion needs no separate model-identity or runtime-verification warning" not in skill_text:
    fail("normal completion suppression rule is missing")
readable_section = skill_text.split("## Readable continuation prompt", 1)
if len(readable_section) != 2:
    fail("readable continuation prompt contract is missing")
readable_section = readable_section[1].split("\n## ", 1)[0]
for phrase in (
    "继续当前任务：<task segment>",
    "Codex 自动路由｜任务段：<task segment>",
    "<!-- CODEX_ROUTER_INTERNAL",
    "任务已完成，正在恢复原模型并返回结果。",
):
    if phrase not in readable_section:
        fail(f"readable continuation prompt phrase is missing: {phrase}")
if not (
    readable_section.index("继续当前任务：<task segment>")
    < readable_section.index("<!-- CODEX_ROUTER_INTERNAL")
    < readable_section.index("ROUTE_PROJECT_MODELS_ROUTED_TURN=1")
):
    fail("continuation prompt must place readable content before machine fields")
if "Never begin it with `ROUTE_PROJECT_MODELS_*`" not in readable_section:
    fail("machine-first continuation guard is missing")
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
for max_contract in (
    "Use Luna/medium as the mechanical floor",
    "Luna/high for ordinary bounded work",
    "Use Luna/xhigh for large bounded scan/review work",
    "Use Luna/max only for genuinely large deterministic deep work",
    "Terra/high is an explicit latency specialist",
    "Eight automatic lanes",
    "The full model-effort matrix remains available by explicit user override",
    "`max` is the highest automatic single-route effort",
    "Never select `ultra` automatically",
    "disable `dependency-parallel-v1`",
):
    if max_contract not in skill_text:
        fail(f"Luna max routing contract is missing: {max_contract}")
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
    "Create only the executors covered by the current ticket batch",
    "dispatch-ticket-v1",
    "prepare-dispatch",
    "End every Apply chat summary with one concise concurrency line",
    "agent_task_name",
    "并发计划：<effective + coordinator> 个任务（含主任务）",
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
    "observed total slots - coordinator - running tasks",
    "scripts/router_runtime.py begin",
    "Later `finish` and `restore` resolve that state with `route_id + segment_id + attempt_id`",
    "dispatch-ticket-v1",
):
    if invariant not in state_machine:
        fail(f"state-machine invariant is missing: {invariant}")

ledger_text = (ROOT / "scripts" / "model_usage_ledger.py").read_text(encoding="utf-8")
ledger_reference = (ROOT / "references" / "usage-ledger.md").read_text(encoding="utf-8")
if "claim --ledger <path> --route-id <id> --plan-hash <hash> --segment-id <id> --attempt-id <id>" not in ledger_reference:
    fail("usage ledger claim example is missing required immutable identity")
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
    '"visible_peak_concurrency"',
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

for installer_name in ("install.sh", "install.ps1"):
    if not (ROOT / installer_name).is_file():
        fail(f"missing cross-platform installer: {installer_name}")
if not (ROOT / "tests" / "test_installation.py").is_file():
    fail("installer contract test is missing")
installer_tests = subprocess.run(
    [sys.executable, "-m", "unittest", "tests/test_installation.py"],
    cwd=ROOT,
    text=True,
    capture_output=True,
)
if installer_tests.returncode:
    fail(f"installer contract tests failed:\n{installer_tests.stdout}\n{installer_tests.stderr}")

preset_mapping = (ROOT / "references" / "preset-mapping.md").read_text(encoding="utf-8")
parallel_reference = (ROOT / "references" / "parallel-execution.md").read_text(encoding="utf-8")
for contract in ("dependency-parallel-v1", "wait-any", "stop-dispatch-drain-running", "write_scopes", "conflict_keys", "parallelism_source=standard|smart-reduced|user-override", "observed_total_slots", "coordinator_slots", "dispatch-ticket-v1", "agent_task_name", "result inbox", "并发计划：<N> 个任务（含主任务）", "任务重叠", "编排空档", "controlled speedup claim"):
    if contract not in parallel_reference:
        fail(f"parallel execution reference is missing: {contract}")
runtime_text = (ROOT / "scripts" / "router_runtime.py").read_text(encoding="utf-8")
for contract in (
    "def begin", "def finish", "def restore", "def worker_start", "def worker_finish",
    "def prepare_dispatch", "def attach", "dispatch-ticket-v1",
    "canonical_plan", "result_inbox", "continuation_ticket",
    "runtime state cannot be persisted", "_fallback_ledger",
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
for key in (
    "max_is_single_route_effort",
    "ultra_is_separate_orchestration_mode",
    "ultra_requires_explicit_user_enable",
    "ultra_disables_router_parallelism",
    "luna_high_precedes_max_for_moderate_depth",
    "full_matrix_remains_explicit_override_only",
    "luna_medium_is_mechanical_floor",
    "terra_high_is_latency_specialist",
    "chatbench_category_scores_are_proxy_only",
):
    if evidence.get("policy", {}).get(key) is not True:
        fail(f"benchmark evidence policy is missing: {key}")
if evidence.get("policy", {}).get("automatic_lane_count") != 8:
    fail("benchmark evidence automatic lane count must be eight")
if len(evidence.get("routing_lanes", {})) != 8:
    fail("benchmark evidence must expose exactly eight automatic lanes")
if len(evidence.get("sources", [])) < 11:
    fail("benchmark evidence does not contain enough attributable sources")
if len(evidence.get("effort_profiles", {}).get("metrics", [])) < 18:
    fail("benchmark evidence effort matrix is incomplete")
if len(evidence.get("cursorbench_3_2", {}).get("results", [])) != 15:
    fail("CursorBench GPT-5.6 effort matrix is incomplete")
if len(evidence.get("chatbench_v0_2_0", {}).get("coding_proxy_results", [])) != 14:
    fail("ChatBench proxy matrix is incomplete")
if "GPT-5.5" not in (ROOT / "references" / "benchmark-evidence.md").read_text(encoding="utf-8"):
    fail("benchmark evidence report is missing the GPT-5.5 comparison")

models = {"sol": "gpt-5.6-sol", "terra": "gpt-5.6-terra", "luna": "gpt-5.6-luna"}
router_count = 0
executor_count = 0
for tier, model in models.items():
    for effort in ("low", "medium", "high", "xhigh", "max"):
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
        instructions = executor.get("developer_instructions", "")
        if "dispatch-ticket-v1" not in instructions or "ROUTE_PROJECT_MODELS_EXECUTOR=1" not in instructions:
            fail(f"executor ticket/legacy guard is missing: {executor_name}")
        if not all(field in instructions for field in ("route_id", "segment_id", "attempt_id")) or "do not plan, route, advance" not in instructions:
            fail(f"executor segment guard is missing: {executor_name}")
        if f"`{executor.get('name')}`" not in preset_mapping:
            fail(f"executor preset mapping is missing: {executor_name}")
        executor_count += 1

if router_count != 15 or executor_count != 15:
    fail(f"expected 15 router and 15 executor presets, found {router_count} and {executor_count}")
if list((ROOT / "codex-agents").glob("*ultra*.toml")):
    fail("Ultra must remain explicit and must not have a Router or executor preset")

legacy_presets = list((ROOT / "codex-agents").glob("project-model-*.toml"))
if legacy_presets:
    fail(f"legacy preset files remain: {legacy_presets}")

readme_text = (ROOT / "README.md").read_text(encoding="utf-8")
if "https://github.com/orange-the-weak/codex-auto-model-router" not in readme_text:
    fail("README install URL does not match the current repository remote")

release_candidates = subprocess.run(
    ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
    cwd=ROOT,
    text=True,
    capture_output=True,
    check=True,
).stdout.splitlines()
local_home_marker = "/Users/" + "yumingcheng/"
for relative in release_candidates:
    if relative.startswith("benchmarks/gpt56-matrix/results/") and relative != "benchmarks/gpt56-matrix/results/.gitkeep":
        fail(f"private benchmark result is a release candidate: {relative}")
    if relative.startswith("docs/xiaohongshu-launch-post/"):
        fail(f"unrelated launch content is a release candidate: {relative}")
    if relative in ("README 2.md", "README.zh-CN 2.md"):
        fail(f"duplicate top-level README is a release candidate: {relative}")
    path = ROOT / relative
    if path.is_file() and local_home_marker in path.read_text(encoding="utf-8", errors="ignore"):
        fail(f"local absolute path is exposed in release candidate: {relative}")

for forbidden in ("s" + "k-" + "live", "BEGIN " + "PRIVATE KEY", "api" + "_key"):
    for relative in release_candidates:
        path = ROOT / relative
        if (
            path.is_file()
            and path.suffix != ".pyc"
            and forbidden in path.read_text(encoding="utf-8", errors="ignore")
        ):
            fail(f"possible secret marker {forbidden!r} in {path}")

print("distribution OK: skill metadata, UI metadata, 15 router presets, 15 executor presets, no obvious secrets")
