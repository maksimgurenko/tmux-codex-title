# Development

`codex-title.tmux` is the TPM/manual entry. `scripts/codex_title.py` owns process
selection, title parsing, tmux state, and the per-server watcher. The README owns
the public configuration and lifecycle contract; use INSTALL.agent.md when
installing on a host.

Run `python3 -B -m unittest discover -s tests -v` and `bash -n codex-title.tmux`.
Integration tests use disposable sockets and synthetic processes with an actual
PTY client. Keep personal servers, conversation files, credentials, and paid
agents outside tests. Use synthetic fixtures and repository-relative paths.

Preserve manual names, the user's original fallback format, and process identity
across PID reuse. Keep process/title data out of shell command strings. Runtime
files and dependencies must remain available without this maintainer's dotfiles.
Release from a reviewed clean history using CONTRIBUTING.md; a checkout alone
does not authorize host installation or publication.
