#!/usr/bin/env python3
"""Select a deterministic Codex model route and inspect current task metadata."""

import argparse
import hashlib
import itertools
import json
import os
import re
import uuid
from datetime import date, timedelta
from pathlib import Path


MODELS = ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna")
GPT55_MODEL = "gpt-5.5"
FAMILY_FALLBACK_ORDER = {
    "gpt-5.6-sol": ("gpt-5.6-terra", "gpt-5.6-luna"),
    "gpt-5.6-terra": ("gpt-5.6-sol", "gpt-5.6-luna"),
    "gpt-5.6-luna": ("gpt-5.6-terra", "gpt-5.6-sol"),
}
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
DEFAULT_AUTO_PARALLELISM = 4
# Kept only to validate already-issued dependency-parallel-v1 envelopes.
EXTENDED_AUTO_PARALLELISM = 6
ADAPTIVE_MIN_READY_TASKS = 5
HARD_MAX_PARALLELISM = MAX_CANDIDATE_SEGMENTS
DEFAULT_COORDINATOR_SLOTS = 1
FAST_PROTOCOL = "apply-fast-v1"
SEGMENTED_PROTOCOL = "segmented-v1"
PARALLEL_PROTOCOL = "dependency-parallel-v1"
DEFAULT_EVIDENCE_PATH = Path(__file__).resolve().parents[1] / "references" / "benchmark-evidence.json"
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


def unavailable_evidence(status="missing", reason="evidence-file-missing"):
    return {
        "status": status,
        "snapshot_id": None,
        "observed_at": None,
        "expires_at": None,
        "source": None,
        "reason": reason,
        "lanes": {},
    }


def load_benchmark_evidence(path=None, today=None):
    """Load a versioned offline snapshot; never fetch evidence during Apply."""
    path = Path(path) if path is not None else DEFAULT_EVIDENCE_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return unavailable_evidence()
    except (OSError, json.JSONDecodeError) as exc:
        return unavailable_evidence("invalid", f"evidence-read-error:{type(exc).__name__}")

    try:
        if data.get("schema_version") != 1:
            raise ValueError("unsupported-schema")
        snapshot_id = data["snapshot_id"]
        observed_at = date.fromisoformat(data["observed_at"])
        expires_after_days = data["expires_after_days"]
        lanes = data["routing_lanes"]
        sources = data["sources"]
        policy = data["policy"]
        effort_metrics = data["effort_profiles"]["metrics"]
        if not isinstance(snapshot_id, str) or not snapshot_id:
            raise ValueError("invalid-snapshot-id")
        if not isinstance(expires_after_days, int) or not 1 <= expires_after_days <= 365:
            raise ValueError("invalid-expiry")
        if data.get("runtime_network_required") is not False:
            raise ValueError("runtime-network-must-be-disabled")
        if policy.get("task_signals_override_benchmark_priors") is not True:
            raise ValueError("task-evidence-precedence-missing")
        if policy.get("gpt55_fallback_requires_gpt56_family_unavailable") is not True:
            raise ValueError("gpt56-family-fallback-guard-missing")
        source_ids = {
            source.get("id") for source in sources if isinstance(source, dict)
        }
        required_sources = {
            "openai-gpt56-launch", "aa-coding-agent-index-v1.1",
            "aa-intelligence-index-v4.1",
        }
        if not required_sources.issubset(source_ids):
            raise ValueError("required-sources-missing")
        gpt56_efforts = {
            (item.get("model"), item.get("effort"))
            for item in effort_metrics if isinstance(item, dict)
            and item.get("model") in MODELS
        }
        expected_efforts = {
            (model, effort) for model in MODELS
            for effort in ("low", "medium", "high", "xhigh")
        }
        if not expected_efforts.issubset(gpt56_efforts):
            raise ValueError("gpt56-effort-matrix-incomplete")
        required_lanes = {
            "mechanical_clear", "mechanical_large", "ordinary_bounded",
            "ordinary_interacting", "complex_bounded",
            "complex_uncertain_or_high_consequence", "complex_failed_escalation",
        }
        if not isinstance(lanes, dict) or not required_lanes.issubset(lanes):
            raise ValueError("missing-routing-lanes")
        for lane in required_lanes:
            normalize_model(lanes[lane].get("model"))
            normalize_effort(lanes[lane].get("effort"))
    except (KeyError, TypeError, ValueError) as exc:
        return unavailable_evidence("invalid", f"evidence-schema-error:{exc}")

    current_day = today or date.today()
    if isinstance(current_day, str):
        current_day = date.fromisoformat(current_day)
    expires_at = observed_at + timedelta(days=expires_after_days)
    status = "active" if current_day <= expires_at else "stale"
    return {
        "status": status,
        "snapshot_id": snapshot_id,
        "observed_at": observed_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "source": str(path),
        "reason": None if status == "active" else "evidence-snapshot-expired",
        "lanes": lanes if status == "active" else {},
    }


def evidence_audit(evidence):
    return {
        key: evidence.get(key)
        for key in ("status", "snapshot_id", "observed_at", "expires_at", "reason")
    }


