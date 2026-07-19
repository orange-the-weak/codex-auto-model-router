#!/usr/bin/env python3
"""Combine deterministic Router state gates into one begin and one finish call."""

import argparse
import hashlib
import inspect
import json
import sys
import time
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


def _validate(
    envelope, trusted_plan_hash=None, trusted_contract_version=None,
    dispatch_capacity_trusted=False,
):
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
        values = (
            plan, envelope.get("segment_id"), envelope.get("completed_ids", []),
            envelope.get("running_ids", []), envelope.get("route_id"),
            envelope.get("attempt_id"), envelope.get("parallelism"),
        )
        parameters = inspect.signature(policy.validate_parallel_envelope).parameters
        extra = {}
        if "dispatch_capacity" in parameters:
            extra["dispatch_capacity"] = envelope.get("dispatch_capacity")
        if "agent_task_name" in parameters:
            extra["agent_task_name"] = envelope.get("agent_task_name")
        if "trusted_plan_hash" in parameters:
            extra["trusted_plan_hash"] = trusted_plan_hash
        if "trusted_contract_version" in parameters:
            extra["trusted_contract_version"] = trusted_contract_version
        if "dispatch_capacity_trusted" in parameters:
            extra["dispatch_capacity_trusted"] = dispatch_capacity_trusted
        if extra:
            return policy.validate_parallel_envelope(*values, **extra)
        return policy.validate_parallel_envelope(*values)
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


def _route_events(path, route_id):
    events, warnings = ledger.read_events(path)
    return [item for item in events if item.get("route_id") == route_id], warnings


def _terminal_results(plan, events):
    by_id = {}
    for item in events:
        if item.get("event") == "segment_result" and item.get("plan_hash") == plan.get("plan_hash"):
            by_id[item["segment_id"]] = item
    # Legal ledgers written before segment_result existed remain readable. The
    # route_id natural key still makes their execution records unambiguous.
    for item in events:
        if item.get("event") == "execution" and item.get("segment_id") not in by_id:
            by_id[item["segment_id"]] = item
    return by_id


def _worker_events(events):
    starts = {
        item["segment_id"]: item for item in events
        if item.get("event") == "parallel_worker_start"
    }
    finishes = {
        item["segment_id"]: item for item in events
        if item.get("event") == "parallel_worker_finish"
    }
    return starts, finishes


def _authoritative_envelope(envelope, events):
    plan = envelope.get("plan")
    if not isinstance(plan, dict):
        return envelope
    protocol = plan.get("protocol")
    terminal = _terminal_results(plan, events)
    segment_order = [item.get("segment_id") for item in plan.get("segments", [])]
    if protocol == policy.SEGMENTED_PROTOCOL:
        completed = []
        for identifier in segment_order:
            item = terminal.get(identifier)
            if item is None or item.get("outcome") != "completed":
                break
            completed.append(identifier)
        envelope["completed_ids"] = completed
        envelope["cursor"] = len(completed)
    elif protocol == policy.PARALLEL_PROTOCOL:
        starts, finishes = _worker_events(events)
        envelope["completed_ids"] = [
            identifier for identifier in segment_order
            if terminal.get(identifier, {}).get("outcome") == "completed"
        ]
        envelope["running_ids"] = [
            identifier for identifier in segment_order
            if identifier in starts and identifier not in finishes
        ]
    return envelope


def _decision_identity(plan, segment):
    return {
        "route_id": plan["route_id"], "plan_hash": plan["plan_hash"],
        "segment_id": segment["segment_id"], "attempt_id": segment["attempt_id"],
    }


def _normalized_runtime_route(model, effort):
    normalized_model = policy.normalize_available_model(model)
    normalized_effort = str(effort or "").strip().lower()
    if normalized_model is None or normalized_effort not in ledger.EFFORTS:
        return None
    return normalized_model, normalized_effort


