#!/usr/bin/env python3
"""Safely append, aggregate, and render the model-routing usage ledger."""

import argparse
import hashlib
import json
import math
import os
import uuid
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None

try:
    import msvcrt
except ImportError:  # POSIX
    msvcrt = None


EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")
MODES = ("assess", "apply", "query", "record", "retune")
OUTCOMES = ("completed", "failed", "escalated", "reworked", "cancelled")
SOURCES = ("user-confirmed", "task-metadata")
PARALLEL_MEASUREMENT_BOUNDARIES = ("parallel-run",)
PARALLEL_SCHEMA_VERSION = 2
PARALLEL_TIMING_PROVENANCE = "coordinator-monotonic-v1"
PARALLEL_CLOCK_SOURCE = "python-monotonic-ns"
ROUTE_CONTRACT_SOURCE = "router-runtime"
VERIFICATIONS = ("deterministic", "manual", "none", "unknown")
EFFICIENCY_DURATIONS = (
    "routing_seconds", "queue_wait_seconds", "executor_start_seconds",
    "model_switch_seconds", "restore_seconds", "useful_execution_seconds",
)
EFFICIENCY_COUNTS = ("model_round_trips", "tool_round_trips")
USAGE_START = "<!-- MODEL_USAGE_START -->"
USAGE_END = "<!-- MODEL_USAGE_END -->"
GPT56_MODELS = ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna")
GPT55_MODEL = "gpt-5.5"
CAPABILITY_DECISION_SOURCE = "capability-interface"


def resolve_ledger_path(repository):
    current = Path(repository).expanduser().resolve()
    if current.is_file():
        current = current.parent
    fallback = current
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate / ".codex" / "model-routing-history.jsonl"
    return fallback / ".codex" / "model-routing-history.jsonl"


def _brief_number(value, digits):
    if value is None:
        return "—"
    return f"{round(value, digits):g}"


def _rounded_integer(value):
    """Round display-only values without changing stored timing precision."""
    return int(math.floor(value + 0.5))


def _brief_duration(seconds):
    total = _rounded_integer(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}小时{minutes}分{seconds}秒"
    if minutes:
        return f"{minutes}分{seconds}秒"
    return f"{seconds}秒"


def parallel_time_saving_estimate(run):
    """Estimate saved time using concatenated task intervals as a serial proxy.

    This is not controlled serial/parallel A/B evidence. The intervals span
    dispatch confirmation through result receipt and can include reasoning,
    tools, and return waiting; they are not pure model-compute measurements.
    """
    worker = run["cumulative_worker_seconds"]
    if worker <= 0:
        return None
    return (1 - run["wall_clock_seconds"] / worker) * 100


def parallel_run_brief(run):
    wall = run["wall_clock_seconds"]
    worker = run["cumulative_worker_seconds"]
    peak = run["peak_concurrency"]
    visible_peak = peak + 1  # Include the coordinator in user-facing totals.
    estimate = parallel_time_saving_estimate(run)
    utilization = (
        (worker + wall) * 100 / (visible_peak * wall) if wall > 0 else 0
    )
    return (
        f"并发：峰值 {visible_peak}（含主任务）｜实际用时：{_brief_duration(wall)}｜"
        f"并行任务累计用时：{_brief_duration(worker)}｜"
        f"并行省时估算：{_rounded_integer(estimate) if estimate is not None else 0}%｜"
        f"槽位利用：{_rounded_integer(utilization)}%"
    )


def pending_parallel_brief(effective, requested):
    return f"并发计划：{effective + 1} 个任务（含主任务）｜测量：待记录"


def parallel_metrics_from_intervals(intervals):
    """Derive every aggregate from coordinator-captured worker intervals."""
    if not intervals:
        raise ValueError("parallel execution requires worker intervals")
    starts = [item["started_monotonic_ns"] for item in intervals]
    finishes = [item["result_received_monotonic_ns"] for item in intervals]
    if any(end <= start for start, end in zip(starts, finishes)):
        raise ValueError("parallel worker interval must have positive duration")
    points = []
    for start, end in zip(starts, finishes):
        points.extend(((start, 1), (end, -1)))
    active = peak = 0
    for _, delta in sorted(points, key=lambda item: (item[0], item[1])):
        active += delta
        peak = max(peak, active)
    first = min(starts)
    last = max(finishes)
    wall = (last - first) / 1_000_000_000
    worker = sum(end - start for start, end in zip(starts, finishes)) / 1_000_000_000
    return {
        "wall_clock_seconds": round(wall, 9),
        "cumulative_worker_seconds": round(worker, 9),
        "peak_concurrency": peak,
        "worker_count": len(intervals),
    }


def is_verified_parallel_run(event):
    return (
        event.get("event") == "parallel_execution"
        and event.get("schema_version") == PARALLEL_SCHEMA_VERSION
        and event.get("timing_provenance") == PARALLEL_TIMING_PROVENANCE
        and event.get("clock_source") == PARALLEL_CLOCK_SOURCE
        and isinstance(event.get("worker_intervals"), list)
        and bool(event["worker_intervals"])
    )


@contextmanager
def locked_file(handle, exclusive):
    if fcntl is not None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return
    if msvcrt is not None:
        handle.seek(0)
        mode = msvcrt.LK_LOCK if exclusive else msvcrt.LK_RLCK
        msvcrt.locking(handle.fileno(), mode, 1)
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    raise RuntimeError("no supported file-lock implementation")


def now():
    return datetime.now(timezone.utc).isoformat()


def _is_gpt55_model(model):
    normalized = str(model or "").strip().lower().replace("_", "-")
    return normalized.startswith("gpt-5.5") or normalized.startswith("gpt 5.5")


