"""Read-only blackbox checks through the same Service as user traffic."""

import json
import os
import re
import signal
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from prometheus_client import Gauge, start_http_server


SUCCESS = Gauge("blog_probe_success", "Last HTTP/content check succeeded.", ["target"])
DURATION = Gauge("blog_probe_duration_seconds", "Full response duration.", ["target"])
STATUS = Gauge("blog_probe_http_status", "Last status, 0 for network failure.", ["target"])
GOOD = Gauge("blog_probe_round_good", "All checks succeeded in at most one second.")
LAST_RUN = Gauge("blog_probe_last_run_timestamp_seconds", "Last completed round.")
STARTED = Gauge("blog_probe_started_timestamp_seconds", "Prober process start.")


def check(url, expected):
    started = time.monotonic()
    status, body = 0, ""
    try:
        with urlopen(Request(url, headers={"Host": "localhost"}), timeout=3) as response:
            status = response.status
            body = response.read(2_000_000).decode("utf-8", errors="replace")
    except HTTPError as error:
        status = error.code
    except (URLError, TimeoutError, OSError):
        pass
    return status == 200 and expected in body, time.monotonic() - started, status, body


def run_round(base):
    results = []
    success, duration, status, body = check(base + "/", "site-main")
    results.append(("home", success, duration, status))
    # Discover a real post from the feed. An empty blog cannot prove post reads.
    links = re.findall(r'href="(/[^/"?]+/\d+/)"', body)
    if links:
        success, duration, status, _ = check(base + links[0], "site-main")
    else:
        success, duration, status = False, 0, 0
    results.append(("post", success, duration, status))
    for target, success, duration, status in results:
        SUCCESS.labels(target).set(int(success))
        DURATION.labels(target).set(duration)
        STATUS.labels(target).set(status)
    good = all(success and duration <= 1 for _, success, duration, _ in results)
    GOOD.set(int(good))
    LAST_RUN.set(time.time())
    print(json.dumps({"good": good, "checks": results}), flush=True)


def main():
    def stop(signum, frame):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    STARTED.set(time.time())
    GOOD.set(0)
    LAST_RUN.set(0)
    start_http_server(9099)
    base = os.getenv("BLOG_URL", "http://blog-web").rstrip("/")
    interval = 10
    while True:
        started = time.monotonic()
        run_round(base)
        time.sleep(max(0, interval - (time.monotonic() - started)))


if __name__ == "__main__":
    main()
