# Install tmux-codex-title

Use this document from the same checked-out revision as the code. Identify its
origin and commit first; honor a user-selected fork or tag. Read the README for
the maintained commands and requirements.

1. Inspect applicable local instructions, Linux/tmux/Python/procps versions,
   and the relevant tmux and Codex configuration. Resolve symlinks and determine
   whether TPM, Stow, or another manager owns the target. Keep discovered machine
   details local.
2. Choose one installation owner. Reuse an existing dotfiles-managed copy when
   present. Explain the concrete plugin path and config entries; installation
   needs no root access or services. Install missing system packages only within
   existing authorization. Resolve conflicting unmanaged files before replacing
   them.
3. Back up the affected configurations. Follow the README's TPM or manual
   installation and merge the single Codex `terminal_title` key into its existing
   `[tui]` section. Preserve unrelated keys, plugin entries, and manual window
   names. Personal settings belong in host config, outside this project's source.
4. Reload tmux and run the documented `status` check. Verify a real named Codex
   conversation if the user already has one running; launching paid agents solely
   for installation tests requires appropriate authorization. Report when a
   Codex restart or an interactive verification remains necessary.
5. Report the installed commit, owner/paths, edited entries, checks, backups, and
   the README's exact stop/update/uninstall procedure. Installation does not
   include committing, publishing, or uploading machine data.
