#!/usr/bin/env python3
"""Fast, fail-open model advice for normal Codex work.

The default path deliberately has no plan hash, cursor, claim, Restore, or
cross-task runtime state. The coordinator may run independent tools directly
or use a bounded leaf executor when route-fit benefit clears its overhead.
"""

import argparse
import json
import os
import sys
import time
import tomllib
from pathlib import Path
from pathlib import PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent))
import model_usage_ledger as ledger
import route_policy as policy


LITE_PROTOCOL = "router-lite-v2"
SKILL_NAME = "codex-auto-model-router"
PROJECT_EXIT_BEGIN = "# BEGIN codex-auto-model-router project exit"
PROJECT_EXIT_END = "# END codex-auto-model-router project exit"
DEFAULT_MAX_TOTAL_TASKS = 4
DEFAULT_MIN_PARALLEL_SECONDS = 90
DEFAULT_MIN_DELEGATE_SECONDS = 90
DEFAULT_FRESH_EXECUTOR_SECONDS = 40
DEFAULT_REUSED_EXECUTOR_SECONDS = 10
# Backward-compatible name for callers that still pass the old startup prior.
DEFAULT_EXECUTOR_STARTUP_SECONDS = DEFAULT_FRESH_EXECUTOR_SECONDS
DEFAULT_COORDINATION_SECONDS = 10
DEFAULT_SPAWN_STAGGER_SECONDS = 8
DEFAULT_AGGREGATION_SECONDS = 10
DEFAULT_MIN_PARALLEL_SAVINGS_SECONDS = 30
DEFAULT_MIN_PARALLEL_SAVINGS_RATIO = 0.15
DEFAULT_MAX_RECOVERY_ATTEMPTS = 1
DEFAULT_MAX_REUSES_PER_EXECUTOR = 2
DEFAULT_EXECUTOR_WAIT_POLL_SECONDS = 30
DEFAULT_EXECUTOR_STALLED_AFTER_SECONDS = 600

EXECUTOR_TERMINAL_STATES = ("completed", "failed", "interrupted")
EXECUTOR_INTERRUPTIBLE_STATE = "running"

EFFORT_RANK = {"low": 0, "medium": 1, "high": 2, "xhigh": 3, "max": 4}

AGENT_TYPES = {
    ("gpt-5.6-sol", "low"): "codex_auto_model_executor_low",
    ("gpt-5.6-sol", "medium"): "codex_auto_model_executor",
    ("gpt-5.6-sol", "high"): "codex_auto_model_executor_high",
    ("gpt-5.6-sol", "xhigh"): "codex_auto_model_executor_xhigh",
    ("gpt-5.6-sol", "max"): "codex_auto_model_executor_max",
    ("gpt-5.6-terra", "low"): "codex_auto_model_executor_terra_low",
    ("gpt-5.6-terra", "medium"): "codex_auto_model_executor_terra",
    ("gpt-5.6-terra", "high"): "codex_auto_model_executor_terra_high",
    ("gpt-5.6-terra", "xhigh"): "codex_auto_model_executor_terra_xhigh",
    ("gpt-5.6-terra", "max"): "codex_auto_model_executor_terra_max",
    ("gpt-5.6-luna", "low"): "codex_auto_model_executor_luna_low",
    ("gpt-5.6-luna", "medium"): "codex_auto_model_executor_luna",
    ("gpt-5.6-luna", "high"): "codex_auto_model_executor_luna_high",
    ("gpt-5.6-luna", "xhigh"): "codex_auto_model_executor_luna_xhigh",
    ("gpt-5.6-luna", "max"): "codex_auto_model_executor_luna_max",
}


class RouterArgumentError(ValueError):
    """Argument errors that must fall back to local execution."""


class FailOpenArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise RouterArgumentError(message)


def _risk_value(value):
    return {"medium": "normal"}.get(value, value)


def _size_value(value):
    return {"small": "normal", "medium": "normal"}.get(value, value)


def _project_root(value=None):
    candidate = Path(value or Path.cwd()).expanduser().resolve()
    if not candidate.is_dir():
        raise ValueError("repository must be an existing directory")
    for directory in (candidate, *candidate.parents):
        if (directory / ".git").exists():
            return directory
    return candidate


def _default_skill_path():
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    installed = codex_home / "skills" / SKILL_NAME / "SKILL.md"
    if installed.is_file():
        return installed.resolve()
    return (Path(__file__).resolve().parents[1] / "SKILL.md").resolve()


def _normalized_skill_path(value, config_path):
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = config_path.parent / path
    path = path.resolve()
    return path if path.name == "SKILL.md" else path / "SKILL.md"


def _project_skill_state(repository=None, skill_path=None):
    root = _project_root(repository)
    config_path = root / ".codex" / "config.toml"
    target = Path(skill_path or _default_skill_path()).expanduser().resolve()
    if target.name != "SKILL.md":
        target /= "SKILL.md"
    text = config_path.read_text(encoding="utf-8") if config_path.is_file() else ""
    managed = PROJECT_EXIT_BEGIN in text and PROJECT_EXIT_END in text
    matching_entries = []
    if text.strip():
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            if managed:
                return {
                    "enabled": False,
                    "managed": True,
                    "repository": str(root),
                    "config_path": str(config_path),
                    "skill_path": str(target),
                    "warning": f"project-config-invalid:{type(exc).__name__}",
                }
            raise ValueError("project .codex/config.toml is invalid") from exc
        entries = data.get("skills", {}).get("config", [])
        if not isinstance(entries, list):
            raise ValueError("project skills.config must be an array")
        matching_entries = [
            entry for entry in entries
            if isinstance(entry, dict)
            and isinstance(entry.get("path"), str)
            and _normalized_skill_path(entry["path"], config_path) == target
        ]
    disabled = managed or any(entry.get("enabled") is False for entry in matching_entries)
    return {
        "enabled": not disabled,
        "managed": managed,
        "repository": str(root),
        "config_path": str(config_path),
        "skill_path": str(target),
        "warning": None,
    }


