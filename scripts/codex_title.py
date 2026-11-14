#!/usr/bin/env python3
"""Keep automatic tmux window names tied to the oldest interactive Codex."""

import argparse
from dataclasses import dataclass
import fcntl
import hashlib
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time


TITLE = "@codex-title"
OWNER = "@codex-title-owner"
WATCHER = "@codex-title-watcher"
SAVED = "@codex-title-saved-format"
OWNED = "@codex-title-owned-format"
NONINTERACTIVE = {
    "exec", "e", "review", "login", "logout", "mcp", "mcp-server", "app-server",
    "exec-server", "completion", "sandbox", "debug", "apply", "a", "cloud",
    "features", "doctor", "help", "update",
}
VALUE_FLAGS = {
    "-c", "--config", "-m", "--model", "-p", "--profile", "-C", "--cd",
    "-i", "--image", "--enable", "--disable", "--add-dir", "-s", "--sandbox",
    "-a", "--ask-for-approval", "--local-provider", "--remote",
}


@dataclass(frozen=True)
class Process:
    pid: int
    parent: int
    tty: int
    start: int

    @property
    def identity(self):
        return f"{self.pid}:{self.start}"


@dataclass(frozen=True)
class Pane:
    server: str
    window: str
    pane: str
    pid: int
    tty: int
    automatic: bool
    dead: bool
    title: str


