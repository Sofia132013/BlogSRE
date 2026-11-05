#!/usr/bin/env python3
"""Normal HTTP/CSRF traffic; only newly registered demonstration accounts."""
import argparse
import http.cookiejar
import json
import re
import secrets
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, HTTPCookieProcessor, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Browser:
    def __init__(self, base):
        self.base = base.rstrip("/")
        self.cookies = http.cookiejar.CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.cookies), NoRedirect())

    def request(self, path, data=None):
        headers = {"Host": "localhost", "Referer": self.base + path}
        if data is not None:
            data = dict(data)
            data["csrfmiddlewaretoken"] = next((c.value for c in self.cookies if c.name == "csrftoken"), "")
            data = urlencode(data).encode()
        try:
            response = self.opener.open(Request(self.base + path, data=data, headers=headers), timeout=10)
        except HTTPError as error:
            response = error
        except (URLError, OSError, TimeoutError):
            return 0, ""
        with response:
            return response.code, response.read().decode("utf-8", errors="replace")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8001")
    parser.add_argument("--seconds", type=int, default=600)
    parser.add_argument("--interval", type=float, default=5)
    parser.add_argument("--manifest", default="artifacts/slo-demo-users.json")
    args = parser.parse_args()
    if args.seconds <= 0 or args.interval < 1:
        parser.error("seconds > 0, interval >= 1")
    manifest = Path(args.manifest)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    if manifest.exists():
        parser.error("Manifest already exists. Clean up this run first or choose another --manifest.")
    run = "slodemo_" + secrets.token_hex(6)
    users = []

    def register():
        username, password = run + "_" + secrets.token_hex(4), secrets.token_urlsafe(24)
        # Record before submission so interrupted requests are also cleanable.
        users.append(username)
        manifest.write_text(json.dumps({"run": run, "users": users}, indent=2) + "\n")
        browser = Browser(args.url)
        browser.request("/auth/signup/")
        code, _ = browser.request("/auth/signup/", {"username": username, "password1": password, "password2": password})
        return browser, username, password, code

    browser, username, password, status = register()
    if status != 302:
        raise SystemExit(f"Initial registration returned {status}. Turn the demo off before starting traffic.")
    browser.request("/auth/login/")
    status, _ = browser.request("/auth/login/", {"username": username, "password": password})
    if status != 302:
        raise SystemExit(f"Login failed: {status}")
    browser.request("/new/")
    status, _ = browser.request("/new/", {"text": "Публикация для проверки SLI"})
    status, body = browser.request("/" + username + "/")
    links = re.findall(r'href="(/' + re.escape(username) + r'/\d+/)"', body)
    if status != 200 or not links:
        raise SystemExit("Cannot find demonstration post")
    post_path = links[0]
    deadline = time.monotonic() + args.seconds
    print(f"run={run}; manifest={manifest}; Ctrl+C stops traffic", flush=True)
    while time.monotonic() < deadline:
        started = time.monotonic()
        _, _, _, registration = register()
        post, _ = browser.request("/new/", {"text": "Публикация для проверки SLI"})
        # The post page contains the comment form and a CSRF token.
        read, _ = browser.request(post_path)
        comment, _ = browser.request(post_path + "comment", {"text": "Комментарий для проверки SLI"})
        print(json.dumps({"time": time.strftime("%H:%M:%S"), "registration": registration,
                          "post": post, "comment": comment, "read": read}), flush=True)
        time.sleep(max(0, args.interval - (time.monotonic() - started)))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Traffic stopped. The manifest is kept for cleanup.")