def _project_disabled_result(state):
    return {
        "protocol": LITE_PROTOCOL,
        "action": "disabled",
        "reason": "project-skill-disabled",
        "execution_reason": "project-skill-disabled",
        "project_skill_enabled": False,
        "project_exit": state,
        "recommended_route": None,
        "agent_type": None,
        "spawn_contract": None,
        "reuse_target": None,
        "restore_required": False,
        "fail_open": True,
    }


def _managed_project_exit_block(skill_path):
    encoded_path = json.dumps(str(Path(skill_path).resolve()), ensure_ascii=False)
    return (
        f"{PROJECT_EXIT_BEGIN}\n"
        "[[skills.config]]\n"
        f"path = {encoded_path}\n"
        "enabled = false\n"
        f"{PROJECT_EXIT_END}\n"
    )


def _write_project_config(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def project_disable(args):
    state = _project_skill_state(args.repository, args.skill_path)
    if state["managed"] or not state["enabled"]:
        result = {**state, "action": "project-disable", "changed": False}
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return
    config_path = Path(state["config_path"])
    existing = config_path.read_text(encoding="utf-8") if config_path.is_file() else ""
    separator = "" if not existing or existing.endswith("\n") else "\n"
    updated = existing + separator + _managed_project_exit_block(state["skill_path"])
    _write_project_config(config_path, updated)
    result = _project_skill_state(state["repository"], state["skill_path"])
    result.update({
        "action": "project-disable",
        "changed": True,
        "takes_effect": "immediately-for-router-commands-and-after-codex-restart-for-skill-loading",
    })
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


def project_enable(args):
    state = _project_skill_state(args.repository, args.skill_path)
    if not state["managed"]:
        result = {**state, "action": "project-enable", "changed": False}
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return
    config_path = Path(state["config_path"])
    text = config_path.read_text(encoding="utf-8")
    start = text.index(PROJECT_EXIT_BEGIN)
    end = text.index(PROJECT_EXIT_END, start) + len(PROJECT_EXIT_END)
    if end < len(text) and text[end] == "\n":
        end += 1
    updated = text[:start] + text[end:]
    if updated and not updated.endswith("\n"):
        updated += "\n"
    _write_project_config(config_path, updated)
    result = _project_skill_state(state["repository"], state["skill_path"])
    result.update({
        "action": "project-enable",
        "changed": True,
        "takes_effect": "immediately-for-router-commands-and-after-codex-restart-for-skill-loading",
    })
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


def project_status(args):
    result = _project_skill_state(args.repository, args.skill_path)
    result.update({"action": "project-status", "changed": False})
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


def _route_is_sufficient(current, selected):
    """Return whether the current GPT-5.6 route is an accepted policy fallback."""
    if current.get("status") != "verified":
        return False
    current_model = current.get("model")
    current_effort = current.get("effort")
    target_model = selected["recommended"]["model"]
    target_effort = selected["recommended"]["effort"]
    if current_model not in policy.MODELS:
        return False
    if current_effort not in EFFORT_RANK or target_effort not in EFFORT_RANK:
        return False
    candidates = [(target_model, target_effort)]
    source = selected["recommended"].get("source", "")
    if source.startswith("benchmark-prior:"):
        lane = source.split(":", 1)[1]
        candidates.extend(policy.LANE_FALLBACK_ROUTES.get(lane, ()))
    return any(
        current_model == model and EFFORT_RANK[current_effort] >= EFFORT_RANK[effort]
        for model, effort in candidates
    )


def _subagent_policy(args):
    """Return the automatic benefit-gated policy with an explicit opt-out."""
    disabled = bool(getattr(args, "no_subagents", False))
    return {
        "mode": "automatic-benefit-gated",
        "allowed": not disabled,
        "automatic_creation": not disabled,
        "automatic_reuse": not disabled,
        "user_permission_required": False,
        "disabled_by_user": disabled,
        # Retained so older wrappers can keep passing the flag while migrating.
        "legacy_allow_flag_seen": bool(getattr(args, "allow_subagents", False)),
    }


def _decision(args, task=None, current=None):
    task = task or {}
    if current is None:
        current = (
            policy.unavailable_current()
            if args.no_runtime_detection
            else policy.detect_current_route(args.sessions_root)
        )
    selected = policy.select_route(
        "apply",
        task_kind=task.get("task_kind", args.task_kind),
        risk=task.get("risk", args.risk),
        size=task.get("size", args.size),
        model_override=task.get("model", args.model),
        effort_override=task.get("effort", args.effort),
        current=current,
        ambiguity=task.get("ambiguity", args.ambiguity),
        coupling=task.get("coupling", args.coupling),
        verification=task.get("verification", args.verification),
        consequence=task.get("consequence", args.consequence),
        prior_failure=task.get("prior_failure", args.prior_failure),
        prior_failure_kind=task.get("prior_failure_kind", args.prior_failure_kind),
        latency_priority=task.get("latency_priority", args.latency_priority),
    )
    model = selected["recommended"]["model"]
    effort = selected["recommended"]["effort"]
    explicit_route = bool(task.get("model", args.model) or task.get("effort", args.effort))
    task_kind = task.get("task_kind", args.task_kind)
    risk = task.get("risk", args.risk)
    size = task.get("size", args.size)
    verification = task.get("verification", args.verification)
    consequence = task.get("consequence", args.consequence)
    tool_bound = bool(task.get("tool_bound", getattr(args, "tool_bound", False)))
    estimated_seconds = task.get("estimated_seconds", getattr(args, "estimated_seconds", None))
    if estimated_seconds is not None:
        estimated_seconds = int(estimated_seconds)
        if estimated_seconds < 0:
            raise ValueError("estimated seconds cannot be negative")
    min_delegate_seconds = int(getattr(args, "min_delegate_seconds", DEFAULT_MIN_DELEGATE_SECONDS))
    if min_delegate_seconds < 0:
        raise ValueError("minimum delegate seconds cannot be negative")
    current_is_gpt56 = str(current.get("model", "")).startswith("gpt-5.6-")
    current_is_sufficient = _route_is_sufficient(current, selected)
    subagent_policy = _subagent_policy(args)
    subagents_allowed = subagent_policy["allowed"]
    short_work = estimated_seconds is not None and estimated_seconds < min_delegate_seconds
    local_cost_fast_path = (
        current.get("status") == "verified"
        and current_is_gpt56
        and not explicit_route
        and not task.get("prior_failure", args.prior_failure)
        and risk != "high"
        and consequence != "high"
        and current_is_sufficient
        and (
            (task_kind == "mechanical" and size == "tiny")
            or (tool_bound and verification in (None, "deterministic"))
            or short_work
        )
    )
    matched = current.get("status") == "verified" and (
        current.get("model"), current.get("effort")
    ) == (model, effort)
    ultra = effort == "ultra"
    route_differs = not matched
    route_benefit_clear = (
        route_differs
        and (
            explicit_route
            or (
                current.get("status") == "verified"
                and not current_is_sufficient
            )
            or not short_work
        )
    )
    if explicit_route:
        benefit_basis = "explicit-route-choice"
    elif current.get("status") == "verified" and not current_is_sufficient:
        benefit_basis = "current-route-insufficient"
    elif not short_work:
        benefit_basis = "route-fit-over-task-duration"
    else:
        benefit_basis = "startup-cost-not-amortized"
    if local_cost_fast_path:
        action = "local"
        actual_model = current["model"]
        actual_effort = current["effort"]
        if task_kind == "mechanical" and size == "tiny":
            reason = "tiny-local-fast-path"
        elif tool_bound and verification in (None, "deterministic"):
            reason = "tool-bound-local-fast-path"
        else:
            reason = "startup-aware-local-fast-path"
    else:
        if ultra:
            action = "native-ultra"
            reason = selected["recommended"]["source"]
        elif matched:
            action = "local"
            reason = "already-matched"
        elif subagents_allowed and route_benefit_clear:
            action = "delegate"
            reason = selected["recommended"]["source"]
        elif not subagents_allowed:
            action = "local"
            reason = "subagents-disabled-by-user"
        else:
            action = "local"
            reason = "route-benefit-not-proven"
        if action == "local":
            actual_model = (
                current.get("model") if current.get("status") == "verified" else None
            )
            actual_effort = (
                current.get("effort") if current.get("status") == "verified" else None
            )
        else:
            actual_model = model
            actual_effort = effort
    agent_type = None if action != "delegate" else AGENT_TYPES.get((model, effort))
    lifecycle_contract = _lifecycle_contract(args)
    if action == "local":
        if reason == "already-matched":
            execution_reason = "current-route-already-matches"
        elif reason == "subagents-disabled-by-user":
            execution_reason = "main-thread-model-fixed-and-subagents-disabled"
        else:
            execution_reason = (
                "main-model-fixed-leaf-startup-cost-exceeds-benefit"
            )
    elif action == "delegate":
        execution_reason = "model-specific-leaf-benefit-clears-overhead"
    else:
        execution_reason = reason
    return {
        "protocol": LITE_PROTOCOL,
        "action": action,
        "model": actual_model,
        "effort": actual_effort,
        "agent_type": agent_type,
        "spawn_contract": (
            None if agent_type is None else {
                "agent_type": agent_type,
                "fork_turns": "none",
                "retry_on_contract_error": False,
                "request_escalated_permissions": False,
                "return_limited_result_on_permission_boundary": True,
                "finalize_immediately_after_acceptance": True,
            }
        ),
        "recommended_route": {"model": model, "effort": effort},
        "reason": reason,
        "execution_reason": execution_reason,
        "current": current,
        "native_ultra": ultra,
        "subagent_policy": subagent_policy,
        "delegation_gate": {
            "automatic": True,
            "user_permission_required": False,
            "benefit_clear": route_benefit_clear,
            "basis": benefit_basis,
            "estimated_seconds": estimated_seconds,
            "minimum_task_seconds": min_delegate_seconds,
            "fresh_executor_seconds": DEFAULT_FRESH_EXECUTOR_SECONDS,
        },
        "tool_concurrency": {
            "allowed": True,
            "creates_child_agents": False,
            "same_model_and_effort": True,
            "scope": "independent-safe-tool-or-process-calls",
        },
        "recommended_route_is_advisory": action == "local" and not matched,
        "user_model_switch_needed": (
            action == "local" and not current_is_sufficient
        ),
        "restore_required": False,
        "fail_open": True,
        "startup_failure_takeover_seconds": 15,
        "lifecycle_contract": lifecycle_contract,
        "estimated_seconds": estimated_seconds,
        "delegate_break_even_seconds": min_delegate_seconds,
        "reuse_target": None,
        "record_contract": {
            "required_after_execution": action == "delegate",
            "best_effort": True,
        },
    }


def _lifecycle_contract(args):
    poll_seconds = int(getattr(
        args, "executor_wait_poll_seconds", DEFAULT_EXECUTOR_WAIT_POLL_SECONDS
    ))
    stalled_after_seconds = int(getattr(
        args, "executor_stalled_after_seconds",
        DEFAULT_EXECUTOR_STALLED_AFTER_SECONDS,
    ))
    if poll_seconds <= 0:
        raise ValueError("executor wait poll seconds must be positive")
    if stalled_after_seconds <= 0 or poll_seconds > stalled_after_seconds:
        raise ValueError(
            "executor stalled threshold must be at least the poll interval"
        )
    return {
        "protocol_only": True,
        "executor": {
            "finalize_immediately_after_acceptance": True,
            "no_post_acceptance_validation_commentary_or_parent_wait": True,
            "request_escalated_permissions": False,
            "permission_boundary_result": "limited",
        },
        "coordinator": {
            "wait_poll_seconds": poll_seconds,
            "terminal_states": list(EXECUTOR_TERMINAL_STATES),
            "interruptible_state": EXECUTOR_INTERRUPTIBLE_STATE,
            "completion_authority": ["child-task-complete", "live-agent-status"],
            "refresh_status_after_wait_update": True,
            "refresh_status_before_parent_final": True,
            "wait_timeout_is_stall": False,
            "parent_final_requires_no_required_running_executors": True,
            "parent_final_requires_all_owned_children_terminal": True,
            "parent_final_stops_new_dispatch": True,
            "parent_final_disables_reuse": True,
            "parent_final_clears_reuse_registry": True,
            "parent_final_interrupts_unneeded_running_children": True,
            "parent_final_interrupts_optional_stragglers": True,
            "parent_final_rechecks_status_after_interrupt": True,
            "parent_final_scope": "current-task-tree-only",
            "delete_child_agent_ui_history_supported": False,
            "stalled_after_seconds": stalled_after_seconds,
            "activity_resets_stall_timer": True,
            "activity_sources": ["reasoning", "tool", "test"],
            "on_stale_parent_running_after_child_complete": "reconcile-completed",
            "on_stall": "refresh-status-then-suggest-interrupt-and-finish-locally",
            "on_completed": "accept-result-and-reuse-only-before-parent-finalization",
            "clear_reuse_registry_on_new_request": True,
            "delete_or_interrupt_completed_on_new_request": False,
        },
    }


def executor_lifecycle_decision(
    state,
    *,
    now_seconds,
    last_activity_seconds=None,
    activity_at_seconds=None,
    task_complete_observed=False,
    stalled_after_seconds=DEFAULT_EXECUTOR_STALLED_AFTER_SECONDS,
):
    """Return coordinator advice without invoking collaboration tools.

    Reasoning, tool, and test progress are represented by ``activity_at_seconds``.
    The latest observed activity becomes the new stall-timer origin.
    """
    if not isinstance(state, str) or not state:
        raise ValueError("executor state must be a non-empty string")
    if not isinstance(task_complete_observed, bool):
        raise ValueError("task complete observation must be boolean")
    now = float(now_seconds)
    threshold = float(stalled_after_seconds)
    if threshold <= 0:
        raise ValueError("executor stalled threshold must be positive")

    last_activity = (
        None if last_activity_seconds is None else float(last_activity_seconds)
    )
    if activity_at_seconds is not None:
        activity_at = float(activity_at_seconds)
        if activity_at > now:
            raise ValueError("executor activity cannot be in the future")
        last_activity = (
            activity_at if last_activity is None else max(last_activity, activity_at)
        )

    reported_state = state
    if task_complete_observed:
        state = "completed"

    if state in EXECUTOR_TERMINAL_STATES:
        if state == "completed" and reported_state != "completed":
            decision = "reconcile-completed"
        else:
            decision = "accept-completed" if state == "completed" else "accept-terminal"
        return {
            "state": state,
            "reported_state": reported_state,
            "decision": decision,
            "should_interrupt": False,
            "last_activity_seconds": last_activity,
            "stalled_for_seconds": None,
            "same_request_reuse": (
                "prequalify" if state == "completed" else "ineligible"
            ),
        }

    if state != EXECUTOR_INTERRUPTIBLE_STATE:
        return {
            "state": state,
            "reported_state": reported_state,
            "decision": "observe",
            "should_interrupt": False,
            "last_activity_seconds": last_activity,
            "stalled_for_seconds": None,
            "same_request_reuse": "ineligible",
        }
    if last_activity is None:
        raise ValueError("running executor requires last activity time")
    if last_activity > now:
        raise ValueError("executor last activity cannot be in the future")

    stalled_for = now - last_activity
    stalled = stalled_for >= threshold
    return {
        "state": state,
        "reported_state": reported_state,
        "decision": "suggest-interrupt" if stalled else "continue-waiting",
        "should_interrupt": stalled,
        "last_activity_seconds": last_activity,
        "stalled_for_seconds": stalled_for,
        "same_request_reuse": "ineligible",
    }


def decide(args):
    project_state = _project_skill_state(getattr(args, "repository", None))
    if not project_state["enabled"]:
        print(json.dumps(
            _project_disabled_result(project_state),
            ensure_ascii=False,
            sort_keys=True,
        ))
        return
    result = _decision(args)
    max_reuses = int(getattr(args, "max_executor_reuses", DEFAULT_MAX_REUSES_PER_EXECUTOR))
    if not 0 <= max_reuses <= 3:
        raise ValueError("max executor reuses must be from 0 to 3")
    subagents_allowed = result["subagent_policy"]["allowed"]
    if subagents_allowed:
        candidates, rejected = _reuse_candidates(
            getattr(args, "reuse_candidates_json", "[]"),
            max_reuses,
            _reuse_identity(args),
        )
        exclusions = _task_reuse_exclusions({}, args)
    else:
        candidates, rejected = [], []
        exclusions = ["subagents_disabled_by_user"]
    reused_seconds = int(getattr(
        args, "reused_executor_seconds", DEFAULT_REUSED_EXECUTOR_SECONDS
    ))
    if reused_seconds < 0:
        raise ValueError("reused executor seconds cannot be negative")
    recommended_differs = (
        result["current"].get("model"), result["current"].get("effort")
    ) != (
        result["recommended_route"]["model"],
        result["recommended_route"]["effort"],
    )
    reuse_beats_local_startup = (
        result["action"] == "local"
        and result["reason"] == "startup-aware-local-fast-path"
        and recommended_differs
        and (
            result["estimated_seconds"] is None
            or result["estimated_seconds"] >= reused_seconds
        )
    )
    if (
        subagents_allowed
        and (result["action"] == "delegate" or reuse_beats_local_startup)
        and not exclusions
    ):
        candidate = next((
            item for item in candidates
            if (item["model"], item["effort"]) == (
                result["recommended_route"]["model"],
                result["recommended_route"]["effort"],
            )
        ), None)
        if candidate is not None:
            result["action"] = "reuse"
            result["reuse_target"] = candidate["agent_task_name"]
            result["reason"] = "safe-same-request-reuse"
            result["execution_reason"] = "compatible-leaf-reuse-clears-overhead"
            result["reused_executor_seconds"] = reused_seconds
            result["spawn_contract"] = None
            result["record_contract"]["required_after_execution"] = True
    result["reuse_policy"] = {
        "enabled": subagents_allowed,
        "max_followups_per_executor": max_reuses if subagents_allowed else 0,
        "eligible_candidates": [item["agent_task_name"] for item in candidates],
        "rejected_candidates": rejected,
        "task_exclusions": exclusions,
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


def _task_name(task, index):
    value = task.get("task_name") or task.get("segment_id")
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"parallel task {index + 1} requires a content-based task_name")
    value = value.strip().replace("-", "_")
    if not policy.AGENT_TASK_NAME_RE.fullmatch(value):
        raise ValueError(f"invalid task_name: {value}")
    return value


def _scope(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("write scopes must be non-empty relative paths")
    normalized = PurePosixPath(value.replace("\\", "/"))
    if normalized.is_absolute() or ".." in normalized.parts:
        raise ValueError("write scopes must stay inside the repository")
    return normalized.parts


def _scopes_overlap(left, right):
    return left[:len(right)] == right or right[:len(left)] == left


def _route_key(item):
    route = item["route"]
    recommended = route.get("recommended_route") or route
    return recommended["model"], recommended["effort"]


def _activation_cost(lane, item, fresh_seconds, reused_seconds, max_reuses):
    if (
        lane["route"] == _route_key(item)
        and lane["followups"] < max_reuses
        and lane["reuse_eligible"]
        and item["reuse_eligible"]
    ):
        return "reused", reused_seconds
    return "fresh", fresh_seconds


def _reuse_identity(args):
    request_id = getattr(args, "request_id", None)
    repository = getattr(args, "repository", None)
    permissions = getattr(args, "permissions_fingerprint", None)
    sandbox = getattr(args, "sandbox_fingerprint", None)
    if not all((request_id, repository, permissions, sandbox)):
        return None
    return {
        "request_id": str(request_id),
        "repository_realpath": os.path.realpath(repository),
        "permissions_fingerprint": str(permissions),
        "sandbox_fingerprint": str(sandbox),
    }


def _task_reuse_exclusions(task, args):
    exclusions = []
    if bool(task.get("fresh_context_required", getattr(args, "fresh_context_required", False))):
        exclusions.append("fresh_context_required")
    if bool(task.get("external_action", getattr(args, "external_action", False))):
        exclusions.append("external_action")
    if bool(task.get("sensitive_data", getattr(args, "sensitive_data", False))):
        exclusions.append("sensitive_data")
    if task.get("risk", args.risk) == "high" or task.get(
        "consequence", args.consequence
    ) == "high":
        exclusions.append("high_consequence")
    if task.get("prior_failure", args.prior_failure):
        exclusions.append("prior_failure")
    return exclusions


def _reuse_candidates(value, max_reuses, identity):
    try:
        candidates = json.loads(value or "[]")
    except json.JSONDecodeError as exc:
        raise ValueError(f"reuse candidates must be valid JSON: {exc}") from exc
    if not isinstance(candidates, list) or any(not isinstance(item, dict) for item in candidates):
        raise ValueError("reuse candidates must be an array of objects")
    normalized = []
    rejected = []
    seen = set()
    for item in candidates:
        name = item.get("agent_task_name")
        if not isinstance(name, str) or not policy.AGENT_TASK_NAME_RE.fullmatch(name):
            raise ValueError("reuse candidate requires a content-based agent_task_name")
        if name in seen:
            raise ValueError("reuse candidate names must be unique")
        model = policy.normalize_model(item.get("model"))
        effort = policy.normalize_effort(item.get("effort"))
        if model not in policy.MODELS or effort not in EFFORT_RANK:
            raise ValueError("reuse candidate requires a supported GPT-5.6 route")
        followups_used = item.get("followups_used", 0)
        if not isinstance(followups_used, int) or followups_used < 0:
            raise ValueError("reuse candidate followups_used must be a non-negative integer")
        reasons = []
        for field in ("idle", "accepted", "ownership_released"):
            if item.get(field) is not True:
                reasons.append(field)
        for field in (
            "pending_tool_call", "external_action", "sensitive_data", "interrupted",
            "failed", "prior_failure", "fresh_context_required", "deployment",
            "authentication", "high_consequence",
        ):
            if item.get(field) is not False:
                reasons.append(field)
        if identity is None:
            reasons.append("identity_unavailable")
        else:
            for field, expected in identity.items():
                actual = item.get(field)
                if field == "repository_realpath" and isinstance(actual, str):
                    actual = os.path.realpath(actual)
                if actual != expected:
                    reasons.append(field)
        if followups_used >= max_reuses:
            reasons.append("reuse_limit")
        candidate = {
            "agent_task_name": name,
            "model": model,
            "effort": effort,
            "followups_used": followups_used,
        }
        if reasons:
            rejected.append({**candidate, "reasons": reasons})
        else:
            normalized.append(candidate)
        seen.add(name)
    return normalized, rejected


def _executor_schedule(
    items, workers, coordination_seconds, spawn_stagger_seconds,
    fresh_seconds, reused_seconds, max_reuses, reuse_candidates,
):
    """Build a deterministic route-aware worker schedule for planning only."""
    ordered = sorted(
        items,
        key=lambda item: (-item["estimated_seconds"], item["task_name"]),
    )
    lanes = []
    unused_candidates = list(reuse_candidates)
    for item in ordered:
        if len(lanes) < workers:
            lane_index = len(lanes)
            candidate = next((
                value for value in unused_candidates
                if (value["model"], value["effort"]) == _route_key(item)
            ), None) if max_reuses and item["reuse_eligible"] else None
            if candidate is not None:
                unused_candidates.remove(candidate)
            activation = "reused" if candidate else "fresh"
            activation_seconds = reused_seconds if candidate else fresh_seconds
            activation_start = coordination_seconds + lane_index * spawn_stagger_seconds
            finish = activation_start + activation_seconds + item["estimated_seconds"]
            lanes.append({
                "lane": lane_index + 1,
                "route": _route_key(item),
                "available_seconds": finish,
                "followups": candidate["followups_used"] + 1 if candidate else 0,
                "reuse_eligible": item["reuse_eligible"],
                "agent_task_name": (
                    candidate["agent_task_name"] if candidate else item["task_name"]
                ),
                "tasks": [{
                    "task_name": item["task_name"],
                    "activation": activation,
                    "activation_seconds": activation_seconds,
                    "reuse_target": candidate["agent_task_name"] if candidate else None,
                    "finish_seconds": finish,
                }],
            })
            continue

        candidates = []
        for lane in lanes:
            activation, seconds = _activation_cost(
                lane, item, fresh_seconds, reused_seconds, max_reuses
            )
            finish = lane["available_seconds"] + seconds + item["estimated_seconds"]
            candidates.append((
                finish,
                0 if activation == "reused" else 1,
                lane["lane"],
                lane,
                activation,
                seconds,
            ))
        finish, _, _, lane, activation, seconds = min(candidates, key=lambda value: value[:3])
        lane["tasks"].append({
            "task_name": item["task_name"],
            "activation": activation,
            "activation_seconds": seconds,
            "reuse_target": lane["agent_task_name"] if activation == "reused" else None,
            "finish_seconds": finish,
        })
        lane["available_seconds"] = finish
        lane["reuse_eligible"] = item["reuse_eligible"]
        if activation == "reused":
            lane["followups"] += 1
        else:
            lane["route"] = _route_key(item)
            lane["followups"] = 0
            lane["agent_task_name"] = item["task_name"]

    activations = [task["activation"] for lane in lanes for task in lane["tasks"]]
    initial_activation_seconds = max(
        (lane["tasks"][0]["activation_seconds"] for lane in lanes), default=0
    )
    return {
        "lanes": lanes,
        "work_seconds": max(
            (lane["available_seconds"] for lane in lanes), default=0
        ),
        "fresh_activations": activations.count("fresh"),
        "reused_activations": activations.count("reused"),
        "initial_activation_seconds": initial_activation_seconds,
    }


def plan(args):
    project_state = _project_skill_state(getattr(args, "repository", None))
    if not project_state["enabled"]:
        print(json.dumps(
            _project_disabled_result(project_state),
            ensure_ascii=False,
            sort_keys=True,
        ))
        return
    try:
        tasks = json.loads(args.tasks_json)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"--tasks-json must be valid JSON: {exc}") from exc
    if not isinstance(tasks, list) or not tasks or any(not isinstance(x, dict) for x in tasks):
        raise SystemExit("--tasks-json must be a non-empty array of objects")
    current = (
        policy.unavailable_current()
        if args.no_runtime_detection
        else policy.detect_current_route(args.sessions_root)
    )
    subagent_policy = _subagent_policy(args)
    subagents_allowed = subagent_policy["allowed"]
    decisions = []
    for index, task in enumerate(tasks):
        item = dict(task)
        item["task_name"] = _task_name(task, index)
        item["route"] = _decision(args, task, current)
        item["leaf_agent_type"] = (
            AGENT_TYPES.get(_route_key(item)) if subagents_allowed else None
        )
        item["estimated_seconds"] = int(task.get("estimated_seconds", 0))
        item["required"] = bool(task.get("required", True))
        item["max_recovery_attempts"] = int(
            task.get("max_recovery_attempts", DEFAULT_MAX_RECOVERY_ATTEMPTS)
        )
        if not 0 <= item["max_recovery_attempts"] <= 3:
            raise ValueError("max recovery attempts must be from 0 to 3")
        item["depends_on"] = list(task.get("depends_on", []))
        item["write_scopes"] = list(task.get("write_scopes", []))
        item["conflict_keys"] = list(task.get("conflict_keys", []))
        item["fresh_context_required"] = bool(task.get("fresh_context_required", False))
        item["external_action"] = bool(task.get("external_action", False))
        item["sensitive_data"] = bool(task.get("sensitive_data", False))
        reuse_exclusions = _task_reuse_exclusions(task, args)
        item["reuse_eligible"] = subagents_allowed and not reuse_exclusions
        item["reuse_exclusions"] = reuse_exclusions
        decisions.append(item)

    names = {item["task_name"] for item in decisions}
    if any(set(item["depends_on"]) - names for item in decisions):
        raise SystemExit("task dependencies must reference task_name values in this plan")
    if not subagents_allowed:
        print(json.dumps({
            "protocol": LITE_PROTOCOL,
            "action": "local",
            "parallel": False,
            "parallel_kind": "none",
            "subagent_policy": subagent_policy,
            "tool_concurrency": {
                "allowed": True,
                "creates_child_agents": False,
                "same_model_and_effort": True,
                "scope": "independent-safe-tool-or-process-calls",
                "planning": "coordinator-direct",
            },
            "tasks": decisions,
            "recommendation": (
                "run in the coordinator; concurrently dispatch only independent "
                "safe tool or process calls"
            ),
        }, ensure_ascii=False, sort_keys=True))
        return
    ready = [item for item in decisions if not item["depends_on"]]
    worthwhile = [
        item for item in ready
        if item["estimated_seconds"] >= args.min_parallel_seconds
    ]
    independent_scopes = True
    seen_scopes = []
    seen_conflicts = set()
    for item in worthwhile:
        scopes = [_scope(value) for value in item["write_scopes"]]
        conflicts = set(item["conflict_keys"])
        if seen_conflicts & conflicts or any(
            _scopes_overlap(left, right)
            for left in seen_scopes for right in scopes
        ):
            independent_scopes = False
        seen_scopes.extend(scopes)
        seen_conflicts |= conflicts
    if not 1 <= args.max_total_tasks <= 16:
        raise ValueError("max total tasks must be from 1 to 16")
    if args.available_worker_slots is not None and args.available_worker_slots < 0:
        raise ValueError("available worker slots cannot be negative")
    fresh_executor_seconds = int(getattr(
        args, "fresh_executor_seconds",
        getattr(args, "executor_startup_seconds", DEFAULT_FRESH_EXECUTOR_SECONDS),
    ))
    reused_executor_seconds = int(getattr(
        args, "reused_executor_seconds", DEFAULT_REUSED_EXECUTOR_SECONDS
    ))
    max_executor_reuses = int(getattr(
        args, "max_executor_reuses", DEFAULT_MAX_REUSES_PER_EXECUTOR
    ))
    reuse_candidates, rejected_reuse_candidates = _reuse_candidates(
        getattr(args, "reuse_candidates_json", "[]"), max_executor_reuses,
        _reuse_identity(args),
    )
    for name in (
        "min_parallel_seconds", "coordination_seconds",
        "spawn_stagger_seconds", "aggregation_seconds", "min_parallel_savings_seconds",
    ):
        if getattr(args, name) < 0:
            raise ValueError(f"{name.replace('_', ' ')} cannot be negative")
    if fresh_executor_seconds < 0 or reused_executor_seconds < 0:
        raise ValueError("executor activation seconds cannot be negative")
    if not 0 <= max_executor_reuses <= 3:
        raise ValueError("max executor reuses must be from 0 to 3")
    if not 0 <= args.min_parallel_savings_ratio <= 1:
        raise ValueError("minimum parallel savings ratio must be from 0 to 1")
    worker_cap = max(0, args.max_total_tasks - 1)
    observed_slots = 1 if args.available_worker_slots is None else args.available_worker_slots
    capacity = max(0, min(worker_cap, observed_slots))
    parallel_workers = min(capacity, len(worthwhile))
    serial_seconds = sum(item["estimated_seconds"] for item in worthwhile)
    schedule = _executor_schedule(
        worthwhile,
        parallel_workers,
        args.coordination_seconds,
        args.spawn_stagger_seconds,
        fresh_executor_seconds,
        reused_executor_seconds,
        max_executor_reuses,
        reuse_candidates,
    ) if parallel_workers else {
        "lanes": [], "work_seconds": serial_seconds,
        "fresh_activations": 0, "reused_activations": 0,
        "initial_activation_seconds": 0,
    }
    dispatch_seconds = (
        args.coordination_seconds
        + max(0, parallel_workers - 1) * args.spawn_stagger_seconds
    )
    predicted_parallel_seconds = schedule["work_seconds"] + args.aggregation_seconds
    predicted_savings_seconds = max(0, serial_seconds - predicted_parallel_seconds)
    predicted_savings_ratio = (
        predicted_savings_seconds / serial_seconds if serial_seconds else 0.0
    )
    net_benefit = (
        predicted_savings_seconds >= args.min_parallel_savings_seconds
        and predicted_savings_ratio >= args.min_parallel_savings_ratio
    )
    parallel = (
        len(worthwhile) >= 2
        and independent_scopes
        and capacity >= 2
        and net_benefit
    )
    priority_order = [
        item["task_name"]
        for item in sorted(
            worthwhile,
            key=lambda item: (-item["estimated_seconds"], item["task_name"]),
        )
    ]
    dispatch_now = priority_order[:parallel_workers] if parallel else []
    print(json.dumps({
        "protocol": LITE_PROTOCOL,
        "action": "parallel" if parallel else "delegate-or-local",
        "parallel": parallel,
        "max_parallelism": min(capacity, len(worthwhile)) if parallel else 1,
        "max_total_tasks": 1 + min(capacity, len(worthwhile)) if parallel else 1,
        "dispatch_now": dispatch_now,
        "local_or_deferred": [
            item["task_name"] for item in decisions if item["task_name"] not in dispatch_now
        ],
        "priority_order": priority_order,
        "executor_lanes": schedule["lanes"] if parallel else [],
        "tasks": decisions,
        "subagent_policy": subagent_policy,
        "planning_estimate": {
            "kind": "planning-only-not-measured-speedup",
            "serial_seconds": serial_seconds,
            "parallel_seconds": predicted_parallel_seconds,
            "startup_seconds": schedule["initial_activation_seconds"],
            "fresh_executor_seconds": fresh_executor_seconds,
            "reused_executor_seconds": reused_executor_seconds,
            "fresh_activations": schedule["fresh_activations"],
            "reused_activations": schedule["reused_activations"],
            "coordination_seconds": args.coordination_seconds,
            "spawn_stagger_seconds": args.spawn_stagger_seconds,
            "dispatch_seconds": dispatch_seconds,
            "aggregation_seconds": args.aggregation_seconds,
            "savings_seconds": predicted_savings_seconds,
            "savings_ratio": round(predicted_savings_ratio, 4),
        },
        "result_policy": {
            "required_tasks": [item["task_name"] for item in decisions if item["required"]],
            "optional_tasks": [item["task_name"] for item in decisions if not item["required"]],
            "stop_optional_after_required": True,
        },
        "reuse_policy": {
            "scope": "same-request-only",
            "max_followups_per_executor": max_executor_reuses,
            "eligible_candidates": [
                item["agent_task_name"] for item in reuse_candidates
            ],
            "rejected_candidates": rejected_reuse_candidates,
            "requires_same_repository": True,
            "requires_same_route": True,
            "requires_same_permissions": True,
            "requires_same_sandbox": True,
            "required_identity_fields": [
                "request_id", "repository_realpath",
                "permissions_fingerprint", "sandbox_fingerprint",
            ],
            "requires_idle_executor": True,
            "requires_resolved_write_ownership": True,
            "requires_accepted_result": True,
            "excludes_fresh_context_reviews": True,
            "excludes_high_consequence_or_prior_failure": True,
            "recheck_immediately_before_followup": True,
            "cross_request_reuse": False,
        },
        "reason": (
            "startup-amortized-independent-tasks" if parallel
            else "insufficient-net-benefit-independence-or-capacity"
        ),
        "fail_open": True,
        "startup_failure_takeover_seconds": 15,
    }, ensure_ascii=False, sort_keys=True))


def record(args):
    project_state = _project_skill_state(getattr(args, "repository", None))
    if not project_state["enabled"]:
        result = _project_disabled_result(project_state)
        result.update({"recorded": False})
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return
    event = {
        "event": "execution",
        "event_id": args.event_id or f"lite-{time.time_ns()}",
        "model": policy.normalize_model(args.model),
        "effort": policy.normalize_effort(args.effort),
        "task_class": args.task_class,
        "outcome": args.outcome,
        "source": args.source,
    }
    if args.duration_seconds is not None:
        event["duration_seconds"] = args.duration_seconds
    if args.concurrency is not None:
        event["concurrency"] = args.concurrency
    try:
        appended = ledger.append_event(args.ledger, event)
        result = {"recorded": bool(appended), "warning": None}
    except (OSError, ValueError) as exc:
        result = {
            "recorded": False,
            "warning": f"ledger-best-effort:{type(exc).__name__}",
        }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


def _add_route_arguments(parser):
    parser.add_argument("--task-kind", choices=("mechanical", "ordinary", "complex"), default="ordinary")
    parser.add_argument(
        "--risk", type=_risk_value, choices=("low", "normal", "high"), default="normal"
    )
    parser.add_argument(
        "--size", type=_size_value, choices=("tiny", "normal", "large"), default="normal"
    )
    parser.add_argument("--ambiguity", choices=("low", "medium", "high"))
    parser.add_argument("--coupling", choices=("low", "medium", "high"))
    parser.add_argument("--verification", choices=("deterministic", "mixed", "judgment"))
    parser.add_argument("--consequence", choices=("low", "normal", "high"))
    parser.add_argument("--latency-priority", choices=("low", "normal", "high"))
    parser.add_argument("--prior-failure", action="store_true")
    parser.add_argument("--prior-failure-kind", choices=("unknown", "reasoning", "verification", "infrastructure"))
    parser.add_argument("--tool-bound", action="store_true")
    parser.add_argument("--estimated-seconds", type=int)
    parser.add_argument(
        "--min-delegate-seconds", type=int, default=DEFAULT_MIN_DELEGATE_SECONDS
    )
    parser.add_argument("--model")
    parser.add_argument("--effort")
    parser.add_argument("--sessions-root", type=Path)
    parser.add_argument("--no-runtime-detection", action="store_true")
    parser.add_argument(
        "--no-subagents", action="store_true",
        help=(
            "Disable automatic delegate, reuse, and agent-parallel actions; "
            "direct tool concurrency remains available"
        ),
    )
    parser.add_argument(
        "--allow-subagents", action="store_true", help=argparse.SUPPRESS,
    )
    # Compatibility-only context accepted from older callers. Routing decisions
    # remain driven by the explicit, validated fields above.
    parser.add_argument("--responsibility", help=argparse.SUPPRESS)
    parser.add_argument("--signals", help=argparse.SUPPRESS)


def _add_reuse_arguments(parser):
    parser.add_argument("--request-id")
    parser.add_argument("--repository", type=Path)
    parser.add_argument("--permissions-fingerprint")
    parser.add_argument("--sandbox-fingerprint")
    parser.add_argument("--reuse-candidates-json", default="[]")
    parser.add_argument(
        "--reused-executor-seconds", type=int,
        default=DEFAULT_REUSED_EXECUTOR_SECONDS,
    )
    parser.add_argument(
        "--max-executor-reuses", type=int,
        default=DEFAULT_MAX_REUSES_PER_EXECUTOR,
    )
    parser.add_argument("--fresh-context-required", action="store_true")
    parser.add_argument("--external-action", action="store_true")
    parser.add_argument("--sensitive-data", action="store_true")
    parser.add_argument(
        "--executor-wait-poll-seconds", type=int,
        default=DEFAULT_EXECUTOR_WAIT_POLL_SECONDS,
    )
    parser.add_argument(
        "--executor-stalled-after-seconds", type=int,
        default=DEFAULT_EXECUTOR_STALLED_AFTER_SECONDS,
    )


def _add_project_arguments(parser):
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--skill-path", type=Path, default=_default_skill_path())


def parser():
    root = FailOpenArgumentParser()
    commands = root.add_subparsers(dest="command", required=True)
    single = commands.add_parser("decide")
    _add_route_arguments(single)
    _add_reuse_arguments(single)
    single.set_defaults(func=decide)
    planner = commands.add_parser("plan")
    _add_route_arguments(planner)
    _add_reuse_arguments(planner)
    planner.add_argument("--tasks-json", required=True)
    planner.add_argument("--max-total-tasks", type=int, default=DEFAULT_MAX_TOTAL_TASKS)
    planner.add_argument("--available-worker-slots", type=int)
    planner.add_argument("--min-parallel-seconds", type=int, default=DEFAULT_MIN_PARALLEL_SECONDS)
    planner.add_argument(
        "--fresh-executor-seconds", "--executor-startup-seconds",
        dest="fresh_executor_seconds", type=int,
        default=DEFAULT_FRESH_EXECUTOR_SECONDS,
    )
    planner.add_argument(
        "--coordination-seconds", type=int, default=DEFAULT_COORDINATION_SECONDS
    )
    planner.add_argument(
        "--spawn-stagger-seconds", type=int, default=DEFAULT_SPAWN_STAGGER_SECONDS
    )
    planner.add_argument(
        "--aggregation-seconds", type=int, default=DEFAULT_AGGREGATION_SECONDS
    )
    planner.add_argument(
        "--min-parallel-savings-seconds",
        type=int,
        default=DEFAULT_MIN_PARALLEL_SAVINGS_SECONDS,
    )
    planner.add_argument(
        "--min-parallel-savings-ratio",
        type=float,
        default=DEFAULT_MIN_PARALLEL_SAVINGS_RATIO,
    )
    planner.set_defaults(func=plan)
    recorder = commands.add_parser("record")
    recorder.add_argument("--ledger", type=Path, required=True)
    recorder.add_argument("--event-id")
    recorder.add_argument("--model", required=True)
    recorder.add_argument("--effort", required=True)
    recorder.add_argument("--task-class", required=True)
    recorder.add_argument("--outcome", choices=ledger.OUTCOMES, required=True)
    recorder.add_argument("--source", choices=ledger.SOURCES, default="task-metadata")
    recorder.add_argument("--duration-seconds", type=float)
    recorder.add_argument("--concurrency", type=int)
    recorder.add_argument("--repository", type=Path, default=Path.cwd())
    recorder.set_defaults(func=record)
    disabler = commands.add_parser("project-disable")
    _add_project_arguments(disabler)
    disabler.set_defaults(func=project_disable)
    enabler = commands.add_parser("project-enable")
    _add_project_arguments(enabler)
    enabler.set_defaults(func=project_enable)
    status = commands.add_parser("project-status")
    _add_project_arguments(status)
    status.set_defaults(func=project_status)
    return root


def main(argv=None):
    try:
        args = parser().parse_args(argv)
        args.func(args)
    except (OSError, ValueError, SystemExit) as exc:
        # Routing advice must never block the requested project work.
        print(json.dumps({
            "protocol": LITE_PROTOCOL,
            "action": "local",
            "fail_open": True,
            "warning": f"router-lite-fallback:{type(exc).__name__}",
        }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
