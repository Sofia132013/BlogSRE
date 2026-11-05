"""HTTP/cookie/CSRF and cleanup isolation checks without the working database."""

from contextlib import contextmanager, redirect_stderr, redirect_stdout
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import stat
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs

from generator import run


@contextmanager
def blog(fault_after_first=False):
    state = {"users": {}, "posts": [], "comments": 0, "fault": False}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, code, body="", cookies=()):
            self.send_response(code)
            for cookie in cookies:
                self.send_header("Set-Cookie", cookie + "; Path=/")
            if code == 302:
                self.send_header("Location", "/")
            self.end_headers()
            self.wfile.write(body.encode())

        def do_GET(self):
            if self.path in ("/auth/signup/", "/auth/login/"):
                self.reply(200, "form", ("csrftoken=form-token",))
            elif self.path.count("/") == 3:
                self.reply(503 if state["fault"] else 200, "site-main")
            else:
                username = self.path.strip("/")
                links = [f'<a href="/{username}/{i}/">post</a>' for i, author in enumerate(state["posts"], 1) if author == username]
                self.reply(200, "site-main " + " ".join(links))

        def do_POST(self):
            payload = parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())
            cookies = SimpleCookie(self.headers.get("Cookie", ""))
            token = cookies.get("csrftoken")
            if not token or payload.get("csrfmiddlewaretoken") != [token.value]:
                return self.reply(403)
            if self.path == "/auth/login/":
                username = payload["username"][0]
                if state["users"].get(username) != payload["password"][0]:
                    return self.reply(200, "bad login")
                return self.reply(302, cookies=("sessionid=" + username, "csrftoken=rotated-token"))
            if state["fault"]:
                return self.reply(503)
            if self.path == "/auth/signup/":
                state["users"][payload["username"][0]] = payload["password1"][0]
                return self.reply(302)
            if not cookies.get("sessionid"):
                return self.reply(403)
            if token.value != "rotated-token":
                return self.reply(403)
            if self.path == "/new/":
                state["posts"].append(cookies["sessionid"].value)
            elif self.path.endswith("/comment"):
                state["comments"] += 1
                if fault_after_first:
                    state["fault"] = True
            else:
                return self.reply(404)
            self.reply(302)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:" + str(server.server_port), state
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


class GeneratorTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.runs = Path(self.directory.name)
        self.output = io.StringIO()
        stdout = redirect_stdout(self.output)
        stderr = redirect_stderr(self.output)
        stdout.__enter__()
        stderr.__enter__()
        self.addCleanup(stdout.__exit__, None, None, None)
        self.addCleanup(stderr.__exit__, None, None, None)

    def generate(self, url, users=3):
        with patch.object(run, "RUNS_DIR", self.runs), patch.object(run.time, "sleep"):
            return run.main(["--url", url, "--users", str(users)])

    def test_real_http_forms_rotate_csrf_and_create_requested_number(self):
        with blog() as (url, state):
            state["users"]["existing-user"] = "existing-password"
            self.assertEqual(self.generate(url), 0)
            data = json.loads(next(self.runs.glob("*.json")).read_text())
            self.assertEqual(len(data["registered_users"]), 3)
            self.assertEqual(data["rounds"], 3)
            self.assertEqual(data["successes"], dict.fromkeys(run.OPERATIONS, 3))
            self.assertEqual(len(state["posts"]), 3)
            self.assertEqual(state["comments"], 3)
            self.assertEqual(state["users"]["existing-user"], "existing-password")
            self.assertEqual(stat.S_IMODE(next(self.runs.glob("*.json")).stat().st_mode), 0o600)

    def test_new_run_does_not_overwrite_previous_users_or_manifest(self):
        with blog() as (url, state):
            self.assertEqual(self.generate(url, 1), 0)
            first = next(self.runs.glob("*.json"))
            before = first.read_bytes()
            self.assertEqual(self.generate(url, 1), 0)
            self.assertEqual(first.read_bytes(), before)
            self.assertEqual(len(list(self.runs.glob("*.json"))), 2)
            self.assertEqual(len(state["users"]), 2)

    def test_duration_mode_finishes_without_creating_an_extra_round(self):
        with blog() as (url, state), patch.object(run, "RUNS_DIR", self.runs):
            self.assertEqual(run.main(["--url", url, "--seconds", "1"]), 0)
            data = json.loads(next(self.runs.glob("*.json")).read_text())
            self.assertEqual(data["rounds"], 1)
            self.assertIn("finished_at", data)
            self.assertEqual(len(state["users"]), 1)

    def test_three_batches_of_ten_at_five_minute_intervals(self):
        clock = [0.0]
        starts = []
        register = run.register

        def register_at(*args):
            starts.append(clock[0])
            return register(*args)

        def sleep(seconds):
            clock[0] += seconds

        with blog() as (url, state), patch.object(run, "RUNS_DIR", self.runs), \
                patch.object(run.time, "monotonic", side_effect=lambda: clock[0]), \
                patch.object(run.time, "sleep", side_effect=sleep), \
                patch.object(run, "register", side_effect=register_at):
            self.assertEqual(run.main([
                "--url", url, "--seconds", "900", "--batch-size", "10", "--interval", "300",
            ]), 0)
            self.assertEqual(starts, [0.0] * 10 + [300.0] * 10 + [600.0] * 10)
            self.assertEqual(clock[0], 900.0)
            self.assertEqual(len(state["users"]), 30)
            self.assertEqual(len(state["posts"]), 30)
            self.assertEqual(state["comments"], 30)

    def test_user_limit_stops_in_the_middle_of_a_batch(self):
        with blog() as (url, state), patch.object(run, "RUNS_DIR", self.runs):
            self.assertEqual(run.main([
                "--url", url, "--users", "3", "--batch-size", "10",
            ]), 0)
            self.assertEqual(len(state["users"]), 3)

    def test_duration_limit_stops_an_unfinished_batch(self):
        clock = [0.0]
        register = run.register

        def slow_register(*args):
            result = register(*args)
            clock[0] += 2
            return result

        with blog() as (url, state), patch.object(run, "RUNS_DIR", self.runs), \
                patch.object(run.time, "monotonic", side_effect=lambda: clock[0]), \
                patch.object(run, "register", side_effect=slow_register):
            self.assertEqual(run.main([
                "--url", url, "--seconds", "5", "--batch-size", "10", "--interval", "300",
            ]), 0)
            self.assertEqual(len(state["users"]), 3)
            self.assertEqual(clock[0], 6.0)

    def test_slow_batches_skip_missed_starts(self):
        clock = [0.0]
        starts = []
        register = run.register

        def slow_register(*args):
            starts.append(clock[0])
            result = register(*args)
            clock[0] += 6
            return result

        def sleep(seconds):
            clock[0] += seconds

        with blog() as (url, state), patch.object(run, "RUNS_DIR", self.runs), \
                patch.object(run.time, "monotonic", side_effect=lambda: clock[0]), \
                patch.object(run.time, "sleep", side_effect=sleep), \
                patch.object(run, "register", side_effect=slow_register):
            self.assertEqual(run.main([
                "--url", url, "--seconds", "30", "--batch-size", "2", "--interval", "5",
            ]), 0)
            self.assertEqual(starts, [0.0, 6.0, 15.0, 21.0])
            self.assertEqual(clock[0], 30.0)

    def test_faults_after_bootstrap_keep_all_actions_running(self):
        with blog(fault_after_first=True) as (url, state):
            self.assertEqual(self.generate(url), 0)
            data = json.loads(next(self.runs.glob("*.json")).read_text())
            self.assertEqual(data["rounds"], 3)
            self.assertEqual(len(data["users"]), 3)
            self.assertEqual(data["successes"], dict.fromkeys(run.OPERATIONS, 1))
            self.assertEqual(len(state["users"]), 1)

    def test_existing_manifest_is_not_overwritten(self):
        file = self.runs / "existing.json"
        file.write_text("keep this")
        self.assertEqual(run.main(["--users", "1", "--manifest", str(file)]), 1)
        self.assertEqual(file.read_text(), "keep this")

    def test_incomplete_response_is_reported_as_network_failure(self):
        class BrokenResponse(io.BytesIO):
            code = 200

            def read(self, *args):
                raise OSError("connection closed")

        browser = run.Browser("http://localhost:8001")
        with patch.object(browser.opener, "open", return_value=BrokenResponse()):
            self.assertEqual(browser.request("/"), (0, ""))

    def manifest(self):
        args = run.parser().parse_args(["--users", "1", "--manifest", str(self.runs / "run.json")])
        path, data = run.new_run(args)
        data["users"] = [data["run"] + "_01234567"]
        run.save(path, data)
        return path, data

    def test_cleanup_rejects_a_name_outside_its_run(self):
        path, data = self.manifest()
        data["users"].append("existing-user")
        run.save(path, data)
        with patch.object(run.subprocess, "run") as command:
            self.assertEqual(run.main(["--cleanup", str(path)]), 1)
            command.assert_not_called()

    def test_cleanup_refuses_a_running_generator(self):
        path, _ = self.manifest()
        with run.lock(path), patch.object(run.subprocess, "run") as command:
            self.assertEqual(run.main(["--cleanup", str(path)]), 1)
            command.assert_not_called()

    def test_cleanup_sends_only_recorded_names_and_is_idempotent(self):
        path, data = self.manifest()
        result = subprocess.CompletedProcess([], 0, '{"deleted_users": 1}\n', '')
        with patch.object(run.subprocess, "run", return_value=result) as command:
            self.assertEqual(run.main(["--cleanup", str(path)]), 0)
            self.assertEqual(json.loads(command.call_args.kwargs["input"]), data["users"])
            self.assertIn("--context=blog-sre", command.call_args.args[0])
            self.assertEqual(run.main(["--cleanup", str(path)]), 0)
            self.assertEqual(command.call_count, 1)

    def test_latest_uses_run_start_time_instead_of_file_name(self):
        path, data = self.manifest()
        data["started_at"] = "2026-10-20T12:00:00+00:00"
        run.save(path, data)
        new_path = self.runs / "a-newer-run.json"
        newer = {**data, "started_at": "2026-10-21T12:00:00+00:00"}
        run.save(new_path, newer)
        result = subprocess.CompletedProcess([], 0, '{"deleted_users": 1}\n', '')
        with patch.object(run, "RUNS_DIR", self.runs), patch.object(run.subprocess, "run", return_value=result):
            self.assertEqual(run.main(["--cleanup", "latest"]), 0)
        self.assertIn("cleaned_at", json.loads(new_path.read_text()))
        self.assertNotIn("cleaned_at", json.loads(path.read_text()))


if __name__ == "__main__":
    unittest.main()
