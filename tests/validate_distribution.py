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
if "Codex 自动路由｜任务：<name>｜建议：<model>/<effort>｜执行：<当前主模型|子智能体 model/effort>" not in skill_text:
    fail("visible routing protocol is missing")
if "Codex auto route | Task: <name> | Recommendation: <model>/<effort> | Execution: <current coordinator|model/effort leaf agent>" not in skill_text:
    fail("English visible routing protocol is missing")
if "in the language of the user's current request" not in skill_text:
    fail("routing notices do not follow the current request language")
for obsolete_segment_counter in (
    "Segment <index>/<total>",
    "Segment 1/1",
    "Segment 1/3",
):
    for path in (ROOT / "SKILL.md", ROOT / "README.md", ROOT / "README.zh-CN.md"):
        if obsolete_segment_counter in path.read_text(encoding="utf-8"):
            fail(f"visible Segment counter remains in {path.name}: {obsolete_segment_counter}")
for default_path_contract in (
    "Use the default fail-open benefit-gated path",
    "router_lite.py decide",
    "Pass `--no-subagents` only when the user explicitly disables child agents",
    "automatically create or reuse a model-specific leaf agent",
    "Call `router_lite.py plan` and collaboration lifecycle tools only",
    "recommended route as actual model use",
    "The coordinator never changes its own model",
    "no Restore step",
    "## Direct tool concurrency",
    "## Automatic benefit-gated subagent mode",
    "within 15 seconds",
    "Treat every ledger error as a non-blocking warning",
    "## Strict compatibility mode",
    "Never silently enter strict mode",
):
    if default_path_contract not in skill_text:
        fail(f"default routing contract is missing: {default_path_contract}")
for distribution_text, label in (
    (skill_text, "SKILL.md"),
    ((ROOT / "README.md").read_text(encoding="utf-8"), "README.md"),
    ((ROOT / "README.zh-CN.md").read_text(encoding="utf-8"), "README.zh-CN.md"),
    ((ROOT / "references" / "parallel-execution.md").read_text(encoding="utf-8"), "parallel-execution.md"),
):
    if "worker_time_compression_percent" in distribution_text:
        fail(f"obsolete compression wording is exposed in {label}")
readme_text = (ROOT / "README.md").read_text(encoding="utf-8")
readme_zh_text = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
for lifecycle_contract in (
    "The recommendation does not switch the current task's model",
    "creates no child-agent cards",
    "no additional user permission prompt is required",
    "`completed` is terminal",
    "reuse never crosses user requests",
    "`--no-subagents` is the explicit opt-out",
    "Visible routing notices follow the language of the current request",
    "interrupts every optional or otherwise unneeded child still genuinely `running`",
    "no collaboration operation for deleting completed child-agent UI history",
):
    if lifecycle_contract not in readme_text:
        fail(f"English executor lifecycle contract is missing: {lifecycle_contract}")
for lifecycle_contract in (
    "Router 不能主动切换它们",
    "不会产生独立推理流或子智能体卡片",
    "不需要额外询问用户许可",
    "`completed` 是正常终态",
    "复用也不会跨用户请求",
    "`--no-subagents` 是明确退出开关",
    "所有可见路由提示都会跟随当前请求的语言",
    "中断所有仍真实 `running` 但已非必需的子智能体",
    "没有删除已完成子智能体 UI 历史的操作",
):
    if lifecycle_contract not in readme_zh_text:
        fail(f"Chinese executor lifecycle contract is missing: {lifecycle_contract}")
for phrase in (
    "Automatic model routing", "Recommendation differs and route benefit clears overhead",
    "Low-overhead concurrency", "run concurrently in the coordinator",
    "What changed in v0.2",
):
    if phrase not in readme_text:
        fail(f"English routing overview or release note is missing: {phrase}")
for phrase in (
    "自动选择模型", "建议不同且路由收益超过开销",
    "低开销并发", "在主线程中并发",
    "v0.2 更新重点",
):
    if phrase not in readme_zh_text:
        fail(f"Chinese routing overview or release note is missing: {phrase}")
for model_contract in (
    "Luna/medium", "Luna/high", "Luna/xhigh", "Luna/max",
    "Terra/high", "Sol/low", "Sol/medium", "Sol/high", "Sol/xhigh",
    "Never select Ultra automatically",
    "GPT-5.5 is allowed only after the complete GPT-5.6 family is proven unavailable",
):
    if model_contract not in skill_text:
        fail(f"model gradient is missing: {model_contract}")
