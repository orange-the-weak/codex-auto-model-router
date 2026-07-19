#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
CODEX_HOME=${CODEX_HOME:-"$HOME/.codex"}
SKILLS_ROOT="$CODEX_HOME/skills"
SKILL_TARGET="$SKILLS_ROOT/codex-auto-model-router"
LEGACY_SKILL_TARGET="$SKILLS_ROOT/codex-model-router"
AGENT_TARGET="$CODEX_HOME/agents"

# Keep all copying and content checks before touching an existing installation.
# The target directory is project-owned, so swapping it also removes stale files.
mkdir -p "$SKILLS_ROOT" "$AGENT_TARGET"
for existing_target in "$SKILL_TARGET" "$LEGACY_SKILL_TARGET"; do
  if { [ -e "$existing_target" ] || [ -L "$existing_target" ]; } && [ ! -d "$existing_target" ]; then
    printf '%s\n' "Refusing to replace non-directory install target: $existing_target" >&2
    exit 1
  fi
done
STAGE_ROOT=$(mktemp -d "$SKILLS_ROOT/.codex-auto-model-router.stage.XXXXXX")
BACKUP_ROOT=$(mktemp -d "$SKILLS_ROOT/.codex-auto-model-router.backup.XXXXXX")
STAGED_SKILL="$STAGE_ROOT/skill"
STAGED_AGENTS="$STAGE_ROOT/agents"
AGENT_BACKUP="$BACKUP_ROOT/agents"
SKILL_BACKUP="$BACKUP_ROOT/skill"
LEGACY_SKILL_BACKUP="$BACKUP_ROOT/legacy-skill"
success=0
skill_swapped=0
legacy_skill_moved=0
agents_changed=0

inject_failure() {
  point=$1
  if [ "${CODEX_AUTO_MODEL_ROUTER_INSTALL_FAIL_AT:-}" = "$point" ]; then
    printf '%s\n' "Injected installer failure at $point" >&2
    return 97
  fi
}

restore_agents() {
  rm -f "$AGENT_TARGET"/codex-auto-model-router*.toml "$AGENT_TARGET"/codex-auto-model-executor*.toml
  for name in $LEGACY_PRESETS; do
    rm -f "$AGENT_TARGET/$name"
  done
  if [ -d "$AGENT_BACKUP" ]; then
    for file in "$AGENT_BACKUP"/*.toml; do
      [ -f "$file" ] || [ -L "$file" ] || continue
      mv "$file" "$AGENT_TARGET/"
    done
  fi
}

rollback() {
  [ "$success" -eq 1 ] && return
  if [ "$agents_changed" -eq 1 ]; then
    restore_agents
    agents_changed=0
  fi
  if [ "$skill_swapped" -eq 1 ]; then
    rm -rf "$SKILL_TARGET"
    if [ -d "$SKILL_BACKUP" ] || [ -L "$SKILL_BACKUP" ]; then
      mv "$SKILL_BACKUP" "$SKILL_TARGET"
    fi
    skill_swapped=0
  fi
  if [ "$legacy_skill_moved" -eq 1 ]; then
    rm -rf "$LEGACY_SKILL_TARGET"
    if [ -d "$LEGACY_SKILL_BACKUP" ] || [ -L "$LEGACY_SKILL_BACKUP" ]; then
      mv "$LEGACY_SKILL_BACKUP" "$LEGACY_SKILL_TARGET"
    fi
    legacy_skill_moved=0
  fi
}

cleanup() {
  rollback
  rm -rf "$STAGE_ROOT" "$BACKUP_ROOT"
}
trap cleanup EXIT HUP INT TERM

mkdir -p "$STAGED_SKILL/agents" "$STAGED_SKILL/references" "$STAGED_SKILL/scripts" "$STAGED_AGENTS"
cp "$ROOT/SKILL.md" "$STAGED_SKILL/SKILL.md"
cp "$ROOT/agents/openai.yaml" "$STAGED_SKILL/agents/openai.yaml"
cp "$ROOT/references/"*.md "$STAGED_SKILL/references/"
cp "$ROOT/references/benchmark-evidence.json" "$STAGED_SKILL/references/benchmark-evidence.json"
cp "$ROOT/scripts/"*.py "$STAGED_SKILL/scripts/"
chmod +x "$STAGED_SKILL/scripts/"*.py
cp "$ROOT/codex-agents/"*.toml "$STAGED_AGENTS/"

cmp -s "$ROOT/SKILL.md" "$STAGED_SKILL/SKILL.md"
cmp -s "$ROOT/agents/openai.yaml" "$STAGED_SKILL/agents/openai.yaml"
for file in "$ROOT/references/"*.md "$ROOT/references/benchmark-evidence.json" "$ROOT/scripts/"*.py; do
  relative=${file#"$ROOT/"}
  cmp -s "$file" "$STAGED_SKILL/$relative"
done
for file in "$ROOT/codex-agents/"*.toml; do
  cmp -s "$file" "$STAGED_AGENTS/${file##*/}"