def _task_signals(task_kind, risk, size, ambiguity=None, coupling=None,
                  verification=None, consequence=None, prior_failure=False):
    ambiguity = ambiguity or ("low" if risk == "low" or size == "tiny" else "medium")
    coupling = coupling or ("low" if size == "tiny" else ("high" if size == "large" and task_kind == "complex" else "medium"))
    verification = verification or ("deterministic" if task_kind == "mechanical" or risk == "low" else "mixed")
    consequence = consequence or ("high" if risk == "high" else ("low" if risk == "low" else "normal"))
    if ambiguity not in ("low", "medium", "high"):
        raise ValueError(f"unsupported ambiguity: {ambiguity}")
    if coupling not in ("low", "medium", "high"):
        raise ValueError(f"unsupported coupling: {coupling}")
    if verification not in ("deterministic", "mixed", "judgment"):
        raise ValueError(f"unsupported verification: {verification}")
    if consequence not in ("low", "normal", "high"):
        raise ValueError(f"unsupported consequence: {consequence}")
    if not isinstance(prior_failure, bool):
        raise ValueError("prior_failure must be a boolean")
    return {
        "ambiguity": ambiguity,
        "coupling": coupling,
        "verification": verification,
        "consequence": consequence,
        "prior_failure": prior_failure,
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


def normalize_available_model(value):
    if not isinstance(value, str) or not value.strip():
        return None
    key = value.strip().lower()
    if key in ("gpt-5.5", "gpt5.5"):
        return GPT55_MODEL
    return MODEL_ALIASES.get(key)


def is_gpt56_model(value):
    return value in MODELS


def resolve_family_fallback(target_model, target_effort, available_models=None):
    """Resolve pre-execution availability without leaving GPT-5.6 prematurely."""
    target_model = normalize_model(target_model)
    target_effort = normalize_effort(target_effort)
    if available_models is None:
        return {
            "target": {"model": target_model, "effort": target_effort},
            "execution": {"model": target_model, "effort": target_effort},
            "fallback": False,
            "gpt56_family_available": None,
            "reason": "availability-unknown-try-gpt56-target-first",
        }

    available = {
        normalized for model in available_models
        if (normalized := normalize_available_model(model)) is not None
    }
    if target_model in available:
        execution_model = target_model
        reason = "target-available"
    else:
        execution_model = next(
            (model for model in FAMILY_FALLBACK_ORDER[target_model] if model in available),
            None,
        )
        reason = "gpt56-family-fallback" if execution_model else None

    family_available = any(model in available for model in MODELS)
    if execution_model is None and not family_available and GPT55_MODEL in available:
        execution_model = GPT55_MODEL
        reason = "gpt56-family-unavailable"
    elif execution_model is None:
        reason = "no-supported-model-available"

    return {
        "target": {"model": target_model, "effort": target_effort},
        "execution": {"model": execution_model, "effort": target_effort},
        "fallback": execution_model != target_model,
        "gpt56_family_available": family_available,
        "reason": reason,
    }


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


def recommended_route(
    mode, task_kind, risk, size, report_model=None, report_effort=None,
    ambiguity=None, coupling=None, verification=None, consequence=None,
    prior_failure=False, evidence=None,
):
    if mode == "apply" and (report_model is not None or report_effort is not None):
        if report_model is None or report_effort is None:
            raise ValueError("report route requires both model and effort")
        return report_model, report_effort, "report"

    signals = _task_signals(
        task_kind, risk, size, ambiguity, coupling, verification,
        consequence, prior_failure,
    )
    evidence = evidence or load_benchmark_evidence()

    if mode in ("assess", "retune"):
        if risk == "high" or task_kind == "complex":
            return "gpt-5.6-sol", "high", "adaptive-default"
        if risk == "low" and task_kind == "mechanical":
            return "gpt-5.6-sol", "low", "adaptive-default"
        return "gpt-5.6-sol", "medium", "default"

    if evidence.get("status") != "active":
        return _legacy_recommended_route(mode, task_kind, risk, size)

    lanes = evidence["lanes"]
    if task_kind == "complex" and signals["prior_failure"]:
        lane = "complex_failed_escalation"
    elif (
        signals["consequence"] == "high" or signals["ambiguity"] == "high"
        or signals["coupling"] == "high" or signals["verification"] == "judgment"
    ):
        lane = "complex_uncertain_or_high_consequence"
    elif task_kind == "complex":
        lane = "complex_bounded"
    elif task_kind == "mechanical":
        lane = "mechanical_large" if size == "large" else "mechanical_clear"
    elif (
        signals["ambiguity"] == "low" and signals["coupling"] == "low"
        and signals["verification"] == "deterministic"
    ):
        lane = "ordinary_bounded"
    else:
        lane = "ordinary_interacting"
    selected = lanes[lane]
    return normalize_model(selected["model"]), normalize_effort(selected["effort"]), f"benchmark-prior:{lane}"


def _legacy_recommended_route(mode, task_kind, risk, size):
    """Retained as an explicit reference for stale/invalid snapshot tests."""
    if risk == "high" or task_kind == "complex":
        return "gpt-5.6-sol", "high", "deterministic-fallback"
    if task_kind == "mechanical":
        effort = "medium" if size == "large" else "low"
        return "gpt-5.6-luna", effort, "deterministic-fallback"
    effort = "high" if size == "large" else ("low" if risk == "low" else "medium")
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
    ambiguity=None,
    coupling=None,
    verification=None,
    consequence=None,
    prior_failure=False,
    evidence_path=None,
):
    report_model = normalize_model(report_model)
    report_effort = normalize_effort(report_effort)
    evidence = load_benchmark_evidence(evidence_path)
    target_model, target_effort, source = recommended_route(
        mode, task_kind, risk, size, report_model, report_effort,
        ambiguity, coupling, verification, consequence, prior_failure, evidence,
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
    if current.get("status") in ("verified", "synthetic") and (
        current.get("model"), current.get("effort")
    ) == (target_model, target_effort):
        dispatch = "local"
        reason = "route-already-matched"
    elif current.get("status") in ("verified", "synthetic") and current.get("thread_id"):
        dispatch = "same-task-switch"
        reason = source
    else:
        dispatch = "selectable-subagent-or-local"
        reason = "original-route-unavailable"

    restore_required = dispatch == "same-task-switch" and is_gpt56_model(
        current.get("model")
    )
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
        "routing_evidence": evidence_audit(evidence),
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


def _optional_segment_list(value, field, segment_id):
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError(f"segment {segment_id} has invalid {field}")
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
            previous["decisions"] = list(dict.fromkeys(
                previous.get("decisions", []) + segment.get("decisions", [])
            ))
            previous["prohibited_actions"] = list(dict.fromkeys(
                previous.get("prohibited_actions", []) + segment.get("prohibited_actions", [])
            ))
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
    segment_budget, switch_budget, budget_source, routing_evidence=None,
    protocol=SEGMENTED_PROTOCOL, parallel=None,
):
    hashable = [
        {key: value for key, value in segment.items() if key != "attempt_id"}
        for segment in segments
    ]
    payload = {
        "protocol": protocol,
        "route_id": route_id,
        "original": original,
        "restore_required": restore_required,
        "segment_budget": segment_budget,
        "switch_budget": switch_budget,
        "budget_source": budget_source,
        "segments": hashable,
    }
    if routing_evidence is not None:
        payload["routing_evidence"] = routing_evidence
    if parallel is not None:
        payload["parallel"] = parallel
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def context_capsule(plan, segment_id):
    """Return bounded worker context; the coordinator retains the full plan/chat."""
    if not isinstance(plan, dict):
        raise ValueError("context capsule requires a plan")
    segment = next(
        (item for item in plan.get("segments", []) if item.get("segment_id") == segment_id),
        None,
    )
    if segment is None:
        raise ValueError("context capsule segment is missing")
    return {
        "protocol": plan.get("protocol"),
        "route_id": plan.get("route_id"),
        "plan_hash": plan.get("plan_hash"),
        "segment_id": segment_id,
        "attempt_id": segment.get("attempt_id"),
        "model": segment.get("model"),
        "effort": segment.get("effort"),
        "goal": segment.get("goal"),
        "depends_on": segment.get("depends_on", []),
        "acceptance": segment.get("acceptance", []),
        "validation_budget": segment.get("validation_budget"),
        "access_mode": segment.get("access_mode"),
        "write_scopes": segment.get("write_scopes", []),
        "conflict_keys": segment.get("conflict_keys", []),
        "decisions": segment.get("decisions", []),
        "prohibited_actions": segment.get("prohibited_actions", [
            "do-not-replan", "do-not-delegate", "do-not-touch-out-of-scope-files",
        ]),
    }


