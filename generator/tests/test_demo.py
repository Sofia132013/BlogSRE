"""Check the automatic timeline and restoration without a real cluster."""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import signal
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from generator import demo


class DemoTest(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(redirect_stdout(io.StringIO()))
        self.stack.enter_context(redirect_stderr(io.StringIO()))
        self.args = SimpleNamespace(context="blog-sre", namespace="blog-sre", url="http://127.0.0.1:8001")
        self.clock = [0.0]
        self.modes = []
        self.controller = Mock()
        self.controller.set_mode.side_effect = lambda mode, ttl=0: self.modes.append((self.clock[0], mode, ttl))
        self.process = Mock(returncode=None)

        def poll():
            if self.clock[0] >= 900:
                self.process.returncode = 0
            return self.process.returncode

        self.process.poll.side_effect = poll
        self.process.wait.side_effect = lambda **kwargs: setattr(self.process, "returncode", 0)

    def automatic(self, sleep=None):
        self.stack.enter_context(patch.object(demo, "Controller", return_value=self.controller))
        self.spawn = self.stack.enter_context(patch.object(demo.subprocess, "Popen", return_value=self.process))
        self.stack.enter_context(patch.object(demo.time, "monotonic", side_effect=lambda: self.clock[0]))

        def advance(seconds):
            self.clock[0] += seconds

        self.stack.enter_context(patch.object(demo.time, "sleep", side_effect=sleep or advance))

    def test_timeline_launches_generator_and_restores_all_modes(self):
        self.automatic()
        self.assertEqual(demo.demonstrate(self.args), 0)
        self.assertEqual(self.modes, [
            (0, "normal", 0), (290, "errors", 120), (345, "slow", 60),
            (420, "normal", 0), (900, "normal", 0),
        ])
        command = self.spawn.call_args.args[0]
        self.assertEqual(command[3:], [
            "--seconds", "900", "--batch-size", "10", "--interval", "300",
            "--url", self.args.url,
        ])
        self.assertTrue(self.spawn.call_args.kwargs["start_new_session"])
        self.process.send_signal.assert_not_called()

    def test_early_generator_failure_does_not_enable_faults(self):
        self.automatic()
        self.process.poll.side_effect = lambda: 1 if self.clock[0] >= 10 else None
        with self.assertRaisesRegex(RuntimeError, "раньше сценария"):
            demo.demonstrate(self.args)
        self.assertEqual([mode for _, mode, _ in self.modes], ["normal", "normal"])

    def test_ctrl_c_stops_generator_and_restores_blog(self):
        def interrupt(seconds):
            raise KeyboardInterrupt

        self.automatic(sleep=interrupt)
        with self.assertRaises(KeyboardInterrupt):
            demo.demonstrate(self.args)
        self.process.send_signal.assert_called_once_with(signal.SIGINT)
        self.process.wait.assert_called_once_with(timeout=15)
        self.assertEqual(self.modes[-1][1], "normal")

    def test_partial_fault_failure_restores_blog_and_stops_generator(self):
        self.automatic()

        def fail(mode, ttl=0):
            self.modes.append((self.clock[0], mode, ttl))
            if mode == "errors":
                raise RuntimeError("one pod failed")

        self.controller.set_mode.side_effect = fail
        with self.assertRaisesRegex(RuntimeError, "one pod failed"):
            demo.demonstrate(self.args)
        self.assertEqual([mode for _, mode, _ in self.modes], ["normal", "errors", "normal"])
        self.process.send_signal.assert_called_once_with(signal.SIGINT)

    def test_generator_launch_failure_still_restores_blog(self):
        self.automatic()
        self.spawn.side_effect = OSError("cannot start")
        with self.assertRaisesRegex(OSError, "cannot start"):
            demo.demonstrate(self.args)
        self.assertEqual([mode for _, mode, _ in self.modes], ["normal", "normal"])

    def test_second_scenario_cannot_clear_the_running_scenarios_faults(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(demo, "RUNS_DIR", Path(directory)), \
                patch.object(demo, "Controller") as controller, demo.lock(Path(directory) / "demo"):
            self.assertEqual(demo.main([]), 1)
            controller.assert_not_called()

    def test_stubborn_generator_is_terminated_then_killed(self):
        self.process.poll.side_effect = None
        self.process.poll.return_value = None
        self.process.wait.side_effect = [
            subprocess.TimeoutExpired("generator", 15),
            subprocess.TimeoutExpired("generator", 5), 0,
        ]
        demo.stop_generator(self.process)
        self.process.terminate.assert_called_once()
        self.process.kill.assert_called_once()

    def test_controller_attempts_every_replica_even_if_one_fails(self):
        commands = []

        def kubectl(command, **kwargs):
            if "get" in command:
                pods = {"items": [
                    {"metadata": {"name": name}, "status": {"phase": "Running"}}
                    for name in ("blog-1", "blog-2", "blog-3")
                ]}
                return subprocess.CompletedProcess(command, 0, json.dumps(pods), "")
            commands.append(command)
            if "blog-2" in command:
                raise subprocess.CalledProcessError(1, command, stderr="unreachable")
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch.object(demo.subprocess, "run", side_effect=kubectl):
            controller = demo.Controller("blog-sre", "blog-sre")
            with self.assertRaisesRegex(RuntimeError, "blog-2: unreachable"):
                controller.set_mode("normal")
            self.assertEqual({command[5] for command in commands}, {"blog-1", "blog-2", "blog-3"})
            for command in commands:
                self.assertIn("p.unlink(missing_ok=True)", command[-1])

    def test_fault_control_file_contains_expiry_and_atomic_replace(self):
        pods = {"items": [{"metadata": {"name": "blog-1"}, "status": {"phase": "Running"}}]}
        with patch.object(demo.subprocess, "run", side_effect=[
            subprocess.CompletedProcess([], 0, json.dumps(pods), ""),
            subprocess.CompletedProcess([], 0, "", ""),
        ]) as kubectl:
            demo.Controller("blog-sre", "blog-sre").set_mode("errors", 120)
            program = kubectl.call_args.args[0][-1]
            self.assertIn('"mode": \'errors\'', program)
            self.assertIn('"expires_at": time.time() + 120', program)
            self.assertIn("os.replace(t, p)", program)
            compile(program, "<fault-control>", "exec")


if __name__ == "__main__":
    unittest.main()
