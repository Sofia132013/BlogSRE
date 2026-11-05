#!/usr/bin/env python3
"""Evaluate every committed Grafana query against the real VictoriaMetrics."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://127.0.0.1:8428")
parser.add_argument("--output", default="artifacts/slo-checks/queries.json")
parser.add_argument("--window", default="1h", choices=["2m", "10m", "30m", "1h", "6h"])
args = parser.parse_args()
dashboard = json.loads(Path("deploy/grafana/blog-slo.json").read_text())
results = []
for panel in dashboard["panels"]:
    for target in panel["targets"]:
        query = target["expr"].replace("$sla_window", args.window)
        with urlopen(args.url + "/api/v1/query?" + urlencode({"query": query, "nocache": "1"}), timeout=30) as response:
            data = json.load(response)
        if data.get("status") != "success":
            raise SystemExit(f'{panel["title"]}: {data}')
        results.append({"panel": panel["title"], "legend": target["legendFormat"], "query": query, "result": data["data"]["result"]})
path = Path(args.output)
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n")
for result in results:
    print(result["panel"], result["legend"], [r.get("value") for r in result["result"]])
print(f"Queries evaluated: {len(results)}; saved to {path}")