def capability_decision_hash(decision):
    encoded = json.dumps(
        decision, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_capability_decision(decision, identity=None, target=None, execution=None):
    """Validate identity-bound, pre-execution model availability evidence."""
    if not isinstance(decision, dict) or decision.get("schema_version") != 1:
        raise ValueError("GPT-5.5 execution requires capability_decision schema_version=1")
    if decision.get("verified") is not True or decision.get("source") != CAPABILITY_DECISION_SOURCE:
        raise ValueError("GPT-5.5 capability_decision must be verified capability-interface evidence")
    if identity is not None and any(
        decision.get(field) != expected for field, expected in identity.items()
    ):
        raise ValueError("GPT-5.5 capability_decision identity mismatch")
    if target is not None and (
        decision.get("target_model") != target[0]
        or decision.get("target_effort") != target[1]
    ):
        raise ValueError("GPT-5.5 capability_decision target mismatch")
    if execution is not None and (
        decision.get("execution_model") != execution[0]
        or decision.get("execution_effort") != execution[1]
    ):
        raise ValueError("GPT-5.5 capability_decision execution mismatch")
    if decision.get("reason") != "gpt56-family-unavailable":
        raise ValueError("GPT-5.5 capability_decision requires gpt56-family-unavailable")

    complete_surface = decision.get("availability_complete") is True
    available = decision.get("available_models")
    complete_surface = complete_surface and isinstance(available, list) and all(
        isinstance(model, str) and model for model in available
    )
    if complete_surface:
        normalized = {model.strip().lower().replace("_", "-") for model in available}
        complete_surface = GPT55_MODEL in normalized and not any(
            model in normalized for model in GPT56_MODELS
        )

    rejections = decision.get("gpt56_rejections")
    complete_rejections = isinstance(rejections, dict) and set(rejections) == set(GPT56_MODELS)
    if complete_rejections:
        complete_rejections = all(
            value == "unavailable" for value in rejections.values()
        )
    if not (complete_surface or complete_rejections):
        raise ValueError(
            "GPT-5.5 capability_decision requires a complete model list or all GPT-5.6 rejections"
        )
    return decision


def validate_event(event, allow_legacy=False):
    if not isinstance(event, dict):
        raise ValueError("event is not an object")
    event_type = event.get("event")
    if event_type == "skill_run":
        if event.get("mode") not in MODES:
            raise ValueError("invalid skill_run mode")
        if not isinstance(event.get("analysis_model"), str) or not event["analysis_model"]:
            raise ValueError("invalid skill_run analysis_model")
        if event.get("effort") not in EFFORTS:
            raise ValueError("invalid skill_run effort")
    elif event_type == "execution":
        if not isinstance(event.get("model"), str) or not event["model"]:
            raise ValueError("invalid execution model")
        if event.get("effort") not in EFFORTS:
            raise ValueError("invalid execution effort")
        if not isinstance(event.get("task_class"), str) or not event["task_class"]:
            raise ValueError("invalid execution task_class")
        if event.get("outcome") not in OUTCOMES:
            raise ValueError("invalid execution outcome")
        if event.get("source") not in SOURCES:
            raise ValueError("invalid execution source")
        if event.get("verification", "unknown") not in VERIFICATIONS:
            raise ValueError("invalid execution verification")
        if _is_gpt55_model(event.get("model")) and not allow_legacy:
            if event.get("fallback_reason") != "gpt56-family-unavailable":
                raise ValueError(
                    "GPT-5.5 execution requires fallback_reason=gpt56-family-unavailable"
                )
            identity = {
                field: event.get(field)
                for field in ("route_id", "plan_hash", "segment_id", "attempt_id")
            }
            if any(not value for value in identity.values()):
                raise ValueError("GPT-5.5 execution requires complete attempt identity")
            validate_capability_decision(
                event.get("capability_decision"), identity=identity,
                target=(event.get("fallback_from"), event.get("effort")),
                execution=(event.get("model"), event.get("effort")),
            )
    elif event_type == "allocation":
        if event.get("basis") not in ("heuristic", "observed", "mixed"):
            raise ValueError("invalid allocation basis")
        allocation = event.get("allocation")
        if not isinstance(allocation, dict) or not allocation:
            raise ValueError("invalid allocation values")
        values = list(allocation.values())
        if any(not isinstance(value, (int, float)) or isinstance(value, bool)
               or not math.isfinite(value) or value < 0 for value in values):
            raise ValueError("invalid allocation percentage")
        if abs(sum(values) - 100) > 0.01:
            raise ValueError("allocation percentages must total 100")
    elif event_type == "route_contract":
        for identifier in ("route_id", "plan_hash", "protocol"):
            if not isinstance(event.get(identifier), str) or not event[identifier]:
                raise ValueError(f"route_contract requires non-empty {identifier}")
        contract_version = event.get("contract_version")
        if contract_version is not None and (
            not isinstance(contract_version, int) or isinstance(contract_version, bool)
            or contract_version < 1
        ):
            raise ValueError("route_contract contract_version must be a positive integer")
        if event.get("source") != ROUTE_CONTRACT_SOURCE:
            raise ValueError("route_contract source must be router-runtime")
    elif event_type == "segment_claim":
        for identifier in ("route_id", "segment_id", "attempt_id"):
            if not isinstance(event.get(identifier), str) or not event[identifier]:
                raise ValueError(f"segment_claim requires non-empty {identifier}")
        if not allow_legacy or "plan_hash" in event:
            if not isinstance(event.get("plan_hash"), str) or not event["plan_hash"]:
                raise ValueError("segment_claim requires non-empty plan_hash")
        if not allow_legacy or "claim_state" in event:
            if event.get("claim_state") != "prepared":
                raise ValueError("segment_claim claim_state must be prepared")
        if "capability_decision_hash" in event and (
            not isinstance(event["capability_decision_hash"], str)
            or not event["capability_decision_hash"]
        ):
            raise ValueError("segment_claim capability_decision_hash must be non-empty")
        if "dispatch_reservation_required" in event and not isinstance(
            event["dispatch_reservation_required"], bool
        ):
            raise ValueError("segment_claim dispatch_reservation_required must be boolean")
    elif event_type == "segment_result":
        for identifier in (
            "route_id", "plan_hash", "segment_id", "attempt_id", "protocol",
        ):
            if not isinstance(event.get(identifier), str) or not event[identifier]:
                raise ValueError(f"segment_result requires non-empty {identifier}")
        if event.get("outcome") not in OUTCOMES:
            raise ValueError("invalid segment_result outcome")
        if "capability_decision_hash" in event and (
            not isinstance(event["capability_decision_hash"], str)
            or not event["capability_decision_hash"]
        ):
            raise ValueError("segment_result capability_decision_hash must be non-empty")
        if "finish_payload_hash" in event and (
            not isinstance(event["finish_payload_hash"], str)
            or len(event["finish_payload_hash"]) != 64
        ):
            raise ValueError("segment_result finish_payload_hash must be sha256")
    elif event_type == "parallel_stop_latch":
        for identifier in ("route_id", "failed_segment_id"):
            if not isinstance(event.get(identifier), str) or not event[identifier]:
                raise ValueError(f"parallel_stop_latch requires non-empty {identifier}")
        if event.get("failure_outcome") not in OUTCOMES[1:]:
            raise ValueError("parallel_stop_latch requires a non-completed outcome")
        for identifier in ("plan_hash", "attempt_id"):
            if not allow_legacy or identifier in event:
                if not isinstance(event.get(identifier), str) or not event[identifier]:
                    raise ValueError(f"parallel_stop_latch requires non-empty {identifier}")
    elif event_type == "parallel_dispatch_reservation":
        for identifier in (
            "route_id", "plan_hash", "segment_id", "attempt_id", "reservation_id",
        ):
            if not isinstance(event.get(identifier), str) or not event[identifier]:
                raise ValueError(
                    f"parallel_dispatch_reservation requires non-empty {identifier}"
                )
        if event.get("capture_source") != "router-runtime":
            raise ValueError("invalid parallel_dispatch_reservation capture_source")
    elif event_type in ("parallel_worker_start", "parallel_worker_finish"):
        identifiers = ["route_id", "segment_id"]
        if not allow_legacy:
            identifiers.extend(("plan_hash", "attempt_id"))
        for identifier in identifiers:
            if not isinstance(event.get(identifier), str) or not event[identifier]:
                raise ValueError(f"{event_type} requires non-empty {identifier}")
        for identifier in ("plan_hash", "attempt_id"):
            if allow_legacy and identifier in event and (
                not isinstance(event[identifier], str) or not event[identifier]
            ):
                raise ValueError(f"{event_type} requires non-empty {identifier}")
        monotonic_ns = event.get("monotonic_ns")
        if not isinstance(monotonic_ns, int) or isinstance(monotonic_ns, bool) or monotonic_ns < 0:
            raise ValueError(f"invalid {event_type} monotonic_ns")
        if event.get("capture_source") != "router-runtime":
            raise ValueError(f"invalid {event_type} capture_source")
        if event.get("clock_source") != PARALLEL_CLOCK_SOURCE:
            raise ValueError(f"invalid {event_type} clock_source")
        if event_type == "parallel_worker_finish" and event.get("outcome") not in OUTCOMES:
            raise ValueError("invalid parallel_worker_finish outcome")
    elif event_type == "parallel_plan":
        if event.get("protocol") != "dependency-parallel-v1":
            raise ValueError("invalid parallel plan protocol")
        for field in ("effective_max_parallelism", "planned_worker_count"):
            if not isinstance(event.get(field), int) or isinstance(event[field], bool) or event[field] < 1:
                raise ValueError(f"invalid parallel plan {field}")
        if event["effective_max_parallelism"] > 16:
            raise ValueError("parallel plan exceeds concurrency hard limit")
        requested = event.get("requested_max_parallelism")
        source = event.get("parallelism_source")
        if (requested is None) != (source is None):
            raise ValueError("parallel plan concurrency intent requires requested cap and source")
        if requested is not None:
            if (
                not isinstance(requested, int) or isinstance(requested, bool)
                or not 1 <= requested <= 16
                or source not in (
                    "standard", "smart-reduced", "adaptive-extended", "user-override"
                )
            ):
                raise ValueError("invalid parallel plan concurrency intent")
            if source == "standard" and requested != 4:
                raise ValueError("standard parallel plan must request four workers")
            if source == "adaptive-extended" and requested != 6:
                raise ValueError("adaptive parallel plan must request six workers")
            if source == "smart-reduced" and (
                requested != 4 or not 1 <= event["effective_max_parallelism"] < 4
            ):
                raise ValueError("smart-reduced parallel plan must reduce default four")
            if event["effective_max_parallelism"] > requested:
                raise ValueError("effective parallelism exceeds requested cap")
        model_plan = event.get("model_plan")
        if not isinstance(model_plan, dict) or any(
            not isinstance(model, str) or not model or not isinstance(count, int)
            or isinstance(count, bool) or count < 0 for model, count in model_plan.items()
        ) or sum(model_plan.values()) != event["planned_worker_count"]:
            raise ValueError("invalid parallel plan model_plan")
    elif event_type == "parallel_execution":
        for field in ("wall_clock_seconds", "cumulative_worker_seconds"):
            value = event.get(field)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value < 0:
                raise ValueError(f"invalid parallel execution {field}")
        for field in ("peak_concurrency", "worker_count"):
            value = event.get(field)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"invalid parallel execution {field}")
        if event["peak_concurrency"] > event["worker_count"] or event["peak_concurrency"] > 16:
            raise ValueError("invalid parallel execution concurrency")
        wall = event["wall_clock_seconds"]
        worker = event["cumulative_worker_seconds"]
        capacity_seconds = event["peak_concurrency"] * wall
        if (wall == 0 and worker > 0) or worker > capacity_seconds + 1e-9:
            raise ValueError("parallel worker time exceeds observed concurrency capacity")
        if event.get("outcome") not in OUTCOMES or event.get("source") not in SOURCES:
            raise ValueError("parallel execution requires verified outcome and source")
        if event.get("schema_version") == PARALLEL_SCHEMA_VERSION:
            if event.get("measurement_boundary") != "dispatch-confirmed-to-result-received":
                raise ValueError("invalid verified parallel measurement boundary")
            if event.get("timing_provenance") != PARALLEL_TIMING_PROVENANCE:
                raise ValueError("invalid verified parallel timing provenance")
            if event.get("clock_source") != PARALLEL_CLOCK_SOURCE:
                raise ValueError("invalid verified parallel clock source")
            intervals = event.get("worker_intervals")
            if not isinstance(intervals, list) or not intervals:
                raise ValueError("verified parallel execution requires worker_intervals")
            identifiers = []
            for interval in intervals:
                if not isinstance(interval, dict):
                    raise ValueError("invalid parallel worker interval")
                identifier = interval.get("segment_id")
                if not isinstance(identifier, str) or not identifier:
                    raise ValueError("invalid parallel worker interval segment_id")
                identifiers.append(identifier)
                for field in ("started_monotonic_ns", "result_received_monotonic_ns"):
                    value = interval.get(field)
                    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                        raise ValueError(f"invalid parallel worker interval {field}")
                if interval.get("outcome") not in OUTCOMES:
                    raise ValueError("invalid parallel worker interval outcome")
                for field in ("started_at", "result_received_at"):
                    if not isinstance(interval.get(field), str) or not interval[field]:
                        raise ValueError(f"invalid parallel worker interval {field}")
            if len(identifiers) != len(set(identifiers)):
                raise ValueError("duplicate parallel worker interval segment_id")
            if event.get("outcome") == "completed" and any(
                interval["outcome"] != "completed" for interval in intervals
            ):
                raise ValueError("completed parallel execution contains failed worker")
            dispatched_ids = event.get("dispatched_ids")
            skipped_ids = event.get("skipped_ids")
            if dispatched_ids is not None or skipped_ids is not None:
                planned_ids = event.get("planned_ids")
                if (
                    not isinstance(dispatched_ids, list)
                    or not isinstance(skipped_ids, list)
                    or not isinstance(planned_ids, list)
                ):
                    raise ValueError(
                        "parallel execution planned_ids, dispatched_ids, and skipped_ids must be lists"
                    )
                if any(
                    not isinstance(identifier, str) or not identifier
                    for identifier in planned_ids + dispatched_ids + skipped_ids
                ):
                    raise ValueError("invalid parallel execution terminal segment IDs")
                if (
                    len(planned_ids) != len(set(planned_ids))
                    or len(dispatched_ids) != len(set(dispatched_ids))
                    or len(skipped_ids) != len(set(skipped_ids))
                ):
                    raise ValueError("duplicate parallel execution terminal segment ID")
                if set(dispatched_ids) & set(skipped_ids):
                    raise ValueError("parallel execution dispatched and skipped IDs overlap")
                if [
                    identifier for identifier in planned_ids if identifier in dispatched_ids
                ] != dispatched_ids or [
                    identifier for identifier in planned_ids if identifier in skipped_ids
                ] != skipped_ids or set(planned_ids) != set(dispatched_ids + skipped_ids):
                    raise ValueError("parallel execution terminal IDs must partition planned_ids")
                if dispatched_ids != identifiers:
                    raise ValueError("parallel execution intervals must cover dispatched_ids")
                if event.get("outcome") == "completed" and skipped_ids:
                    raise ValueError("completed parallel execution cannot contain skipped_ids")
            derived = parallel_metrics_from_intervals(intervals)
            for field in ("wall_clock_seconds", "cumulative_worker_seconds"):
                if not math.isclose(event[field], derived[field], abs_tol=1e-9):
                    raise ValueError(f"parallel execution {field} does not match intervals")
            for field in ("peak_concurrency", "worker_count"):
                if event[field] != derived[field]:
                    raise ValueError(f"parallel execution {field} does not match intervals")
        elif event.get("schema_version") in (None, 1):
            boundary = event.get("measurement_boundary")
            provenance = event.get("timing_provenance")
            if boundary is not None and boundary not in PARALLEL_MEASUREMENT_BOUNDARIES:
                raise ValueError("invalid legacy parallel measurement boundary")
            if provenance is not None and provenance not in SOURCES:
                raise ValueError("invalid legacy parallel timing provenance")
        else:
            raise ValueError("unsupported parallel execution schema_version")
    elif event_type == "routing_efficiency":
        if event.get("source") not in SOURCES:
            raise ValueError("routing efficiency requires task metadata or user confirmation")
        supplied = False
        for field in EFFICIENCY_DURATIONS:
            value = event.get(field)
            if value is not None:
                supplied = True
                if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value < 0:
                    raise ValueError(f"invalid routing efficiency {field}")
        for field in EFFICIENCY_COUNTS:
            value = event.get(field)
            if value is not None:
                supplied = True
                if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                    raise ValueError(f"invalid routing efficiency {field}")
        gate = event.get("state_gate")
        if gate is not None:
            supplied = True
            if gate not in ("passed", "stopped"):
                raise ValueError("invalid routing efficiency state_gate")
        if not supplied:
            raise ValueError("routing efficiency requires at least one observed metric")
        if event.get("state_gate_reason") is not None and (
            not isinstance(event["state_gate_reason"], str) or not event["state_gate_reason"]
        ):
            raise ValueError("invalid routing efficiency state_gate_reason")
    else:
        raise ValueError("unknown event type")

    duration = event.get("duration_seconds")
    if duration is not None and (
        not isinstance(duration, (int, float)) or isinstance(duration, bool)
        or not math.isfinite(duration) or duration < 0
    ):
        raise ValueError("duration must be finite and non-negative")
    if "event_id" in event and not isinstance(event["event_id"], str):
        raise ValueError("event_id must be a string")
    for identifier in ("task_id", "route_id", "segment_id"):
        if identifier in event and (
            not isinstance(event[identifier], str) or not event[identifier]
        ):
            raise ValueError(f"{identifier} must be a non-empty string")
    if event_type == "execution" and (("route_id" in event) != ("segment_id" in event)):
        raise ValueError("segmented execution requires both route_id and segment_id")
    if event_type in (
        "parallel_plan", "parallel_execution", "parallel_worker_start",
        "parallel_worker_finish", "parallel_dispatch_reservation",
        "parallel_stop_latch", "routing_efficiency", "route_contract",
    ) and not event.get("route_id"):
        raise ValueError(f"{event_type} requires route_id")
    concurrency = event.get("concurrency")
    if concurrency is not None and (
        event_type != "execution" or not isinstance(concurrency, int)
        or isinstance(concurrency, bool) or not 1 <= concurrency <= 16
    ):
        raise ValueError("execution concurrency must be an integer from 1 to 16")
    return event