for parallel_contract in (
    "## Direct tool concurrency", "same coordinator model and effort",
    "## Automatic benefit-gated subagent mode", "does not need to grant separate permission",
    "--no-subagents", "roughly 90 seconds each",
    "non-overlapping write scopes", "verified free worker capacity",
    "both 30 seconds and 15%", "Order ready tasks longest-first",
    "at most four total tasks including the coordinator",
    "Do not create a waiting agent queue", "Leaf agents may not delegate",
    "Never claim speedup without a controlled serial comparison",
):
    if parallel_contract not in skill_text:
        fail(f"parallel contract is missing: {parallel_contract}")
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
    "def prepare_route", "def begin", "def finish", "def restore", "def worker_start", "def worker_finish",
    "def prepare_dispatch", "def attach", "dispatch-ticket-v1",
    "canonical_plan", "result_inbox", "continuation_ticket",
    "runtime state cannot be persisted", "_fallback_ledger",
    "validate_fast_envelope", "segment_claim", "routing_efficiency", "context_capsule",
):
    if contract not in runtime_text:
        fail(f"combined Router runtime contract is missing: {contract}")
lite_text = (ROOT / "scripts" / "router_lite.py").read_text(encoding="utf-8")
for contract in (
    'LITE_PROTOCOL = "router-lite-v2"', '"action": "local"',
    '"action": "parallel" if parallel', '"restore_required": False',
    '"fail_open": True', 'startup_failure_takeover_seconds',
    '"route-benefit-not-proven"', '"subagent_policy"',
    '"automatic-benefit-gated"', '"automatic_creation": not disabled',
    '"automatic_reuse": not disabled', '"user_permission_required": False',
    '"delegation_gate"', '"tool_concurrency"',
    '"creates_child_agents": False', '"same_model_and_effort": True',
    '"--no-subagents"', '"--allow-subagents"',
    'ledger-best-effort', 'DEFAULT_MAX_TOTAL_TASKS = 4',
    'DEFAULT_MIN_PARALLEL_SECONDS = 90',
    'DEFAULT_MIN_DELEGATE_SECONDS = 90',
    'DEFAULT_FRESH_EXECUTOR_SECONDS = 40',
    'DEFAULT_REUSED_EXECUTOR_SECONDS = 10',
    'DEFAULT_MAX_REUSES_PER_EXECUTOR = 2',
    'DEFAULT_SPAWN_STAGGER_SECONDS = 8',
    'DEFAULT_MIN_PARALLEL_SAVINGS_RATIO = 0.15',
    '"startup-aware-local-fast-path"', '"dispatch_now"',
    '"executor_lanes"', '"reuse_policy"', '"same-request-only"',
    'result["action"] = "reuse"', '"reuse_target"',
    '"--reuse-candidates-json"', '"--request-id"', '"--repository"',
    '"--permissions-fingerprint"', '"--sandbox-fingerprint"',
    '"repository_realpath"', '"fresh_context_required"',
    'def executor_lifecycle_decision(',
    '"terminal_states"', '"interruptible_state"',
    '"completion_authority"', '"refresh_status_after_wait_update"',
    '"refresh_status_before_parent_final"', '"wait_timeout_is_stall"',
    '"parent_final_requires_no_required_running_executors"',
    '"parent_final_requires_all_owned_children_terminal"',
    '"parent_final_stops_new_dispatch"',
    '"parent_final_disables_reuse"',
    '"parent_final_clears_reuse_registry"',
    '"parent_final_interrupts_unneeded_running_children"',
    '"parent_final_interrupts_optional_stragglers"',
    '"parent_final_rechecks_status_after_interrupt"',
    '"parent_final_scope": "current-task-tree-only"',
    '"delete_child_agent_ui_history_supported": False',
    '"on_stale_parent_running_after_child_complete"',
    '"stalled_after_seconds"', '"activity_resets_stall_timer"',
    '"on_stall"', '"on_completed"',
    '"clear_reuse_registry_on_new_request"',
    '"delete_or_interrupt_completed_on_new_request"',
    '"protocol_only": True',
):
    if contract not in lite_text:
        fail(f"routing implementation contract is missing: {contract}")
for misleading_lifecycle_contract in (
    '"max_wait_seconds"', '"terminate_idle_on_request_end"',
    '"terminate_when_reuse_ineligible"',
):
    if misleading_lifecycle_contract in lite_text:
        fail(
            "misleading executor lifecycle contract remains: "
            f"{misleading_lifecycle_contract}"
        )
for contract in (
    "35.5–39.6 seconds", "2.7–9.4 seconds",
    "Two follow-ups per executor", "recheck identity, live state, and ownership",
    'boolean "same" claims are not identity',
):
    if contract not in parallel_reference:
        fail(f"executor reuse reference is missing: {contract}")
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
    "luna_large_lanes_allow_normal_consequence",
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
        if "Perform only Assess or Retune" not in data.get("developer_instructions", "") or "recursive delegation" not in data.get("developer_instructions", ""):
            fail(f"router subagent scope guard is missing: {name}")
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
        for phrase in (
            "Accept a direct routed task", "do not require route IDs, hashes, tickets",
            "do not route or delegate", "Treat the task capsule as self-contained",
            "immediately send exactly one final reply", "do not continue validation",
            "do not request approval", "return a limited result",
            "Never create a top-level Codex task",
        ):
            if phrase not in instructions:
                fail(f"executor routing guard is missing from {executor_name}: {phrase}")
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