done

LEGACY_PRESETS='project-model-router.toml project-model-router-low.toml project-model-router-high.toml project-model-router-xhigh.toml project-model-router-terra.toml project-model-router-terra-low.toml project-model-router-terra-high.toml project-model-router-terra-xhigh.toml project-model-router-luna.toml project-model-router-luna-low.toml project-model-router-luna-high.toml project-model-router-luna-xhigh.toml project-model-executor.toml project-model-executor-low.toml project-model-executor-high.toml project-model-executor-xhigh.toml project-model-executor-terra.toml project-model-executor-terra-low.toml project-model-executor-terra-high.toml project-model-executor-terra-xhigh.toml project-model-executor-luna.toml project-model-executor-luna-low.toml project-model-executor-luna-high.toml project-model-executor-luna-xhigh.toml'

if [ -d "$LEGACY_SKILL_TARGET" ]; then
  mv "$LEGACY_SKILL_TARGET" "$LEGACY_SKILL_BACKUP"
  legacy_skill_moved=1
fi
inject_failure after-legacy-backup

if [ -d "$SKILL_TARGET" ]; then
  mv "$SKILL_TARGET" "$SKILL_BACKUP"
fi
skill_swapped=1
mv "$STAGED_SKILL" "$SKILL_TARGET"
inject_failure after-skill-swap

mkdir -p "$AGENT_BACKUP"
agent_backup_count=0
for file in "$AGENT_TARGET"/codex-auto-model-router*.toml "$AGENT_TARGET"/codex-auto-model-executor*.toml; do
  [ -f "$file" ] || [ -L "$file" ] || continue
  cp -P "$file" "$AGENT_BACKUP/"
  agent_backup_count=$((agent_backup_count + 1))
  [ "$agent_backup_count" -ne 1 ] || inject_failure during-agent-backup
done
for name in $LEGACY_PRESETS; do
  [ -f "$AGENT_TARGET/$name" ] || [ -L "$AGENT_TARGET/$name" ] || continue
  cp -P "$AGENT_TARGET/$name" "$AGENT_BACKUP/"
  agent_backup_count=$((agent_backup_count + 1))
  [ "$agent_backup_count" -ne 1 ] || inject_failure during-agent-backup
done
agents_changed=1
rm -f "$AGENT_TARGET"/codex-auto-model-router*.toml "$AGENT_TARGET"/codex-auto-model-executor*.toml
for name in $LEGACY_PRESETS; do
  rm -f "$AGENT_TARGET/$name"
done
for file in "$STAGED_AGENTS"/*.toml; do
  mv "$file" "$AGENT_TARGET/"
done
inject_failure after-agent-swap

success=1
printf '%s\n' "Installed codex-auto-model-router into $CODEX_HOME"
printf '%s\n' "Reconciled this project's skill and custom-agent presets; migrated legacy names when present."
printf '%s\n' "Restart Codex to refresh skills and custom agents."
