"""Generate the committed Grafana dashboard from the actual calculation queries."""
import json
from pathlib import Path
from .queries import BUSINESS, P95, GOOD_SLOT, ratio, sla_ok, tbslo

DS = {"type": "prometheus", "uid": "blog-slo-vm"}
panels = []


def panel(title, expressions, unit="percent", kind="timeseries", description="", threshold=99.5):
    n = len(panels)
    targets = [{"refId": chr(65+i), "expr": expr, "legendFormat": label, "datasource": DS}
               for i, (label, expr) in enumerate(expressions)]
    panels.append({
        "id": n+1, "title": title, "type": kind, "datasource": DS,
        "description": description, "gridPos": {"x": (n % 2)*12, "y": (n//2)*8, "w": 12, "h": 8},
        "targets": targets,
        "fieldConfig": {"defaults": {"unit": unit, "min": 0,
            **({"max": 100} if unit == "percent" else {}),
            "thresholds": {"mode": "absolute", "steps": [{"color": "red", "value": None}, {"color": "green", "value": threshold}]},
            "custom": {"drawStyle": "line", "lineWidth": 2, "showPoints": "auto", "spanNulls": False, "thresholdsStyle": {"mode": "line"}}}, "overrides": []},
        "options": {"legend": {"displayMode": "table", "placement": "bottom", "calcs": ["lastNotNull"]}, "tooltip": {"mode": "multi"}},
    })
    if unit == "s":
        panels[-1]["fieldConfig"]["defaults"]["thresholds"]["steps"] = [
            {"color": "green", "value": None}, {"color": "red", "value": threshold}
        ]

for op, (_, label) in BUSINESS.items():
    panel(f"SLI: {label}, окно 2 минуты", [(label, ratio(op, "2m")), ("SLO 99.5%", "vector(99.5)")],
          description="Успешно сохранённые действия / валидные попытки × 100. Пустая форма и отсутствие входа исключены. Без попыток: No data.")
panel("SLI: p95 чтения, SLO ≤ 1 секунды", [("p95", P95), ("SLO 1 секунда", "vector(1)")], "s", threshold=1,
      description="95% просмотров главной и поста укладываются в показанное время. Служебные запросы исключены.")
panel("Пробер: доступность и время ответа", [("HTTP и содержимое, {{target}}", 'blog_probe_success{job="blog-prober"}'),
      ("Сбор пробера", 'up{job="blog-prober"}'), ("Хороший интервал", GOOD_SLOT)], "short", threshold=1,
      description="1 означает выполнение проверки, 0 означает сбой. Хороший интервал требует ответа двух страниц ≤ 1 секунды и свежих данных.")
panel("Пробер: длительность полного ответа", [("{{target}}", 'blog_probe_duration_seconds{job="blog-prober"}'), ("Порог", "vector(1)")], "s", threshold=1)
panel("Успешность операций (RBSLO, ${sla_window:text})", [(label, ratio(op, "$sla_window")) for op, (_, label) in BUSINESS.items()] + [("SLA 99%", "vector(99)")], threshold=99,
      description="Для каждого действия отдельно: успешные сохранения / валидные попытки. Цель SLA ≥ 99%. Без трафика результат неизвестен.")
panel("Доступность чтения (TBSLO, ${sla_window:text})", [("Доля хорошего времени", tbslo("$sla_window")), ("SLA 99%", "vector(99)")], threshold=99,
      description="Доля хороших 15-секундных интервалов. Отказ, ответ > 1 с, недоступный пробер и устаревшие данные дают 0. До первого запуска интервалы исключены.")
panel("SLA выполнено: 1 да, 0 нет", [("Все обязательства SLA", sla_ok("$sla_window"))], "short", threshold=1,
      description="Все три RBSLO и TBSLO должны быть ≥ 99%. Если нет данных о действиях, общего подтверждения нет.")
panels[-1]["fieldConfig"]["defaults"].update({"max": 1, "color": {"mode": "thresholds"}})
panels[-1]["fieldConfig"]["defaults"]["custom"].update({
    "lineInterpolation": "stepAfter", "thresholdsStyle": {"mode": "off"},
})
windows = [("2m", "2 минуты"), ("10m", "10 минут"), ("30m", "30 минут"), ("1h", "1 час"), ("6h", "6 часов")]
dashboard = {"uid": "blog-slo-sla", "title": "Blog · SLI SLO SLA", "schemaVersion": 39, "version": 1,
    "tags": ["Blog", "SRE", "SLO"], "timezone": "browser", "refresh": "15s",
    "time": {"from": "now-30m", "to": "now"}, "panels": panels,
    "templating": {"list": [{"name": "sla_window", "label": "Окно SLA (2 минуты для показа)", "type": "custom", "query": ", ".join(f"{label} : {value}" for value, label in windows),
        "current": {"text": "1 час", "value": "1h"}, "options": [{"text": label, "value": value, "selected": value == "1h"} for value, label in windows]}]}}
Path("deploy/grafana/blog-slo.json").write_text(json.dumps(dashboard, ensure_ascii=False, indent=2) + "\n")
