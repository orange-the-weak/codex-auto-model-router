#!/usr/bin/env python3
"""Fast, fail-open model routing for normal Codex work.

The Lite path deliberately has no plan hash, cursor, claim, Restore, or
cross-task runtime state. The coordinator keeps its model; a mismatched route
is executed by one explicitly selected leaf agent.
"""

import argparse
import json
import sys
import time
from pathlib import Path
from pathlib import PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent))
import model_usage_ledger as ledger
import route_policy as policy


LITE_PROTOCOL = "router-lite-v2"
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
DEFAULT_MAX_REUSES_PER_EXECUTOR = 1

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
    short_work = estimated_seconds is not None and estimated_seconds < min_delegate_seconds
    local_cost_fast_path = (
        current.get("status") == "verified"
        and current_is_gpt56
        and not explicit_route
        and not task.get("prior_failure", args.prior_failure)
        and risk != "high"
        and consequence != "high"
        and (
            (task_kind == "mechanical" and size == "tiny")
            or (tool_bound and verification in (None, "deterministic"))
            or (short_work and current_is_sufficient)
        )
    )
    matched = current.get("status") == "verified" and (
        current.get("model"), current.get("effort")
    ) == (model, effort)
    ultra = effort == "ultra"
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
        action = "native-ultra" if ultra else "local" if matched else "delegate"
        actual_model = model
        actual_effort = effort
        reason = "already-matched" if matched else selected["recommended"]["source"]
    return {
        "protocol": LITE_PROTOCOL,
        "action": action,
        "model": actual_model,
        "effort": actual_effort,
        "agent_type": None if action != "delegate" else AGENT_TYPES.get((model, effort)),
        "recommended_route": {"model": model, "effort": effort},
        "reason": reason,
        "current": current,
        "native_ultra": ultra,
        "restore_required": False,
        "fail_open": True,
        "startup_failure_takeover_seconds": 15,
        "estimated_seconds": estimated_seconds,
        "delegate_break_even_seconds": min_delegate_seconds,
    }


def decide(args):
    print(json.dumps(_decision(args), ensure_ascii=False, sort_keys=True))


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
    ):
        return "reused", reused_seconds
    return "fresh", fresh_seconds


def _reuse_candidates(value):
    try:
        candidates = json.loads(value or "[]")
    except json.JSONDecodeError as exc:
        raise ValueError(f"reuse candidates must be valid JSON: {exc}") from exc
    if not isinstance(candidates, list) or any(not isinstance(item, dict) for item in candidates):
        raise ValueError("reuse candidates must be an array of objects")
    normalized = []
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
        normalized.append({"agent_task_name": name, "model": model, "effort": effort})
        seen.add(name)
    return normalized


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
            ), None) if max_reuses else None
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
                "followups": 1 if candidate else 0,
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
    decisions = []
    for index, task in enumerate(tasks):
        item = dict(task)
        item["task_name"] = _task_name(task, index)
        item["route"] = _decision(args, task, current)
        item["leaf_agent_type"] = AGENT_TYPES.get(_route_key(item))
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
        decisions.append(item)

    names = {item["task_name"] for item in decisions}
    if any(set(item["depends_on"]) - names for item in decisions):
        raise SystemExit("task dependencies must reference task_name values in this plan")
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
    reuse_candidates = _reuse_candidates(getattr(args, "reuse_candidates_json", "[]"))
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
            "requires_same_repository": True,
            "requires_same_route": True,
            "requires_same_permissions": True,
            "requires_idle_executor": True,
            "requires_resolved_write_ownership": True,
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
    parser.add_argument("--risk", choices=("low", "normal", "high"), default="normal")
    parser.add_argument("--size", choices=("tiny", "normal", "large"), default="normal")
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


def parser():
    root = argparse.ArgumentParser()
    commands = root.add_subparsers(dest="command", required=True)
    single = commands.add_parser("decide")
    _add_route_arguments(single)
    single.set_defaults(func=decide)
    planner = commands.add_parser("plan")
    _add_route_arguments(planner)
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
        "--reused-executor-seconds", type=int,
        default=DEFAULT_REUSED_EXECUTOR_SECONDS,
    )
    planner.add_argument(
        "--max-executor-reuses", type=int,
        default=DEFAULT_MAX_REUSES_PER_EXECUTOR,
    )
    planner.add_argument(
        "--reuse-candidates-json", default="[]",
        help="Coordinator-prequalified idle executors from this user request only",
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
    recorder.set_defaults(func=record)
    return root


if __name__ == "__main__":
    args = parser().parse_args()
    try:
        args.func(args)
    except (OSError, ValueError, SystemExit) as exc:
        # Routing advice must never block the requested project work.
        print(json.dumps({
            "protocol": LITE_PROTOCOL,
            "action": "local",
            "fail_open": True,
            "warning": f"router-lite-fallback:{type(exc).__name__}",
        }, ensure_ascii=False, sort_keys=True))