def load_lines(text, source):
    events, warnings = [], []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
            events.append(validate_event(event, allow_legacy=True))
        except (json.JSONDecodeError, ValueError) as exc:
            warnings.append(f"skipped invalid event at {source}:{number}: {exc}")
    return events, warnings


def read_events(path):
    if not path.exists():
        return [], []
    with path.open("r", encoding="utf-8") as handle:
        with locked_file(handle, exclusive=False):
            text = handle.read()
    return load_lines(text, path)


def _prepare_event(event):
    event_type = event.get("event")
    if event_type in (
        "execution", "segment_claim", "segment_result",
        "parallel_worker_start", "parallel_worker_finish",
        "parallel_dispatch_reservation",
    ) and event.get("route_id") and event.get("segment_id"):
        identity_suffix = ""
        if event_type != "execution" and event.get("plan_hash") and event.get("attempt_id"):
            identity_suffix = f":{event['plan_hash']}:{event['attempt_id']}"
        event.setdefault("event_id", str(uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"codex-auto-model-router:{event_type}:{event['route_id']}:{event['segment_id']}"
            f"{identity_suffix}",
        )))
    elif event_type in (
        "parallel_plan", "parallel_execution", "parallel_stop_latch",
        "route_contract",
    ) and event.get("route_id"):
        schema_suffix = (
            ":verified-v2"
            if event_type == "parallel_execution" and is_verified_parallel_run(event)
            else ""
        )
        event.setdefault("event_id", str(uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"codex-auto-model-router:{event_type}:{event['route_id']}{schema_suffix}",
        )))
    elif event_type == "routing_efficiency" and event.get("route_id"):
        efficiency_kind = (
            "gate-stop" if event.get("state_gate") == "stopped"
            and not any(field in event for field in EFFICIENCY_DURATIONS + EFFICIENCY_COUNTS)
            else "execution"
        )
        event.setdefault("event_id", str(uuid.uuid5(
            uuid.NAMESPACE_URL,
            "codex-auto-model-router:routing-efficiency:"
            f"{event['route_id']}:{event.get('segment_id', 'route')}:{efficiency_kind}",
        )))
    else:
        event.setdefault("event_id", str(uuid.uuid4()))
    event.setdefault("timestamp", now())
    validate_event(event)
    return event


