"""Routing profiles adapted from David Soff's PR #6; current catalog remains authoritative."""
import json
import os
import re
import tomllib
import uuid
from pathlib import Path
import model_catalog as catalog

ROUTING_CONFIG_SCHEMA_VERSION = 1
DEFAULT_ROUTING_PROFILE = "balanced"
TASK_LANES = {lane: {} for lane in (
    "mechanical_default", "ordinary_default", "bounded_scan",
    "bounded_deep_deterministic", "latency_priority", "complex_bounded",
    "complex_uncertain", "high_consequence", "complex_failed_escalation")}
ROUTED_EFFORTS = ("low", "medium", "high", "xhigh", "max")
ROUTING_PROFILES = {
    "balanced": {
        "mechanical_default": {"model": "gpt-6-luna", "effort": "medium"},
        "ordinary_default": {"model": "gpt-6-luna", "effort": "high"},
        "bounded_scan": {"model": "gpt-6-luna", "effort": "xhigh"},
        "bounded_deep_deterministic": {"model": "gpt-6-luna", "effort": "max"},
        "latency_priority": {"model": "gpt-5.6-terra", "effort": "high"},
        "complex_bounded": {"model": "gpt-6.1-sol", "effort": "medium"},
        "complex_uncertain": {"model": "gpt-6-astra", "effort": "low"},
        "high_consequence": {"model": "gpt-6-astra", "effort": "low"},
        "complex_failed_escalation": {"model": "gpt-6-astra", "effort": "medium"},
    }
}
ROUTING_PROFILES["economy"] = {
    lane: dict(route) for lane, route in ROUTING_PROFILES["balanced"].items()}
for lane in ("complex_bounded", "complex_uncertain"):
    ROUTING_PROFILES["economy"][lane] = {"model": "gpt-6-luna", "effort": "high"}
ROUTING_PROFILES["quality"] = {
    lane: dict(route) for lane, route in ROUTING_PROFILES["balanced"].items()}
for lane in ("ordinary_default", "bounded_scan", "bounded_deep_deterministic"):
    ROUTING_PROFILES["quality"][lane]["model"] = "gpt-6.1-sol"

# These are explicit policy choices, never inferred account entitlements. Keep
# the existing three profiles and the default selection exactly as they were.
PLAN_PROFILES = ("plus", "pro")
SCOPED_TASK_SUBTYPES = ("scoped_implementation", "existing_iteration", "ui", "careful_maintenance")
DEEP_TASK_SUBTYPES = ("large_repo", "autonomous_investigation", "complex_planning", "deep_multi_module")
TASK_SUBTYPES = ("general", *SCOPED_TASK_SUBTYPES, *DEEP_TASK_SUBTYPES, "extreme")
PRO_BUDGET_WARNING = (
    "Pro opts into GPT-6 Astra/xhigh for extreme/high-consequence tasks or a "
    "substantive failure of the corresponding Sol/xhigh branch; this can use substantially more budget."
)
ROUTING_PROFILES["plus"] = {
    lane: {"model": "gpt-6-luna", "effort": "xhigh"} for lane in TASK_LANES}
ROUTING_PROFILES["plus"]["mechanical_default"]["effort"] = "high"
for lane in ("complex_bounded", "complex_uncertain", "high_consequence", "complex_failed_escalation"):
    ROUTING_PROFILES["plus"][lane] = {
        "model": "gpt-6.1-sol", "effort": "high" if lane == "complex_bounded" else "xhigh"}
ROUTING_PROFILES["pro"] = {
    lane: dict(route) for lane, route in ROUTING_PROFILES["plus"].items()}
ROUTING_PROFILES["pro"]["complex_bounded"] = {"model": "gpt-5.6-sol", "effort": "xhigh"}
for lane in ("high_consequence", "complex_failed_escalation"):
    ROUTING_PROFILES["pro"][lane] = {"model": "gpt-6-astra", "effort": "xhigh"}

# Role changes in the reviewed catalog propagate without renaming lanes.
for table in ROUTING_PROFILES.values():
    for route in table.values():
        role = {"gpt-6-luna": "efficient", "gpt-6.1-sol": "strong", "gpt-6-astra": "frontier"}.get(route["model"])
        if role:
            route["model"] = catalog.CATALOG["roles"].get(role, route["model"])

def normalize_model(value):
    if not isinstance(value, str):
        raise ValueError("model must be a string")
    import route_policy as policy
    return catalog.normalize(value) or policy.normalize_model(value)

def normalize_effort(value):
    if not isinstance(value, str) or value not in ROUTED_EFFORTS:
        raise ValueError("unsupported reasoning effort")
    return value

def require_routable_model(value):
    import route_policy as policy
    if value not in (*catalog.MODELS, *policy.MODELS):
        raise ValueError("model is not in the reviewed catalog")
    return value

def lane_for(source, risk=None, consequence=None):
    lane = source.rsplit(":", 1)[-1]
    if lane == "complex_uncertain_or_high_consequence":
        return "high_consequence" if risk == "high" or consequence == "high" else "complex_uncertain"
    return lane


