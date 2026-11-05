#!/usr/bin/env python3
"""Export actual VictoriaMetrics history as JSON and a standalone SVG plot."""
import json
import math
import time
from datetime import datetime
from html import escape
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

from sys import path as module_path
module_path.insert(0, str(Path(__file__).resolve().parents[1]))
from monitoring.queries import BUSINESS, P95, ratio, tbslo

out = Path("artifacts/slo-checks")
end = time.time()
# Include only this probe installation, never invent a preceding green baseline.
with urlopen("http://127.0.0.1:8428/api/v1/query?" + urlencode({"query": "min(min_over_time(blog_probe_started_timestamp_seconds[1h]))"})) as response:
    result = json.load(response)["data"]["result"]
start = max(end - 1800, float(result[0]["value"][1]))
series = []
queries = [(title, ratio(op, "2m"), "percent") for op, (_, title) in BUSINESS.items()]
queries += [("p95 чтения", P95, "seconds"), ("SLA TBSLO за час", tbslo("1h"), "percent")]
for title, query, unit in queries:
    params = {"query": query, "start": start, "end": end, "step": 15, "nocache": 1}
    with urlopen("http://127.0.0.1:8428/api/v1/query_range?" + urlencode(params), timeout=30) as response:
        data = json.load(response)
    assert data["status"] == "success", data
    series.append({"title": title, "query": query, "unit": unit, "result": data["data"]["result"]})
(out / "history.json").write_text(json.dumps(series, ensure_ascii=False, indent=2) + "\n")
svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="1250" viewBox="0 0 1200 1250">',
       '<rect width="1200" height="1250" fill="#111827"/>',
       '<g font-family="sans-serif" fill="#f3f4f6"><text x="45" y="35" font-size="22">Blog: реальные данные VictoriaMetrics</text>']
for n, entry in enumerate(series):
    top = 70 + n*230
    finite_values = [float(v) for result in entry["result"] for _, v in result["values"] if math.isfinite(float(v))]
    limit = max(2, math.ceil(max(finite_values, default=0))) if entry["unit"] == "seconds" else 100
    threshold = 1 if entry["unit"] == "seconds" else (99 if n == 4 else 99.5)
    svg += [f'<text x="45" y="{top}" font-size="18">{escape(entry["title"])}</text>']
    for val in [0, limit/2, limit]:
        y = top+175-150*val/limit
        svg += [f'<path d="M90 {y} H1160" stroke="#374151"/>', f'<text x="45" y="{y+5}" font-size="12">{val:g}</text>']
    y = top+175-150*threshold/limit
    svg += [f'<path d="M90 {y} H1160" stroke="#f87171" stroke-dasharray="6 4"/>']
    for values in entry["result"]:
        points = []
        for stamp, value in values["values"]:
            val = float(value)
            if math.isfinite(val):
                points.append(f'{90+1070*(stamp-start)/(end-start):.1f},{top+175-150*min(val,limit)/limit:.1f}')
        svg += [f'<polyline points="{" ".join(points)}" fill="none" stroke="#38bdf8" stroke-width="2"/>']
    for fraction in [0,.25,.5,.75,1]:
        stamp = start+(end-start)*fraction
        label = datetime.fromtimestamp(stamp).strftime("%H:%M:%S")
        svg += [f'<text x="{90+1070*fraction-20}" y="{top+200}" font-size="12">{label}</text>']
svg += ['</g></svg>']
(out / "history.svg").write_text("\n".join(svg))
print(out / "history.svg")
