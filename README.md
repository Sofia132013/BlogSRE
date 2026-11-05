# BlogSRE

Блог на Django для практики SRE: публикации с изображениями, категории,
комментарии, подписки, метрики Prometheus, JSON-логи и демонстрация SLO.

Python 3.12, Django 5.2, PostgreSQL 16, Gunicorn, WhiteNoise и Bootstrap.
Изображения и пользовательские данные хранятся в PostgreSQL.

## Запуск через Docker Compose

Нужны Git, Docker и Docker Compose. Все команды выполняются из корня проекта.

```bash
git clone https://github.com/Sofia132013/BlogSRE.git
cd BlogSRE
cp .env.example .env
```

Если `.env` уже настроен, сохраните его. Для нового окружения замените
`DJANGO_SECRET_KEY` и `POSTGRES_PASSWORD` в `.env` своими значениями.
Ключ можно сгенерировать командой:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(50))'
```

`DATABASE_URL` в примере собирается из `POSTGRES_*` и использует хост `db`.
Специальные символы пароля нужно URL-кодировать в `DATABASE_URL`.
Compose загружает `.env`; Django сам этот файл не читает.
Секреты исключены из Git и Docker-образа.

```bash
docker compose build web
docker compose up -d --wait db
docker compose run --rm web python manage.py migrate --noinput
docker compose up -d --wait web
```

Сайт: http://127.0.0.1:8001/. Порт задаётся переменной `PORT` в `.env`.
Для доступа с другого устройства добавьте адрес компьютера в
`DJANGO_ALLOWED_HOSTS`. В Compose отладочный режим выключен.

После изменения исходников:

```bash
docker compose build web
docker compose run --rm web python manage.py migrate --noinput
docker compose up -d --wait web
```

Если схема БД не менялась, для обновления достаточно
`docker compose up -d --build --wait web`.
После изменения только `.env` используйте
`docker compose up -d --force-recreate --wait web`.

### Существующая база после переноса

По умолчанию Compose создаёт том `<имя проекта>_postgres_data`.
Чтобы использовать уже существующую базу, задайте в локальном `.env`:

```dotenv
POSTGRES_VOLUME_NAME=имя_существующего_тома
POSTGRES_VOLUME_EXTERNAL=true
```

Имя можно посмотреть через `docker volume ls`. Сохраните прежние
`POSTGRES_DB`, `POSTGRES_USER` и `POSTGRES_PASSWORD`: переменные окружения
не меняют пароль в уже созданной БД. Остановите прежний контейнер PostgreSQL
перед подключением этого тома к новому контейнеру.
Внешний том Compose не создаёт и не удаляет даже при `down -v`.
Для новой базы оставьте `POSTGRES_VOLUME_EXTERNAL=false` и не задавайте имя тома.

Обычная остановка с сохранением базы:

```bash
docker compose down
```

### Пользователи и почта

Создание администратора:

```bash
docker compose run --rm web python manage.py createsuperuser
```

Панель: http://127.0.0.1:8001/admin/.
Команда `seed_blog` добавляет 7 демо-авторов с постами и 15 категорий.
Она требует пароль для создаваемых аккаунтов:

```bash
read -rsp 'Пароль демо-аккаунтов: ' BLOG_DEMO_PASSWORD
export BLOG_DEMO_PASSWORD
docker compose run --rm -e BLOG_DEMO_PASSWORD web python manage.py seed_blog
unset BLOG_DEMO_PASSWORD
```

Письма по умолчанию не отправляются. Для восстановления пароля настройте
`DJANGO_EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend`,
`EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`,
`EMAIL_USE_TLS` и `DEFAULT_FROM_EMAIL` в `.env`.

## Проверки

После сборки образа и запуска БД:

```bash
docker compose config --quiet
docker compose run --rm web python manage.py check
docker compose run --rm web python manage.py makemigrations --check --dry-run
docker compose run --rm -e DJANGO_DEBUG=true web python -m pytest
docker compose run --rm -e DJANGO_DEBUG=true web python manage.py test posts users --verbosity 1
python3 -B -m unittest discover -s generator/tests -v
```

Тесты Django используют отдельную тестовую БД. Пользователю PostgreSQL
нужно право её создавать. Тесты генератора работают без БД и Kubernetes.

GitHub Actions выполняет эти проверки, миграции и Docker-сборку.
После push в `main` публикуется образ
`ghcr.io/sofia132013/blogsre:<commit-sha>`.
Для запуска опубликованного образа укажите его в `APP_IMAGE` и используйте
`docker compose pull web`, затем миграции и запуск с `--no-build`.

## Разработка без Docker

Нужны Python 3.12 и отдельный PostgreSQL 16.
В Bash, с подготовленным `.env`:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
set -a
source .env
set +a
```

Замените хост `db` в `DATABASE_URL` на адрес доступного PostgreSQL,
задайте `DJANGO_DEBUG=true`, затем выполните:

```bash
python manage.py migrate
python manage.py runserver "0.0.0.0:${PORT:-8001}"
```

