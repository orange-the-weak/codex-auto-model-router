"""Current route tables and configuration; legacy task classification is shared.

Profiles were adapted from David Soff's PR #6. The reviewed catalog owns model
roles/availability; this module alone owns current default model/effort choices.
"""
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
    "complex_uncertain", "high_consequence", "complex_failed_escalation",
    "specialist_default")}
ROUTED_EFFORTS = ("low", "medium", "high", "xhigh", "max")
TASK_FOCUSES = ("general", "visual", "computer_use", "writing", "scoped_fix")


def normalize_task_focus(value):
    value = "general" if value is None else value
    if value not in TASK_FOCUSES:
        raise ValueError("unsupported task_focus")
    return value


def specialist_eligible(focus, task_kind, signals):
    """A concrete bounded focus, not generic difficulty or UI vocabulary."""
    return (normalize_task_focus(focus) != "general" and task_kind != "complex"
            and signals["ambiguity"] != "high" and signals["coupling"] != "high"
            and signals["consequence"] != "high" and not signals["prior_failure"])

ROUTING_PROFILES = {
    "balanced": {
        "mechanical_default": {"model": "gpt-6-luna", "effort": "medium"},
        "ordinary_default": {"model": "gpt-6.1-sol", "effort": "medium"},
        "bounded_scan": {"model": "gpt-6.1-sol", "effort": "high"},
        "bounded_deep_deterministic": {"model": "gpt-6.1-sol", "effort": "high"},
        "latency_priority": {"model": "gpt-6.1-sol", "effort": "low"},
        "complex_bounded": {"model": "gpt-6.1-sol", "effort": "medium"},
        "complex_uncertain": {"model": "gpt-6.1-sol", "effort": "high"},
        "high_consequence": {"model": "gpt-6.1-sol", "effort": "high"},
        "complex_failed_escalation": {"model": "gpt-6-astra", "effort": "medium"},
        "specialist_default": {"model": "gpt-6.1-terra", "effort": "medium"},
    }
}
ROUTING_PROFILES["economy"] = {
    lane: dict(route) for lane, route in ROUTING_PROFILES["balanced"].items()}
for lane in ("ordinary_default", "latency_priority"):
    ROUTING_PROFILES["economy"][lane] = {"model": "gpt-6-luna", "effort": "high"}
ROUTING_PROFILES["economy"]["bounded_scan"] = {"model": "gpt-6-luna", "effort": "xhigh"}
ROUTING_PROFILES["economy"]["bounded_deep_deterministic"] = {"model": "gpt-6-luna", "effort": "max"}
ROUTING_PROFILES["quality"] = {
    lane: dict(route) for lane, route in ROUTING_PROFILES["balanced"].items()}
ROUTING_PROFILES["quality"]["specialist_default"]["effort"] = "high"
for lane in ("ordinary_default", "complex_bounded"):
    ROUTING_PROFILES["quality"][lane]["effort"] = "high"
for lane in ("complex_uncertain", "high_consequence", "bounded_deep_deterministic"):
    ROUTING_PROFILES["quality"][lane]["effort"] = "xhigh"

# Role changes in the reviewed catalog propagate without renaming lanes.
for table in ROUTING_PROFILES.values():
    for route in table.values():
        role = {"gpt-6-luna": "efficient", "gpt-6.1-sol": "strong", "gpt-6-astra": "frontier", "gpt-6.1-terra": "specialist"}.get(route["model"])
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
    return {"scope": scope, "profile": profile, "config_path": str(path), "changed": updated != existing}
