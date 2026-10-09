"""Reviewed routing data and read-only model-surface change detection."""
import argparse
import json
import re
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "references/model-catalog.json"


def load(path=PATH):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("unsupported model catalog schema")
    if set(data["roles"]) != {"frontier", "strong", "efficient"}:
        raise ValueError("catalog requires three capability roles")
    for model, entry in data["models"].items():
        if not model.startswith("gpt-") or not entry["efforts"]:
            raise ValueError("invalid catalog model")
        if any(e not in ("low", "medium", "high", "xhigh", "max") for e in entry["efforts"]):
            raise ValueError("invalid catalog effort")
        if not re.fullmatch(r"codex_auto_model_executor_[a-z0-9_]+", entry["preset_stem"]):
            raise ValueError("invalid preset stem")
        known = set(data["models"]) | {"gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"}
        if not isinstance(entry["fallbacks"], list) or any(m not in known for m in entry["fallbacks"]):
            raise ValueError("unknown fallback model")
    if any(m not in data["models"] for m in data["roles"].values()):
        raise ValueError("unknown role model")
    return data


try:
    CATALOG = load()
    LOAD_ERROR = None
except (OSError, ValueError, KeyError, TypeError) as exc:
    CATALOG = {"models": {}, "roles": {}}
    LOAD_ERROR = f"invalid-model-catalog:{type(exc).__name__}"
MODELS = CATALOG["models"]


def normalize(value):
    if value is not None and not isinstance(value, str):
        raise ValueError("model ID must be a string")
    value = value.strip().lower() if value else value
    aliases = {"astra": CATALOG["roles"].get("frontier")}
    key = aliases.get(value, value)
    return key if key in MODELS else None


def automatic_effort(model, effort, explicit_effort=False, failed_reasoning=False):
    if model == "gpt-6-astra" and not explicit_effort:
        return "medium" if failed_reasoning else "low"
    return effort


def resolve(model, effort, available=None, explicit=False, explicit_effort=False, failed_reasoning=False,
            excluded_models=()):
    if available is not None and (not isinstance(available, list) or any(not isinstance(m, str) for m in available)):
        raise ValueError("available models must be a complete list of model IDs")
    chain = [model] if explicit else [model, *MODELS.get(model, {}).get("fallbacks", [])]
    chain = [candidate for candidate in chain if candidate not in excluded_models]
    chosen = model if available is None else next((m for m in chain if m in available
        and effort in MODELS.get(m, {"efforts": ["low", "medium", "high", "xhigh", "max", "ultra"]})["efforts"]), None)
    execution_effort = automatic_effort(chosen, effort, explicit_effort, failed_reasoning) if chosen else None
    return {"preferred": {"model": model, "effort": effort},
            "execution": {"model": chosen, "effort": execution_effort},
            "availability_complete": available is not None,
            "fallback": chosen is not None and chosen != model,
            "quality_degraded": chosen is not None and chosen != model and MODELS.get(model, {}).get("role") == "frontier",
            "reason": "explicit-model-unavailable" if chosen is None and explicit else
                      "no-supported-model-available" if chosen is None else
                      "availability-unknown" if available is None else "resolved"}


def check_surface(observed, previous=None):
    if LOAD_ERROR:
        raise ValueError(LOAD_ERROR)
    if previous is not None and (not isinstance(previous, list) or any(not isinstance(m, str) for m in previous)):
        raise ValueError("previous surface must be a JSON array of model IDs")
    if not isinstance(observed, list) or any(not isinstance(m, str) for m in observed):
        raise ValueError("model surface must be a JSON array of model IDs")
    known = set(MODELS) | {"gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"}
    current = set(observed)
    baseline = set(previous) if previous is not None else known
    return {"action": "review-model-catalog", "unknown_models": sorted(current - known),
            "added": sorted(current - baseline), "removed": sorted(baseline - current),
            "update_suggested": bool(current - known or (previous is not None and current != baseline)),
            "routing_changed": False, "observed_models": sorted(current)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--available-models-json", required=True)
    parser.add_argument("--previous-models-json")
    args = parser.parse_args()
    try:
        result = check_surface(json.loads(args.available_models_json),
                               json.loads(args.previous_models_json) if args.previous_models_json else None)
    except (ValueError, TypeError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