def _validated_capability_decision(decision, plan, segment, execution_route):
    identity = _decision_identity(plan, segment)
    target = (
        policy.normalize_model(segment.get("model")),
        policy.normalize_effort(segment.get("effort")),
    )
    if execution_route[0] == ledger.GPT55_MODEL:
        ledger.validate_capability_decision(
            decision, identity=identity, target=target, execution=execution_route,
        )
        return decision
    if not isinstance(decision, dict) or decision.get("schema_version") != 1:
        raise ValueError("model fallback requires capability_decision schema_version=1")
    if decision.get("verified") is not True or decision.get("source") != ledger.CAPABILITY_DECISION_SOURCE:
        raise ValueError("model fallback requires verified capability-interface evidence")
    if any(decision.get(field) != expected for field, expected in identity.items()):
        raise ValueError("capability_decision identity mismatch")
    if (
        decision.get("target_model") != target[0]
        or decision.get("target_effort") != target[1]
        or decision.get("execution_model") != execution_route[0]
        or decision.get("execution_effort") != execution_route[1]
    ):
        raise ValueError("capability_decision route mismatch")
    available = decision.get("available_models")
    if decision.get("availability_complete") is not True or not isinstance(available, list):
        raise ValueError("GPT-5.6 fallback requires a complete capability model list")
    resolved = policy.resolve_family_fallback(target[0], target[1], available)
    if (
        resolved.get("execution", {}).get("model") != execution_route[0]
        or resolved.get("execution", {}).get("effort") != execution_route[1]
        or resolved.get("reason") != decision.get("reason")
    ):
        raise ValueError("capability_decision does not match deterministic family fallback")
    return decision


def _begin_runtime_route(envelope, plan, segment, current):
    if current.get("status") != "verified":
        raise ValueError(
            "current model/effort is unverified; use an explicit model-selectable executor/switch"
        )
    actual = _normalized_runtime_route(current.get("model"), current.get("effort"))
    if actual is None:
        raise ValueError(
            "current model/effort is unknown; use an explicit model-selectable executor/switch"
        )
    target = (
        policy.normalize_model(segment.get("model")),
        policy.normalize_effort(segment.get("effort")),
    )
    decision = envelope.get("capability_decision")
    expected = target
    if decision is not None:
        candidate = _normalized_runtime_route(
            decision.get("execution_model") if isinstance(decision, dict) else None,
            decision.get("execution_effort") if isinstance(decision, dict) else None,
        )
        if candidate is None:
            raise ValueError("capability_decision has an invalid execution route")
        _validated_capability_decision(decision, plan, segment, candidate)
        expected = candidate
    if actual != expected:
        raise ValueError(
            f"runtime route {actual[0]}/{actual[1]} does not match Segment route "
            f"{expected[0]}/{expected[1]}; use an explicit model-selectable executor/switch"
        )
    return decision