def _is_duplicate(existing, event):
    if any(item.get("event_id") == event["event_id"] for item in existing):
        return True
    event_type = event.get("event")
    if event_type in (
        "execution", "segment_claim", "segment_result",
        "parallel_worker_start", "parallel_worker_finish",
        "parallel_dispatch_reservation",
    ) and event.get("route_id"):
        return any(
            item.get("event") == event_type
            and item.get("route_id") == event.get("route_id")
            and item.get("segment_id") == event.get("segment_id")
            and (
                event_type == "execution"
                or (
                    item.get("plan_hash") == event.get("plan_hash")
                    and item.get("attempt_id") == event.get("attempt_id")
                )
            )
            for item in existing
        )
    if event_type == "parallel_execution" and event.get("route_id"):
        verified = is_verified_parallel_run(event)
        return any(
            item.get("event") == event_type
            and item.get("route_id") == event.get("route_id")
            and is_verified_parallel_run(item) == verified
            for item in existing
        )
    if event_type in (
        "parallel_plan", "parallel_stop_latch", "route_contract",
    ) and event.get("route_id"):
        return any(
            item.get("event") == event_type
            and item.get("route_id") == event.get("route_id")
            for item in existing
        )
    return False


def _failure_latch(event, existing):
    if (
        event.get("event") not in ("parallel_worker_finish", "segment_result")
        or event.get("outcome") == "completed"
        or (
            event.get("event") == "segment_result"
            and event.get("protocol") != "dependency-parallel-v1"
        )
    ):
        return None
    latch = {
        "event": "parallel_stop_latch",
        "route_id": event["route_id"],
        "plan_hash": event["plan_hash"],
        "failed_segment_id": event["segment_id"],
        "attempt_id": event["attempt_id"],
        "failure_outcome": event["outcome"],
    }
    return _prepare_event(latch)


def _matching_claim(existing, event):
    return next((
        item for item in existing
        if item.get("event") == "segment_claim"
        and item.get("route_id") == event.get("route_id")
        and item.get("plan_hash") == event.get("plan_hash")
        and item.get("segment_id") == event.get("segment_id")
        and item.get("attempt_id") == event.get("attempt_id")
    ), None)


def _matching_worker_event(existing, event_type, event):
    return next((
        item for item in existing
        if item.get("event") == event_type
        and item.get("route_id") == event.get("route_id")
        and item.get("plan_hash") == event.get("plan_hash")
        and item.get("segment_id") == event.get("segment_id")
        and item.get("attempt_id") == event.get("attempt_id")
    ), None)


def _matching_dispatch_reservation(existing, event):
    return next((
        item for item in existing
        if item.get("event") == "parallel_dispatch_reservation"
        and item.get("route_id") == event.get("route_id")
        and item.get("plan_hash") == event.get("plan_hash")
        and item.get("segment_id") == event.get("segment_id")
        and item.get("attempt_id") == event.get("attempt_id")
    ), None)


def _route_is_latched(existing, event):
    return any(
        item.get("event") == "parallel_stop_latch"
        and item.get("route_id") == event.get("route_id")
        and item.get("plan_hash", event.get("plan_hash")) == event.get("plan_hash")
        for item in existing
    )


def _semantic_payload(event):
    return {
        key: value for key, value in event.items()
        if key not in ("event_id", "timestamp")
    }


def _matching_natural_event(existing, event):
    return next((item for item in existing if _is_duplicate([item], event)), None)


def _require_same_payload(existing_event, candidate, label):
    if _semantic_payload(existing_event) != _semantic_payload(candidate):
        raise ValueError(f"{label} payload conflicts with recorded event")


