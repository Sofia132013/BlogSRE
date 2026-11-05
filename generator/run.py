#!/usr/bin/env python3
"""Create demo users and exercise Blog through its real HTTP forms."""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import http.cookiejar
from http.client import HTTPException
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPCookieProcessor, Request, build_opener


ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = ROOT / "artifacts" / "generator"
OPERATIONS = ("registration", "post", "read", "comment")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Browser:
    def __init__(self, base):
        self.base = base.rstrip("/")
        self.cookies = http.cookiejar.CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.cookies), NoRedirect())

    def request(self, path, data=None):
        # localhost is allowed by Blog even when the transport uses a forwarded IP.
        headers = {"Host": "localhost", "Referer": urlsplit(self.base).scheme + "://localhost" + path}
        if data is not None:
            data = dict(data)
            data["csrfmiddlewaretoken"] = next(
                (cookie.value for cookie in self.cookies if cookie.name == "csrftoken"), ""
            )
            data = urlencode(data).encode()
        try:
            try:
                response = self.opener.open(
                    Request(self.base + path, data=data, headers=headers), timeout=10
                )
            except HTTPError as error:
                response = error  # A successful form submission returns HTTP 302.
            with response:
                return response.code, response.read().decode("utf-8", errors="replace")
        except (URLError, OSError, TimeoutError, HTTPException):
            return 0, ""


def now():
    return datetime.now(timezone.utc).isoformat()