def begin(args):
    envelope = None
    try:
        envelope = _load(args.envelope_json, "envelope")
        plan = envelope.get("plan")
        route_id = plan.get("route_id") if isinstance(plan, dict) else None
        events, _ = _route_events(args.ledger, route_id) if route_id else ([], [])
        envelope = _authoritative_envelope(envelope, events)
        anchor = ledger.route_contract(args.ledger, route_id) if route_id else None
        contract_version = (
            plan.get("parallel", {}).get("contract_version")
            if isinstance(plan, dict) and isinstance(plan.get("parallel"), dict)
            else None
        )
        trusted_capacity = getattr(args, "trusted_dispatch_capacity_json", None)
        if trusted_capacity:
            envelope["dispatch_capacity"] = _load(
                trusted_capacity, "trusted dispatch capacity"
            )
        segment = _validate(
            envelope,
            trusted_plan_hash=(anchor or {}).get("plan_hash", plan.get("plan_hash")),
            trusted_contract_version=(
                anchor.get("contract_version") if anchor is not None else contract_version
            ),
            dispatch_capacity_trusted=bool(trusted_capacity),
        )
        if contract_version is not None:
            ledger.bind_route_contract(args.ledger, {
                "event": "route_contract", "route_id": plan["route_id"],
                "plan_hash": plan["plan_hash"], "protocol": plan["protocol"],
                "contract_version": contract_version,
                "source": ledger.ROUTE_CONTRACT_SOURCE,
            })
    except ValueError as exc:
        raise SystemExit(f"state gate stopped: {exc}") from exc
    plan = envelope["plan"]
    if any(
        item.get("event") == "parallel_stop_latch"
        and item.get("plan_hash", plan["plan_hash"]) == plan["plan_hash"]
        for item in events
    ):
        _record_gate_stop(args, envelope, "parallel-failure-latch")
        raise SystemExit("state gate stopped: parallel route dispatch stopped by failure latch")
    current = _current(args)
    try:
        decision = _begin_runtime_route(envelope, plan, segment, current)
    except ValueError as exc:
        _record_gate_stop(args, envelope, exc)
        raise SystemExit(f"state gate stopped: {exc}") from exc
    claim_required = not (
        plan["protocol"] == policy.FAST_PROTOCOL
        and segment.get("dispatch") == "local"
        and decision is None
    )
    claimed = None
    claim_state = "not-required"
    reservation_event = None
    if claim_required:
        claim_event = {
            "event": "segment_claim", "route_id": plan["route_id"],
            "segment_id": segment["segment_id"],
            "attempt_id": segment["attempt_id"],
            "plan_hash": plan["plan_hash"],
            "claim_state": "prepared",
        }
        if plan["protocol"] == policy.PARALLEL_PROTOCOL:
            claim_event["dispatch_reservation_required"] = True
            reservation_event = {
                "event": "parallel_dispatch_reservation",
                "route_id": plan["route_id"], "plan_hash": plan["plan_hash"],
                "segment_id": segment["segment_id"],
                "attempt_id": segment["attempt_id"],
                "reservation_id": hashlib.sha256(
                    f"{plan['route_id']}:{plan['plan_hash']}:{segment['segment_id']}:"
                    f"{segment['attempt_id']}:dispatch".encode("utf-8")
                ).hexdigest(),
                "capture_source": "router-runtime",
            }
        if decision is not None:
            claim_event["capability_decision_hash"] = ledger.capability_decision_hash(decision)
        try:
            claim_state = ledger.prepare_segment_claim(
                args.ledger, claim_event,
                allow_prepared_recovery=plan["protocol"] == policy.PARALLEL_PROTOCOL,
                reservation_event=reservation_event,
            )
        except ValueError as exc:
            _record_gate_stop(args, envelope, exc)
            raise SystemExit(f"state gate stopped: {exc}") from exc
        claimed = claim_state == "prepared"
        if claim_state not in ("prepared", "recovered"):
            _record_gate_stop(args, envelope, f"segment-claim-{claim_state}")
            message = (
                "segment already claimed" if claim_state == "already-claimed"
                else f"segment claim is {claim_state}"
            )
            raise SystemExit(f"state gate stopped: {message}")
    print(json.dumps({
        "ok": True,
        "state_gate": "passed",
        "claimed": claimed,
        "claim_state": claim_state,
        "prepared_recovery": claim_state == "recovered",
        "claim_required": claim_required,
        "dispatch_reserved": reservation_event is not None,
        "dispatch": segment.get("dispatch"),
        "current": current,
        "context_capsule": policy.context_capsule(plan, segment["segment_id"]),
    }, ensure_ascii=False, sort_keys=True))