def task_evidence(task_subtype=None, prior_failure=False, prior_failure_model=None, prior_failure_effort=None):
    subtype = task_subtype or "general"
    if subtype not in TASK_SUBTYPES:
        raise ValueError("unsupported task_subtype")
    if prior_failure_model is not None:
        if not prior_failure:
            raise ValueError("prior_failure_model requires prior_failure=true")
        prior_failure_model = require_routable_model(normalize_model(prior_failure_model))
    if prior_failure_effort is not None:
        if not prior_failure:
            raise ValueError("prior_failure_effort requires prior_failure=true")
        prior_failure_effort = normalize_effort(prior_failure_effort)
    return subtype, prior_failure_model, prior_failure_effort


def profile_lane(config, lane, task_kind, size, signals, failure_kind,
                 task_subtype=None, prior_failure_model=None, prior_failure_effort=None):
    """Refine only the opt-in profiles using actual task and failure evidence."""
    subtype, failed_model, failed_effort = task_evidence(
        task_subtype, signals["prior_failure"], prior_failure_model, prior_failure_effort)
    if config["profile"] not in PLAN_PROFILES:
        return lane
    substantive_failure = signals["prior_failure"] and failure_kind in ("reasoning", "verification")
    if config["profile"] == "plus":
        if subtype == "extreme" or signals["consequence"] == "high":
            return "high_consequence"
        if subtype in DEEP_TASK_SUBTYPES:
            return "complex_uncertain"
        if substantive_failure:
            return "complex_failed_escalation" if failed_model in ("gpt-5.6-sol", "gpt-6.1-sol", "gpt-6-sol") else "complex_bounded"
        return lane
    if subtype == "extreme" or signals["consequence"] == "high":
        return "high_consequence"
    deep = subtype in DEEP_TASK_SUBTYPES or (
        subtype not in SCOPED_TASK_SUBTYPES and (
            signals["ambiguity"] == "high" or signals["coupling"] == "high"
            or (task_kind == "complex" and size == "large")))
    sol_lane = "complex_uncertain" if deep else "complex_bounded"
    corresponding_sol = "gpt-6.1-sol" if deep else "gpt-5.6-sol"
    if substantive_failure and failed_model == corresponding_sol and failed_effort == "xhigh":
        return "complex_failed_escalation"
    if substantive_failure or task_kind == "complex" or deep or lane.startswith("complex_"):
        return sol_lane
    return lane


def configured_effort(config, lane):
    """Explicit lane edits and the narrowly opted-in Pro top tier authorize effort."""
    route = config["routes"][lane]
    return config["route_sources"][lane] in ("global", "project") or (
        config["profile"] == "pro"
        and lane in ("high_consequence", "complex_failed_escalation")
        and route == {"model": "gpt-6-astra", "effort": "xhigh"})


def fallback_exclusions(profile, model):
    # Availability is not task evidence and must never promote a Sol/Luna
    # recommendation into Astra. Explicitly selected Astra remains possible.
    return ("gpt-6-astra",) if profile in PLAN_PROFILES and model != "gpt-6-astra" else ()


def routing_config_paths(repository=None, environ=None):
    environ = os.environ if environ is None else environ
    codex_home = Path(environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()
    root = Path(repository or Path.cwd()).expanduser().resolve()
    return {
        "global": codex_home / "router.toml",
        "project": root / ".codex" / "router.toml",
    }


def _read_routing_config(path, scope):
    if not path.is_file():
        return {"profile": None, "overrides": {}}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"invalid {scope} router config {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"invalid {scope} router config {path}: expected a TOML table")
    if set(data) - {"schema_version", "profile", "profiles"}:
        extra = sorted(set(data) - {"schema_version", "profile", "profiles"})
        raise ValueError(f"invalid {scope} router config {path}: unknown top-level keys {extra}")
    version = data.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int) or version != ROUTING_CONFIG_SCHEMA_VERSION:
        raise ValueError(
            f"invalid {scope} router config {path}: schema_version must be {ROUTING_CONFIG_SCHEMA_VERSION}"
        )
    profile = data.get("profile")
    if profile is not None and (
        not isinstance(profile, str) or profile not in ROUTING_PROFILES
    ):
        raise ValueError(f"invalid {scope} router config {path}: unsupported profile {profile!r}")
    profiles = data.get("profiles", {})
    if not isinstance(profiles, dict):
        raise ValueError(f"invalid {scope} router config {path}: profiles must be a table")
    overrides = {}
    for profile_name, profile_config in profiles.items():
        if profile_name not in ROUTING_PROFILES or not isinstance(profile_config, dict):
            raise ValueError(
                f"invalid {scope} router config {path}: unsupported profile {profile_name!r}"
            )
        if set(profile_config) - {"routes"}:
            raise ValueError(
                f"invalid {scope} router config {path}: profile {profile_name!r} only supports routes"
            )
        routes = profile_config.get("routes", {})
        if not isinstance(routes, dict):
            raise ValueError(
                f"invalid {scope} router config {path}: profile {profile_name!r} routes must be a table"
            )
        for lane, route in routes.items():
            if lane not in TASK_LANES:
                raise ValueError(f"invalid {scope} router config {path}: unknown lane {lane!r}")
            if not isinstance(route, dict) or set(route) != {"model", "effort"}:
                raise ValueError(
                    f"invalid {scope} router config {path}: {profile_name}.{lane} requires model and effort"
                )
            try:
                model = require_routable_model(normalize_model(route["model"]))
                effort = normalize_effort(route["effort"])
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"invalid {scope} router config {path}: {profile_name}.{lane}: {exc}"
                ) from exc
            if effort not in ROUTED_EFFORTS:
                raise ValueError(
                    f"invalid {scope} router config {path}: {profile_name}.{lane} effort must be one of {', '.join(ROUTED_EFFORTS)}"
                )
            overrides.setdefault(profile_name, {})[lane] = {
                "model": model, "effort": effort,
            }
    return {"profile": profile, "overrides": overrides}


