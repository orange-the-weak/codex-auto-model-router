#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
CODEX_HOME=${CODEX_HOME:-"$HOME/.codex"}
SKILL_TARGET="$CODEX_HOME/skills/codex-model-router"
AGENT_TARGET="$CODEX_HOME/agents"

mkdir -p "$SKILL_TARGET/agents" "$SKILL_TARGET/references" "$SKILL_TARGET/scripts" "$AGENT_TARGET"

cp "$ROOT/SKILL.md" "$SKILL_TARGET/SKILL.md"
cp "$ROOT/agents/openai.yaml" "$SKILL_TARGET/agents/openai.yaml"
cp "$ROOT/references/"*.md "$SKILL_TARGET/references/"
cp "$ROOT/scripts/model_usage_ledger.py" "$SKILL_TARGET/scripts/model_usage_ledger.py"
cp "$ROOT/codex-agents/"*.toml "$AGENT_TARGET/"

chmod +x "$SKILL_TARGET/scripts/model_usage_ledger.py"

printf '%s\n' "Installed codex-model-router into $CODEX_HOME"
printf '%s\n' "Restart Codex to refresh skills and custom agents."