def _capture_worker_event(args, event_type, outcome=None):
    anchor = ledger.route_contract(args.ledger, args.route_id)
    if anchor is not None and anchor.get("plan_hash") != args.plan_hash:
        raise SystemExit("worker state gate stopped: route contract plan hash mismatch")
    event = {
        "event": event_type,
        "route_id": args.route_id,
        "plan_hash": args.plan_hash,
        "segment_id": args.segment_id,
        "attempt_id": args.attempt_id,
        "monotonic_ns": time.monotonic_ns(),
        "clock_source": ledger.PARALLEL_CLOCK_SOURCE,
        "capture_source": "router-runtime",
    }
    if outcome is not None:
        event["outcome"] = outcome
    try:
        appended = ledger.append_event(args.ledger, event)
    except ValueError as exc:
        raise SystemExit(f"worker state gate stopped: {exc}") from exc
    events, _ = _route_events(args.ledger, args.route_id)
    stop_latched = any(
        item.get("event") == "parallel_stop_latch" for item in events
    )
    print(json.dumps({
        "captured": appended,
        "state": (
            "dispatch-confirmed" if event_type == "parallel_worker_start" and appended
            else "result-received" if event_type == "parallel_worker_finish" and appended
            else "already-captured"
        ),
        "route_id": args.route_id,
        "plan_hash": args.plan_hash,
        "segment_id": args.segment_id,
        "attempt_id": args.attempt_id,
        "event": event_type,
        "timestamp": event.get("timestamp"),
        "stop_latched": stop_latched,
    }, ensure_ascii=False, sort_keys=True))


def worker_start(args):
    _capture_worker_event(args, "parallel_worker_start")


def worker_finish(args):
    _capture_worker_event(args, "parallel_worker_finish", args.outcome)


def _identity(plan, segment):
    return {
        "route_id": plan["route_id"],
        "plan_hash": plan["plan_hash"],
        "segment_id": segment["segment_id"],
        "attempt_id": segment["attempt_id"],
    }


def _validate_result_identity(result, identity):
    for field, expected in identity.items():
        supplied = result.get(field)
        if supplied is not None and supplied != expected:
            raise ValueError(f"finish {field} mismatch")


def _trusted_task_metadata(result, identity):
    metadata = result.get("task_metadata")
    if isinstance(metadata, dict):
        trusted = metadata.get("trusted") is True or metadata.get("verified") is True
        source = metadata.get("source", "task-metadata")
        if trusted and source == "task-metadata" and all(
            metadata.get(field) == expected for field, expected in identity.items()
        ):
            model = metadata.get("actual_model", metadata.get("model"))
            effort = metadata.get("actual_effort", metadata.get("effort"))
            if model and effort:
                return model, effort, "task-metadata", metadata
    trusted = (
        result.get("source") == "task-metadata"
        and result.get("task_metadata_trusted") is True
        and all(result.get(field) == expected for field, expected in identity.items())
    )
    if trusted and result.get("actual_model") and result.get("actual_effort"):
        return (
            result["actual_model"], result["actual_effort"], "task-metadata",
            {field: result.get(field) for field in (*identity, "actual_model", "actual_effort")},
        )
    return None


def _observed_route(result, current, identity, protocol):
    source = result.get("source")
    if source == "user-confirmed" and result.get("actual_model") and result.get("actual_effort"):
        return result["actual_model"], result["actual_effort"], source, None
    trusted = _trusted_task_metadata(result, identity)
    if trusted:
        return trusted
    # The coordinator's current route is not executor metadata. It is usable
    # only for same-task serial execution, never for a parallel leaf worker.
    if protocol != policy.PARALLEL_PROTOCOL and current.get("status") == "verified":
        return current.get("model"), current.get("effort"), "task-metadata", current
    return None, None, None, None


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


def _active_concurrency(events, segment_id):
    starts, finishes = _worker_events(events)
    target_start = starts.get(segment_id)
    target_finish = finishes.get(segment_id)
    if target_start is None or target_finish is None:
        return None
    first = target_start["monotonic_ns"]
    last = target_finish["monotonic_ns"]
    if last <= first:
        return None
    intervals = []
    for identifier, start in starts.items():
        start_ns = max(first, start["monotonic_ns"])
        finish = finishes.get(identifier)
        finish_ns = min(last, finish["monotonic_ns"] if finish else last)
        if finish_ns > start_ns:
            intervals.append({
                "started_monotonic_ns": start_ns,
                "result_received_monotonic_ns": finish_ns,
            })
    if not intervals:
        return None
    return ledger.parallel_metrics_from_intervals(intervals)["peak_concurrency"]


