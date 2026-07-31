#!/usr/bin/env python3
"""Combine deterministic Router state gates into one begin and one finish call."""

import argparse
import hashlib
import inspect
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import model_usage_ledger as ledger  # noqa: E402
import route_policy as policy  # noqa: E402


RUNTIME_STATE_SCHEMA_VERSION = 1
RUNTIME_STATE_DIR = "codex-auto-model-router-runtime-v1"


def _load(value, label):
    try:
        result = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid {label}: {exc}") from exc
    if not isinstance(result, dict):
        raise ValueError(f"{label} must be an object")
    return result


def _canonical_json(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _state_key(route_id):
    if not isinstance(route_id, str) or not route_id:
        raise ValueError("runtime state requires route_id")
    return hashlib.sha256(route_id.encode("utf-8")).hexdigest()


def _state_roots(args):
    override = getattr(args, "state_root", None)
    if override is not None:
        root = Path(override)
        return [root]
    primary = Path(args.ledger).parent / "model-routing-runtime"
    fallback = Path(tempfile.gettempdir()) / RUNTIME_STATE_DIR
    return [primary] if primary == fallback else [primary, fallback]


def _state_path(root, route_id):
    return root / f"{_state_key(route_id)}.json"


def _state_lock_path(root, route_id):
    return root / f"{_state_key(route_id)}.lock"


def _secure_directory(path):
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass


def _atomic_write_json(path, value):
    _secure_directory(path.parent)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.stem}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(_canonical_json(value) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        try:
            temporary_path.chmod(0o600)
        except OSError:
            pass
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _read_state_file(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"runtime state is unreadable: {type(exc).__name__}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != RUNTIME_STATE_SCHEMA_VERSION:
        raise ValueError("runtime state has an unsupported schema")
    return value


def _locate_state(args, route_id):
    candidates = []
    failures = []
    for index, root in enumerate(_state_roots(args)):
        path = _state_path(root, route_id)
        if path.exists():
            try:
                state = _read_state_file(path)
            except ValueError as exc:
                failures.append(str(exc))
                continue
            if state.get("route_id") != route_id:
                raise ValueError("runtime state route_id mismatch")
            candidates.append((int(state.get("revision", 0)), -index, state, path))
    if candidates:
        _, _, state, path = max(candidates, key=lambda item: item[:2])
        return state, path
    if failures:
        raise ValueError(failures[0])
    return None, None


def _write_state_at(path, state):
    root = path.parent
    _secure_directory(root)
    lock_path = _state_lock_path(root, state["route_id"])
    with lock_path.open("a+", encoding="utf-8") as handle:
        with ledger.locked_file(handle, exclusive=True):
            existing = _read_state_file(path)
            if existing is not None and existing.get("route_id") != state.get("route_id"):
                raise ValueError("runtime state route_id mismatch")
            state["revision"] = max(
                int(state.get("revision", 0)),
                int((existing or {}).get("revision", 0)),
            ) + 1
            _atomic_write_json(path, state)


def _persist_new_state(args, state):
    failures = []
    for root in _state_roots(args):
        path = _state_path(root, state["route_id"])
        try:
            _write_state_at(path, state)
            return path, failures
        except OSError as exc:
            failures.append(f"{path}:{type(exc).__name__}")
    raise ValueError(
        "runtime state cannot be persisted"
        + (f" ({'; '.join(failures)})" if failures else "")
    )


def _fallback_ledger(args, route_id):
    root = _state_roots(args)[-1] / "ledgers"
    _secure_directory(root)
    return root / f"{_state_key(route_id)}.jsonl"


def _new_runtime_state(plan, segment, primary_ledger):
    canonical_plan = json.loads(_canonical_json(plan))
    return {
        "schema_version": RUNTIME_STATE_SCHEMA_VERSION,
        "revision": 0,
        "route_id": plan["route_id"],
        "plan_hash": plan["plan_hash"],
        "protocol": plan["protocol"],
        "attempts": {
            item["segment_id"]: item["attempt_id"]
            for item in canonical_plan.get("segments", [])
        },
        "last_segment_id": segment["segment_id"],
        "last_attempt_id": segment["attempt_id"],
        "original": canonical_plan.get("original", {}),
        "restore_required": bool(canonical_plan.get("restore_required")),
        "canonical_plan": canonical_plan,
        "primary_ledger": str(Path(primary_ledger).resolve()),
        "effective_ledger": str(Path(primary_ledger).resolve()),
        "ledger_fallback": False,
        "claim": None,
        "segment_results": {},
        "finishes": {},
        "restore": None,
        "warnings": [],
    }


def _validate_state_identity(state, route_id, segment_id, attempt_id):
    for field, value in {"route_id": route_id}.items():
        if not isinstance(value, str) or not value:
            raise ValueError(f"runtime identity requires {field}")
        if state.get(field) != value:
            raise ValueError(f"runtime state {field} mismatch")
    if not isinstance(segment_id, str) or not segment_id:
        raise ValueError("runtime identity requires segment_id")
    if not isinstance(attempt_id, str) or not attempt_id:
        raise ValueError("runtime identity requires attempt_id")
    attempts = state.get("attempts")
    if not isinstance(attempts, dict) or segment_id not in attempts:
        raise ValueError("runtime state segment_id mismatch")
    if attempts.get(segment_id) != attempt_id:
        raise ValueError("runtime state attempt_id mismatch")
    plan = state.get("canonical_plan")
    if not isinstance(plan, dict) or plan.get("plan_hash") != state.get("plan_hash"):
        raise ValueError("runtime state canonical plan mismatch")
    return plan


def _bind_or_verify_state(args, plan, segment):
    state, path = _locate_state(args, plan["route_id"])
    candidate = _new_runtime_state(plan, segment, args.ledger)
    if state is None:
        path, failures = _persist_new_state(args, candidate)
        if failures:
            candidate["warnings"].append(
                "project runtime state unavailable; using isolated temporary state"
            )
            _write_state_at(path, candidate)
        return candidate, path
    _validate_state_identity(
        state, plan["route_id"], segment["segment_id"], segment["attempt_id"]
    )
    if _canonical_json(state["canonical_plan"]) != _canonical_json(candidate["canonical_plan"]):
        raise ValueError("runtime state canonical plan conflicts with begin plan")
    state["last_segment_id"] = segment["segment_id"]
    state["last_attempt_id"] = segment["attempt_id"]
    _write_state_at(path, state)
    return state, path


def _effective_ledger(state):
    return Path(state["effective_ledger"])


def _switch_to_fallback_ledger(args, state, state_path, reason):
    fallback = _fallback_ledger(args, state["route_id"])
    state["effective_ledger"] = str(fallback.resolve())
    state["ledger_fallback"] = True
    warning = f"project ledger unavailable; using isolated temporary ledger ({reason})"
    if warning not in state["warnings"]:
        state["warnings"].append(warning)
    _write_state_at(state_path, state)
    return fallback


def _write_state_after_completion(args, state_path, state):
    """Persist coordinator state without blocking an already completed project result."""
    try:
        if state_path is None:
            state_path, failures = _persist_new_state(args, state)
            if failures:
                state["warnings"].append(
                    "project runtime state unavailable; using isolated temporary state"
                )
                _write_state_at(state_path, state)
        else:
            _write_state_at(state_path, state)
        return state_path, []
    except (OSError, ValueError) as exc:
        fallback_path = _state_path(_state_roots(args)[-1], state["route_id"])
        if state_path != fallback_path:
            try:
                warning = (
                    "runtime state became unavailable after project completion; "
                    "continuing with isolated temporary state"
                )
                if warning not in state["warnings"]:
                    state["warnings"].append(warning)
                _write_state_at(fallback_path, state)
                return fallback_path, [warning]
            except (OSError, ValueError):
                pass
        return state_path, [
            "runtime state could not be updated after project completion: "
            f"{type(exc).__name__}"
        ]


def _route_events_safe(path, route_id):
    try:
        return _route_events(path, route_id)
    except OSError:
        return [], ["ledger-unreadable"]


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


def _record_gate_stop(args, envelope, reason, ledger_path=None):
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
    try:
        return ledger.append_event(ledger_path or args.ledger, event)
    except OSError:
        return False


def _route_events(path, route_id):
    events, warnings = ledger.read_events(path)
    return [item for item in events if item.get("route_id") == route_id], warnings


def _state_result_events(state):
    if not isinstance(state, dict):
        return []
    return [
        item["event"]
        for item in state.get("segment_results", {}).values()
        if isinstance(item, dict) and isinstance(item.get("event"), dict)
    ]


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


def _hydrate_envelope_from_state(envelope, state):
    """Restore deterministic envelope fields lost to context compaction."""
    if not isinstance(state, dict):
        return envelope
    plan = state["canonical_plan"]
    original = plan.get("original", {})
    defaults = {
        "route_id": plan.get("route_id"),
        "protocol": plan.get("protocol"),
        "restore_required": plan.get("restore_required"),
        "segment_budget": plan.get("segment_budget"),
        "switch_budget": plan.get("switch_budget"),
        "budget_source": plan.get("budget_source"),
        "original_model": original.get("model"),
        "original_effort": original.get("effort"),
    }
    for field, value in defaults.items():
        if envelope.get(field) is None and value is not None:
            envelope[field] = value
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
    state = None
    state_path = None
    effective_ledger = Path(args.ledger)
    warnings = []
    try:
        envelope = _load(args.envelope_json, "envelope")
        plan = envelope.get("plan")
        route_id = (
            plan.get("route_id") if isinstance(plan, dict)
            else envelope.get("route_id")
        )
        if route_id:
            state, state_path = _locate_state(args, route_id)
        if not isinstance(plan, dict) and state is not None:
            plan = state["canonical_plan"]
            envelope["plan"] = plan
        if not isinstance(plan, dict):
            raise ValueError(
                "first begin requires a canonical plan; compact retries require persisted state"
            )
        route_id = plan.get("route_id")
        if state is not None:
            envelope = _hydrate_envelope_from_state(envelope, state)
            effective_ledger = _effective_ledger(state)
        events, warnings = (
            _route_events_safe(effective_ledger, route_id) if route_id else ([], [])
        )
        if state is not None:
            stored_events = _state_result_events(state)
            existing_ids = {item.get("event_id") for item in events}
            events.extend(
                item for item in stored_events
                if item.get("event_id") not in existing_ids
            )
        envelope = _authoritative_envelope(envelope, events)
        try:
            anchor = (
                ledger.route_contract(effective_ledger, route_id) if route_id else None
            )
        except OSError:
            anchor = None
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
        _record_gate_stop(args, envelope, exc, effective_ledger)
        raise SystemExit(f"state gate stopped: {exc}") from exc
    try:
        state, state_path = _bind_or_verify_state(args, plan, segment)
        effective_ledger = _effective_ledger(state)
    except ValueError as exc:
        raise SystemExit(f"state gate stopped: {exc}") from exc
    if contract_version is not None:
        contract_event = {
            "event": "route_contract", "route_id": plan["route_id"],
            "plan_hash": plan["plan_hash"], "protocol": plan["protocol"],
            "contract_version": contract_version,
            "source": ledger.ROUTE_CONTRACT_SOURCE,
        }
        try:
            ledger.bind_route_contract(effective_ledger, contract_event)
        except OSError as exc:
            try:
                effective_ledger = _switch_to_fallback_ledger(
                    args, state, state_path, type(exc).__name__
                )
                ledger.bind_route_contract(effective_ledger, contract_event)
            except OSError as fallback_exc:
                raise SystemExit(
                    "state gate stopped: runtime ledger and isolated fallback are unavailable"
                ) from fallback_exc
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
                effective_ledger, claim_event,
                allow_prepared_recovery=plan["protocol"] == policy.PARALLEL_PROTOCOL,
                reservation_event=reservation_event,
            )
        except OSError as exc:
            try:
                effective_ledger = _switch_to_fallback_ledger(
                    args, state, state_path, type(exc).__name__
                )
                claim_state = ledger.prepare_segment_claim(
                    effective_ledger, claim_event,
                    allow_prepared_recovery=plan["protocol"] == policy.PARALLEL_PROTOCOL,
                    reservation_event=reservation_event,
                )
            except OSError as fallback_exc:
                raise SystemExit(
                    "state gate stopped: runtime ledger and isolated fallback are unavailable"
                ) from fallback_exc
        except ValueError as exc:
            _record_gate_stop(args, envelope, exc, effective_ledger)
            raise SystemExit(f"state gate stopped: {exc}") from exc
        claimed = claim_state == "prepared"
        if claim_state not in ("prepared", "recovered"):
            _record_gate_stop(
                args, envelope, f"segment-claim-{claim_state}", effective_ledger
            )
            message = (
                "segment already claimed" if claim_state == "already-claimed"
                else f"segment claim is {claim_state}"
            )
            raise SystemExit(f"state gate stopped: {message}")
    state.setdefault("claims", {})[segment["segment_id"]] = {
        "attempt_id": segment["attempt_id"],
        "plan_hash": plan["plan_hash"],
        "required": claim_required,
        "state": claim_state,
    }
    state["effective_ledger"] = str(effective_ledger.resolve())
    _write_state_at(state_path, state)
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
        "runtime_state_persisted": True,
        "ledger_fallback": state.get("ledger_fallback", False),
        "warnings": state.get("warnings", []) + warnings,
        "context_capsule": policy.context_capsule(plan, segment["segment_id"]),
    }, ensure_ascii=False, sort_keys=True))


