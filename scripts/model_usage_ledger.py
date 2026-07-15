#!/usr/bin/env python3
"""Safely append, aggregate, and render the model-routing usage ledger."""

import argparse
import json
import math
import os
import statistics
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


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


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
        durations = [item["duration_seconds"] for item in active_items if item.get("duration_seconds") is not None]
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
            "duration_median_seconds": round(statistics.median(durations), 1) if durations else None,
            "duration_p75_seconds": round(percentile(durations, 0.75), 1) if durations else None,
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
    legacy_models = Counter(item.get("model", "unknown") for item in legacy_attempts)
    analyses = Counter(
        item.get("analysis_model", "unknown")
        for item in events if item.get("event") == "skill_run"
    )
    latest = next((item for item in reversed(events) if item.get("event") == "allocation"), None)
    return {
        "actual_execution": proportions(actual_models),
        "model_effort_usage": proportions(model_effort),
        "legacy_execution": proportions(legacy_models),
        "analysis_runs": proportions(analyses),
        "recommended_allocation": latest,
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
                "fallback_reason", "verification"):
        value = getattr(args, key, None)
        if value is not None:
            event[key] = value
    if args.duration_seconds is not None:
        event["duration_seconds"] = args.duration_seconds
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
    rec.set_defaults(func=record)
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
