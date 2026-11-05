#!/usr/bin/env python3
"""Cross-check business ratios and time fractions against their components."""
import json
import math
import time
from pathlib import Path
from sys import path
from urllib.parse import urlencode
from urllib.request import urlopen

path.insert(0, str(Path(__file__).resolve().parents[1]))
from monitoring.queries import BUSINESS, GOOD_SLOT, ratio, tbslo

stamp = time.time()

def value(query):
    with urlopen('http://127.0.0.1:8428/api/v1/query?' + urlencode({'query': query, 'time': stamp, 'nocache': 1}), timeout=30) as response:
        result = json.load(response)['data']['result']
    return float(result[0]['value'][1]) if result else None

results = []
for op, (metric, _) in BUSINESS.items():
    success = value(f'sum(increase({metric}{{job="blog-web"}}[2m]))')
    attempts = value(f'sum(increase(blog_business_attempts_total{{job="blog-web",operation="{op}"}}[2m]))')
    actual = value(ratio(op, '2m'))
    expected = 100*success/attempts if attempts else None
    assert actual is None and expected is None or math.isclose(actual, expected, abs_tol=1e-6), (op, actual, expected)
    results.append({'operation': op, 'success': success, 'attempts': attempts, 'SLI': actual})
slots = value(f'count_over_time(({GOOD_SLOT})[1h:15s])')
good = value(f'sum_over_time(({GOOD_SLOT})[1h:15s])')
actual = value(tbslo('1h'))
assert slots and math.isclose(actual, 100*good/slots, abs_tol=1e-6), (actual, slots, good)
results.append({'slots': slots, 'good_slots': good, 'TBSLO': actual})
Path('artifacts/slo-checks/math.json').write_text(json.dumps(results, ensure_ascii=False, indent=2)+'\n')
print(json.dumps(results, ensure_ascii=False, indent=2))
