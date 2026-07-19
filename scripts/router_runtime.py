#!/usr/bin/env python3
"""Combine deterministic Router state gates into one begin and one finish call."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import model_usage_ledger as ledger  # noqa: E402
import route_policy as policy  # noqa: E402


def _load(value, label):
    try:
        result = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid {label}: {exc}") from exc
    if not isinstance(result, dict):
        raise ValueError(f"{label} must be an object")
    return result


def _validate(envelope):
    plan = envelope.get("plan")
    protocol = plan.get("protocol") if isinstance(plan, dict) else None
    if protocol == policy.FAST_PROTOCOL:
        return policy.validate_fast_envelope(
            plan, envelope.get("route_id"), envelope.get("segment_id"),
            envelope.get("attempt_id"),
        )
    if protocol == policy.SEGMENTED_PROTOCOL:
        return policy.validate_segment_cursor(
            plan, envelope.get("cursor"), envelope.get("segment_id"),
            envelope.get("completed_ids"), envelope.get("route_id"),
            envelope.get("attempt_id"), envelope.get("original_model"),
            envelope.get("original_effort"), envelope.get("protocol"),
            envelope.get("restore_required"), envelope.get("segment_budget"),
            envelope.get("switch_budget"), envelope.get("budget_source"),
        )
    if protocol == policy.PARALLEL_PROTOCOL:
        return policy.validate_parallel_envelope(
            plan, envelope.get("segment_id"), envelope.get("completed_ids", []),
            envelope.get("running_ids", []), envelope.get("route_id"),
            envelope.get("attempt_id"), envelope.get("parallelism"),
        )
    raise ValueError("unsupported routing protocol")


def _current(args):
    return (
        policy.unavailable_current()
        if args.no_runtime_detection else policy.detect_current_route(args.sessions_root)
    )


def _record_gate_stop(args, envelope, reason):
    plan = envelope.get("plan") if isinstance(envelope, dict) else None
    route_id = plan.get("route_id") if isinstance(plan, dict) else None
    if not route_id:
        return False
    event = {
        "event": "routing_efficiency", "route_id": route_id,
        "source": "task-metadata", "state_gate": "stopped",
        "state_gate_reason": str(reason),
    }
    segment_id = envelope.get("segment_id")
    if segment_id:
        event["segment_id"] = segment_id
    return ledger.append_event(args.ledger, event)


def begin(args):
    envelope = None
    try:
        envelope = _load(args.envelope_json, "envelope")
        segment = _validate(envelope)
    except ValueError as exc:
        _record_gate_stop(args, envelope, exc)
        raise SystemExit(f"state gate stopped: {exc}") from exc
    plan = envelope["plan"]
    claim_required = not (
        plan["protocol"] == policy.FAST_PROTOCOL
        and segment.get("dispatch") == "local"
    )
    claimed = None
    if claim_required:
        claimed = ledger.append_event(args.ledger, {
            "event": "segment_claim", "route_id": plan["route_id"],
            "segment_id": segment["segment_id"],
            "attempt_id": segment["attempt_id"],
        })
        if not claimed:
            _record_gate_stop(args, envelope, "segment-already-claimed")
            raise SystemExit("state gate stopped: segment already claimed")
    current = _current(args)
    print(json.dumps({
        "ok": True,
        "state_gate": "passed",
        "claimed": claimed,
        "claim_required": claim_required,
        "dispatch": segment.get("dispatch"),
        "current": current,
        "context_capsule": policy.context_capsule(plan, segment["segment_id"]),
    }, ensure_ascii=False, sort_keys=True))


def _observed_route(result, current):
    source = result.get("source")
    if source == "user-confirmed" and result.get("actual_model") and result.get("actual_effort"):
        return result["actual_model"], result["actual_effort"], source
    if current.get("status") == "verified":
        return current.get("model"), current.get("effort"), "task-metadata"
    return None, None, None


def _validate_finish_plan(plan, segment):
    protocol = plan.get("protocol")
    if protocol == policy.FAST_PROTOCOL:
        return policy.validate_fast_envelope(
            plan, plan.get("route_id"), segment.get("segment_id"),
            segment.get("attempt_id"),
        )
    if protocol not in (policy.SEGMENTED_PROTOCOL, policy.PARALLEL_PROTOCOL):
        raise ValueError("unsupported finish protocol")
    expected_hash = policy.plan_hash(
        plan.get("segments"), plan.get("route_id"), plan.get("original"),
        plan.get("restore_required"), plan.get("segment_budget"),
        plan.get("switch_budget"), plan.get("budget_source"),
        plan.get("routing_evidence"), protocol,
        plan.get("parallel") if protocol == policy.PARALLEL_PROTOCOL else None,
    )
    if plan.get("plan_hash") != expected_hash:
        raise ValueError("finish plan hash mismatch")
    expected_attempt = hashlib.sha256(
        f"{plan['route_id']}:{expected_hash}:{segment['segment_id']}".encode("utf-8")
    ).hexdigest()
    if segment.get("attempt_id") != expected_attempt:
        raise ValueError("finish attempt_id mismatch")
    return segment


def _next_action(plan, result, current):
    if result.get("outcome") != "completed":
        return {"action": "stop", "reason": "segment-failed"}
    protocol = plan["protocol"]
    if protocol == policy.SEGMENTED_PROTOCOL:
        cursor = result.get("cursor", 0)
        if cursor + 1 < len(plan["segments"]):
            return {"action": "advance", "cursor": cursor + 1}
    elif protocol == policy.PARALLEL_PROTOCOL:
        completed = set(result.get("completed_ids", [])) | {result["segment_id"]}
        if len(completed) < len(plan["segments"]):
            return {"action": "refill-frontier", "completed_ids": sorted(completed)}
    original = plan.get("original", {})
    current_route = (current.get("model"), current.get("effort"))
    original_route = (original.get("model"), original.get("effort"))
    if plan.get("restore_required") and current_route != original_route:
        return {"action": "restore", "model": original_route[0], "effort": original_route[1]}
    return {"action": "return"}


def finish(args):
    result = _load(args.result_json, "result")
    plan = result.get("plan")
    if not isinstance(plan, dict):
        raise SystemExit("finish requires plan")
    segment = next(
        (item for item in plan.get("segments", []) if item.get("segment_id") == result.get("segment_id")),
        None,
    )
    if segment is None:
        raise SystemExit("finish segment is missing from plan")
    try:
        _validate_finish_plan(plan, segment)
    except ValueError as exc:
        raise SystemExit(f"finish state gate stopped: {exc}") from exc
    current = _current(args)
    model, effort, source = _observed_route(result, current)
    execution_recorded = False
    if model and effort and source:
        event = {
            "event": "execution", "route_id": plan["route_id"],
            "segment_id": segment["segment_id"], "model": model, "effort": effort,
            "task_class": result.get("task_class", segment.get("task_kind", "unknown")),
            "outcome": result.get("outcome", "failed"), "source": source,
            "verification": result.get("verification", "unknown"),
            "fallback_from": segment.get("model") if model != segment.get("model") else None,
            "fallback_to": model if model != segment.get("model") else None,
        }
        execution_recorded = ledger.append_event(
            args.ledger, {key: value for key, value in event.items() if value is not None}
        )
    metrics_recorded = False
    metrics = result.get("metrics")
    if isinstance(metrics, dict):
        event = {
            "event": "routing_efficiency", "route_id": plan["route_id"],
            "segment_id": segment["segment_id"], "source": metrics.get("source"),
        }
        for field in ledger.EFFICIENCY_DURATIONS + ledger.EFFICIENCY_COUNTS + (
            "state_gate", "state_gate_reason",
        ):
            if metrics.get(field) is not None:
                event[field] = metrics[field]
        metrics_recorded = ledger.append_event(args.ledger, event)
    print(json.dumps({
        "ok": result.get("outcome") == "completed",
        "execution_recorded": execution_recorded,
        "metrics_recorded": metrics_recorded,
        "current": current,
        "next": _next_action(plan, result, current),
    }, ensure_ascii=False, sort_keys=True))


def parser():
    root = argparse.ArgumentParser()
    root.add_argument("--sessions-root", type=Path)
    root.add_argument("--no-runtime-detection", action="store_true")
    commands = root.add_subparsers(dest="command", required=True)
    starter = commands.add_parser("begin")
    starter.add_argument("--ledger", type=Path, required=True)
    starter.add_argument("--envelope-json", required=True)
    starter.set_defaults(func=begin)
    finisher = commands.add_parser("finish")
    finisher.add_argument("--ledger", type=Path, required=True)
    finisher.add_argument("--result-json", required=True)
    finisher.set_defaults(func=finish)
    return root


if __name__ == "__main__":
    arguments = parser().parse_args()
    arguments.func(arguments)
