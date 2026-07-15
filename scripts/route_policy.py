#!/usr/bin/env python3
"""Select a deterministic Codex model route and inspect current task metadata."""

import argparse
import hashlib
import json
import os
import re
import uuid
from pathlib import Path


MODELS = ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna")
RUNTIME_EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")
THREAD_ID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")
SEGMENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")
MAX_CANDIDATE_SEGMENTS = 16
DEFAULT_MAX_SEGMENTS = 4
DEFAULT_MAX_SWITCHES = 4
EXTENDED_MAX_SEGMENTS = 6
EXTENDED_MAX_SWITCHES = 6
HARD_MAX_SEGMENTS = 8
HARD_MAX_SWITCHES = 8
MODEL_ALIASES = {
    "gpt-5.6": "gpt-5.6-sol",
    "gpt-5.6 sol": "gpt-5.6-sol",
    "gpt5.6": "gpt-5.6-sol",
    "gpt5.6 sol": "gpt-5.6-sol",
    "sol": "gpt-5.6-sol",
    "gpt-5.6-sol": "gpt-5.6-sol",
    "terra": "gpt-5.6-terra",
    "gpt-5.6 terra": "gpt-5.6-terra",
    "gpt5.6 terra": "gpt-5.6-terra",
    "gpt-5.6-terra": "gpt-5.6-terra",
    "luna": "gpt-5.6-luna",
    "gpt-5.6 luna": "gpt-5.6-luna",
    "gpt5.6 luna": "gpt-5.6-luna",
    "gpt-5.6-luna": "gpt-5.6-luna",
}
EFFORT_ALIASES = {
    "low": "low", "medium": "medium", "high": "high", "xhigh": "xhigh",
    "very high": "xhigh", "very-high": "xhigh",
    "extra high": "xhigh", "extra-high": "xhigh",
}


def normalize_model(value):
    if value is None:
        return None
    normalized = MODEL_ALIASES.get(value.strip().lower())
    if normalized is None:
        raise ValueError(f"unsupported model: {value}")
    return normalized


def normalize_effort(value):
    if value is None:
        return None
    normalized = EFFORT_ALIASES.get(value.strip().lower())
    if normalized is None:
        raise ValueError(f"unsupported effort: {value}")
    return normalized


def unavailable_current(thread_id=None, reason="metadata-unavailable"):
    return {
        "status": "unavailable",
        "thread_id": thread_id,
        "model": None,
        "effort": None,
        "source": None,
        "reason": reason,
    }


def detect_current_route(sessions_root=None, environ=None):
    environ = os.environ if environ is None else environ
    thread_id = environ.get("CODEX_THREAD_ID")
    if not thread_id or not THREAD_ID_RE.fullmatch(thread_id):
        return unavailable_current(reason="CODEX_THREAD_ID-unavailable")

    if sessions_root is None:
        codex_home = Path(environ.get("CODEX_HOME", Path.home() / ".codex"))
        sessions_root = codex_home / "sessions"
    else:
        sessions_root = Path(sessions_root)

    try:
        candidates = list(sessions_root.glob(f"*/*/*/*{thread_id}*.jsonl"))
        if not candidates:
            candidates = list(sessions_root.rglob(f"*{thread_id}*.jsonl"))
    except OSError:
        return unavailable_current(thread_id, "sessions-unreadable")
    if not candidates:
        return unavailable_current(thread_id, "session-not-found")

    verified = []
    try:
        for session in candidates:
            session_id = None
            latest = None
            latest_source = None
            with session.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not any(marker in line for marker in (
                        '"type":"session_meta"', '"type": "session_meta"',
                        '"thread_settings_applied"',
                        '"type":"turn_context"', '"type": "turn_context"',
                    )):
                        continue
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    payload = item.get("payload", {})
                    if item.get("type") == "session_meta":
                        session_id = payload.get("id") or payload.get("session_id")
                        continue
                    if item.get("type") == "event_msg" and payload.get("type") == "thread_settings_applied":
                        settings = payload.get("thread_settings", {})
                        model = settings.get("model")
                        effort = settings.get("reasoning_effort")
                        source = "thread_settings_applied"
                    elif item.get("type") == "turn_context":
                        collaboration = payload.get("collaboration_mode", {}).get("settings", {})
                        model = payload.get("model") or collaboration.get("model")
                        effort = payload.get("effort") or collaboration.get("reasoning_effort")
                        source = "turn_context"
                    else:
                        continue
                    if isinstance(model, str) and isinstance(effort, str):
                        latest = (model, effort)
                        latest_source = source
            if session_id == thread_id and latest is not None:
                verified.append((session.stat().st_mtime_ns, latest, latest_source))
    except OSError:
        return unavailable_current(thread_id, "session-unreadable")

    if not verified:
        return unavailable_current(thread_id, "verified-settings-not-found")
    _, latest, latest_source = max(verified, key=lambda item: item[0])
    return {
        "status": "verified",
        "thread_id": thread_id,
        "model": latest[0],
        "effort": latest[1],
        "source": f"local-session-metadata:{latest_source}",
        "reason": None,
    }