def _restore_or_return(plan, current):
    protocol = plan["protocol"]
    original = plan.get("original", {})
    current_route = (current.get("model"), current.get("effort"))
    original_route = (original.get("model"), original.get("effort"))
    if plan.get("restore_required") and current_route != original_route:
        return {"action": "restore", "model": original_route[0], "effort": original_route[1]}
    return {"action": "return"}


def _next_action(plan, current, events):
    segment_order = [item["segment_id"] for item in plan["segments"]]
    terminal = _terminal_results(plan, events)
    failures = [
        identifier for identifier in segment_order
        if identifier in terminal and terminal[identifier].get("outcome") != "completed"
    ]
    if plan["protocol"] == policy.SEGMENTED_PROTOCOL:
        if failures:
            return {"action": "stop", "reason": "segment-failed", "failed_ids": failures}
        completed_ids = [
            identifier for identifier in segment_order
            if terminal.get(identifier, {}).get("outcome") == "completed"
        ]
        if len(completed_ids) < len(segment_order):
            return {"action": "advance", "cursor": len(completed_ids)}
        return _restore_or_return(plan, current)
    if plan["protocol"] == policy.PARALLEL_PROTOCOL:
        starts, finishes = _worker_events(events)
        dispatched_ids = [identifier for identifier in segment_order if identifier in starts]
        running_ids = [identifier for identifier in dispatched_ids if identifier not in finishes]
        finished_unrecorded = [
            identifier for identifier in dispatched_ids
            if identifier in finishes and identifier not in terminal
        ]
        latched = any(item.get("event") == "parallel_stop_latch" for item in events)
        if latched and running_ids:
            return {
                "action": "drain-running", "reason": "parallel-stop-latched",
                "running_ids": running_ids, "dispatched_ids": dispatched_ids,
            }
        if finished_unrecorded:
            return {
                "action": "await-result-recording",
                "pending_result_ids": finished_unrecorded,
            }
        skipped_ids = [identifier for identifier in segment_order if identifier not in starts]
        if latched or failures:
            return {
                "action": "stop", "reason": "segment-failed",
                "failed_ids": failures, "dispatched_ids": dispatched_ids,
                "skipped_ids": skipped_ids,
            }
        completed_ids = [
            identifier for identifier in segment_order
            if terminal.get(identifier, {}).get("outcome") == "completed"
        ]
        if len(completed_ids) < len(segment_order):
            return {
                "action": "refill-frontier", "completed_ids": completed_ids,
                "running_ids": running_ids,
            }
        return _restore_or_return(plan, current)
    return _restore_or_return(plan, current)


def _parallel_finalization(
    state, pending_reason=None, missing_fields=None, brief=None,
):
    return {
        "parallel_execution_recorded": state == "recorded",
        "parallel_execution_state": state,
        "parallel_execution_pending_reason": pending_reason,
        "parallel_execution_missing_fields": missing_fields or [],
        "parallel_execution_brief": brief,
    }


