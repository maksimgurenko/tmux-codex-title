# tmux-codex-title

Name each tmux window after its first running Codex conversation.

A window running **Plan the migration** displays that conversation title instead
of `codex`. The earliest-started instance owns the name across pane switches.
When it exits, the next running instance takes over. When all instances exit,
tmux returns to its usual automatic name. Manual window names stay manual.

## Requirements

Linux, tmux, Python 3.10+, and procps `ps`. No Python packages, credentials,
systemd services, or changes to Codex's launch command are needed. Local tests
use tmux 3.8 and Python 3.14; CI also exercises its Ubuntu tmux package.
macOS, remote Codex processes over SSH, and container-isolated processes are
not supported. The watcher must see the same processes as the tmux server.

## Install

In Codex's `config.toml`, merge this key into the existing `[tui]` section:

```toml
[tui]
terminal_title = ["thread-title", "project"]
```

This supplies an identifiable `Conversation | project` terminal title; the
plugin drops the project suffix. Restart Codex after changing this setting.
See the [official configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference).
Existing titles in that format, including a leading spinner, also work.

With [TPM](https://github.com/tmux-plugins/tpm), put this before TPM's `run` line
in your tmux config, then press **prefix + I**:

```tmux
set -g @plugin 'maksimgurenko/tmux-codex-title#v0.1.1'
```

For a manual install, clone this repository at `v0.1.1` into
`~/.tmux/plugins/tmux-codex-title`, then add:

```tmux
run-shell '"$HOME/.tmux/plugins/tmux-codex-title/codex-title.tmux"'
```

Use one installation method. Reload your tmux config after manual installation.
Windows must have `automatic-rename` enabled, and panes must allow applications
to set their titles (`allow-set-title on`). The plugin preserves both settings.
To opt a manually named window back in, run
`tmux set-option -w automatic-rename on` in that window.

For an agent-assisted install, use [INSTALL.agent.md](INSTALL.agent.md) from the
same revision as the code.

## Verify and troubleshoot

From inside tmux:

```sh
plugin="$HOME/.tmux/plugins/tmux-codex-title"
socket="$(tmux display-message -p '#{socket_path}')"
python3 -B "$plugin/scripts/codex_title.py" --socket "$socket" status
```

Expected output: `running`. Launch Codex and start or resume a named
conversation; the tab should update within about two seconds. Starting another
Codex in a split pane does not displace the first instance.

If the label stays `codex`, inspect `tmux display-message -p '#{pane_title}'` in
that pane. It must contain `Conversation | project`; an unnamed conversation
uses `codex`, including when Codex emits a bare thread UUID. Titles retain any
truncation already applied by Codex. An editor
title without that separator leaves the last valid conversation title intact.
Custom application titles containing the same separator are indistinguishable
from Codex titles while a Codex process remains in the pane.

For startup errors, run the helper in the foreground:

```sh
python3 -B "$plugin/scripts/codex_title.py" --socket "$socket" watch
```

Only one watcher can hold a server's lock. Reloading is safe. Each watcher checks
once a second and ends when its server exits. It reads process metadata and pane
titles, without reading conversation files or sending data over the network.
Runtime lock files live in `$XDG_RUNTIME_DIR/tmux-codex-title-UID`, or a private
directory beneath the temporary directory when XDG runtime storage is absent.

## Update, rollback, and remove

Stop the current watcher **before** updating or rolling back files:

```sh
python3 -B "$plugin/scripts/codex_title.py" --socket "$socket" stop
```

Wait until `status` reports `stopped`. For TPM, change the selected tag and use
TPM's update command; for a manual checkout, check out the selected tag. Reload
the config to start the selected version. Stop restores the previous global
automatic-name format, unless you changed that format while the plugin ran.

To uninstall, stop the watcher, remove only its plugin/config entry, and use
your installation manager to remove its directory. Keep your other tmux and
Codex settings. Stow users should remove the source through their dotfiles
rather than replacing the managed installation with a TPM clone.

## Development

```sh
python3 -B -m unittest discover -s tests -v
bash -n codex-title.tmux
```

Tests use disposable tmux servers, actual pseudo-terminal clients, and synthetic
Codex processes. They never launch a real coding agent. See
[CONTRIBUTING.md](CONTRIBUTING.md) for release instructions. MIT licensed.