def recommended_route(mode, task_kind, risk, size, report_model=None, report_effort=None):
    if mode == "apply" and (report_model is not None or report_effort is not None):
        if report_model is None or report_effort is None:
            raise ValueError("report route requires both model and effort")
        return report_model, report_effort, "report"

    if mode in ("assess", "retune"):
        if risk == "high" or task_kind == "complex":
            return "gpt-5.6-sol", "high", "adaptive-default"
        if risk == "low" and task_kind == "mechanical":
            return "gpt-5.6-sol", "low", "adaptive-default"
        return "gpt-5.6-sol", "medium", "default"

    if risk == "high" or task_kind == "complex":
        return "gpt-5.6-sol", "high", "deterministic-fallback"
    if task_kind == "mechanical":
        effort = "medium" if size == "large" else "low"
        return "gpt-5.6-luna", effort, "deterministic-fallback"
    effort = "high" if size == "large" else "medium"
    return "gpt-5.6-terra", effort, "deterministic-fallback"


def select_route(
    mode,
    task_kind="ordinary",
    risk="normal",
    size="normal",
    model_override=None,
    effort_override=None,
    report_model=None,
    report_effort=None,
    current=None,
):
    report_model = normalize_model(report_model)
    report_effort = normalize_effort(report_effort)
    target_model, target_effort, source = recommended_route(
        mode, task_kind, risk, size, report_model, report_effort
    )

    explicit_override = model_override is not None or effort_override is not None
    if model_override is not None:
        target_model = normalize_model(model_override)
    if effort_override is not None:
        target_effort = normalize_effort(effort_override)
    if explicit_override:
        source = "user-override"

    current = current or unavailable_current()
    execution_model, execution_effort = target_model, target_effort
    tiny_fast_path = (
        mode == "apply" and task_kind == "mechanical" and size == "tiny"
        and risk != "high" and not explicit_override
    )
    if tiny_fast_path:
        dispatch = "local"
        execution_model = current.get("model") or "current-route"
        execution_effort = current.get("effort") or "keep"
        reason = "tiny-task-switch-cost"
    elif current.get("status") == "verified" and (
        current.get("model"), current.get("effort")
    ) == (target_model, target_effort):
        dispatch = "local"
        reason = "route-already-matched"
    elif current.get("status") == "verified" and current.get("thread_id"):
        dispatch = "same-task-switch"
        reason = source
    else:
        dispatch = "selectable-subagent-or-local"
        reason = "original-route-unavailable"

    restore_required = dispatch == "same-task-switch"
    return {
        "route_id": str(uuid.uuid4()),
        "mode": mode,
        "recommended": {"model": target_model, "effort": target_effort, "source": source},
        "execution": {
            "model": execution_model,
            "effort": execution_effort,
            "dispatch": dispatch,
            "reason": reason,
        },
        "current": current,
        "restore_required": restore_required,
        "explicit_override": explicit_override,
    }


def _segment_text(value, field, segment_id):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"segment {segment_id} requires non-empty {field}")
    return value.strip()


def _segment_list(value, field, segment_id):
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not value or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError(f"segment {segment_id} requires non-empty {field}")
    return [item.strip() for item in value]