def _finalize_parallel_execution(args, plan, result, next_state):
    if plan.get("protocol") != policy.PARALLEL_PROTOCOL:
        return None
    if next_state.get("action") not in ("return", "restore", "stop"):
        return _parallel_finalization("pending", "aggregate-not-ready")

    parallel_plan = plan.get("parallel", {})
    pending_brief = ledger.pending_parallel_brief(
        parallel_plan.get("effective_max_parallelism", 1),
        parallel_plan.get("requested_max_parallelism", 1),
    )
    events, warnings = ledger.read_events(args.ledger)
    segment_order = [item["segment_id"] for item in plan.get("segments", [])]
    planned = set(segment_order)
    starts = {
        item["segment_id"]: item for item in events
        if item.get("event") == "parallel_worker_start"
        and item.get("route_id") == plan["route_id"]
        and item.get("segment_id") in planned
    }
    finishes = {
        item["segment_id"]: item for item in events
        if item.get("event") == "parallel_worker_finish"
        and item.get("route_id") == plan["route_id"]
        and item.get("segment_id") in planned
    }
    if not starts:
        return _parallel_finalization(
            "pending", "missing-worker-start-events", segment_order, pending_brief,
        )
    if next_state.get("action") in ("return", "restore") and set(starts) != planned:
        missing = [identifier for identifier in segment_order if identifier not in starts]
        return _parallel_finalization(
            "pending", "missing-worker-start-events", missing, pending_brief,
        )
    unfinished = [identifier for identifier in starts if identifier not in finishes]
    if unfinished:
        return _parallel_finalization(
            "pending", "worker-results-still-pending", unfinished, pending_brief,
        )
    try:
        intervals = []
        for identifier in segment_order:
            if identifier not in starts:
                continue
            start = starts[identifier]
            finish = finishes[identifier]
            if finish["monotonic_ns"] <= start["monotonic_ns"]:
                raise ValueError("parallel worker interval must have positive duration")
            intervals.append({
                "segment_id": identifier,
                "started_monotonic_ns": start["monotonic_ns"],
                "result_received_monotonic_ns": finish["monotonic_ns"],
                "started_at": start["timestamp"],
                "result_received_at": finish["timestamp"],
                "outcome": finish["outcome"],
            })
        metrics = ledger.parallel_metrics_from_intervals(intervals)
        dispatched_ids = [identifier for identifier in segment_order if identifier in starts]
        skipped_ids = [identifier for identifier in segment_order if identifier not in starts]
        failed_intervals = [
            interval for interval in intervals if interval["outcome"] != "completed"
        ]
        aggregate_outcome = (
            failed_intervals[0]["outcome"] if failed_intervals else "completed"
        )
        if aggregate_outcome == "completed" and skipped_ids:
            raise ValueError("completed parallel execution contains skipped workers")
        effective_parallelism = plan.get("parallel", {}).get(
            "effective_max_parallelism"
        )
        if metrics["peak_concurrency"] > effective_parallelism:
            raise ValueError("observed peak concurrency exceeds current plan")
        event = {
            "event": "parallel_execution",
            "schema_version": ledger.PARALLEL_SCHEMA_VERSION,
            "route_id": plan["route_id"],
            "plan_hash": plan["plan_hash"],
            **metrics,
            "worker_intervals": intervals,
            "planned_ids": segment_order,
            "dispatched_ids": dispatched_ids,
            "skipped_ids": skipped_ids,
            "outcome": aggregate_outcome,
            "source": "task-metadata",
            "measurement_boundary": "dispatch-confirmed-to-result-received",
            "timing_provenance": ledger.PARALLEL_TIMING_PROVENANCE,
            "clock_source": ledger.PARALLEL_CLOCK_SOURCE,
        }
        appended = ledger.append_event(args.ledger, event)
    except (KeyError, TypeError, ValueError):
        return _parallel_finalization(
            "pending", "invalid-worker-timing-trace", brief=pending_brief,
        )
    recorded_event = event
    if not appended:
        stored_events, _ = ledger.read_events(args.ledger)
        recorded_event = next((
            item for item in reversed(stored_events)
            if item.get("event") == "parallel_execution"
            and item.get("route_id") == plan["route_id"]
            and ledger.is_verified_parallel_run(item)
        ), None)
        immutable_fields = (
            "schema_version", "route_id", "plan_hash", "wall_clock_seconds",
            "cumulative_worker_seconds", "peak_concurrency", "worker_count",
            "worker_intervals", "planned_ids", "dispatched_ids", "skipped_ids",
            "outcome", "source", "measurement_boundary", "timing_provenance",
            "clock_source",
        )
        if recorded_event is None or any(
            recorded_event.get(field) != event.get(field)
            for field in immutable_fields
        ):
            return _parallel_finalization(
                "pending", "recorded-aggregate-conflicts", brief=pending_brief,
            )
    brief = ledger.parallel_run_brief(recorded_event)
    response = (
        _parallel_finalization("recorded", brief=brief)
        if appended else _parallel_finalization("already-recorded", brief=brief)
    )
    response["ledger_warning_count"] = len(warnings)
    return response