def _capture_worker_event(args, event_type, outcome=None):
    try:
        state, state_path = _locate_state(args, args.route_id)
    except ValueError as exc:
        raise SystemExit(f"worker state gate stopped: {exc}") from exc
    event_ledger = Path(args.ledger)
    if state is not None:
        try:
            _validate_state_identity(
                state, args.route_id, args.segment_id, args.attempt_id
            )
        except ValueError as exc:
            raise SystemExit(f"worker state gate stopped: {exc}") from exc
        if state.get("plan_hash") != args.plan_hash:
            raise SystemExit(
                "worker state gate stopped: runtime state plan hash mismatch"
            )
        event_ledger = _effective_ledger(state)
    try:
        anchor = ledger.route_contract(event_ledger, args.route_id)
    except OSError:
        anchor = None
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
        appended = ledger.append_event(event_ledger, event)
    except OSError as exc:
        if state is None:
            raise SystemExit(
                f"worker state gate stopped: ledger unavailable ({type(exc).__name__})"
            ) from exc
        try:
            event_ledger = _switch_to_fallback_ledger(
                args, state, state_path, type(exc).__name__
            )
            appended = ledger.append_event(event_ledger, event)
        except OSError as fallback_exc:
            raise SystemExit(
                "worker state gate stopped: runtime ledger and isolated fallback "
                "are unavailable"
            ) from fallback_exc
    except ValueError as exc:
        raise SystemExit(f"worker state gate stopped: {exc}") from exc
    events, _ = _route_events(event_ledger, args.route_id)
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
    model_fallback = actual_route[0] != target_route[0]
    if model_fallback:
        _validated_capability_decision(decision, plan, segment, actual_route)
    elif decision is not None:
        _validated_capability_decision(decision, plan, segment, actual_route)
    event = {
        "event": "execution", **identity,
        "model": actual_route[0], "effort": actual_route[1],
        "task_class": result.get("task_class", segment.get("task_kind", "unknown")),
        "outcome": outcome, "source": source,
        "verification": result.get("verification", "unknown"),
        "fallback_from": target_route[0] if model_fallback else None,
        "fallback_to": actual_route[0] if model_fallback else None,
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


def _segment_for_identity(plan, segment_id):
    return next(
        (
            item for item in plan.get("segments", [])
            if item.get("segment_id") == segment_id
        ),
        None,
    )


def _finish_identity(result, supplied_plan):
    route_id = result.get("route_id")
    segment_id = result.get("segment_id")
    attempt_id = result.get("attempt_id")
    if isinstance(supplied_plan, dict):
        route_id = route_id or supplied_plan.get("route_id")
        segment = _segment_for_identity(supplied_plan, segment_id)
        if segment is not None:
            attempt_id = attempt_id or segment.get("attempt_id")
    return route_id, segment_id, attempt_id


def _degraded_finish(result, reason):
    outcome = result.get("outcome")
    if outcome not in ledger.OUTCOMES:
        raise SystemExit("finish requires a valid outcome")
    response = {
        "ok": outcome == "completed",
        "state_gate": "degraded",
        "execution_recorded": False,
        "metrics_recorded": False,
        "claim_consumed": False,
        "finish_recovered": False,
        "ledger_warning_count": 1,
        "warnings": [reason],
        "next": {"action": "return", "reason": "runtime-state-unavailable"},
    }
    print(json.dumps(response, ensure_ascii=False, sort_keys=True))


def finish(args):
    result = _load(args.result_json, "result")
    supplied_plan = result.get("plan")
    route_id, segment_id, attempt_id = _finish_identity(result, supplied_plan)
    if not route_id or not segment_id or not attempt_id:
        _degraded_finish(
            result,
            "finish identity is incomplete; project result returned without ledger or Restore",
        )
        return
    try:
        state, state_path = _locate_state(args, route_id)
    except ValueError as exc:
        raise SystemExit(f"finish state gate stopped: {exc}") from exc
    legacy_recovered = False
    if state is None:
        if not isinstance(supplied_plan, dict):
            _degraded_finish(
                result,
                "persisted runtime state is missing; project result returned without ledger or Restore",
            )
            return
        segment = _segment_for_identity(supplied_plan, segment_id)
        if segment is None:
            raise SystemExit("finish segment is missing from legacy plan")
        attempt_id = attempt_id or segment.get("attempt_id")
        try:
            _validate_finish_plan(supplied_plan, segment)
            state, state_path = _bind_or_verify_state(args, supplied_plan, segment)
        except ValueError as exc:
            if "runtime state cannot be persisted" not in str(exc):
                raise SystemExit(f"finish state gate stopped: {exc}") from exc
            state = _new_runtime_state(supplied_plan, segment, args.ledger)
            state["warnings"].append(
                "runtime state unavailable after project completion; using in-memory finish"
            )
            state_path = None
        state["warnings"].append(
            "runtime state was recovered from a legacy full-plan finish payload"
        )
        state_path, state_warnings = _write_state_after_completion(
            args, state_path, state
        )
        state["warnings"].extend(
            warning for warning in state_warnings
            if warning not in state["warnings"]
        )
        legacy_recovered = True
    try:
        plan = _validate_state_identity(state, route_id, segment_id, attempt_id)
    except ValueError as exc:
        raise SystemExit(f"finish state gate stopped: {exc}") from exc
    segment = _segment_for_identity(plan, segment_id)
    if segment is None:
        raise SystemExit("finish state gate stopped: persisted Segment is missing")
    if isinstance(supplied_plan, dict) and (
        supplied_plan.get("route_id") != plan.get("route_id")
        or supplied_plan.get("plan_hash") != plan.get("plan_hash")
    ):
        raise SystemExit("finish state gate stopped: supplied legacy plan identity mismatch")
    result = dict(result)
    result["route_id"] = route_id
    result["segment_id"] = segment_id
    result["attempt_id"] = attempt_id
    result["plan_hash"] = plan["plan_hash"]
    finishes = state.setdefault("finishes", {})
    recorded_finish = finishes.get(segment_id)
    if recorded_finish is not None:
        if recorded_finish.get("outcome") != result.get("outcome"):
            raise SystemExit("finish state gate stopped: finish outcome conflicts with persisted result")
        response = dict(recorded_finish["response"])
        response.update({
            "execution_recorded": False,
            "metrics_recorded": False,
            "finish_recovered": True,
            "claim_consumed": True,
        })
        print(json.dumps(response, ensure_ascii=False, sort_keys=True))
        return
    try:
        identity = _identity(plan, segment)
        _validate_result_identity(result, identity)
    except ValueError as exc:
        raise SystemExit(f"finish state gate stopped: {exc}") from exc
    current = _current(args)
    effective_ledger = _effective_ledger(state)
    pre_ledger_warnings = []
    parallel_contract = plan.get("parallel", {}).get("contract_version")
    if legacy_recovered and parallel_contract is not None:
        try:
            ledger.bind_route_contract(effective_ledger, {
                "event": "route_contract",
                "route_id": plan["route_id"],
                "plan_hash": plan["plan_hash"],
                "protocol": plan["protocol"],
                "contract_version": parallel_contract,
                "source": ledger.ROUTE_CONTRACT_SOURCE,
            })
        except OSError as exc:
            pre_ledger_warnings.append(
                "route contract ledger write failed after project completion: "
                f"{type(exc).__name__}"
            )
        except ValueError as exc:
            raise SystemExit(f"finish state gate stopped: {exc}") from exc
    events, warnings = _route_events_safe(effective_ledger, plan["route_id"])
    stored_events = _state_result_events(state)
    existing_ids = {item.get("event_id") for item in events}
    events.extend(
        item for item in stored_events if item.get("event_id") not in existing_ids
    )
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
    ledger_warnings = pre_ledger_warnings + list(warnings)
    try:
        transaction = ledger.commit_segment_finish(
            effective_ledger, result_event, [execution_event, metrics_event],
            claim_required=claim_required,
        )
    except OSError as exc:
        transaction = {
            "result_recorded": False, "execution_recorded": False,
            "metrics_recorded": False, "recovered": False,
        }
        ledger_warnings.append(
            f"ledger write failed after project completion: {type(exc).__name__}"
        )
    except ValueError as exc:
        persisted_claim = state.get("claims", {}).get(segment_id)
        if (
            "matching segment claim" in str(exc)
            and isinstance(persisted_claim, dict)
            and persisted_claim.get("attempt_id") == attempt_id
            and persisted_claim.get("state") in ("prepared", "recovered")
        ):
            transaction = {
                "result_recorded": False, "execution_recorded": False,
                "metrics_recorded": False, "recovered": False,
            }
            ledger_warnings.append(
                "ledger claim disappeared after begin; persisted runtime identity preserved completion"
            )
        else:
            raise SystemExit(f"finish state gate stopped: {exc}") from exc
    execution_recorded = transaction["execution_recorded"]
    metrics_recorded = transaction["metrics_recorded"]
    stored_result_event = dict(result_event)
    ledger._prepare_event(stored_result_event)
    state.setdefault("segment_results", {})[segment_id] = {
        "outcome": outcome,
        "event": stored_result_event,
    }
    events, post_warnings = _route_events_safe(effective_ledger, plan["route_id"])
    events.extend(
        item for item in _state_result_events(state)
        if item.get("event_id") not in {event.get("event_id") for event in events}
    )
    next_state = _next_action(plan, current, events)
    response = {
        "ok": outcome == "completed",
        "execution_recorded": execution_recorded,
        "metrics_recorded": metrics_recorded,
        "claim_consumed": True,
        "finish_recovered": transaction["recovered"],
        "current": current,
        "execution_runtime_metadata": runtime_metadata,
        "ledger_warning_count": len(post_warnings) + len(ledger_warnings),
        "runtime_state_recovered_from_legacy_plan": legacy_recovered,
        "warnings": state.get("warnings", []) + ledger_warnings + post_warnings,
        "next": next_state,
    }
    try:
        runtime_args = SimpleNamespace(**vars(args))
        runtime_args.ledger = effective_ledger
        parallel_finalization = _finalize_parallel_execution(
            runtime_args, plan, result, next_state
        )
    except OSError:
        parallel_finalization = (
            _parallel_finalization(
                "pending", "ledger-unavailable-after-completion"
            )
            if plan.get("protocol") == policy.PARALLEL_PROTOCOL else None
        )
    if parallel_finalization is not None:
        response.update(parallel_finalization)
    finishes[segment_id] = {
        "outcome": outcome,
        "response": response,
    }
    if next_state.get("action") == "restore":
        state["restore"] = {
            "status": "pending",
            "model": next_state.get("model"),
            "effort": next_state.get("effort"),
            "after_segment_id": segment_id,
            "attempt_id": attempt_id,
        }
    state_path, state_warnings = _write_state_after_completion(
        args, state_path, state
    )
    if state_warnings:
        response["warnings"].extend(
            warning for warning in state_warnings
            if warning not in response["warnings"]
        )
        response["ledger_warning_count"] += len(state_warnings)
        finishes[segment_id]["response"] = response
    print(json.dumps(response, ensure_ascii=False, sort_keys=True))


def _degraded_restore(reason):
    print(json.dumps({
        "ok": True,
        "state_gate": "degraded",
        "restored": False,
        "restore_recovered": False,
        "warnings": [reason],
        "next": {"action": "return", "reason": "restore-state-unavailable"},
    }, ensure_ascii=False, sort_keys=True))


def restore(args):
    """Verify Restore from persisted begin/finish state using identity only."""
    try:
        state, state_path = _locate_state(args, args.route_id)
    except ValueError as exc:
        raise SystemExit(f"restore state gate stopped: {exc}") from exc
    if state is None:
        _degraded_restore(
            "persisted runtime state is missing; project result returned without "
            "blocking on Restore"
        )
        return
    try:
        _validate_state_identity(
            state, args.route_id, args.segment_id, args.attempt_id
        )
    except ValueError as exc:
        raise SystemExit(f"restore state gate stopped: {exc}") from exc
    finished = state.get("finishes", {}).get(args.segment_id)
    if not isinstance(finished, dict):
        _degraded_restore(
            "persisted finish result is missing; Restore was not recorded"
        )
        return
    original = state.get("original", {})
    target = {
        "model": original.get("model"),
        "effort": original.get("effort"),
    }
    recorded = state.get("restore")
    if isinstance(recorded, dict) and recorded.get("status") == "completed":
        restored = recorded.get("reason") != "not-required"
        print(json.dumps({
            "ok": True,
            "state_gate": "passed",
            "restored": restored,
            "restore_recovered": True,
            "original": target,
            "warnings": state.get("warnings", []),
            "next": {"action": "return"},
        }, ensure_ascii=False, sort_keys=True))
        return
    if isinstance(recorded, dict) and recorded.get("status") == "warning":
        print(json.dumps({
            "ok": True,
            "state_gate": "degraded",
            "restored": False,
            "restore_recovered": True,
            "original": target,
            "current": recorded.get("current"),
            "warnings": state.get("warnings", []) + [recorded.get("warning")],
            "next": {"action": "return", "reason": "restore-unverified"},
        }, ensure_ascii=False, sort_keys=True))
        return
    if not state.get("restore_required"):
        state["restore"] = {
            "status": "completed",
            "reason": "not-required",
            "after_segment_id": args.segment_id,
            "attempt_id": args.attempt_id,
        }
        state_path, write_warnings = _write_state_after_completion(
            args, state_path, state
        )
        print(json.dumps({
            "ok": True,
            "state_gate": "passed",
            "restored": False,
            "restore_recovered": False,
            "original": target,
            "warnings": state.get("warnings", []) + write_warnings,
            "next": {"action": "return"},
        }, ensure_ascii=False, sort_keys=True))
        return
    if not isinstance(recorded, dict) or recorded.get("status") != "pending":
        _degraded_restore(
            "Restore is not pending for this completed Segment; project result "
            "returned without changing the route"
        )
        return
    if (
        recorded.get("after_segment_id") != args.segment_id
        or recorded.get("attempt_id") != args.attempt_id
    ):
        raise SystemExit("restore state gate stopped: pending Restore identity mismatch")
    current = _current(args)
    actual = (
        _normalized_runtime_route(current.get("model"), current.get("effort"))
        if current.get("status") == "verified" else None
    )
    expected = _normalized_runtime_route(target["model"], target["effort"])
    if actual is None or expected is None or actual != expected:
        warning = (
            "Restore could not be verified; completed project result is returned "
            "without retrying or reconstructing the plan"
        )
        state["restore"] = {
            "status": "warning",
            "after_segment_id": args.segment_id,
            "attempt_id": args.attempt_id,
            "current": current,
            "warning": warning,
        }
        state_path, write_warnings = _write_state_after_completion(
            args, state_path, state
        )
        print(json.dumps({
            "ok": True,
            "state_gate": "degraded",
            "restored": False,
            "restore_recovered": False,
            "original": target,
            "current": current,
            "warnings": state.get("warnings", []) + [warning] + write_warnings,
            "next": {"action": "return", "reason": "restore-unverified"},
        }, ensure_ascii=False, sort_keys=True))
        return
    state["restore"] = {
        "status": "completed",
        "after_segment_id": args.segment_id,
        "attempt_id": args.attempt_id,
        "model": expected[0],
        "effort": expected[1],
    }
    state_path, write_warnings = _write_state_after_completion(
        args, state_path, state
    )
    print(json.dumps({
        "ok": True,
        "state_gate": "passed",
        "restored": True,
        "restore_recovered": False,
        "original": target,
        "current": current,
        "warnings": state.get("warnings", []) + write_warnings,
        "next": {"action": "return"},
    }, ensure_ascii=False, sort_keys=True))


def parser():
    root = argparse.ArgumentParser()
    root.add_argument("--sessions-root", type=Path)
    root.add_argument("--no-runtime-detection", action="store_true")
    root.add_argument("--state-root", type=Path)
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
    restorer = commands.add_parser("restore")
    restorer.add_argument("--ledger", type=Path, required=True)
    restorer.add_argument("--route-id", required=True)
    restorer.add_argument("--segment-id", required=True)
    restorer.add_argument("--attempt-id", required=True)
    restorer.set_defaults(func=restore)
    return root


if __name__ == "__main__":
    arguments = parser().parse_args()
    arguments.func(arguments)