def resolve_routing_config(repository=None, profile_override=None, environ=None):
    """Resolve built-in routes plus global and repository-local TOML overrides."""
    paths = routing_config_paths(repository, environ)
    loaded = {
        scope: _read_routing_config(path, scope)
        for scope, path in paths.items()
    }
    profile = profile_override or loaded["project"]["profile"] or loaded["global"]["profile"] or DEFAULT_ROUTING_PROFILE
    if profile not in ROUTING_PROFILES:
        raise ValueError(f"unsupported routing profile: {profile!r}")
    routes = {lane: dict(route) for lane, route in ROUTING_PROFILES[profile].items()}
    sources = {lane: "built-in" for lane in routes}
    for scope in ("global", "project"):
        for lane, route in loaded[scope]["overrides"].get(profile, {}).items():
            routes[lane] = dict(route)
            sources[lane] = scope
    return {
        "profile": profile,
        **({"budget_warning": PRO_BUDGET_WARNING} if profile == "pro" else {}),
        "routes": routes,
        "route_sources": sources,
        "config_paths": {scope: str(path) for scope, path in paths.items()},
        "selected_from": (
            "command-line" if profile_override else
            "project" if loaded["project"]["profile"] else
            "global" if loaded["global"]["profile"] else "default"
        ),
    }


def _upsert_toml_root_value(text, key, value_source):
    """Replace one validated root TOML assignment while retaining comments."""
    lines = text.splitlines(keepends=True)
    assignment = re.compile(rf"^\s*{re.escape(key)}\s*=")
    for start, line in enumerate(lines):
        if not assignment.match(line):
            continue
        for end in range(start + 1, len(lines) + 1):
            statement = "".join(lines[start:end])
            try:
                parsed = tomllib.loads(statement)
            except tomllib.TOMLDecodeError:
                continue
            if key not in parsed:
                continue
            last_line = lines[end - 1]
            line_ending = "\r\n" if last_line.endswith("\r\n") else "\n"
            comment = re.search(r"[ \t]+#.*$", last_line.rstrip("\r\n"))
            suffix = f" {comment.group(0).lstrip()}" if comment else ""
            lines[start:end] = [f"{key} = {value_source}{suffix}{line_ending}"]
            return "".join(lines)
        raise ValueError(f"could not locate the end of the {key} assignment")
    return f"{key} = {value_source}\n" + text


def set_routing_profile(profile, scope="project", repository=None, environ=None):
    if profile not in ROUTING_PROFILES:
        raise ValueError(f"unsupported routing profile: {profile!r}")
    if scope not in ("global", "project"):
        raise ValueError("profile scope must be global or project")
    paths = routing_config_paths(repository, environ)
    path = paths[scope]
    if scope == "global":
        other_path = paths["project"]
    else:
        other_path = paths["global"]
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    _read_routing_config(path, scope)
    # Parse the other layer too; profile selection must not conceal invalid policy.
    _read_routing_config(other_path, "project" if scope == "global" else "global")
    first_table = re.search(r"(?m)^\s*\[", existing)
    split = first_table.start() if first_table else len(existing)
    preamble, rest = existing[:split], existing[split:]
    preamble = _upsert_toml_root_value(preamble, "profile", json.dumps(profile))
    preamble = _upsert_toml_root_value(
        preamble, "schema_version", str(ROUTING_CONFIG_SCHEMA_VERSION)
    )
    updated = preamble + rest
    if not updated.endswith("\n"):
        updated += "\n"
    try:
        parsed = tomllib.loads(updated)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"refusing to write invalid router config {path}: {exc}") from exc
    if parsed.get("profile") != profile or parsed.get("schema_version") != ROUTING_CONFIG_SCHEMA_VERSION:
        raise ValueError(f"refusing to write invalid router config {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}")
    try:
        temporary.write_text(updated, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {"scope": scope, "profile": profile, "config_path": str(path), "changed": updated != existing,
            **({"budget_warning": PRO_BUDGET_WARNING} if profile == "pro" else {})}
