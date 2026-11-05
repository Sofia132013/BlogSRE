"""Local, expiring fault injection, controlled only through kubectl exec."""

import json
import time
from pathlib import Path

from django.http import HttpResponse

from .metrics import BUSINESS_ATTEMPTS


CONTROL_FILE = Path("/tmp/blog-slo-demo.json")


def demo_response():
    try:
        config = json.loads(CONTROL_FILE.read_text())
        remaining = float(config["expires_at"]) - time.time()
        if not 0 < remaining <= 300:
            return None
    except (OSError, ValueError, TypeError, KeyError):
        return None
    if config.get("mode") == "errors":
        return HttpResponse("Temporary SLO demonstration", status=503)
    if config.get("mode") == "slow":
        time.sleep(1.2)
    return None


def business_attempt(operation):
    BUSINESS_ATTEMPTS.labels(operation).inc()
    return demo_response()