## Kubernetes / Minikube

Манифесты рассчитаны на профиль `blog-sre` и namespace `blog-sre`.
Для web, миграций и пробера используется один локальный образ `blog:local`.
`imagePullPolicy: Never` требует собрать его внутри Minikube:

```bash
minikube start -p blog-sre
minikube -p blog-sre image build -t blog:local .
```

Для нового окружения скопируйте `deploy/secret.example.yaml` в
`deploy/secret.yaml` и замените заглушки. Если файл уже настроен, сохраните его.
Используйте одинаковый пароль PostgreSQL в обоих Secret; хост в Kubernetes
`DATABASE_URL` — `postgres`. При существующем PVC сохраняйте пароль БД.

```bash
kubectl --context=blog-sre apply -f deploy/k8s/namespace.yaml
kubectl --context=blog-sre -n blog-sre apply -f deploy/k8s/configmap.yaml -f deploy/secret.yaml
kubectl --context=blog-sre -n blog-sre apply -f deploy/k8s/postgres-statefulset-service.yaml
kubectl --context=blog-sre -n blog-sre rollout status statefulset/postgres --timeout=180s
kubectl --context=blog-sre -n blog-sre delete job blog-migrate --ignore-not-found=true
kubectl --context=blog-sre -n blog-sre apply -f deploy/k8s/migrations-job.yaml
kubectl --context=blog-sre -n blog-sre wait --for=condition=complete job/blog-migrate --timeout=180s
kubectl --context=blog-sre -n blog-sre apply -f deploy/k8s/deployment-service.yaml -f deploy/k8s/blog-prober.yaml
kubectl --context=blog-sre -n blog-sre rollout status deployment/blog-web --timeout=180s
kubectl --context=blog-sre -n blog-sre port-forward svc/blog-web 8001:80
```

Удаляйте прежний Job миграций после завершения его работы.
При пересборке того же тега обновите pod через `rollout restart` для
`deployment/blog-web` и `deployment/blog-prober` и дождитесь rollout.
Проберу нужен хотя бы один пост: создайте его через сайт или `seed_blog`.

### Мониторинг

VictoriaMetrics собирает метрики с аннотированных pod каждые 15 секунд.
Настройки Helm находятся в `deploy/victoriametrics-values.yaml`:

```bash
helm repo add vm https://victoriametrics.github.io/helm-charts/
helm repo update vm
helm --kube-context blog-sre upgrade --install vmsingle vm/victoria-metrics-single \
  --version 0.49.0 --namespace blog-sre \
  -f deploy/victoriametrics-values.yaml --wait --timeout 180s
```

Логи собирает Vector и отправляет в VictoriaLogs:

```bash
kubectl --context=blog-sre apply -f deploy/k8s/victorialogs.yaml -f deploy/k8s/vector.yaml
kubectl --context=blog-sre apply -f deploy/k8s/grafana.yaml
```

Дашборд: `deploy/grafana/blog-slo.json`. Настройки источника VictoriaMetrics
и файлового провижининга лежат рядом в `deploy/grafana/`.
Для настройки панели в Grafana создайте источник типа Prometheus с UID
`blog-slo-vm` и URL `http://victoriametrics.blog-sre.svc.cluster.local:8428`,
затем импортируйте JSON дашборда. Панель будет доступна на `/d/blog-slo-sla/`.
Каждый port-forward запускайте в отдельном терминале:

```bash
kubectl --context=blog-sre -n blog-sre port-forward svc/grafana 3000:3000
kubectl --context=blog-sre -n blog-sre port-forward svc/victoriametrics 8428:8428
```

Grafana: http://127.0.0.1:3000/.
VictoriaMetrics: http://127.0.0.1:8428/vmui/.
Проверка запросов дашборда:

```bash
python3 scripts/check-slo.py
```

## Генератор нагрузки и демонстрация SLO

Генератор работает через HTTP-формы сайта и создаёт собственные аккаунты,
посты и комментарии. Запуск на уже работающем сайте:

```bash
python3 generator/run.py --users 10
```

Автоматическая 15-минутная демонстрация с ошибками, задержкой и восстановлением
требует доступа `kubectl` к профилю `blog-sre`:

```bash
python3 generator/demo.py
```

Ctrl+C завершает сценарий и отключает воздействие.
Детали запуска, графиков и очистки — в [generator/README.md](generator/README.md).
Локальные результаты в `artifacts/` исключены из Git и Docker-образа.

## Диагностика

`/healthz/` проверяет процесс, `/readyz/` — соединение с БД,
`/metrics` отдаёт метрики Prometheus. Логи приложения имеют формат JSON.

```bash
docker compose ps
docker compose logs --tail=50 web
curl -fsS http://127.0.0.1:8001/healthz/
curl -fsS http://127.0.0.1:8001/readyz/
```

Настройки Compose предназначены для локального HTTP-запуска.
Публичное HTTPS-развёртывание требует соответствующих настроек Django и прокси;
проверить их можно через `python manage.py check --deploy`.
