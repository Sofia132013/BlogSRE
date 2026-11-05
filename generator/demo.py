#!/usr/bin/env python3
"""Run the 15-minute Blog screencast scenario with scheduled faults."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import signal
import subprocess
import sys
import time

if __package__:
    from .run import ROOT, RUNS_DIR, lock
else:
    from run import ROOT, RUNS_DIR, lock


SCHEDULE = (
    (290, "errors", 120, "Включаем ошибки 503. На 5-й минуте начнётся вторая группа."),
    (345, "slow", 60, "Включаем задержку 1,2 секунды. Смотрите p95 и пробер."),
    (420, "normal", 0, "Восстанавливаем Blog. На 10-й минуте придёт группа без ошибок."),
)


class Controller:
    def __init__(self, context, namespace):
        self.command = ["kubectl", "--context=" + context, "-n", namespace]

    def pods(self):
        result = subprocess.run(
            self.command + ["get", "pods", "-l", "app=blog-web", "-o", "json"],
            check=True, capture_output=True, text=True, timeout=20,
        )
        items = json.loads(result.stdout)["items"]
        names = [
            item["metadata"]["name"] for item in items
            if item.get("status", {}).get("phase") == "Running"
            and not item["metadata"].get("deletionTimestamp")
        ]
        if not names:
            raise RuntimeError("Не найдены работающие pod приложения Blog. Проверьте Minikube и контекст.")
        return names

    def set_mode(self, mode, ttl=0):
        if mode not in ("normal", "errors", "slow") or not 0 <= ttl <= 300:
            raise ValueError("Неизвестный режим или срок действия воздействия.")
        program = '''
import json, os, time
from pathlib import Path
p = Path("/tmp/blog-slo-demo.json")
'''
        if mode == "normal":
            program += 'p.unlink(missing_ok=True)\n'
        else:
            program += (
                't = p.with_suffix(".tmp")\n'
                f't.write_text(json.dumps({{"mode": {mode!r}, "expires_at": time.time() + {ttl}}}))\n'
                'os.replace(t, p)\n'
            )

        def apply(pod):
            try:
                subprocess.run(
                    self.command + ["exec", pod, "-c", "web", "--", "python", "-c", program],
                    check=True, capture_output=True, text=True, timeout=15,
                )
                return None
            except subprocess.CalledProcessError as error:
                return pod + ": " + (error.stderr or str(error)).strip()
            except (OSError, subprocess.TimeoutExpired) as error:
                return pod + ": " + str(error)

        # A slow/failed replica must not prevent restoration of the other replicas.
        pods = self.pods()
        with ThreadPoolExecutor(max_workers=min(8, len(pods))) as pool:
            errors = [error for error in pool.map(apply, pods) if error]
        if errors:
            raise RuntimeError("Не удалось установить режим " + mode + ": " + "; ".join(errors))


def stop_generator(process):
    if process is None or process.poll() is not None:
        return
    process.send_signal(signal.SIGINT)
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def wait_until(process, deadline):
    while True:
        code = process.poll()
        if code is not None:
            raise RuntimeError(f"Генератор завершился раньше сценария (код {code}). Воздействие отключается.")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(1, remaining))


def demonstrate(args):
    controller = Controller(args.context, args.namespace)
    process = None
    try:
        print("Подготовка: отключаем прежние демо-ошибки во всех pod Blog.", flush=True)
        controller.set_mode("normal")
        started = time.monotonic()
        process = subprocess.Popen([
            sys.executable, "-u", str(ROOT / "generator/run.py"),
            "--seconds", "900", "--batch-size", "10", "--interval", "300",
            "--url", args.url,
        ], cwd=ROOT, start_new_session=True)
        print("00:00 | Сценарий запущен. Откройте Grafana. Остановка: Ctrl+C.", flush=True)
        for seconds, mode, ttl, message in SCHEDULE:
            wait_until(process, started + seconds)
            controller.set_mode(mode, ttl)
            print(f"{seconds // 60:02}:{seconds % 60:02} | {message}", flush=True)
        while process.poll() is None:
            if time.monotonic() > started + 1020:
                raise RuntimeError("Генератор не завершился вовремя. Останавливаем сценарий.")
            time.sleep(1)
        if process.returncode != 0:
            raise RuntimeError(f"Генератор завершился с ошибкой (код {process.returncode}).")
    finally:
        try:
            stop_generator(process)
        finally:
            controller.set_mode("normal")
    print("Завершено", flush=True)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Скринкаст Blog: 15 минут, по 10 пользователей каждые 5 минут, ошибки и восстановление автоматически."
    )
    parser.add_argument("--url", default="http://127.0.0.1:8001", help="Адрес уже запущенного Blog.")
    parser.add_argument("--context", default="blog-sre", help="Контекст Kubernetes.")
    parser.add_argument("--namespace", default="blog-sre", help="Namespace Kubernetes.")
    args = parser.parse_args(argv)

    def interrupted(signum, frame):
        raise KeyboardInterrupt

    previous = signal.signal(signal.SIGTERM, interrupted)
    try:
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        # A second scenario must not clear or overwrite the first one's faults.
        with lock(RUNS_DIR / "demo"):
            return demonstrate(args)
    except KeyboardInterrupt:
        print("Сценарий остановлен. Учебные данные сохранены.", flush=True)
        return 130
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        detail = error.stderr if isinstance(error, subprocess.CalledProcessError) else str(error)
        print("Ошибка сценария: " + (detail or str(error)), file=sys.stderr)
        print("Если Kubernetes недоступен, воздействие само истечёт: ошибки — за 120 секунд, задержка — за 60 секунд.", file=sys.stderr)
        return 1
    finally:
        signal.signal(signal.SIGTERM, previous)


if __name__ == "__main__":
    raise SystemExit(main())