def _bounded_integer(value, field, maximum):
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= maximum:
        raise ValueError(f"{field} must be an integer from 1 to {maximum}")
    return value


def _scopes_overlap(left, right):
    left = left.rstrip("/")
    right = right.rstrip("/")
    return left == right or left.startswith(right + "/") or right.startswith(left + "/")


def _normalized_scope_list(value, field, segment_id, required=False):
    if value is None:
        value = []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or (required and not value):
        raise ValueError(f"segment {segment_id} requires non-empty {field}")
    result = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"segment {segment_id} has invalid {field}")
        item = item.strip().replace("\\", "/").rstrip("/")
        if field == "write_scopes" and (
            item.startswith("/") or item in (".", "..") or ".." in item.split("/")
            or any(character in item for character in "*?[]")
        ):
            raise ValueError(
                f"segment {segment_id} {field} must contain concrete repository-relative paths"
            )
        result.append(item)
    return sorted(set(result))


def _dependency_reachable(by_id, ancestor, descendant, memo):
    key = (ancestor, descendant)
    if key in memo:
        return memo[key]
    dependencies = by_id[descendant]["depends_on"]
    reachable = ancestor in dependencies or any(
        _dependency_reachable(by_id, ancestor, dependency, memo)
        for dependency in dependencies
    )
    memo[key] = reachable
    return reachable


def _merge_short_siblings(segments):
    successors = {item["segment_id"]: [] for item in segments}
    for item in segments:
        for dependency in item["depends_on"]:
            successors[dependency].append(item["segment_id"])
    groups = {}
    for item in segments:
        if item["work_estimate"] != "short":
            continue
        key = (
            tuple(item["depends_on"]), tuple(successors[item["segment_id"]]),
            item["model"], item["effort"], item["access_mode"],
            item["task_kind"], item["risk"], tuple(item["conflict_keys"]),
        )
        groups.setdefault(key, []).append(item)
    replaced = {}
    for siblings in groups.values():
        # Three short tasks approximate one normal task; larger sets remain separate.
        for offset in range(0, len(siblings), 3):
            chunk = siblings[offset:offset + 3]
            if len(chunk) < 2:
                continue
            if chunk[0]["access_mode"] == "write" and any(
                _scopes_overlap(left, right)
                for index, item in enumerate(chunk)
                for other in chunk[index + 1:]
                for left in item["write_scopes"] for right in other["write_scopes"]
            ):
                continue
            target = chunk[0]
            for item in chunk[1:]:
                target["goal"] += " Then: " + item["goal"]
                target["acceptance"].extend(item["acceptance"])
                target["validation_budget"] += "; " + item["validation_budget"]
                target["source_ids"].extend(item["source_ids"])
                target["decisions"] = list(dict.fromkeys(
                    target.get("decisions", []) + item.get("decisions", [])
                ))
                target["prohibited_actions"] = list(dict.fromkeys(
                    target.get("prohibited_actions", []) + item.get("prohibited_actions", [])
                ))
                target["write_scopes"] = sorted(set(target["write_scopes"] + item["write_scopes"]))
                replaced[item["segment_id"]] = target["segment_id"]
            target["work_estimate"] = "normal"
            target["reason"] = "compatible-short-siblings-merged"
    merged = [item for item in segments if item["segment_id"] not in replaced]
    for item in merged:
        item["depends_on"] = list(dict.fromkeys(
            replaced.get(dependency, dependency) for dependency in item["depends_on"]
            if replaced.get(dependency, dependency) != item["segment_id"]
        ))
    return merged


def _serialize_parallel_conflicts(segments):
    by_id = {item["segment_id"]: item for item in segments}
    serialized = []
    for later_index, later in enumerate(segments):
        for earlier in segments[:later_index]:
            shared_key = sorted(set(earlier["conflict_keys"]) & set(later["conflict_keys"]))
            overlapping_write = (
                earlier["access_mode"] == "write" and later["access_mode"] == "write"
                and any(
                    _scopes_overlap(left, right)
                    for left in earlier["write_scopes"] for right in later["write_scopes"]
                )
            )
            if not shared_key and not overlapping_write:
                continue
            memo = {}
            if _dependency_reachable(by_id, earlier["segment_id"], later["segment_id"], memo):
                continue
            later["depends_on"].append(earlier["segment_id"])
            serialized.append({
                "before": earlier["segment_id"],
                "after": later["segment_id"],
                "reason": "shared-conflict-key" if shared_key else "overlapping-write-scope",
                "conflict_keys": shared_key,
            })
    return serialized