def finish_payload_hash(result_event, derived_events):
    payload = {
        "result": _semantic_payload(result_event),
        "derived": [_semantic_payload(item) for item in derived_events if item is not None],
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def bind_route_contract(path, event):
    """Persist one immutable route contract or verify the existing anchor."""
    path.parent.mkdir(parents=True, exist_ok=True)
    _prepare_event(event)
    with path.open("a+", encoding="utf-8") as handle:
        with locked_file(handle, exclusive=True):
            handle.seek(0)
            existing_text = handle.read()
            existing, _ = load_lines(existing_text, path)
            matching = next((
                item for item in existing
                if item.get("event") == "route_contract"
                and item.get("route_id") == event.get("route_id")
            ), None)
            if matching is not None:
                _require_same_payload(matching, event, "route contract")
                return False
            _write_events(handle, existing_text, [event])
            return True


def route_contract(path, route_id):
    events, _ = read_events(path)
    return next((
        item for item in events
        if item.get("event") == "route_contract" and item.get("route_id") == route_id
    ), None)


def prepare_segment_claim(
    path, event, allow_prepared_recovery=False, reservation_event=None,
):
    """Atomically create/recover a claim and reserve parallel dispatch."""
    path.parent.mkdir(parents=True, exist_ok=True)
    event.setdefault("claim_state", "prepared")
    _prepare_event(event)
    if reservation_event is not None:
        _prepare_event(reservation_event)
    with path.open("a+", encoding="utf-8") as handle:
        with locked_file(handle, exclusive=True):
            handle.seek(0)
            existing_text = handle.read()
            existing, _ = load_lines(existing_text, path)
            if _route_is_latched(existing, event):
                raise ValueError("parallel route dispatch stopped by failure latch")
            matching = _matching_claim(existing, event)
            if matching is None:
                conflicting = any(
                    item.get("event") == "segment_claim"
                    and item.get("route_id") == event.get("route_id")
                    and item.get("segment_id") == event.get("segment_id")
                    for item in existing
                )
                if conflicting:
                    raise ValueError("segment claim identity conflicts with existing claim")
                pending = [event]
                if reservation_event is not None:
                    pending.append(reservation_event)
                _write_events(handle, existing_text, pending)
                return "prepared"
            if matching.get("capability_decision_hash") != event.get(
                "capability_decision_hash"
            ):
                raise ValueError("recovered segment claim capability decision mismatch")
            if any(
                item.get("event") == "segment_result"
                and item.get("route_id") == event.get("route_id")
                and item.get("plan_hash") == event.get("plan_hash")
                and item.get("segment_id") == event.get("segment_id")
                and item.get("attempt_id") == event.get("attempt_id")
                for item in existing
            ):
                return "consumed"
            if _matching_worker_event(existing, "parallel_worker_start", event):
                return "dispatch-confirmed"
            if reservation_event is not None:
                matching_reservation = _matching_dispatch_reservation(
                    existing, reservation_event
                )
                if matching_reservation is None:
                    _write_events(handle, existing_text, [reservation_event])
                else:
                    _require_same_payload(
                        matching_reservation, reservation_event,
                        "parallel dispatch reservation",
                    )
            return "recovered" if allow_prepared_recovery else "already-claimed"


def _validate_worker_transition(existing, event):
    matching_claim = _matching_claim(existing, event)
    if matching_claim is None:
        raise ValueError("parallel worker event requires a matching prepared claim")
    if any(
        item.get("event") == "segment_result"
        and item.get("route_id") == event.get("route_id")
        and item.get("plan_hash") == event.get("plan_hash")
        and item.get("segment_id") == event.get("segment_id")
        and item.get("attempt_id") == event.get("attempt_id")
        for item in existing
    ):
        raise ValueError("parallel worker event refers to a consumed claim")
    if event.get("event") == "parallel_worker_start":
        reservation = _matching_dispatch_reservation(existing, event)
        if matching_claim.get("dispatch_reservation_required") and reservation is None:
            raise ValueError("parallel worker start requires a dispatch reservation")
        # A reservation is the total-order boundary. A later failure latch may
        # not cancel work whose dispatch right was already reserved.
        if _route_is_latched(existing, event) and reservation is None:
            raise ValueError("parallel route dispatch stopped by failure latch")
        return
    if _matching_worker_event(existing, "parallel_worker_start", event) is None:
        raise ValueError("parallel worker finish requires a matching dispatch-confirmed start")


def _write_events(handle, existing_text, events):
    handle.seek(0, os.SEEK_END)
    prefix = "\n" if existing_text and not existing_text.endswith("\n") else ""
    encoded = "\n".join(
        json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        for event in events
    )
    handle.write(prefix + encoded + "\n")
    handle.flush()
    os.fsync(handle.fileno())


def append_event(path, event):
    path.parent.mkdir(parents=True, exist_ok=True)
    _prepare_event(event)
    with path.open("a+", encoding="utf-8") as handle:
        with locked_file(handle, exclusive=True):
            handle.seek(0)
            existing_text = handle.read()
            existing, _ = load_lines(existing_text, path)
            duplicate = _is_duplicate(existing, event)
            if duplicate and event.get("event") == "parallel_worker_finish":
                matching = _matching_worker_event(
                    existing, "parallel_worker_finish", event
                )
                if matching is not None and matching.get("outcome") != event.get("outcome"):
                    raise ValueError("parallel worker finish outcome conflicts with recorded event")
            if event.get("event") in (
                "parallel_worker_start", "parallel_worker_finish",
            ) and not duplicate:
                _validate_worker_transition(existing, event)
            pending = [] if duplicate else [event]
            latch_source = (
                matching
                if duplicate
                and event.get("event") == "parallel_worker_finish"
                and matching is not None
                else event
            )
            latch = _failure_latch(latch_source, existing + pending)
            if latch is not None and not _is_duplicate(existing + pending, latch):
                pending.append(latch)
            if pending:
                _write_events(handle, existing_text, pending)
            return not duplicate


def consume_segment_claim(path, result_event, claim_required=True):
    """Atomically bind one terminal result to one real, unconsumed claim."""
    path.parent.mkdir(parents=True, exist_ok=True)
    _prepare_event(result_event)
    with path.open("a+", encoding="utf-8") as handle:
        with locked_file(handle, exclusive=True):
            handle.seek(0)
            existing_text = handle.read()
            existing, _ = load_lines(existing_text, path)
            if _is_duplicate(existing, result_event) or any(
                item.get("event") == "execution"
                and item.get("route_id") == result_event["route_id"]
                and item.get("segment_id") == result_event["segment_id"]
                for item in existing
            ):
                return False
            if claim_required:
                matching_claim = next((
                    item for item in existing
                    if item.get("event") == "segment_claim"
                    and item.get("route_id") == result_event["route_id"]
                    and item.get("segment_id") == result_event["segment_id"]
                    and item.get("attempt_id") == result_event["attempt_id"]
                    and item.get("plan_hash", result_event["plan_hash"])
                    == result_event["plan_hash"]
                ), None)
                if matching_claim is None:
                    raise ValueError("finish requires a matching segment claim")
                decision_hash = matching_claim.get("capability_decision_hash")
                if decision_hash != result_event.get("capability_decision_hash"):
                    raise ValueError("finish capability decision does not match segment claim")
            pending = [result_event]
            latch = _failure_latch(result_event, existing + pending)
            if latch is not None and not _is_duplicate(existing + pending, latch):
                pending.append(latch)
            _write_events(handle, existing_text, pending)
    return True


def commit_segment_finish(path, result_event, derived_events, claim_required=True):
    """Recoverably append a terminal result and its deterministic derivatives.

    One lock orders claim consumption, failure latching, and all derivative
    events. If an OS interruption leaves a prefix on disk, the same payload may
    be retried to append only missing events; any changed payload is rejected.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    derived_events = [item for item in derived_events if item is not None]
    result_event = dict(result_event)
    result_event["finish_payload_hash"] = finish_payload_hash(
        result_event, derived_events
    )
    candidates = [result_event, *derived_events]
    for candidate in candidates:
        _prepare_event(candidate)
    with path.open("a+", encoding="utf-8") as handle:
        with locked_file(handle, exclusive=True):
            handle.seek(0)
            existing_text = handle.read()
            existing, _ = load_lines(existing_text, path)
            if claim_required and _matching_claim(existing, result_event) is None:
                raise ValueError("finish requires a matching segment claim")
            matching_claim = _matching_claim(existing, result_event)
            if matching_claim is not None and (
                matching_claim.get("capability_decision_hash")
                != result_event.get("capability_decision_hash")
            ):
                raise ValueError("finish capability decision does not match segment claim")

            pending = []
            recorded = {}
            for candidate in candidates:
                matching = _matching_natural_event(existing + pending, candidate)
                if matching is None:
                    pending.append(candidate)
                    recorded[candidate["event"]] = True
                else:
                    _require_same_payload(matching, candidate, candidate["event"])
                    recorded[candidate["event"]] = False
            latch = _failure_latch(result_event, existing + pending)
            if latch is not None and not _is_duplicate(existing + pending, latch):
                pending.append(latch)
            if pending:
                _write_events(handle, existing_text, pending)
            return {
                "result_recorded": recorded.get("segment_result", False),
                "execution_recorded": recorded.get("execution", False),
                "metrics_recorded": recorded.get("routing_efficiency", False),
                "recovered": not recorded.get("segment_result", False),
            }


def proportions(counter):
    total = sum(counter.values())
    return {
        "total": total,
        "items": {
            key: {"count": count, "percent": round(count * 100 / total, 1)}
            for key, count in sorted(counter.items())
        } if total else {},
    }


def route_performance(executions):
    groups = defaultdict(list)
    for event in executions:
        key = " | ".join((
            event.get("task_class", "unknown"),
            event.get("model", "unknown"),
            event.get("effort", "unknown"),
        ))
        groups[key].append(event)
    result = {}
    for key, items in sorted(groups.items()):
        outcomes = Counter(item.get("outcome", "unknown") for item in items)
        attempts = sum(value for name, value in outcomes.items() if name != "cancelled")
        completed = outcomes.get("completed", 0)
        pressure = sum(outcomes.get(name, 0) for name in ("failed", "escalated", "reworked"))
        active_items = [item for item in items if item.get("outcome") != "cancelled"]
        deterministic = sum(item.get("verification") == "deterministic" for item in active_items)
        if attempts >= 5 and pressure / attempts >= 0.4:
            signal = "raise_candidate"
        elif attempts >= 10 and completed / attempts >= 0.9 and pressure == 0 and deterministic == attempts:
            signal = "lower_candidate"
        elif attempts < 5:
            signal = "insufficient_sample"
        else:
            signal = "hold"
        result[key] = {
            "attempts": attempts,
            "outcomes": dict(sorted(outcomes.items())),
            "success_rate": round(completed * 100 / attempts, 1) if attempts else None,
            "pressure_rate": round(pressure * 100 / attempts, 1) if attempts else None,
            "deterministic_verification_rate": round(deterministic * 100 / attempts, 1) if attempts else None,
            "retune_signal": signal,
        }
    return result


def build_summary(events, warnings, current_route_id=None):
    executions = [item for item in events if item.get("event") == "execution"]
    attempts = [item for item in executions if item.get("outcome") != "cancelled"]
    segment_attempts = [
        item for item in attempts
        if item.get("route_id") and item.get("segment_id") and item.get("source") in SOURCES
    ]
    legacy_attempts = [item for item in attempts if not (item.get("route_id") and item.get("segment_id"))]
    actual_models = Counter(item.get("model", "unknown") for item in segment_attempts)
    model_effort = Counter(
        f"{item.get('model', 'unknown')} | {item.get('effort', 'unknown')}" for item in segment_attempts
    )
    model_concurrency = Counter(
        f"{item.get('model', 'unknown')} | {item['concurrency']}"
        for item in segment_attempts if item.get("concurrency") is not None
    )
    legacy_models = Counter(item.get("model", "unknown") for item in legacy_attempts)
    analyses = Counter(
        item.get("analysis_model", "unknown")
        for item in events if item.get("event") == "skill_run"
    )
    latest = next((item for item in reversed(events) if item.get("event") == "allocation"), None)
    parallel_plans = [item for item in events if item.get("event") == "parallel_plan"]
    all_parallel_runs = [item for item in events if item.get("event") == "parallel_execution"]
    parallel_runs = [item for item in all_parallel_runs if is_verified_parallel_run(item)]
    legacy_parallel_runs = [item for item in all_parallel_runs if not is_verified_parallel_run(item)]
    efficiency_events = [item for item in events if item.get("event") == "routing_efficiency"]
    parallel_wall = sum(item["wall_clock_seconds"] for item in parallel_runs)
    parallel_worker = sum(item["cumulative_worker_seconds"] for item in parallel_runs)
    leaf_parallel_capacity = sum(
        item["peak_concurrency"] * item["wall_clock_seconds"]
        for item in parallel_runs
    )
    visible_parallel_capacity = sum(
        (item["peak_concurrency"] + 1) * item["wall_clock_seconds"]
        for item in parallel_runs
    )
    current_parallel_event = next(
        (
            item for item in reversed(parallel_runs)
            if current_route_id is not None and item["route_id"] == current_route_id
        ),
        None,
    )
    current_parallel_run = None
    if current_parallel_event:
        wall = current_parallel_event["wall_clock_seconds"]
        worker = current_parallel_event["cumulative_worker_seconds"]
        current_parallel_run = {
            "route_id": current_parallel_event["route_id"],
            "schema_version": current_parallel_event["schema_version"],
            "measurement_boundary": current_parallel_event.get(
                "measurement_boundary", "legacy-unspecified"
            ),
            "timing_provenance": current_parallel_event.get(
                "timing_provenance", current_parallel_event["source"]
            ),
            "clock_source": current_parallel_event["clock_source"],
            "wall_clock_seconds": wall,
            "cumulative_worker_seconds": worker,
            "peak_concurrency": current_parallel_event["peak_concurrency"],
            "visible_peak_concurrency": current_parallel_event["peak_concurrency"] + 1,
            "worker_count": current_parallel_event["worker_count"],
            "outcome": current_parallel_event["outcome"],
            "effective_parallel_factor": round(worker / wall, 2) if wall > 0 else None,
            "parallel_time_saving_estimate_percent": (
                round(parallel_time_saving_estimate(current_parallel_event), 1)
                if worker > 0 else None
            ),
            "leaf_parallel_utilization_percent": (
                round(
                    worker * 100
                    / (current_parallel_event["peak_concurrency"] * wall),
                    1,
                )
                if wall > 0 else None
            ),
            "parallel_utilization_percent": (
                round(
                    (worker + wall) * 100
                    / ((current_parallel_event["peak_concurrency"] + 1) * wall),
                    1,
                )
                if wall > 0 else None
            ),
        }
    return {
        "actual_execution": proportions(actual_models),
        "model_effort_usage": proportions(model_effort),
        "model_concurrency_usage": proportions(model_concurrency),
        "legacy_execution": proportions(legacy_models),
        "analysis_runs": proportions(analyses),
        "recommended_allocation": latest,
        "parallel_plans": {
            "count": len(parallel_plans),
            "latest": parallel_plans[-1] if parallel_plans else None,
        },
        "parallel_execution": {
            "current_run": current_parallel_run,
            "legacy_unverified": {
                "count": len(legacy_parallel_runs),
                "route_ids": [item["route_id"] for item in legacy_parallel_runs],
            },
            "historical_summary": {
                "count": len(parallel_runs),
                "wall_clock_seconds": round(parallel_wall, 3),
                "cumulative_worker_seconds": round(parallel_worker, 3),
                "peak_concurrency": max((item["peak_concurrency"] for item in parallel_runs), default=None),
                "visible_peak_concurrency": (
                    max((item["peak_concurrency"] for item in parallel_runs), default=0) + 1
                    if parallel_runs else None
                ),
                "effective_parallel_factor": round(parallel_worker / parallel_wall, 2) if parallel_wall > 0 else None,
                "parallel_time_saving_estimate_percent": (
                    round((1 - parallel_wall / parallel_worker) * 100, 1)
                    if parallel_worker > 0 else None
                ),
                "leaf_parallel_utilization_percent": (
                    round(parallel_worker * 100 / leaf_parallel_capacity, 1)
                    if leaf_parallel_capacity > 0 else None
                ),
                "parallel_utilization_percent": (
                    round(
                        (parallel_worker + parallel_wall) * 100
                        / visible_parallel_capacity,
                        1,
                    )
                    if visible_parallel_capacity > 0 else None
                ),
            },
        },
        "routing_efficiency": {
            "count": len(efficiency_events),
            "durations": {
                field: (
                    round(sum(item[field] for item in efficiency_events if field in item), 3)
                    if any(field in item for item in efficiency_events) else None
                )
                for field in EFFICIENCY_DURATIONS
            },
            "round_trips": {
                field: (
                    sum(item[field] for item in efficiency_events if field in item)
                    if any(field in item for item in efficiency_events) else None
                )
                for field in EFFICIENCY_COUNTS
            },
            "state_gates": dict(Counter(
                item.get("state_gate") for item in efficiency_events if item.get("state_gate")
            )),
        },
        "route_performance": route_performance(segment_attempts),
        "actual_sample": "insufficient" if not segment_attempts else ("early" if len(segment_attempts) < 5 else "established"),
        "warnings": warnings,
    }


def markdown_table(view, first_header):
    rows = [f"| {first_header} | Count | Percent |", "|---|---:|---:|"]
    for name, values in view["items"].items():
        safe_name = str(name).replace("|", "\\|")
        rows.append(f"| {safe_name} | {values['count']} | {values['percent']}% |")
    if not view["items"]:
        rows.append("| Insufficient observed data | 0 | — |")
    return "\n".join(rows)


def render_markdown(summary):
    sample = summary["actual_sample"]
    efficiency = summary["routing_efficiency"]

    def observed(value, suffix=""):
        return "—" if value is None else f"{value:g}{suffix}"

    switch_restore = None
    if (
        efficiency["durations"]["model_switch_seconds"] is not None
        or efficiency["durations"]["restore_seconds"] is not None
    ):
        switch_restore = (
            (efficiency["durations"]["model_switch_seconds"] or 0)
            + (efficiency["durations"]["restore_seconds"] or 0)
        )
    parallel = summary["parallel_execution"]
    historical_parallel = parallel["historical_summary"]
    legacy_parallel = parallel["legacy_unverified"]
    current_parallel = parallel["current_run"]
    lines = [
        USAGE_START,
        f"_Observed sample: **{sample}**. Actual use counts non-cancelled Segment attempts backed by task metadata or user confirmation._",
        "",
        "### Actual Segment execution by model",
        "",
        markdown_table(summary["actual_execution"], "Model"),
        "",
        "### Actual Segment execution by model and effort",
        "",
        markdown_table(summary["model_effort_usage"], "Model and effort"),
        "",
        "### Actual Segment execution by model and concurrency",
        "",
        markdown_table(summary["model_concurrency_usage"], "Model and verified concurrency"),
        "",
        "### Historical verified parallel execution",
        "",
        (
            f"Aggregate of {historical_parallel['count']} verified run(s): actual elapsed: "
            f"{historical_parallel['wall_clock_seconds']:g}s; cumulative parallel-task time: "
            f"{historical_parallel['cumulative_worker_seconds']:g}s; peak concurrency including main: "
            f"{historical_parallel['visible_peak_concurrency'] if historical_parallel['visible_peak_concurrency'] is not None else '—'}; parallel time-saving estimate: "
            f"{historical_parallel['parallel_time_saving_estimate_percent'] if historical_parallel['parallel_time_saving_estimate_percent'] is not None else '—'}%; slot utilization: "
            f"{historical_parallel['parallel_utilization_percent'] if historical_parallel['parallel_utilization_percent'] is not None else '—'}%. "
            "The estimate is 1 - wall clock / cumulative parallel-task time, using "
            "dispatch-confirmed-to-result-received task intervals concatenated as a "
            "serial proxy. It includes reasoning, tools, and result-return waiting; it "
            "is not pure model compute or controlled A/B speedup."
            if historical_parallel["count"] else
            "Insufficient verified parallel timing data."
        ),
        "",
        "### Legacy/unverified parallel records",
        "",
        (
            f"Excluded from verified metrics: {legacy_parallel['count']} record(s)."
            if legacy_parallel["count"] else
            "No legacy parallel records."
        ),
        "",
        "### Verified routing overhead",
        "",
        (
            f"Samples: {efficiency['count']}; routing: "
            f"{observed(efficiency['durations']['routing_seconds'], 's')}; queue wait: "
            f"{observed(efficiency['durations']['queue_wait_seconds'], 's')}; executor startup: "
            f"{observed(efficiency['durations']['executor_start_seconds'], 's')}; model switch + Restore: "
            f"{observed(switch_restore, 's')}; model/tool round trips: "
            f"{observed(efficiency['round_trips']['model_round_trips'])}/"
            f"{observed(efficiency['round_trips']['tool_round_trips'])}."
            if efficiency["count"] else
            "Insufficient verified routing-overhead data."
        ),
        "",
        "### Legacy whole-task execution records",
        "",
        markdown_table(summary["legacy_execution"], "Model"),
        "",
        "### Router analysis runs",
        "",
        markdown_table(summary["analysis_runs"], "Analysis model"),
        "",
        "### Latest recommended allocation",
        "",
    ]
    if current_parallel:
        current_run_lines = [
            "### Current verified parallel run",
            "",
            (
                f"Route: `{current_parallel['route_id']}`; schema: "
                f"v{current_parallel['schema_version']}; measurement boundary: "
                f"`{current_parallel['measurement_boundary']}`; timing provenance: "
                f"`{current_parallel['timing_provenance']}`; clock: "
                f"`{current_parallel['clock_source']}`; actual elapsed: "
                f"{current_parallel['wall_clock_seconds']:g}s; cumulative parallel-task time: "
                f"{current_parallel['cumulative_worker_seconds']:g}s; peak concurrency including main: "
                f"{current_parallel['visible_peak_concurrency']}; parallel time-saving estimate: "
                f"{current_parallel['parallel_time_saving_estimate_percent'] if current_parallel['parallel_time_saving_estimate_percent'] is not None else '—'}%; "
                f"slot utilization: {current_parallel['parallel_utilization_percent'] if current_parallel['parallel_utilization_percent'] is not None else '—'}%."
            ),
            "",
        ]
        insert_at = lines.index("### Verified routing overhead")
        lines[insert_at:insert_at] = current_run_lines
    allocation = summary.get("recommended_allocation")
    if allocation:
        lines.extend([
            f"Basis: `{allocation.get('basis', 'unknown')}`",
            "",
            "| Model | Recommended share |",
            "|---|---:|",
        ])
        for model, percent in sorted(allocation.get("allocation", {}).items()):
            lines.append(f"| {model} | {percent:g}% |")
    else:
        lines.append("No recommended allocation has been recorded.")
    signals = [
        (route, values["retune_signal"])
        for route, values in summary["route_performance"].items()
        if values["retune_signal"] in ("raise_candidate", "lower_candidate")
    ]
    lines.extend(["", "### Retuning signals", ""])
    if signals:
        lines.extend(f"- `{route}`: `{signal}`" for route, signal in signals)
    else:
        lines.append("No route currently meets the automatic retuning evidence threshold.")
    if summary["warnings"]:
        lines.extend(["", f"Ledger warnings: {len(summary['warnings'])} invalid event(s) skipped."])
    lines.append(USAGE_END)
    return "\n".join(lines)


def update_report(path, block):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        with locked_file(handle, exclusive=True):
            handle.seek(0)
            text = handle.read()
            starts, ends = text.count(USAGE_START), text.count(USAGE_END)
            if starts != ends or starts > 1:
                raise SystemExit("report has unmatched or duplicate model-usage markers")
            if starts == 1 and text.index(USAGE_START) > text.index(USAGE_END):
                raise SystemExit("report model-usage START marker must precede END marker")
            if starts == 1:
                before = text.split(USAGE_START, 1)[0].rstrip()
                after = text.split(USAGE_END, 1)[1].lstrip("\n")
                updated = before + "\n\n" + block + ("\n\n" + after if after else "\n")
            else:
                heading = "# Codex model routing report\n" if not text.strip() else text.rstrip()
                updated = heading + "\n\n## Usage proportions\n\n" + block + "\n"
            handle.seek(0)
            handle.truncate()
            handle.write(updated)
            handle.flush()
            os.fsync(handle.fileno())


def record(args):
    required = {
        "skill_run": ("mode", "analysis_model", "effort"),
        "execution": ("model", "effort", "task_class", "outcome", "source"),
    }[args.event]
    missing = [key for key in required if getattr(args, key, None) is None]
    if missing:
        raise SystemExit(f"{args.event} requires: {', '.join(missing)}")
    if args.duration_seconds is not None and (not math.isfinite(args.duration_seconds) or args.duration_seconds < 0):
        raise SystemExit("duration must be finite and non-negative")
    event = {"event": args.event}
    for key in ("event_id", "task_id", "route_id", "plan_hash", "segment_id", "attempt_id",
                "mode", "analysis_model", "model", "effort",
                "task_class", "outcome", "source", "fallback_from", "fallback_to",
                "fallback_reason", "verification", "concurrency"):
        value = getattr(args, key, None)
        if value is not None:
            event[key] = value
    if args.duration_seconds is not None:
        event["duration_seconds"] = args.duration_seconds
    if args.capability_decision_json is not None:
        try:
            decision = json.loads(args.capability_decision_json)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"--capability-decision-json must be a JSON object: {exc}") from exc
        if not isinstance(decision, dict):
            raise SystemExit("--capability-decision-json must be a JSON object")
        event["capability_decision"] = decision
    print(json.dumps({"appended": append_event(args.ledger, event), "event_id": event.get("event_id")}, ensure_ascii=False))


def parallel_plan(args):
    try:
        model_plan = json.loads(args.model_plan)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"--model-plan must be a JSON object: {exc}") from exc
    event = {
        "event": "parallel_plan", "route_id": args.route_id,
        "protocol": args.protocol,
        "requested_max_parallelism": args.requested_max_parallelism,
        "parallelism_source": args.parallelism_source,
        "effective_max_parallelism": args.effective_max_parallelism,
        "planned_worker_count": args.planned_worker_count,
        "model_plan": model_plan,
    }
    if args.requested_max_parallelism is None and args.parallelism_source is None:
        event.pop("requested_max_parallelism")
        event.pop("parallelism_source")
    print(json.dumps({"appended": append_event(args.ledger, event), "event_id": event.get("event_id")}, ensure_ascii=False))


def parallel_execution(args):
    event = {
        "event": "parallel_execution", "route_id": args.route_id,
        "schema_version": 1,
        "wall_clock_seconds": args.wall_clock_seconds,
        "cumulative_worker_seconds": args.cumulative_worker_seconds,
        "peak_concurrency": args.peak_concurrency,
        "worker_count": args.worker_count,
        "outcome": args.outcome, "source": args.source,
    }
    if args.measurement_boundary is not None:
        event["measurement_boundary"] = args.measurement_boundary
    if args.timing_provenance is not None:
        event["timing_provenance"] = args.timing_provenance
    print(json.dumps({"appended": append_event(args.ledger, event), "event_id": event.get("event_id")}, ensure_ascii=False))


def routing_efficiency(args):
    event = {
        "event": "routing_efficiency", "route_id": args.route_id,
        "source": args.source,
    }
    if args.segment_id:
        event["segment_id"] = args.segment_id
    for field in EFFICIENCY_DURATIONS + EFFICIENCY_COUNTS + (
        "state_gate", "state_gate_reason",
    ):
        value = getattr(args, field, None)
        if value is not None:
            event[field] = value
    print(json.dumps({
        "appended": append_event(args.ledger, event),
        "event_id": event.get("event_id"),
    }, ensure_ascii=False))


def allocation(args):
    try:
        values = json.loads(args.values)
        numeric = {str(key): float(value) for key, value in values.items()}
    except (json.JSONDecodeError, AttributeError, TypeError, ValueError) as exc:
        raise SystemExit(f"--values must be a JSON object with numeric percentages: {exc}") from exc
    if not numeric or any(not math.isfinite(value) or value < 0 for value in numeric.values()):
        raise SystemExit("allocation percentages must be finite and non-negative")
    if abs(sum(numeric.values()) - 100) > 0.01:
        raise SystemExit("allocation percentages must total 100")
    event = {"event": "allocation", "basis": args.basis, "allocation": numeric}
    if args.event_id:
        event["event_id"] = args.event_id
    print(json.dumps({"appended": append_event(args.ledger, event), "event_id": event.get("event_id")}, ensure_ascii=False))


def claim(args):
    event = {
        "event": "segment_claim",
        "route_id": args.route_id,
        "segment_id": args.segment_id,
        "attempt_id": args.attempt_id,
        "plan_hash": args.plan_hash,
        "claim_state": "prepared",
    }
    if args.task_id:
        event["task_id"] = args.task_id
    state = prepare_segment_claim(args.ledger, event)
    print(json.dumps({
        "claimed": state == "prepared", "claim_state": state,
        "event_id": event.get("event_id"),
    }, ensure_ascii=False))


def summarize(args):
    events, warnings = read_events(args.ledger)
    summary = build_summary(events, warnings, current_route_id=args.route_id)
    if args.format == "markdown":
        print(render_markdown(summary))
    else:
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


def render(args):
    events, warnings = read_events(args.ledger)
    update_report(args.report, render_markdown(build_summary(
        events, warnings, current_route_id=args.route_id,
    )))
    print(args.report)


def resolve_ledger(args):
    print(resolve_ledger_path(args.repository))


def parser():
    root = argparse.ArgumentParser()
    commands = root.add_subparsers(dest="command", required=True)
    rec = commands.add_parser("record")
    rec.add_argument("--ledger", type=Path, required=True)
    rec.add_argument("--event", choices=("skill_run", "execution"), required=True)
    rec.add_argument("--event-id")
    rec.add_argument("--task-id")
    rec.add_argument("--route-id")
    rec.add_argument("--plan-hash")
    rec.add_argument("--segment-id")
    rec.add_argument("--attempt-id")
    rec.add_argument("--mode", choices=MODES)
    rec.add_argument("--analysis-model")
    rec.add_argument("--model")
    rec.add_argument("--effort", choices=EFFORTS)
    rec.add_argument("--task-class")
    rec.add_argument("--outcome", choices=OUTCOMES)
    rec.add_argument("--source", choices=SOURCES)
    rec.add_argument("--verification", choices=VERIFICATIONS)
    rec.add_argument("--fallback-from")
    rec.add_argument("--fallback-to")
    rec.add_argument("--fallback-reason")
    rec.add_argument("--capability-decision-json")
    rec.add_argument("--duration-seconds", type=float)
    rec.add_argument("--concurrency", type=int, help="Verified active worker count for this Segment")
    rec.set_defaults(func=record)
    planned = commands.add_parser("parallel-plan")
    planned.add_argument("--ledger", type=Path, required=True)
    planned.add_argument("--route-id", required=True)
    planned.add_argument("--protocol", default="dependency-parallel-v1")
    planned.add_argument("--requested-max-parallelism", type=int)
    planned.add_argument(
        "--parallelism-source",
        choices=("standard", "smart-reduced", "adaptive-extended", "user-override"),
    )
    planned.add_argument("--effective-max-parallelism", type=int, required=True)
    planned.add_argument("--planned-worker-count", type=int, required=True)
    planned.add_argument("--model-plan", required=True)
    planned.set_defaults(func=parallel_plan)
    measured = commands.add_parser("parallel-execution")
    measured.add_argument("--ledger", type=Path, required=True)
    measured.add_argument("--route-id", required=True)
    measured.add_argument("--wall-clock-seconds", type=float, required=True)
    measured.add_argument("--cumulative-worker-seconds", type=float, required=True)
    measured.add_argument("--peak-concurrency", type=int, required=True)
    measured.add_argument("--worker-count", type=int, required=True)
    measured.add_argument("--outcome", choices=OUTCOMES, required=True)
    measured.add_argument("--source", choices=SOURCES, required=True)
    measured.add_argument("--measurement-boundary", choices=PARALLEL_MEASUREMENT_BOUNDARIES)
    measured.add_argument("--timing-provenance", choices=SOURCES)
    measured.set_defaults(func=parallel_execution)
    efficiency = commands.add_parser("efficiency")
    efficiency.add_argument("--ledger", type=Path, required=True)
    efficiency.add_argument("--route-id", required=True)
    efficiency.add_argument("--segment-id")
    efficiency.add_argument("--source", choices=SOURCES, required=True)
    for field in EFFICIENCY_DURATIONS:
        efficiency.add_argument("--" + field.replace("_", "-"), type=float)
    for field in EFFICIENCY_COUNTS:
        efficiency.add_argument("--" + field.replace("_", "-"), type=int)
    efficiency.add_argument("--state-gate", choices=("passed", "stopped"))
    efficiency.add_argument("--state-gate-reason")
    efficiency.set_defaults(func=routing_efficiency)
    alloc = commands.add_parser("allocation")
    alloc.add_argument("--ledger", type=Path, required=True)
    alloc.add_argument("--values", required=True, help='JSON object such as {"Sol":30,"Terra":50,"Luna":20}')
    alloc.add_argument("--basis", choices=("heuristic", "observed", "mixed"), default="heuristic")
    alloc.add_argument("--event-id")
    alloc.set_defaults(func=allocation)
    claimer = commands.add_parser("claim")
    claimer.add_argument("--ledger", type=Path, required=True)
    claimer.add_argument("--route-id", required=True)
    claimer.add_argument("--segment-id", required=True)
    claimer.add_argument("--attempt-id", required=True)
    claimer.add_argument("--plan-hash", required=True)
    claimer.add_argument("--task-id")
    claimer.set_defaults(func=claim)
    report = commands.add_parser("summary")
    report.add_argument("--ledger", type=Path, required=True)
    report.add_argument("--route-id", help="Select the current verified parallel run by route")
    report.add_argument("--format", choices=("json", "markdown"), default="json")
    report.set_defaults(func=summarize)
    renderer = commands.add_parser("render")
    renderer.add_argument("--ledger", type=Path, required=True)
    renderer.add_argument("--report", type=Path, required=True)
    renderer.add_argument("--route-id", help="Select the current verified parallel run by route")
    renderer.set_defaults(func=render)
    resolver = commands.add_parser("resolve-ledger")
    resolver.add_argument("--repository", type=Path, required=True)
    resolver.set_defaults(func=resolve_ledger)
    return root


if __name__ == "__main__":
    arguments = parser().parse_args()
    arguments.func(arguments)