def process(pid, proc=Path("/proc")):
    try:
        # comm is parenthesized and may itself contain spaces or parentheses.
        fields = (proc / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()
        if fields[0] == "Z":
            return None
        return Process(int(pid), int(fields[1]), int(fields[4]), int(fields[19]))
    except (OSError, ValueError, IndexError):
        return None


def interactive(argv):
    args = iter(argv[1:])
    for arg in args:
        if arg == "--":
            return True
        if arg in VALUE_FLAGS:
            next(args, None)
        elif arg in {"-h", "--help", "-V", "--version"}:
            return False
        elif not arg.startswith("-"):
            return arg not in NONINTERACTIVE
    return True


def codex_processes(proc=Path("/proc")):
    result = subprocess.run(
        ["ps", "-C", "codex", "-o", "pid="], capture_output=True, text=True, timeout=2,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError("cannot list Codex processes with procps ps")
    found = []
    for value in result.stdout.split():
        item = process(value, proc)
        if not item or not item.tty:
            continue
        try:
            argv = (proc / value / "cmdline").read_bytes().decode(errors="replace").rstrip("\0").split("\0")
        except OSError:
            continue
        if interactive(argv):
            found.append(item)
    return found


def owners(panes, candidates, read_process=process):
    """Match by ancestry and controlling tty; ignore nested agent processes."""
    roots = {pane.pid: pane for pane in panes if not pane.dead}
    candidates = {item.pid: item for item in candidates}
    selected = {}
    for item in candidates.values():
        current, seen = item, set()
        pane = None
        while current and current.pid not in seen:
            seen.add(current.pid)
            if current.pid in roots:
                pane = roots[current.pid]
                break
            if current.pid != item.pid and current.pid in candidates:
                break
            current = read_process(current.parent) if current.parent > 0 else None
        if pane and item.tty == pane.tty:
            previous = selected.get(pane.window)
            if previous is None or (item.start, item.pid) < (previous[1].start, previous[1].pid):
                selected[pane.window] = (pane, item)
    return selected


def conversation_title(raw):
    # Codex's thread-title + project configuration supplies an identifiable suffix.
    text = " ".join(raw.split())
    if text and ("\u2800" <= text[0] <= "\u28ff"):
        text = text[1:].lstrip()
    title, separator, project = text.rpartition(" | ")
    if not separator or not project or not title.strip():
        return None
    return title.strip()


class Tmux:
    def __init__(self, socket):
        self.socket = socket

    def run(self, *args):
        result = subprocess.run(
            ["tmux", "-S", self.socket, *args], capture_output=True, text=True, timeout=3,
        )
        if result.returncode:
            raise RuntimeError("tmux server unavailable")
        return result.stdout.rstrip("\n")

    def get(self, name):
        return self.run("show-options", "-gqv", name)

    def set(self, name, value, window=None):
        target = ["-w", "-t", window] if window else ["-g"]
        self.run("set-option", *target, name, value)

    def unset(self, name, window=None):
        target = ["-w", "-t", window] if window else ["-g"]
        self.run("set-option", "-u", *target, name)

    def server(self):
        return self.run("display-message", "-p", "#{pid}")

    def refresh_names(self):
        # Reapplying the existing value schedules tmux's name timer without
        # changing any window's inherited or explicit automatic-rename choice.
        self.set("automatic-rename", self.get("automatic-rename"))

    def panes(self):
        fmt = "\t".join(("#{pid}", "#{window_id}", "#{pane_id}", "#{pane_pid}",
                         "#{pane_tty}", "#{automatic-rename}", "#{pane_dead}", "#{pane_title}"))
        panes = []
        for line in self.run("list-panes", "-a", "-F", fmt).splitlines():
            try:
                server, window, pane, pid, tty, automatic, dead, title = line.split("\t", 7)
                panes.append(Pane(server, window, pane, int(pid), os.stat(tty).st_rdev,
                                  automatic == "1", dead == "1", title))
            except (OSError, ValueError):
                continue
        return panes


class Watcher:
    def __init__(self, tmux, server):
        self.tmux, self.server = tmux, server
        self.titles = {}
        self.applied = {}

    def sync(self):
        panes = self.tmux.panes()
        if any(pane.server != self.server for pane in panes):
            raise RuntimeError("tmux server replaced")
        selected = owners(panes, codex_processes())
        live = set()
        changed = False
        for window in {pane.window for pane in panes}:
            if window in selected:
                pane, item = selected[window]
                live.add(item.identity)
                title = conversation_title(pane.title)
                if title:
                    self.titles[item.identity] = title
                value = (self.titles.get(item.identity, "codex"), item.identity)
            else:
                value = ("", "")
            if self.applied.get(window) != value:
                # Arguments stay literal: titles never enter a shell or a tmux command string.
                try:
                    self.tmux.set(TITLE, value[0], window)
                    self.tmux.set(OWNER, value[1], window)
                except RuntimeError:
                    if self.tmux.server() != self.server:
                        raise
                    continue  # A window can close between the snapshot and write.
                self.applied[window] = value
                changed = True
        self.titles = {key: value for key, value in self.titles.items() if key in live}
        self.applied = {key: value for key, value in self.applied.items()
                        if key in {pane.window for pane in panes}}
        if changed:
            self.tmux.refresh_names()

    def cleanup(self):
        if self.tmux.server() != self.server:
            return
        owned, saved = self.tmux.get(OWNED), self.tmux.get(SAVED)
        if owned and self.tmux.get("automatic-rename-format") == owned:
            self.tmux.set("automatic-rename-format", saved)
        for window in {pane.window for pane in self.tmux.panes()}:
            self.tmux.unset(TITLE, window)
            self.tmux.unset(OWNER, window)
        for name in (WATCHER, SAVED, OWNED):
            self.tmux.unset(name)
        self.tmux.refresh_names()


def lock_file(socket, server):
    base = Path(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir())
    directory = base / f"tmux-codex-title-{os.getuid()}"
    directory.mkdir(mode=0o700, exist_ok=True)
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError("watcher runtime directory must be private and owned by this user")
    key = hashlib.sha256(f"{socket}\0{server}".encode()).hexdigest()
    fd = os.open(directory / (key + ".lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    return os.fdopen(fd, "r+")


def watch(tmux):
    server = tmux.server()
    with lock_file(tmux.socket, server) as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        watcher = Watcher(tmux, server)
        stopped = threading.Event()
        for signum in (signal.SIGTERM, signal.SIGINT):
            signal.signal(signum, lambda *_: stopped.set())
        saved = tmux.get("automatic-rename-format")
        # Recover the original fallback after an unclean watcher termination.
        if saved == tmux.get(OWNED) and tmux.get(SAVED):
            saved = tmux.get(SAVED)
        owned = "#{?" + TITLE + ",#{" + TITLE + "}," + saved + "}"
        tmux.set(SAVED, saved)
        tmux.set(OWNED, owned)
        tmux.set("automatic-rename-format", owned)
        identity = process(os.getpid()).identity
        tmux.set(WATCHER, identity)
        try:
            while not stopped.is_set():
                watcher.sync()
                stopped.wait(1)
        finally:
            try:
                watcher.cleanup()
            except (RuntimeError, subprocess.TimeoutExpired):
                pass


def watcher_process(tmux):
    identity = tmux.get(WATCHER)
    try:
        item = process(int(identity.split(":")[0]))
    except ValueError:
        return None
    return item if item and item.identity == identity else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", required=True, help="tmux server socket path")
    parser.add_argument("command", choices=("start", "watch", "status", "stop"))
    args = parser.parse_args()
    tmux = Tmux(args.socket)
    try:
        if args.command == "start":
            tmux.server()  # Fail visibly before detaching if the server is unavailable.
            if watcher_process(tmux):
                return 0
            child = subprocess.Popen(
                [sys.executable, "-B", str(Path(__file__).resolve()), "--socket", args.socket, "watch"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                if watcher_process(tmux):
                    return 0
                if child.poll() is not None:
                    break
                time.sleep(.05)
            raise RuntimeError("watcher did not start; run the watch command for diagnostics")
        elif args.command == "watch":
            watch(tmux)
        else:
            item = watcher_process(tmux)
            if args.command == "status":
                print("running" if item else "stopped")
                return 0 if item else 1
            if item:
                os.kill(item.pid, signal.SIGTERM)
        return 0
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"tmux-codex-title: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