def _parallel_segments_conflict(left, right):
    if set(left["conflict_keys"]) & set(right["conflict_keys"]):
        return True
    return (
        left["access_mode"] == "write" and right["access_mode"] == "write"
        and any(
            _scopes_overlap(left_scope, right_scope)
            for left_scope in left["write_scopes"]
            for right_scope in right["write_scopes"]
        )
    )


def _critical_path_priorities(segments):
    by_id = {item["segment_id"]: item for item in segments}
    children = {identifier: [] for identifier in by_id}
    for item in segments:
        for dependency in item["depends_on"]:
            children[dependency].append(item["segment_id"])
    critical = {}

    def visit(identifier):
        if identifier not in critical:
            critical[identifier] = {"short": 1, "normal": 2, "long": 4}[
                by_id[identifier]["work_estimate"]
            ] + max(
                (visit(child) for child in children[identifier]), default=0
            )
        return critical[identifier]

    for identifier in by_id:
        visit(identifier)
    source_order = {item["segment_id"]: index for index, item in enumerate(segments)}
    priority_order = sorted(
        by_id, key=lambda identifier: (-critical[identifier], source_order[identifier])
    )
    initial_frontier = [
        identifier for identifier in priority_order if not by_id[identifier]["depends_on"]
    ]
    return critical, priority_order, initial_frontier


def _parallel_capacity_evaluation(segments, initial_frontier):
    """Find useful model concurrency after dependencies, merging, and conflicts."""
    by_id = {item["segment_id"]: item for item in segments}
    model_ids = [item["segment_id"] for item in segments]
    model_ready = list(initial_frontier)
    descendants = {}

    def collect_descendants(identifier):
        if identifier not in descendants:
            direct = [
                item["segment_id"] for item in segments
                if identifier in item["depends_on"]
            ]
            descendants[identifier] = set(direct)
            for child in direct:
                descendants[identifier].update(collect_descendants(child))
        return descendants[identifier]

    for identifier in model_ids:
        collect_descendants(identifier)

    useful_parallelism = 1
    for width in range(len(model_ids), 1, -1):
        if any(
            all(
                right not in descendants[left] and left not in descendants[right]
                for left, right in itertools.combinations(candidate, 2)
            )
            for candidate in itertools.combinations(model_ids, width)
        ):
            useful_parallelism = width
            break
    return {
        "model_task_count": len(model_ids),
        "initial_ready_model_task_count": len(model_ready),
        "useful_parallelism": useful_parallelism,
        "basis": "maximum-dependency-independent-model-width",
        "queue_policy": "dispatch-only-into-confirmed-free-slots",
    }


