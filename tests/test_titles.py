import importlib.util
import os
from pathlib import Path
import pty
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("codex_title", ROOT / "scripts/codex_title.py")
plugin = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = plugin
SPEC.loader.exec_module(plugin)


class SelectionTest(unittest.TestCase):
    def pane(self, window, pid, tty=10, dead=False):
        return plugin.Pane("1", window, f"%{pid}", pid, tty, True, dead, "Task | demo")

    def test_launch_order_wins_over_pane_order_and_pid_order(self):
        panes = [self.pane("@1", 10), self.pane("@1", 20)]
        processes = {10: plugin.Process(10, 1, 10, 1), 20: plugin.Process(20, 1, 10, 2)}
        newer = plugin.Process(30, 10, 10, 200)
        oldest = plugin.Process(40, 20, 10, 100)
        selected = plugin.owners(panes, [newer, oldest], processes.get)
        self.assertEqual(selected["@1"][1], oldest)
        self.assertEqual(plugin.owners(panes, [newer], processes.get)["@1"][1], newer)

    def test_ignore_nested_background_terminals_and_dead_panes(self):
        root = plugin.Process(30, 10, 10, 100)
        nested = plugin.Process(40, 30, 10, 101)
        wrong_tty = plugin.Process(50, 10, 11, 90)
        outside = plugin.Process(60, 999, 10, 80)
        processes = {10: plugin.Process(10, 1, 10, 1), 30: root}
        panes = [self.pane("@1", 10)]
        selected = plugin.owners(panes, [root, nested, wrong_tty, outside], processes.get)
        self.assertEqual(selected["@1"][1], root)
        self.assertFalse(plugin.owners([self.pane("@1", 10, dead=True)], [root], processes.get))

    def test_separate_windows_get_separate_owners(self):
        first, second = plugin.Process(10, 1, 10, 10), plugin.Process(20, 1, 20, 20)
        selected = plugin.owners([self.pane("@1", 10), self.pane("@2", 20, tty=20)], [first, second])
        self.assertEqual(set(selected), {"@1", "@2"})

    def test_titles_keep_punctuation_and_drop_only_final_project_suffix(self):
        for raw, expected in (
            ("\u2827 Plan widgets | demo", "Plan widgets"),
            ("Résumé | 日本語 | demo", "Résumé | 日本語"),
            ("$(touch unexpected); #[fg=red] #{pid} | demo", "$(touch unexpected); #[fg=red] #{pid}"),
            ("  spaced\t title | demo", "spaced title"),
            ("12345678-1234-1234-1234-123456789abc | demo", "codex"),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(plugin.conversation_title(raw), expected)
        for raw in ("demo", "file.txt - Nvim", " | demo", "Task | ", ""):
            self.assertIsNone(plugin.conversation_title(raw))

    def test_noninteractive_commands_do_not_own_windows(self):
        for argv in (
            ["codex", "exec", "hello"], ["codex", "--model", "example", "review"],
            ["codex", "-c", "model='example'", "app-server"], ["codex", "--help"],
        ):
            self.assertFalse(plugin.interactive(argv))
        for argv in (
            ["codex"], ["codex", "--yolo"], ["codex", "--model", "example", "resume"],
            ["codex", "--", "review"], ["codex", "--model=example", "A task"],
        ):
            self.assertTrue(plugin.interactive(argv))

    def test_process_start_identity_and_disappearing_processes(self):
        current = plugin.process(os.getpid())
        self.assertEqual(current.pid, os.getpid())
        self.assertGreater(current.start, 0)
        self.assertIsNone(plugin.process(999999999))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "123"
            path.mkdir()
            fields = ["S", "9", "0", "0", "77"] + ["0"] * 14 + ["456"]
            (path / "stat").write_text("123 (name with ) brackets) " + " ".join(fields))
            self.assertEqual(plugin.process(123, Path(directory)), plugin.Process(123, 9, 77, 456))


@unittest.skipUnless(shutil.which("tmux") and shutil.which("ps"), "tmux and procps required")
class TmuxIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="codex title tests ")
        self.directory = Path(self.temp.name)
        self.socket = str(self.directory / "server.sock")
        self.env = dict(os.environ, XDG_RUNTIME_DIR=str(self.directory), TERM="xterm-256color")
        self.env.pop("TMUX", None)
        self.env.pop("TMUX_PANE", None)
        self.commands = []
        self.tmux("-f", "/dev/null", "new-session", "-d", "-s", "test", "exec sleep 120")
        self.addCleanup(self.close)
        # Exercise an actual terminal client, including tmux's name timers.
        self.client_pid, self.client_fd = pty.fork()
        if self.client_pid == 0:
            os.execvpe("tmux", ["tmux", "-S", self.socket, "attach-session", "-t", "test"], self.env)
        os.set_blocking(self.client_fd, False)
        self.initial = self.tmux("display-message", "-p", "#{pane_id}")
        self.window = self.tmux("display-message", "-p", "#{window_id}")
        self.default = self.tmux("show-options", "-gqv", "automatic-rename-format")
        self.fixture = self.directory / "agent.py"
        self.fixture.write_text('''import ctypes,json,sys,time
from pathlib import Path
ctypes.CDLL(None).prctl(15,b"codex",0,0,0)
path=Path(sys.argv[1])
previous=None
while True:
    try: current=json.loads(path.read_text())
    except (OSError,ValueError): time.sleep(.03); continue
    if current.get("exit"): break
    title=current.get("title", "")
    if title!=previous:
        print("\\033]0;"+title+"\\007",end="",flush=True)
        previous=title
    time.sleep(.03)
''')

    def tmux(self, *args):
        result = subprocess.run(["tmux", "-S", self.socket, *args], env=self.env,
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.rstrip("\n")

    def cli(self, command):
        return subprocess.run([sys.executable, "-B", str(ROOT / "scripts/codex_title.py"),
                               "--socket", self.socket, command], env=self.env,
                              capture_output=True, text=True, timeout=5)

    def close(self):
        self.cli("stop")
        subprocess.run(["tmux", "-S", self.socket, "kill-server"], env=self.env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.waitpid(self.client_pid, 0)
        os.close(self.client_fd)
        self.temp.cleanup()

    def wait_for(self, predicate, timeout=6):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                os.read(self.client_fd, 65536)
            except OSError:
                pass
            if predicate():
                return
            time.sleep(.05)
        if not predicate():
            details = self.tmux("list-panes", "-a", "-F",
                                "#{window_name} #{pane_id} #{pane_pid} #{pane_current_command} #{pane_title} title=#{@codex-title} owner=#{@codex-title-owner} auto=#{automatic-rename} format=#{automatic-rename-format}")
            self.fail("tmux state did not reach the expected value: " + details)

    def start(self):
        # Exercise the actual TPM executable entry, including paths containing spaces.
        self.tmux("run-shell", shlex.quote(str(ROOT / "codex-title.tmux")))
        self.wait_for(lambda: self.cli("status").returncode == 0)

    def control(self, path, **values):
        import json
        path.write_text(json.dumps(values))

    def agent(self, title, replace=False):
        control = self.directory / f"control {len(self.commands)}.json"
        self.commands.append(control)
        self.control(control, title=title)
        command = shlex.join([sys.executable, "-B", str(self.fixture), str(control)]) + "; exec sleep 120"
        if replace:
            self.tmux("respawn-pane", "-k", "-t", self.initial, command)
            pane = self.initial
        else:
            pane = self.tmux("split-window", "-h", "-P", "-F", "#{pane_id}", command)
        self.wait_for(lambda: self.tmux("display-message", "-p", "-t", pane, "#{pane_title}") == title)
        return pane, control

    def name(self):
        return self.tmux("display-message", "-p", "-t", self.window, "#{window_name}")

    def test_native_titles_launch_order_focus_takeover_and_fallback(self):
        self.start()
        oldest, first = self.agent("Oldest conversation | demo")
        self.wait_for(lambda: self.name() == "Oldest conversation")
        newer, second = self.agent("Newer conversation | demo", replace=True)
        self.tmux("select-pane", "-t", newer)
        time.sleep(1.2)
        self.assertEqual(self.name(), "Oldest conversation")
        self.control(first, title="\u2839 Renamed 日本語 | demo")
        self.wait_for(lambda: self.name() == "Renamed 日本語")
        self.control(first, title="notes.txt - Nvim")
        time.sleep(1.2)
        self.assertEqual(self.name(), "Renamed 日本語")
        self.control(first, exit=True)
        self.wait_for(lambda: self.name() == "Newer conversation")
        self.control(second, exit=True)
        self.wait_for(lambda: self.name() == "sleep")
        self.assertEqual(self.tmux("show-options", "-wqv", "-t", self.window, plugin.TITLE), "")

    def test_manual_names_and_stop_restore_original_format(self):
        self.start()
        self.agent("Task | demo")
        self.wait_for(lambda: self.name() == "Task")
        self.tmux("rename-window", "-t", self.window, "My manual name")
        time.sleep(1.2)
        self.assertEqual(self.name(), "My manual name")
        self.assertEqual(self.cli("stop").returncode, 0)
        self.wait_for(lambda: self.tmux("show-options", "-gqv", "automatic-rename-format") == self.default)
        self.assertEqual(self.name(), "My manual name")

    def test_reload_reuses_watcher_and_literal_titles_cannot_execute(self):
        self.start()
        original = self.tmux("show-options", "-gqv", plugin.WATCHER)
        self.start()
        self.start()
        time.sleep(.2)
        self.assertEqual(self.tmux("show-options", "-gqv", plugin.WATCHER), original)
        title = "$(touch unexpected); #[fg=red] #{pid}"
        self.agent(title + " | demo")
        self.wait_for(lambda: self.name() == title)
        self.assertFalse((ROOT / "unexpected").exists())
        self.assertFalse((self.directory / "unexpected").exists())

    def test_unnamed_codex_and_closed_panes(self):
        self.start()
        pane, control = self.agent("demo")
        self.wait_for(lambda: self.name() == "codex")
        self.control(control, title="Now named | demo")
        self.wait_for(lambda: self.name() == "Now named")
        self.control(control, title="12345678-1234-1234-1234-123456789abc | demo")
        self.wait_for(lambda: self.name() == "codex")
        self.tmux("kill-pane", "-t", pane)
        self.wait_for(lambda: self.name() == "sleep")
        self.assertEqual(self.cli("status").returncode, 0)

    def test_server_exit_stops_watcher(self):
        self.start()
        identity = self.tmux("show-options", "-gqv", plugin.WATCHER)
        pid = int(identity.split(":")[0])
        self.tmux("kill-server")
        self.wait_for(lambda: plugin.process(pid) is None)

    def test_separate_servers_and_recovery_after_crash(self):
        self.start()
        first = self.tmux("show-options", "-gqv", plugin.WATCHER)
        other = TmuxIntegrationTest("test_server_exit_stops_watcher")
        other.setUp()
        self.addCleanup(other.doCleanups)
        other.start()
        second = other.tmux("show-options", "-gqv", plugin.WATCHER)
        self.assertNotEqual(first, second)
        self.agent("First server | demo")
        other.agent("Second server | demo")
        self.wait_for(lambda: self.name() == "First server")
        other.wait_for(lambda: other.name() == "Second server")
        os.kill(int(first.split(":")[0]), signal.SIGKILL)
        self.wait_for(lambda: self.cli("status").returncode == 1)
        self.start()
        self.assertNotEqual(self.tmux("show-options", "-gqv", plugin.WATCHER), first)
        self.assertEqual(self.tmux("show-options", "-gqv", plugin.SAVED), self.default)


if __name__ == "__main__":
    unittest.main()