def _merge_adjacent_segments(segments):
    merged = []
    for segment in segments:
        if merged and (merged[-1]["model"], merged[-1]["effort"]) == (
            segment["model"], segment["effort"]
        ):
            previous = merged[-1]
            previous["goal"] += " Then: " + segment["goal"]
            previous["acceptance"].extend(segment["acceptance"])
            previous["validation_budget"] += "; " + segment["validation_budget"]
            previous["source_ids"].extend(segment["source_ids"])
            previous["size"] = "large" if "large" in (previous["size"], segment["size"]) else "normal"
            previous["reason"] = "adjacent-same-route-merged"
            continue
        merged.append(segment)
    for index, segment in enumerate(merged):
        segment["index"] = index + 1
        segment["depends_on"] = [] if index == 0 else [merged[index - 1]["segment_id"]]
    return merged


def plan_hash(
    segments, route_id, original, restore_required,
    segment_budget, switch_budget, budget_source,
):
    hashable = [
        {key: value for key, value in segment.items() if key != "attempt_id"}
        for segment in segments
    ]
    payload = {
        "protocol": "segmented-v1",
        "route_id": route_id,
        "original": original,
        "restore_required": restore_required,
        "segment_budget": segment_budget,
        "switch_budget": switch_budget,
        "budget_source": budget_source,
        "segments": hashable,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_segment_cursor(
    plan, cursor, segment_id, completed_ids,
    route_id, attempt_id, original_model, original_effort,
    protocol, restore_required, segment_budget, switch_budget, budget_source,
):
    if not isinstance(plan, dict) or plan.get("protocol") != "segmented-v1":
        raise ValueError("invalid segmented plan protocol")
    if protocol != plan.get("protocol"):
        raise ValueError("envelope protocol mismatch")
    segments = plan.get("segments")
    if not isinstance(segments, list) or not segments:
        raise ValueError("segmented plan has no segments")
    if not isinstance(route_id, str) or route_id != plan.get("route_id"):
        raise ValueError("envelope route_id mismatch")
    if restore_required is not plan.get("restore_required"):
        raise ValueError("envelope Restore decision mismatch")
    if (segment_budget, switch_budget, budget_source) != (
        plan.get("segment_budget"), plan.get("switch_budget"), plan.get("budget_source")
    ):
        raise ValueError("envelope budget mismatch")
    if (
        not isinstance(segment_budget, int) or isinstance(segment_budget, bool)
        or not 1 <= segment_budget <= HARD_MAX_SEGMENTS
        or not isinstance(switch_budget, int) or isinstance(switch_budget, bool)
        or not 1 <= switch_budget <= HARD_MAX_SWITCHES
        or budget_source not in ("standard", "adaptive-extended", "user-override")
    ):
        raise ValueError("invalid segmented plan budget")
    if len(segments) > segment_budget:
        raise ValueError("segmented plan exceeds its Segment budget")
    actual_switches = sum(
        segment.get("dispatch") == "same-task-switch" for segment in segments
    ) + int(plan.get("restore_required") is True)
    if plan.get("switch_count") != actual_switches or actual_switches > switch_budget:
        raise ValueError("segmented plan exceeds its switch budget")
    original = plan.get("original")
    if not isinstance(original, dict) or (
        original.get("model"), original.get("effort")
    ) != (original_model, original_effort):
        raise ValueError("envelope original route mismatch")
    if plan.get("plan_hash") != plan_hash(
        segments, plan.get("route_id"), original, plan.get("restore_required"),
        segment_budget, switch_budget, budget_source,
    ):
        raise ValueError("segmented plan hash mismatch")
    if not isinstance(cursor, int) or isinstance(cursor, bool) or not 0 <= cursor < len(segments):
        raise ValueError("segment cursor is out of range")
    expected_completed = [item["segment_id"] for item in segments[:cursor]]
    if completed_ids != expected_completed:
        raise ValueError("completed segment sequence does not match cursor")
    expected_segment = segments[cursor]["segment_id"]
    if segment_id != expected_segment:
        raise ValueError("segment_id does not match cursor")
    expected_attempt = hashlib.sha256(
        f"{route_id}:{plan['plan_hash']}:{expected_segment}".encode("utf-8")
    ).hexdigest()
    if segments[cursor].get("attempt_id") != expected_attempt:
        raise ValueError("segment attempt_id mismatch")
    if attempt_id != expected_attempt:
        raise ValueError("envelope attempt_id mismatch")
    return segments[cursor]


def _validate_user_budget(value, field, hard_max):
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= hard_max:
        raise ValueError(f"{field} must be an integer from 1 to {hard_max}")
    return value


def _resolve_plan_budget(segments, switches, max_segments=None, max_switches=None):
    requested_segments = _validate_user_budget(
        max_segments, "max_segments", HARD_MAX_SEGMENTS
    )
    requested_switches = _validate_user_budget(
        max_switches, "max_switches", HARD_MAX_SWITCHES
    )
    if requested_segments is not None or requested_switches is not None:
        shared = requested_segments if requested_segments is not None else requested_switches
        segment_budget = requested_segments if requested_segments is not None else shared
        switch_budget = requested_switches if requested_switches is not None else shared
        source = "user-override"
    elif len(segments) <= DEFAULT_MAX_SEGMENTS and switches <= DEFAULT_MAX_SWITCHES:
        segment_budget = DEFAULT_MAX_SEGMENTS
        switch_budget = DEFAULT_MAX_SWITCHES
        source = "standard"
    else:
        has_extension_basis = any(
            segment["task_kind"] == "complex" or segment["size"] == "large"
            for segment in segments
        )
        if not has_extension_basis:
            raise ValueError(
                "Apply plan exceeds the standard 4/4 budget; automatic extension requires "
                "a complex or large Segment, or an explicit user budget"
            )
        segment_budget = EXTENDED_MAX_SEGMENTS
        switch_budget = EXTENDED_MAX_SWITCHES
        source = "adaptive-extended"

    if len(segments) > segment_budget:
        raise ValueError(
            f"Apply plan has {len(segments)} routed segments after merging; "
            f"budget is {segment_budget}"
        )
    if switches > switch_budget:
        raise ValueError(
            f"Apply plan needs {switches} switches including Restore; budget is {switch_budget}"
        )
    return segment_budget, switch_budget, source


def plan_apply_segments(
    raw_segments,
    current=None,
    model_override=None,
    effort_override=None,
    report_model=None,
    report_effort=None,
    max_segments=None,
    max_switches=None,
):
    """Validate and route a bounded, linear Apply segment plan."""
    if not isinstance(raw_segments, list) or not raw_segments:
        raise ValueError("Apply segment plan must be a non-empty list")
    if len(raw_segments) > MAX_CANDIDATE_SEGMENTS:
        raise ValueError(f"Apply plan exceeds {MAX_CANDIDATE_SEGMENTS} candidate segments")

    global_model = normalize_model(model_override)
    global_effort = normalize_effort(effort_override)
    report_model = normalize_model(report_model)
    report_effort = normalize_effort(report_effort)
    if (report_model is None) != (report_effort is None):
        raise ValueError("report route requires both model and effort")
    if report_model is not None and len(raw_segments) != 1:
        raise ValueError(
            "a global report route applies only to one-segment Apply; use per-segment report routes"
        )
    current = current or unavailable_current()
    current_route = None
    if current.get("status") in ("verified", "synthetic"):
        current_route = (current.get("model"), current.get("effort"))

    routed = []
    seen_ids = set()
    previous_id = None
    for index, raw in enumerate(raw_segments):
        if not isinstance(raw, dict):
            raise ValueError(f"segment {index + 1} is not an object")
        segment_id = raw.get("segment_id") or f"segment-{index + 1}"
        if not isinstance(segment_id, str) or not SEGMENT_ID_RE.fullmatch(segment_id):
            raise ValueError(f"invalid segment_id: {segment_id}")
        if segment_id in seen_ids:
            raise ValueError(f"duplicate segment_id: {segment_id}")
        seen_ids.add(segment_id)

        dependencies = raw.get("depends_on", [] if index == 0 else [previous_id])
        if isinstance(dependencies, str):
            dependencies = [dependencies]
        expected = [] if index == 0 else [previous_id]
        if dependencies != expected:
            raise ValueError(f"segment {segment_id} must depend only on the previous segment")

        task_kind = raw.get("task_kind", "ordinary")
        risk = raw.get("risk", "normal")
        size = raw.get("size", "normal")
        if task_kind not in ("mechanical", "ordinary", "complex"):
            raise ValueError(f"invalid task_kind for segment {segment_id}")
        if risk not in ("low", "normal", "high"):
            raise ValueError(f"invalid risk for segment {segment_id}")
        if size not in ("tiny", "normal", "large"):
            raise ValueError(f"invalid size for segment {segment_id}")

        target_model, target_effort, source = recommended_route(
            "apply", task_kind, risk, size
        )
        segment_model = normalize_model(raw.get("model"))
        segment_effort = normalize_effort(raw.get("effort"))
        route_source = raw.get("route_source", "user-override" if segment_model or segment_effort else None)
        if route_source not in (None, "user-override", "report"):
            raise ValueError(f"invalid route_source for segment {segment_id}")
        if route_source == "report" and ((segment_model is None) != (segment_effort is None)):
            raise ValueError(f"report route requires both model and effort for segment {segment_id}")
        if global_model and segment_model and global_model != segment_model:
            if route_source == "user-override":
                raise ValueError(f"conflicting model overrides for segment {segment_id}")
            segment_model = None
        if global_effort and segment_effort and global_effort != segment_effort:
            if route_source == "user-override":
                raise ValueError(f"conflicting effort overrides for segment {segment_id}")
            segment_effort = None
        report_default_model = report_model if len(raw_segments) == 1 else None
        report_default_effort = report_effort if len(raw_segments) == 1 else None
        explicit = any((global_model, global_effort)) or route_source == "user-override"
        target_model = global_model or segment_model or report_default_model or target_model
        target_effort = global_effort or segment_effort or report_default_effort or target_effort
        if explicit:
            source = "user-override"
        elif route_source == "report" or report_default_model:
            source = "report"

        if task_kind == "mechanical" and size == "tiny" and risk != "high" and not explicit:
            if routed:
                target_model, target_effort = routed[-1]["model"], routed[-1]["effort"]
            elif current_route:
                target_model, target_effort = current_route
            source = "tiny-segment-switch-cost"

        routed.append({
            "segment_id": segment_id,
            "source_ids": [segment_id],
            "index": index + 1,
            "goal": _segment_text(raw.get("goal"), "goal", segment_id),
            "depends_on": dependencies,
            "task_kind": task_kind,
            "risk": risk,
            "size": size,
            "acceptance": _segment_list(raw.get("acceptance"), "acceptance", segment_id),
            "validation_budget": _segment_text(
                raw.get("validation_budget"), "validation_budget", segment_id
            ),
            "model": target_model,
            "effort": target_effort,
            "reason": source,
        })
        previous_id = segment_id

    segments = _merge_adjacent_segments(routed)
    if len(segments) > HARD_MAX_SEGMENTS:
        raise ValueError(
            f"Apply plan exceeds the hard limit of {HARD_MAX_SEGMENTS} routed segments after merging"
        )

    switches = 0
    previous_route = current_route
    for segment in segments:
        route = (segment["model"], segment["effort"])
        if current_route is None:
            segment["dispatch"] = "selectable-subagent-or-local"
        elif route == previous_route:
            segment["dispatch"] = "local"
        else:
            segment["dispatch"] = "same-task-switch"
            switches += 1
        previous_route = route

    restore_required = bool(
        current_route and previous_route and previous_route != current_route
    )
    if restore_required:
        switches += 1
    segment_budget, switch_budget, budget_source = _resolve_plan_budget(
        segments, switches, max_segments, max_switches
    )

    route_id = str(uuid.uuid4())
    original = {
        "model": current.get("model") if current.get("status") in ("verified", "synthetic") else None,
        "effort": current.get("effort") if current.get("status") in ("verified", "synthetic") else None,
    }
    result = {
        "route_id": route_id,
        "mode": "apply",
        "protocol": "segmented-v1",
        "current": current,
        "original": original,
        "segments": segments,
        "segment_count": len(segments),
        "switch_count": switches,
        "segment_budget": segment_budget,
        "switch_budget": switch_budget,
        "budget_source": budget_source,
        "max_segments": segment_budget,
        "max_switches": switch_budget,
        "hard_max_segments": HARD_MAX_SEGMENTS,
        "hard_max_switches": HARD_MAX_SWITCHES,
        "restore_required": restore_required,
        "explicit_override": bool(
            max_segments is not None or max_switches is not None
            or global_model or global_effort or any(
            (raw.get("model") or raw.get("effort"))
            and raw.get("route_source", "user-override") == "user-override"
            for raw in raw_segments
        )),
    }
    result["plan_hash"] = plan_hash(
        segments, route_id, original, restore_required,
        segment_budget, switch_budget, budget_source,
    )
    for segment in segments:
        segment["attempt_id"] = hashlib.sha256(
            f"{route_id}:{result['plan_hash']}:{segment['segment_id']}".encode("utf-8")
        ).hexdigest()
    return result


def parser():
    root = argparse.ArgumentParser()
    root.add_argument("--inspect-current", action="store_true")
    root.add_argument("--sessions-root", type=Path)
    root.add_argument("--no-runtime-detection", action="store_true")
    root.add_argument("--current-model")
    root.add_argument("--current-effort", choices=RUNTIME_EFFORTS)
    root.add_argument("--mode", choices=("apply", "assess", "retune"))
    root.add_argument("--task-kind", choices=("mechanical", "ordinary", "complex"), default="ordinary")
    root.add_argument("--risk", choices=("low", "normal", "high"), default="normal")
    root.add_argument("--size", choices=("tiny", "normal", "large"), default="normal")
    root.add_argument("--model")
    root.add_argument("--effort")
    root.add_argument("--report-model")
    root.add_argument("--report-effort")
    root.add_argument("--segments-json", help="JSON array for a bounded multi-segment Apply plan")
    root.add_argument("--max-segments", type=int, help="User Segment budget override (1-8)")
    root.add_argument("--max-switches", type=int, help="User switch budget override including Restore (1-8)")
    root.add_argument("--validate-envelope-json", help="JSON object containing plan, cursor, segment_id, and completed_ids")
    root.add_argument("--synthetic-current-for-test", action="store_true", help=argparse.SUPPRESS)
    return root


def main():
    args = parser().parse_args()
    if args.validate_envelope_json is not None:
        try:
            envelope = json.loads(args.validate_envelope_json)
            segment = validate_segment_cursor(
                envelope.get("plan"), envelope.get("cursor"),
                envelope.get("segment_id"), envelope.get("completed_ids"),
                envelope.get("route_id"), envelope.get("attempt_id"),
                envelope.get("original_model"), envelope.get("original_effort"),
                envelope.get("protocol"), envelope.get("restore_required"),
                envelope.get("segment_budget"), envelope.get("switch_budget"),
                envelope.get("budget_source"),
            )
        except (json.JSONDecodeError, AttributeError, ValueError) as exc:
            raise SystemExit(f"invalid segment envelope: {exc}") from exc
        print(json.dumps({"valid": True, "segment": segment}, ensure_ascii=False, sort_keys=True))
        return
    if (args.current_model is None) != (args.current_effort is None):
        raise SystemExit("--current-model and --current-effort must be supplied together")
    if args.current_model is not None:
        if not args.synthetic_current_for_test:
            raise SystemExit("explicit current route injection requires --synthetic-current-for-test")
        current = {
            "status": "synthetic",
            "thread_id": os.environ.get("CODEX_THREAD_ID"),
            "model": args.current_model,
            "effort": args.current_effort,
            "source": "synthetic-test-input",
            "reason": "not-runtime-verified",
        }
    elif args.no_runtime_detection:
        current = unavailable_current()
    else:
        current = detect_current_route(args.sessions_root)
    if args.inspect_current:
        print(json.dumps(current, ensure_ascii=False, sort_keys=True))
        return
    if args.mode is None:
        raise SystemExit("--mode is required unless --inspect-current is used")
    if args.segments_json is None and (
        args.max_segments is not None or args.max_switches is not None
    ):
        raise SystemExit("--max-segments and --max-switches require --segments-json")
    try:
        if args.segments_json is not None:
            if args.mode != "apply":
                raise ValueError("--segments-json is valid only for Apply")
            try:
                raw_segments = json.loads(args.segments_json)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid --segments-json: {exc}") from exc
            route = plan_apply_segments(
                raw_segments,
                current=current,
                model_override=args.model,
                effort_override=args.effort,
                report_model=args.report_model,
                report_effort=args.report_effort,
                max_segments=args.max_segments,
                max_switches=args.max_switches,
            )
            print(json.dumps(route, ensure_ascii=False, sort_keys=True))
            return
        route = select_route(
            args.mode,
            args.task_kind,
            args.risk,
            args.size,
            args.model,
            args.effort,
            args.report_model,
            args.report_effort,
            current,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(route, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