def plan_parallel_segments(
    raw_segments, current=None, model_override=None, effort_override=None,
    report_model=None, report_effort=None, max_segments=None, max_switches=None,
    max_parallelism=None, runtime_max_threads=None, runtime_total_slots=None,
    runtime_running_workers=0, coordinator_slots=DEFAULT_COORDINATOR_SLOTS,
    evidence_path=None,
):
    """Create a dependency-aware, wait-any Apply plan without executing it."""
    if not isinstance(raw_segments, list) or not raw_segments:
        raise ValueError("Apply segment plan must be a non-empty list")
    if len(raw_segments) > MAX_CANDIDATE_SEGMENTS:
        raise ValueError(f"Apply plan exceeds {MAX_CANDIDATE_SEGMENTS} candidate segments")
    if (report_model is None) != (report_effort is None):
        raise ValueError("report route requires both model and effort")
    if report_model is not None and len(raw_segments) != 1:
        raise ValueError(
            "a global report route applies only to one-segment Apply; use per-segment report routes"
        )
    if runtime_total_slots is not None and runtime_max_threads is not None:
        raise ValueError("use runtime_total_slots or legacy runtime_max_threads, not both")
    if not isinstance(runtime_running_workers, int) or isinstance(runtime_running_workers, bool) or runtime_running_workers < 0:
        raise ValueError("runtime_running_workers must be a non-negative integer")
    if runtime_running_workers and runtime_total_slots is None:
        raise ValueError("runtime_running_workers requires observed runtime_total_slots")
    coordinator_slots = _bounded_integer(coordinator_slots, "coordinator_slots", 8)
    if runtime_total_slots is not None:
        runtime_total_slots = _bounded_integer(runtime_total_slots, "runtime_total_slots", 64)
        available_worker_slots = max(
            0, runtime_total_slots - coordinator_slots - runtime_running_workers
        )
        capacity_source = "observed-total-slots"
    elif runtime_max_threads is not None:
        # Backward compatibility: older callers supplied observed worker capacity.
        available_worker_slots = _bounded_integer(
            runtime_max_threads, "runtime_max_threads", 64
        )
        capacity_source = "legacy-observed-worker-capacity"
    else:
        # Unknown capacity must not become a pre-created executor queue.
        available_worker_slots = 1
        capacity_source = "unverified-dispatch-probe"
    if available_worker_slots < 1:
        raise ValueError("parallel planning has no observed free worker slot")
    user_parallelism = None if max_parallelism is None else _bounded_integer(
        max_parallelism, "max_parallelism", HARD_MAX_PARALLELISM
    )
    current = current or unavailable_current()
    routed, seen_ids = [], set()
    for index, raw in enumerate(raw_segments):
        if not isinstance(raw, dict):
            raise ValueError(f"segment {index + 1} is not an object")
        segment_id = raw.get("segment_id") or f"segment-{index + 1}"
        if not isinstance(segment_id, str) or not SEGMENT_ID_RE.fullmatch(segment_id):
            raise ValueError(f"invalid segment_id: {segment_id}")
        if segment_id in seen_ids:
            raise ValueError(f"duplicate segment_id: {segment_id}")
        dependencies = raw.get("depends_on", [])
        if isinstance(dependencies, str):
            dependencies = [dependencies]
        if not isinstance(dependencies, list) or any(
            not isinstance(item, str) or item not in seen_ids for item in dependencies
        ):
            raise ValueError(f"segment {segment_id} dependencies must reference earlier segments")
        if len(set(dependencies)) != len(dependencies):
            raise ValueError(f"segment {segment_id} dependencies must be unique")
        seen_ids.add(segment_id)
        sanitized = dict(raw, segment_id=segment_id, depends_on=[])
        single = plan_apply_segments(
            [sanitized], current=current, model_override=model_override,
            effort_override=effort_override, report_model=report_model,
            report_effort=report_effort, evidence_path=evidence_path,
        )["segments"][0]
        single.pop("attempt_id", None)
        single["depends_on"] = list(dict.fromkeys(dependencies))
        work_estimate = raw.get("work_estimate", "normal")
        if work_estimate not in ("short", "normal", "long"):
            raise ValueError(f"segment {segment_id} has invalid work_estimate")
        access_mode = raw.get("access_mode", "read")
        if access_mode not in ("read", "write"):
            raise ValueError(f"segment {segment_id} has invalid access_mode")
        single["work_estimate"] = work_estimate
        single["access_mode"] = access_mode
        single["write_scopes"] = _normalized_scope_list(
            raw.get("write_scopes"), "write_scopes", segment_id, access_mode == "write"
        )
        single["conflict_keys"] = _normalized_scope_list(
            raw.get("conflict_keys"), "conflict_keys", segment_id
        )
        routed.append(single)
    segments = _merge_short_siblings(routed)
    if len(segments) > HARD_MAX_SEGMENTS:
        raise ValueError(
            f"Apply plan exceeds the hard limit of {HARD_MAX_SEGMENTS} routed segments after merging"
        )
    serialized_conflicts = _serialize_parallel_conflicts(segments)
    critical, priority_order, initial_frontier = _critical_path_priorities(segments)
    capacity_evaluation = _parallel_capacity_evaluation(segments, initial_frontier)
    if user_parallelism is not None:
        requested_parallelism = user_parallelism
    else:
        requested_parallelism = DEFAULT_AUTO_PARALLELISM
    model_segment_count = len(segments)
    useful_parallelism = capacity_evaluation["useful_parallelism"]
    if requested_parallelism > DEFAULT_AUTO_PARALLELISM:
        if capacity_source not in (
            "observed-total-slots", "legacy-observed-worker-capacity"
        ):
            raise ValueError(
                "max_parallelism above four requires observed free worker capacity"
            )
        if available_worker_slots < requested_parallelism:
            raise ValueError(
                "max_parallelism above four exceeds confirmed runtime capacity"
            )
        if useful_parallelism < requested_parallelism:
            raise ValueError(
                "max_parallelism above four exceeds independent ready-task capacity"
            )
    effective_parallelism = min(
        requested_parallelism, available_worker_slots, useful_parallelism
    )
    if user_parallelism is not None:
        parallelism_source = "user-override"
    elif effective_parallelism < DEFAULT_AUTO_PARALLELISM:
        parallelism_source = "smart-reduced"
    else:
        parallelism_source = "standard"
    reduction_reasons = []
    if available_worker_slots < requested_parallelism:
        reduction_reasons.append("runtime-capacity")
    if useful_parallelism < requested_parallelism:
        reduction_reasons.append("dependency-independent-width")
    for index, segment in enumerate(segments):
        segment["index"] = index + 1
        segment["critical_path_work"] = critical[segment["segment_id"]]
        segment["dispatch"] = "parallel-executor"
    segment_budget, switch_budget, budget_source = _resolve_plan_budget(
        segments, 0, max_segments, max_switches
    )
    evidence = load_benchmark_evidence(evidence_path)
    route_id = str(uuid.uuid4())
    original = {
        "model": current.get("model") if current.get("status") in ("verified", "synthetic") else None,
        "effort": current.get("effort") if current.get("status") in ("verified", "synthetic") else None,
    }
    parallel = {
        "scheduler": "critical-path-priority-wait-any",
        "parallelism_source": parallelism_source,
        "requested_max_parallelism": requested_parallelism,
        "runtime_total_slots": runtime_total_slots,
        "coordinator_reserved_slots": coordinator_slots,
        "runtime_running_workers": runtime_running_workers,
        "available_worker_slots": available_worker_slots,
        "capacity_source": capacity_source,
        "runtime_max_threads": runtime_max_threads,
        "runtime_max_threads_source": (
            "runtime-config" if runtime_max_threads is not None else None
        ),
        "effective_max_parallelism": effective_parallelism,
        "available_task_count": model_segment_count,
        "model_segment_count": model_segment_count,
        "capacity_evaluation": capacity_evaluation,
        "reduction_reasons": reduction_reasons,
        "priority_order": priority_order,
        "initial_frontier": initial_frontier,
        "aggregation_order": [item["segment_id"] for item in segments],
        "serialized_conflicts": serialized_conflicts,
        "failure_policy": "stop-dispatch-drain-running",
        "coordinator_owns_frontier": True,
        "workers_may_delegate": False,
        "timing_kind": "estimate-only",
        "context_policy": "bounded-worker-capsule",
    }
    result = {
        "route_id": route_id, "mode": "apply", "protocol": PARALLEL_PROTOCOL,
        "current": current, "original": original,
        "routing_evidence": evidence_audit(evidence), "segments": segments,
        "segment_count": len(segments), "switch_count": 0,
        "segment_budget": segment_budget, "switch_budget": switch_budget,
        "budget_source": budget_source, "max_segments": segment_budget,
        "max_switches": switch_budget, "hard_max_segments": HARD_MAX_SEGMENTS,
        "hard_max_switches": HARD_MAX_SWITCHES, "restore_required": False,
        "parallel": parallel,
        "explicit_override": bool(
            max_segments is not None or max_switches is not None or max_parallelism is not None
            or model_override or effort_override or any(
                (raw.get("model") or raw.get("effort"))
                and raw.get("route_source", "user-override") == "user-override"
                for raw in raw_segments
            )
        ),
    }
    result["plan_hash"] = plan_hash(
        segments, route_id, original, False, segment_budget, switch_budget,
        budget_source, result["routing_evidence"], PARALLEL_PROTOCOL, parallel,
    )
    for segment in segments:
        segment["attempt_id"] = hashlib.sha256(
            f"{route_id}:{result['plan_hash']}:{segment['segment_id']}".encode("utf-8")
        ).hexdigest()
    return result