def save(path, data):
    # Credentials stay outside Git/Docker context, with owner-only access.
    descriptor, temporary = tempfile.mkstemp(prefix=".generator-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


@contextmanager
def lock(path):
    with path.with_suffix(".lock").open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Этот запуск ещё работает. Сначала остановите его через Ctrl+C.") from None
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def new_run(args):
    run = "slodemo_" + secrets.token_hex(6)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    path = args.manifest or RUNS_DIR / (stamp + "_" + run + ".json")
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise RuntimeError("Файл запуска уже существует. Выберите другой --manifest или уберите этот параметр.") from None
    os.close(descriptor)
    data = {
        "run": run, "url": args.url.rstrip("/"), "started_at": now(),
        "password": secrets.token_urlsafe(24), "users": [], "registered_users": [],
        "rounds": 0, "successes": dict.fromkeys(OPERATIONS, 0),
    }
    save(path, data)
    return path, data


def register(path, data):
    username = data["run"] + "_" + secrets.token_hex(4)
    # Record before HTTP: an interrupted response can still have saved the user.
    data["users"].append(username)
    save(path, data)
    browser = Browser(data["url"])
    status, _ = browser.request("/auth/signup/")
    if status == 200:
        status, _ = browser.request("/auth/signup/", {
            "username": username,
            "password1": data["password"], "password2": data["password"],
        })
        if status == 302:
            data["registered_users"].append(username)
    save(path, data)
    return browser, username, status


def record(path, data, statuses):
    data["rounds"] += 1
    for operation, status in statuses.items():
        expected = 200 if operation == "read" else 302
        data["successes"][operation] += int(status == expected)
    save(path, data)
    values = " | ".join(f"{operation}={statuses[operation]}" for operation in OPERATIONS)
    print(f"{time.strftime('%H:%M:%S')} | {values} | пользователей: {len(data['registered_users'])}", flush=True)


def generate(args):
    path, data = new_run(args)
    print("Файл запуска и пароли:", path, flush=True)
    print("Остановка: Ctrl+C. Очистка: python3 generator/run.py --cleanup " + shlex.quote(str(path)), flush=True)
    started = time.monotonic()
    deadline = started + (args.seconds if args.seconds is not None else 900)
    with lock(path):
        if json.loads(path.read_text()).get("cleaned_at"):
            raise RuntimeError("Этот запуск уже очищен. Повторите запуск генератора.")
        try:
            worker, username, registration = register(path, data)
            if registration != 302:
                raise RuntimeError(
                    f"Начальная регистрация не выполнена (код {registration}). "
                    "Проверьте адрес Blog, port-forward и отключите демо-ошибки."
                )
            worker.request("/auth/login/")
            status, _ = worker.request("/auth/login/", {
                "username": username, "password": data["password"],
            })
            if status != 302:
                raise RuntimeError(f"Не удалось войти в учебный аккаунт (код {status}).")
            worker.request("/new/")
            post, _ = worker.request("/new/", {"text": "Публикация генератора Blog"})
            status, body = worker.request("/" + username + "/")
            links = re.findall(r'href="(/' + re.escape(username) + r'/\d+/)"', body)
            if post != 302 or status != 200 or not links:
                raise RuntimeError("Не удалось создать или найти первый пост. Запустите генератор при нормальной работе Blog.")
            post_path = links[0]
            read, _ = worker.request(post_path)
            comment, _ = worker.request(post_path + "comment", {"text": "Комментарий генератора Blog"})
            record(path, data, {"registration": registration, "post": post, "read": read, "comment": comment})
            print("Учебный профиль:", data["url"] + "/" + username + "/", flush=True)

            # The first account belongs to the first batch. Batches are sequential;
            # their start times are scheduled from the beginning of this run.
            batch_remaining = args.batch_size - 1
            next_batch = started + args.interval
            # One logged-in account keeps writes measurable even if later signups fail.
            while args.users is None or data["rounds"] < args.users:
                if batch_remaining == 0:
                    current = time.monotonic()
                    if current > next_batch:
                        elapsed = current - started
                        next_batch = started + (int(elapsed // args.interval) + 1) * args.interval
                    wake_at = min(next_batch, deadline) if args.users is None else next_batch
                    time.sleep(max(0, wake_at - time.monotonic()))
                    batch_remaining = args.batch_size
                    # Skip missed starts instead of firing several overdue batches.
                    elapsed = max(0, time.monotonic() - started)
                    next_batch = started + (int(elapsed // args.interval) + 1) * args.interval
                if args.users is None and time.monotonic() >= deadline:
                    break
                _, _, registration = register(path, data)
                post, _ = worker.request("/new/", {"text": "Публикация генератора Blog"})
                read, _ = worker.request(post_path)
                comment, _ = worker.request(post_path + "comment", {"text": "Комментарий генератора Blog"})
                record(path, data, {"registration": registration, "post": post, "read": read, "comment": comment})
                batch_remaining -= 1
        except KeyboardInterrupt:
            print("\nГенератор остановлен.")
        finally:
            data["finished_at"] = now()
            save(path, data)
    return 0


def cleanup(value, args):
    if value == "latest":
        paths = list(RUNS_DIR.glob("*.json"))
        if not paths:
            raise RuntimeError("Сохранённых запусков генератора нет.")
        def started(item):
            try:
                return datetime.fromisoformat(json.loads(item.read_text())["started_at"]).timestamp()
            except (KeyError, TypeError, ValueError):
                raise RuntimeError("Не удалось определить время запуска. Укажите конкретный файл для --cleanup.") from None
        path = max(paths, key=started)
    else:
        path = Path(value).resolve()
    if not path.is_file():
        raise RuntimeError("Файл запуска не найден: " + str(path))
    with lock(path):
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            raise RuntimeError("Некорректный файл запуска. Удаление отменено.")
        run, users = data.get("run"), data.get("users")
        if not isinstance(run, str) or not re.fullmatch(r"slodemo_[0-9a-f]{12}", run):
            raise RuntimeError("Некорректный идентификатор запуска. Удаление отменено.")
        if not isinstance(users, list) or any(
            not isinstance(user, str) or not re.fullmatch(re.escape(run) + r"_[0-9a-f]{8}", user)
            for user in users
        ):
            raise RuntimeError("Некорректный список пользователей. Удаление отменено.")
        if data.get("cleaned_at"):
            print("Этот запуск уже очищен:", path)
            return 0
        program = '''
import json, os, sys
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "blog.settings")
import django
django.setup()
from django.contrib.auth import get_user_model
from django.db import transaction
names = json.loads(sys.stdin.read())
with transaction.atomic():
    query = get_user_model().objects.filter(username__in=names, is_staff=False, is_superuser=False)
    count = query.count()
    query.delete()
print(json.dumps({"deleted_users": count}))
'''
        result = subprocess.run([
            "kubectl", "--context=" + args.context, "-n", args.namespace,
            "exec", "-i", "deployment/blog-web", "-c", "web", "--", "python", "-c", program,
        ], input=json.dumps(users), text=True, capture_output=True, check=True)
        deleted = json.loads(result.stdout)["deleted_users"]
        data["cleaned_at"] = now()
        data["deleted_users"] = deleted
        save(path, data)
        print(f"Удалено учебных пользователей: {deleted}. Их посты и комментарии также удалены.")
        print("Файл запуска сохранён:", path)
    return 0


def positive_integer(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("Укажите целое число больше нуля.")
    return number


def parser():
    result = argparse.ArgumentParser(description="Генератор пользователей, постов и комментариев Blog.")
    mode = result.add_mutually_exclusive_group()
    mode.add_argument("--seconds", type=positive_integer, help="Продолжительность в секундах; по умолчанию 900.")
    mode.add_argument("--users", type=positive_integer, help="Число попыток регистрации, включая первый аккаунт.")
    mode.add_argument("--cleanup", metavar="latest|FILE", help="Удалить данные последнего или указанного запуска.")
    result.add_argument("--batch-size", type=positive_integer, default=1, help="Попыток регистрации в группе; по умолчанию 1. Первая группа запускается сразу.")
    result.add_argument("--interval", type=positive_integer, default=5, help="Интервал между началами групп, секунды; по умолчанию 5.")
    result.add_argument("--url", default="http://127.0.0.1:8001", help="Адрес уже запущенного Blog.")
    result.add_argument("--manifest", type=Path, help="Свой путь для нового файла запуска; существующий не перезаписывается.")
    result.add_argument("--context", default="blog-sre", help="Контекст Kubernetes для очистки.")
    result.add_argument("--namespace", default="blog-sre", help="Namespace Kubernetes для очистки.")
    return result


def main(argv=None):
    cli = parser()
    args = cli.parse_args(argv)
    try:
        address = urlsplit(args.url)
        valid = address.scheme in ("http", "https") and address.hostname and address.port != 0 and not (
            address.query or address.fragment or address.username
        )
    except ValueError:
        valid = False
    if not valid:
        cli.error("--url должен содержать адрес Blog вида http://127.0.0.1:8001 без параметров и пароля.")
    try:
        return cleanup(args.cleanup, args) if args.cleanup else generate(args)
    except (RuntimeError, OSError, ValueError, subprocess.CalledProcessError) as error:
        print("Ошибка:", error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