def _canonical_finish_outcome(plan, segment, result, events):
    supplied = result.get("outcome")
    if supplied not in ledger.OUTCOMES:
        raise ValueError("finish requires a valid outcome")
    terminal = _terminal_results(plan, events)
    if segment["segment_id"] in terminal:
        recorded = terminal[segment["segment_id"]]
        identity = _identity(plan, segment)
        if (
            recorded.get("event") == "segment_result"
            and all(recorded.get(field) == value for field, value in identity.items())
            and recorded.get("outcome") == supplied
        ):
            return supplied
        raise ValueError("segment result conflicts with recorded result")
    if plan["protocol"] == policy.SEGMENTED_PROTOCOL:
        for planned in plan["segments"]:
            identifier = planned["segment_id"]
            previous = terminal.get(identifier)
            if previous is None:
                if identifier != segment["segment_id"]:
                    raise ValueError("finish segment does not match authoritative cursor")
                break
            if previous.get("outcome") != "completed":
                raise ValueError("sequential route already stopped on failure")
    elif plan["protocol"] == policy.PARALLEL_PROTOCOL:
        starts, finishes = _worker_events(events)
        identifier = segment["segment_id"]
        if identifier not in starts:
            raise ValueError("parallel finish requires a captured worker start")
        finish = finishes.get(identifier)
        if finish is None:
            raise ValueError("parallel finish requires a captured worker finish")
        captured = finish["outcome"]
        if supplied != captured:
            raise ValueError("finish outcome does not match captured worker result")
        return captured
    return supplied


def _execution_event(plan, segment, result, current, identity, events, outcome):
    model, effort, source, runtime_metadata = _observed_route(
        result, current, identity, plan["protocol"]
    )
    if not (model and effort and source):
        return None, runtime_metadata
    actual_route = _normalized_runtime_route(model, effort)
    if actual_route is None:
        raise ValueError("execution metadata contains an unsupported runtime route")
    target_route = (
        policy.normalize_model(segment.get("model")),
        policy.normalize_effort(segment.get("effort")),
    )
    decision = result.get("capability_decision")
    if actual_route != target_route:
        _validated_capability_decision(decision, plan, segment, actual_route)
    elif decision is not None:
        _validated_capability_decision(decision, plan, segment, actual_route)
    event = {
        "event": "execution", **identity,
        "model": actual_route[0], "effort": actual_route[1],
        "task_class": result.get("task_class", segment.get("task_kind", "unknown")),
        "outcome": outcome, "source": source,
        "verification": result.get("verification", "unknown"),
        "fallback_from": target_route[0] if actual_route != target_route else None,
        "fallback_to": actual_route[0] if actual_route != target_route else None,
        "fallback_reason": decision.get("reason") if decision is not None else None,
        "capability_decision": decision,
    }
    if plan["protocol"] == policy.PARALLEL_PROTOCOL:
        concurrency = _active_concurrency(events, segment["segment_id"])
        if concurrency is not None:
            event["concurrency"] = concurrency
    event = {key: value for key, value in event.items() if value is not None}
    ledger.validate_event(event)
    return event, runtime_metadata


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
        contract_version = (
            plan.get("parallel", {}).get("contract_version")
            if isinstance(plan.get("parallel"), dict) else None
        )
        if contract_version is not None:
            ledger.bind_route_contract(args.ledger, {
                "event": "route_contract", "route_id": plan["route_id"],
                "plan_hash": plan["plan_hash"], "protocol": plan["protocol"],
                "contract_version": contract_version,
                "source": ledger.ROUTE_CONTRACT_SOURCE,
            })
        identity = _identity(plan, segment)
        _validate_result_identity(result, identity)
    except ValueError as exc:
        raise SystemExit(f"finish state gate stopped: {exc}") from exc
    current = _current(args)
    events, warnings = _route_events(args.ledger, plan["route_id"])
    try:
        outcome = _canonical_finish_outcome(plan, segment, result, events)
        execution_event, runtime_metadata = _execution_event(
            plan, segment, result, current, identity, events, outcome
        )
    except ValueError as exc:
        raise SystemExit(f"finish state gate stopped: {exc}") from exc
    metrics_event = None
    metrics = result.get("metrics")
    if isinstance(metrics, dict):
        metrics_event = {
            "event": "routing_efficiency", "route_id": plan["route_id"],
            "segment_id": segment["segment_id"], "source": metrics.get("source"),
        }
        for field in ledger.EFFICIENCY_DURATIONS + ledger.EFFICIENCY_COUNTS + (
            "state_gate", "state_gate_reason",
        ):
            if metrics.get(field) is not None:
                metrics_event[field] = metrics[field]
        try:
            ledger.validate_event(metrics_event)
        except ValueError as exc:
            raise SystemExit(f"finish state gate stopped: {exc}") from exc
    claim_required = not (
        plan["protocol"] == policy.FAST_PROTOCOL
        and segment.get("dispatch") == "local"
        and result.get("capability_decision") is None
    )
    result_event = {
        "event": "segment_result", **identity,
        "protocol": plan["protocol"], "outcome": outcome,
    }
    decision = result.get("capability_decision")
    if decision is not None:
        result_event["capability_decision_hash"] = ledger.capability_decision_hash(decision)
    try:
        transaction = ledger.commit_segment_finish(
            args.ledger, result_event, [execution_event, metrics_event],
            claim_required=claim_required,
        )
    except ValueError as exc:
        raise SystemExit(f"finish state gate stopped: {exc}") from exc
    execution_recorded = transaction["execution_recorded"]
    metrics_recorded = transaction["metrics_recorded"]
    events, post_warnings = _route_events(args.ledger, plan["route_id"])
    next_state = _next_action(plan, current, events)
    response = {
        "ok": outcome == "completed",
        "execution_recorded": execution_recorded,
        "metrics_recorded": metrics_recorded,
        "claim_consumed": True,
        "finish_recovered": transaction["recovered"],
        "current": current,
        "execution_runtime_metadata": runtime_metadata,
        "ledger_warning_count": len(post_warnings),
        "next": next_state,
    }
    parallel_finalization = _finalize_parallel_execution(
        args, plan, result, next_state
    )
    if parallel_finalization is not None:
        response.update(parallel_finalization)
    print(json.dumps(response, ensure_ascii=False, sort_keys=True))