def validate_parallel_envelope(
    plan, segment_id, completed_ids, running_ids, route_id, attempt_id,
    envelope_parallelism=None,
):
    if not isinstance(plan, dict) or plan.get("protocol") != PARALLEL_PROTOCOL:
        raise ValueError("invalid parallel plan protocol")
    if route_id != plan.get("route_id"):
        raise ValueError("envelope route_id mismatch")
    segments = plan.get("segments")
    if not isinstance(segments, list) or not segments:
        raise ValueError("parallel plan has no segments")
    by_id = {item.get("segment_id"): item for item in segments}
    if segment_id not in by_id:
        raise ValueError("parallel segment is missing")
    all_ids = set(by_id)
    if not isinstance(completed_ids, list) or not isinstance(running_ids, list):
        raise ValueError("parallel frontier state must be lists")
    if len(set(completed_ids + running_ids)) != len(completed_ids + running_ids):
        raise ValueError("parallel frontier contains duplicate segment IDs")
    if not set(completed_ids + running_ids).issubset(all_ids):
        raise ValueError("parallel frontier contains unknown segment IDs")
    # A claimed completed descendant must not unlock work before its own
    # prerequisites have completed.
    for completed_id in completed_ids:
        if any(
            dependency not in completed_ids
            for dependency in by_id[completed_id]["depends_on"]
        ):
            raise ValueError("parallel completed state has incomplete dependencies")
    segment = by_id[segment_id]
    if not all(dependency in completed_ids for dependency in segment["depends_on"]):
        raise ValueError("parallel segment dependencies are incomplete")
    if segment_id in completed_ids or segment_id in running_ids:
        raise ValueError("parallel segment was already dispatched")
    parallel = plan.get("parallel")
    if not isinstance(parallel, dict):
        raise ValueError("parallel plan metadata is missing")
    parallelism_source = parallel.get("parallelism_source")
    if parallelism_source is not None and parallelism_source not in (
        "standard", "smart-reduced", "adaptive-extended", "user-override"
    ):
        raise ValueError("invalid parallelism_source")
    requested_parallelism = parallel.get("requested_max_parallelism")
    effective_parallelism = parallel.get("effective_max_parallelism")
    if parallelism_source == "standard" and requested_parallelism != DEFAULT_AUTO_PARALLELISM:
        raise ValueError("standard parallelism must request four workers")
    if parallelism_source == "smart-reduced" and (
        requested_parallelism != DEFAULT_AUTO_PARALLELISM
        or not isinstance(effective_parallelism, int)
        or not 1 <= effective_parallelism < DEFAULT_AUTO_PARALLELISM
    ):
        raise ValueError("smart-reduced parallelism must reduce the default four")
    if parallelism_source == "adaptive-extended" and (
        requested_parallelism != EXTENDED_AUTO_PARALLELISM
        or parallel.get("adaptive_evaluation", {}).get("eligible") is not True
    ):
        raise ValueError("adaptive parallelism lacks deterministic benefit evidence")
    if parallelism_source == "user-override":
        _bounded_integer(requested_parallelism, "requested_max_parallelism", HARD_MAX_PARALLELISM)
        capacity = parallel.get("capacity_evaluation")
        if requested_parallelism > DEFAULT_AUTO_PARALLELISM and capacity is not None:
            if parallel.get("capacity_source") not in (
                "observed-total-slots", "legacy-observed-worker-capacity"
            ) and parallel.get("runtime_max_threads_source") != "runtime-config":
                raise ValueError("parallel override above four lacks observed runtime capacity")
            available_slots = parallel.get(
                "available_worker_slots", parallel.get("runtime_max_threads", 0)
            )
            if available_slots < requested_parallelism:
                raise ValueError("parallel override above four exceeds runtime capacity")
            if capacity.get("useful_parallelism", 0) < requested_parallelism:
                raise ValueError("parallel override above four exceeds useful task capacity")
    if envelope_parallelism is not None:
        expected_envelope = {
            "parallelism_source": parallelism_source,
            "requested_max_parallelism": requested_parallelism,
            "effective_max_parallelism": effective_parallelism,
        }
        if envelope_parallelism != expected_envelope:
            raise ValueError("parallel envelope concurrency metadata mismatch")
    priority = parallel.get("priority_order", [])
    ready = [
        identifier for identifier in priority
        if identifier not in completed_ids and identifier not in running_ids
        and all(dependency in completed_ids for dependency in by_id[identifier]["depends_on"])
    ]
    if len(running_ids) >= parallel.get("effective_max_parallelism", 0):
        raise ValueError("parallel plan has no available worker slot")
    expected = ready[0] if ready else None
    if expected is None or segment_id != expected:
        raise ValueError("parallel segment is not the deterministic frontier priority")
    expected_hash = plan_hash(
        segments, route_id, plan.get("original"), False,
        plan.get("segment_budget"), plan.get("switch_budget"), plan.get("budget_source"),
        plan.get("routing_evidence"), PARALLEL_PROTOCOL, parallel,
    )
    if plan.get("plan_hash") != expected_hash:
        raise ValueError("parallel plan hash mismatch")
    expected_attempt = hashlib.sha256(
        f"{route_id}:{expected_hash}:{segment_id}".encode("utf-8")
    ).hexdigest()
    if segment.get("attempt_id") != expected_attempt or attempt_id != expected_attempt:
        raise ValueError("parallel attempt_id mismatch")
    return segment


