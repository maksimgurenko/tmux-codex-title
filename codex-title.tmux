#!/usr/bin/env bash
set -eu
plugin_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
if ! command -v python3 >/dev/null 2>&1 || ! command -v ps >/dev/null 2>&1; then
    tmux display-message 'tmux-codex-title requires python3 and procps ps'
    exit 1
fi
socket="$(tmux display-message -p '#{socket_path}')"
exec python3 -B "$plugin_dir/scripts/codex_title.py" --socket "$socket" start
