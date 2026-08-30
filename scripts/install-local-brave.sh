#!/usr/bin/env bash
set -euo pipefail

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=1
  shift
fi
if (( $# )); then
  echo "usage: $0 [--dry-run]" >&2
  exit 2
fi

REPO_ROOT="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
CONFIG_ROOT="${XDG_CONFIG_HOME:-$HOME/.config}/browser-harness"
WORKSPACE_LINK="$CONFIG_ROOT/agent-workspace"
COMMAND_LINK="$HOME/.local/bin/bh-agent"
OLD_COMMAND="$CONFIG_ROOT/bin/bh-agent"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_ROOT="${BH_SETUP_BACKUP_DIR:-$HOME/Library/Application Support/browser-harness/migration-backups/$STAMP}"

run() {
  if (( DRY_RUN )); then
    printf 'DRY RUN:'
    printf ' %q' "$@"
    printf '\n'
  else
    "$@"
  fi
}

backup_existing() {
  local path="$1"
  local label="$2"
  [[ -e "$path" || -L "$path" ]] || return 0
  run mkdir -p "$BACKUP_ROOT"
  run mv "$path" "$BACKUP_ROOT/$label"
}

link_exact() {
  local source="$1"
  local target="$2"
  local label="$3"
  if [[ -L "$target" && "$(readlink "$target")" == "$source" ]]; then
    echo "already linked: $target -> $source"
    return 0
  fi
  backup_existing "$target" "$label"
  run mkdir -p "$(dirname "$target")"
  run ln -s "$source" "$target"
}

echo "Repository: $REPO_ROOT"
link_exact "$REPO_ROOT/agent-workspace" "$WORKSPACE_LINK" agent-workspace
link_exact "$REPO_ROOT/agent-workspace/bin/bh-agent" "$COMMAND_LINK" bh-agent-command
backup_existing "$OLD_COMMAND" old-config-bh-agent

if (( ! DRY_RUN )); then
  chmod +x "$REPO_ROOT/agent-workspace/bin/bh-agent" \
    "$REPO_ROOT/agent-workspace/bin/launch-brave"
fi

echo "Local Brave setup installed. Backups, if any: $BACKUP_ROOT"
echo "Verify with: bh-agent setup-check <<'PY'"
echo "print(page_info())"
echo "PY"