def validate_segment_cursor(
    plan, cursor, segment_id, completed_ids,
    route_id, attempt_id, original_model, original_effort,
    protocol, restore_required, segment_budget, switch_budget, budget_source,
):
    if not isinstance(plan, dict) or plan.get("protocol") != SEGMENTED_PROTOCOL:
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
    if plan.get("restore_required") and not is_gpt56_model(original.get("model")):
        raise ValueError("Restore to a non-GPT-5.6 original is forbidden")
    if plan.get("plan_hash") != plan_hash(
        segments, plan.get("route_id"), original, plan.get("restore_required"),
        segment_budget, switch_budget, budget_source, plan.get("routing_evidence"),
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


def validate_fast_envelope(plan, route_id, segment_id, attempt_id):
    """Validate the compact continuation used by a one-Segment Apply."""
    if not isinstance(plan, dict) or plan.get("protocol") != FAST_PROTOCOL:
        raise ValueError("invalid fast plan protocol")
    segments = plan.get("segments")
    if not isinstance(segments, list) or len(segments) != 1:
        raise ValueError("fast plan requires exactly one segment")
    if route_id != plan.get("route_id"):
        raise ValueError("fast envelope route_id mismatch")
    if plan.get("restore_required") and not is_gpt56_model(
        plan.get("original", {}).get("model")
    ):
        raise ValueError("Restore to a non-GPT-5.6 original is forbidden")
    segment = segments[0]
    if segment_id != segment.get("segment_id"):
        raise ValueError("fast envelope segment_id mismatch")
    expected_hash = plan_hash(
        segments, route_id, plan.get("original"), plan.get("restore_required"),
        plan.get("segment_budget"), plan.get("switch_budget"),
        plan.get("budget_source"), plan.get("routing_evidence"), FAST_PROTOCOL,
    )
    if plan.get("plan_hash") != expected_hash:
        raise ValueError("fast plan hash mismatch")
    actual_switches = int(segment.get("dispatch") == "same-task-switch") + int(
        plan.get("restore_required") is True
    )
    if plan.get("switch_count") != actual_switches:
        raise ValueError("fast plan switch count mismatch")
    expected_attempt = hashlib.sha256(
        f"{route_id}:{expected_hash}:{segment_id}".encode("utf-8")
    ).hexdigest()
    if attempt_id != expected_attempt or segment.get("attempt_id") != expected_attempt:
        raise ValueError("fast attempt_id mismatch")
    return segment


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
    evidence_path=None,
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
    evidence = load_benchmark_evidence(evidence_path)
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
        ambiguity = raw.get("ambiguity")
        coupling = raw.get("coupling")
        verification = raw.get("verification")
        consequence = raw.get("consequence")
        prior_failure = raw.get("prior_failure", False)
        if task_kind not in ("mechanical", "ordinary", "complex"):
            raise ValueError(f"invalid task_kind for segment {segment_id}")
        if risk not in ("low", "normal", "high"):
            raise ValueError(f"invalid risk for segment {segment_id}")
        if size not in ("tiny", "normal", "large"):
            raise ValueError(f"invalid size for segment {segment_id}")

        signals = _task_signals(
            task_kind, risk, size, ambiguity, coupling, verification,
            consequence, prior_failure,
        )
        target_model, target_effort, source = recommended_route(
            "apply", task_kind, risk, size,
            ambiguity=signals["ambiguity"], coupling=signals["coupling"],
            verification=signals["verification"], consequence=signals["consequence"],
            prior_failure=signals["prior_failure"], evidence=evidence,
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

        routed.append({
            "segment_id": segment_id,
            "source_ids": [segment_id],
            "index": index + 1,
            "goal": _segment_text(raw.get("goal"), "goal", segment_id),
            "depends_on": dependencies,
            "task_kind": task_kind,
            "risk": risk,
            "size": size,
            **signals,
            "acceptance": _segment_list(raw.get("acceptance"), "acceptance", segment_id),
            "validation_budget": _segment_text(
                raw.get("validation_budget"), "validation_budget", segment_id
            ),
            "decisions": _optional_segment_list(
                raw.get("decisions"), "decisions", segment_id
            ),
            "prohibited_actions": _optional_segment_list(
                raw.get("prohibited_actions"), "prohibited_actions", segment_id
            ) or ["do-not-replan", "do-not-delegate", "do-not-touch-out-of-scope-files"],
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
        and is_gpt56_model(current_route[0])
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
    protocol = FAST_PROTOCOL if len(segments) == 1 else SEGMENTED_PROTOCOL
    result = {
        "route_id": route_id,
        "mode": "apply",
        "protocol": protocol,
        "current": current,
        "original": original,
        "routing_evidence": evidence_audit(evidence),
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
    if protocol == FAST_PROTOCOL:
        dispatch = segments[0]["dispatch"]
        result["fast_path"] = {
            "full_plan_continuation_required": False,
            "cursor_required": False,
            "claim_required": dispatch != "local",
            "continuation_required": dispatch != "local",
            "restore_required": restore_required,
        }
    result["plan_hash"] = plan_hash(
        segments, route_id, original, restore_required,
        segment_budget, switch_budget, budget_source, result["routing_evidence"], protocol,
    )
    for segment in segments:
        segment["attempt_id"] = hashlib.sha256(
            f"{route_id}:{result['plan_hash']}:{segment['segment_id']}".encode("utf-8")
        ).hexdigest()
    return result


def parser():
    root = argparse.ArgumentParser()
    root.add_argument("--inspect-current", action="store_true")
    root.add_argument("--resolve-fallback", action="store_true")
    root.add_argument("--target-model")
    root.add_argument("--target-effort")
    root.add_argument("--available-model", action="append")
    root.add_argument("--sessions-root", type=Path)
    root.add_argument("--no-runtime-detection", action="store_true")
    root.add_argument("--current-model")
    root.add_argument("--current-effort", choices=RUNTIME_EFFORTS)
    root.add_argument("--mode", choices=("apply", "assess", "retune"))
    root.add_argument("--task-kind", choices=("mechanical", "ordinary", "complex"), default="ordinary")
    root.add_argument("--risk", choices=("low", "normal", "high"), default="normal")
    root.add_argument("--size", choices=("tiny", "normal", "large"), default="normal")
    root.add_argument("--ambiguity", choices=("low", "medium", "high"))
    root.add_argument("--coupling", choices=("low", "medium", "high"))
    root.add_argument("--verification", choices=("deterministic", "mixed", "judgment"))
    root.add_argument("--consequence", choices=("low", "normal", "high"))
    root.add_argument("--prior-failure", action="store_true")
    root.add_argument("--evidence-path", type=Path, help="Offline benchmark evidence snapshot")
    root.add_argument("--model")
    root.add_argument("--effort")
    root.add_argument("--report-model")
    root.add_argument("--report-effort")
    root.add_argument("--segments-json", help="JSON array for a bounded multi-segment Apply plan")
    root.add_argument("--max-segments", type=int, help="User Segment budget override (1-8)")
    root.add_argument("--max-switches", type=int, help="User switch budget override including Restore (1-8)")
    root.add_argument("--parallel", action="store_true", help="Enable dependency-aware parallel planning")
    root.add_argument(
        "--max-parallelism", type=int,
        help="User concurrency cap (1-16); values above 4 require observed matching runtime capacity",
    )
    root.add_argument("--runtime-max-threads", type=int, help="Observed Codex agents.max_threads constraint")
    root.add_argument("--runtime-total-slots", type=int, help="Observed total slots including this coordinator")
    root.add_argument("--runtime-running-workers", type=int, default=0, help="Workers already occupying observed slots")
    root.add_argument("--coordinator-slots", type=int, default=DEFAULT_COORDINATOR_SLOTS)
    root.add_argument("--context-capsule-segment", help="Emit bounded worker context for this segment")
    root.add_argument("--validate-envelope-json", help="JSON object containing plan, cursor, segment_id, and completed_ids")
    root.add_argument("--validate-fast-envelope-json", help="Compact one-Segment continuation envelope")
    root.add_argument("--validate-parallel-envelope-json", help="JSON object containing plan and frontier state")
    root.add_argument("--synthetic-current-for-test", action="store_true", help=argparse.SUPPRESS)
    return root


def main():
    args = parser().parse_args()
    if args.resolve_fallback:
        if args.target_model is None or args.target_effort is None:
            raise SystemExit("--resolve-fallback requires --target-model and --target-effort")
        try:
            result = resolve_family_fallback(
                args.target_model, args.target_effort, args.available_model
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return
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
    if args.validate_fast_envelope_json is not None:
        try:
            envelope = json.loads(args.validate_fast_envelope_json)
            segment = validate_fast_envelope(
                envelope.get("plan"), envelope.get("route_id"),
                envelope.get("segment_id"), envelope.get("attempt_id"),
            )
        except (json.JSONDecodeError, AttributeError, ValueError) as exc:
            raise SystemExit(f"invalid fast envelope: {exc}") from exc
        print(json.dumps({"valid": True, "segment": segment}, ensure_ascii=False, sort_keys=True))
        return
    if args.validate_parallel_envelope_json is not None:
        try:
            envelope = json.loads(args.validate_parallel_envelope_json)
            segment = validate_parallel_envelope(
                envelope.get("plan"), envelope.get("segment_id"),
                envelope.get("completed_ids"), envelope.get("running_ids"),
                envelope.get("route_id"), envelope.get("attempt_id"),
                {
                    "parallelism_source": envelope.get("parallelism_source"),
                    "requested_max_parallelism": envelope.get("requested_max_parallelism"),
                    "effective_max_parallelism": envelope.get("effective_max_parallelism"),
                } if envelope.get("plan", {}).get("parallel", {}).get("parallelism_source") is not None else None,
            )
        except (json.JSONDecodeError, AttributeError, ValueError) as exc:
            raise SystemExit(f"invalid parallel envelope: {exc}") from exc
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
        or args.parallel or args.max_parallelism is not None or args.runtime_max_threads is not None
        or args.runtime_total_slots is not None or args.runtime_running_workers != 0
    ):
        raise SystemExit("segment budget and parallel options require --segments-json")
    try:
        if args.segments_json is not None:
            if args.mode != "apply":
                raise ValueError("--segments-json is valid only for Apply")
            try:
                raw_segments = json.loads(args.segments_json)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid --segments-json: {exc}") from exc
            nonlinear = False
            if isinstance(raw_segments, list):
                for index, item in enumerate(raw_segments):
                    if not isinstance(item, dict):
                        continue
                    previous = None if index == 0 else raw_segments[index - 1]
                    previous_id = None if index == 0 else (
                        previous.get("segment_id", f"segment-{index}")
                        if isinstance(previous, dict) else f"segment-{index}"
                    )
                    expected = [] if index == 0 else [previous_id]
                    dependencies = item.get("depends_on", expected)
                    if isinstance(dependencies, str):
                        dependencies = [dependencies]
                    if dependencies != expected:
                        nonlinear = True
                        break
            planner = plan_parallel_segments if args.parallel or nonlinear else plan_apply_segments
            planner_options = dict(
                current=current,
                model_override=args.model,
                effort_override=args.effort,
                report_model=args.report_model,
                report_effort=args.report_effort,
                max_segments=args.max_segments,
                max_switches=args.max_switches,
                evidence_path=args.evidence_path,
            )
            if planner is plan_parallel_segments:
                planner_options["max_parallelism"] = args.max_parallelism
                planner_options["runtime_max_threads"] = args.runtime_max_threads
                planner_options["runtime_total_slots"] = args.runtime_total_slots
                planner_options["runtime_running_workers"] = args.runtime_running_workers
                planner_options["coordinator_slots"] = args.coordinator_slots
            route = planner(raw_segments, **planner_options)
            if args.context_capsule_segment:
                print(json.dumps(
                    context_capsule(route, args.context_capsule_segment),
                    ensure_ascii=False, sort_keys=True,
                ))
                return
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
            args.ambiguity,
            args.coupling,
            args.verification,
            args.consequence,
            args.prior_failure,
            args.evidence_path,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(route, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