def parser():
    root = argparse.ArgumentParser()
    root.add_argument("--sessions-root", type=Path)
    root.add_argument("--no-runtime-detection", action="store_true")
    commands = root.add_subparsers(dest="command", required=True)
    starter = commands.add_parser("begin")
    starter.add_argument("--ledger", type=Path, required=True)
    starter.add_argument("--envelope-json", required=True)
    starter.add_argument("--trusted-dispatch-capacity-json")
    starter.set_defaults(func=begin)
    worker_started = commands.add_parser("worker-start")
    worker_started.add_argument("--ledger", type=Path, required=True)
    worker_started.add_argument("--route-id", required=True)
    worker_started.add_argument("--plan-hash", required=True)
    worker_started.add_argument("--segment-id", required=True)
    worker_started.add_argument("--attempt-id", required=True)
    worker_started.set_defaults(func=worker_start)
    worker_finished = commands.add_parser("worker-finish")
    worker_finished.add_argument("--ledger", type=Path, required=True)
    worker_finished.add_argument("--route-id", required=True)
    worker_finished.add_argument("--plan-hash", required=True)
    worker_finished.add_argument("--segment-id", required=True)
    worker_finished.add_argument("--attempt-id", required=True)
    worker_finished.add_argument("--outcome", choices=ledger.OUTCOMES, required=True)
    worker_finished.set_defaults(func=worker_finish)
    finisher = commands.add_parser("finish")
    finisher.add_argument("--ledger", type=Path, required=True)
    finisher.add_argument("--result-json", required=True)
    finisher.set_defaults(func=finish)
    return root


if __name__ == "__main__":
    arguments = parser().parse_args()
    arguments.func(arguments)
