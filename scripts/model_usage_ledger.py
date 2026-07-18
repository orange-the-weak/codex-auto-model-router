#!/usr/bin/env python3
"""Safely append, aggregate, and render the model-routing usage ledger."""

import argparse
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
VERIFICATIONS = ("deterministic", "manual", "none", "unknown")
USAGE_START = "<!-- MODEL_USAGE_START -->"
USAGE_END = "<!-- MODEL_USAGE_END -->"


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


def validate_event(event):
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
    elif event_type == "segment_claim":
        for identifier in ("route_id", "segment_id", "attempt_id"):
            if not isinstance(event.get(identifier), str) or not event[identifier]:
                raise ValueError(f"segment_claim requires non-empty {identifier}")
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
        if event.get("outcome") not in OUTCOMES or event.get("source") not in SOURCES:
            raise ValueError("parallel execution requires verified outcome and source")
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
    if event_type in ("parallel_plan", "parallel_execution") and not event.get("route_id"):
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
            events.append(validate_event(event))
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


def append_event(path, event):
    path.parent.mkdir(parents=True, exist_ok=True)
    if event.get("event") in ("execution", "segment_claim") and event.get("route_id") and event.get("segment_id"):
        event.setdefault("event_id", str(uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"codex-auto-model-router:{event['event']}:{event['route_id']}:{event['segment_id']}",
        )))
    elif event.get("event") in ("parallel_plan", "parallel_execution") and event.get("route_id"):
        event.setdefault("event_id", str(uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"codex-auto-model-router:{event['event']}:{event['route_id']}",
        )))
    else:
        event.setdefault("event_id", str(uuid.uuid4()))
    event.setdefault("timestamp", now())
    validate_event(event)
    encoded = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    with path.open("a+", encoding="utf-8") as handle:
        with locked_file(handle, exclusive=True):
            handle.seek(0)
            existing_text = handle.read()
            existing, _ = load_lines(existing_text, path)
            if any(item.get("event_id") == event["event_id"] for item in existing):
                return False
            if event.get("event") in ("execution", "segment_claim") and event.get("route_id"):
                if any(
                    item.get("event") == event.get("event")
                    and item.get("route_id") == event.get("route_id")
                    and item.get("segment_id") == event.get("segment_id")
                    for item in existing
                ):
                    return False
            if event.get("event") in ("parallel_plan", "parallel_execution") and event.get("route_id"):
                if any(
                    item.get("event") == event.get("event")
                    and item.get("route_id") == event.get("route_id")
                    for item in existing
                ):
                    return False
            handle.seek(0, os.SEEK_END)
            if existing_text and not existing_text.endswith("\n"):
                handle.write("\n")
            handle.write(encoded + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    return True


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


def build_summary(events, warnings):
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
    parallel_runs = [item for item in events if item.get("event") == "parallel_execution"]
    parallel_wall = sum(item["wall_clock_seconds"] for item in parallel_runs)
    parallel_worker = sum(item["cumulative_worker_seconds"] for item in parallel_runs)
    latest_parallel = parallel_runs[-1] if parallel_runs else None
    latest_parallel_brief = None
    if latest_parallel:
        wall = latest_parallel["wall_clock_seconds"]
        worker = latest_parallel["cumulative_worker_seconds"]
        latest_parallel_brief = {
            "route_id": latest_parallel["route_id"],
            "wall_clock_seconds": wall,
            "cumulative_worker_seconds": worker,
            "peak_concurrency": latest_parallel["peak_concurrency"],
            "effective_parallel_factor": round(worker / wall, 2) if wall > 0 else None,
            "worker_time_compression_percent": (
                round((1 - wall / worker) * 100, 1) if worker > 0 else None
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
            "count": len(parallel_runs),
            "wall_clock_seconds": round(parallel_wall, 3),
            "cumulative_worker_seconds": round(parallel_worker, 3),
            "peak_concurrency": max((item["peak_concurrency"] for item in parallel_runs), default=None),
            "effective_parallel_factor": round(parallel_worker / parallel_wall, 2) if parallel_wall > 0 else None,
            "worker_time_compression_percent": (
                round((1 - parallel_wall / parallel_worker) * 100, 1)
                if parallel_worker > 0 else None
            ),
            "latest": latest_parallel_brief,
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
        "### Verified parallel execution",
        "",
        (
            f"Runs: {summary['parallel_execution']['count']}; wall clock: "
            f"{summary['parallel_execution']['wall_clock_seconds']:g}s; cumulative worker time: "
            f"{summary['parallel_execution']['cumulative_worker_seconds']:g}s; peak concurrency: "
            f"{summary['parallel_execution']['peak_concurrency'] or '—'}; effective parallel factor: "
            f"{summary['parallel_execution']['effective_parallel_factor'] or '—'}x "
            "(cumulative worker time / wall clock; not a controlled serial A/B)."
            if summary["parallel_execution"]["count"] else
            "Insufficient verified parallel timing data."
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
    for key in ("event_id", "task_id", "route_id", "segment_id", "mode", "analysis_model", "model", "effort",
                "task_class", "outcome", "source", "fallback_from", "fallback_to",
                "fallback_reason", "verification", "concurrency"):
        value = getattr(args, key, None)
        if value is not None:
            event[key] = value
    if args.duration_seconds is not None:
        event["duration_seconds"] = args.duration_seconds
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
        "wall_clock_seconds": args.wall_clock_seconds,
        "cumulative_worker_seconds": args.cumulative_worker_seconds,
        "peak_concurrency": args.peak_concurrency,
        "worker_count": args.worker_count,
        "outcome": args.outcome, "source": args.source,
    }
    print(json.dumps({"appended": append_event(args.ledger, event), "event_id": event.get("event_id")}, ensure_ascii=False))


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
    }
    if args.task_id:
        event["task_id"] = args.task_id
    claimed = append_event(args.ledger, event)
    print(json.dumps({"claimed": claimed, "event_id": event.get("event_id")}, ensure_ascii=False))


def summarize(args):
    events, warnings = read_events(args.ledger)
    summary = build_summary(events, warnings)
    if args.format == "markdown":
        print(render_markdown(summary))
    else:
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


def render(args):
    events, warnings = read_events(args.ledger)
    update_report(args.report, render_markdown(build_summary(events, warnings)))
    print(args.report)


def parser():
    root = argparse.ArgumentParser()
    commands = root.add_subparsers(dest="command", required=True)
    rec = commands.add_parser("record")
    rec.add_argument("--ledger", type=Path, required=True)
    rec.add_argument("--event", choices=("skill_run", "execution"), required=True)
    rec.add_argument("--event-id")
    rec.add_argument("--task-id")
    rec.add_argument("--route-id")
    rec.add_argument("--segment-id")
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
    measured.set_defaults(func=parallel_execution)
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
    claimer.add_argument("--task-id")
    claimer.set_defaults(func=claim)
    report = commands.add_parser("summary")
    report.add_argument("--ledger", type=Path, required=True)
    report.add_argument("--format", choices=("json", "markdown"), default="json")
    report.set_defaults(func=summarize)
    renderer = commands.add_parser("render")
    renderer.add_argument("--ledger", type=Path, required=True)
    renderer.add_argument("--report", type=Path, required=True)
    renderer.set_defaults(func=render)
    return root


if __name__ == "__main__":
    arguments = parser().parse_args()
    arguments.func(arguments)
