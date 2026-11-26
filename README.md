# Лабораторная работа №7 — «Масштабирование ПО»

Проект реализует три экземпляра Flask-сервиса, балансировщик Round Robin,
проверку доступности `/health`, общий счётчик PostgreSQL и периодическую
задачу с PostgreSQL Advisory Lock.

## 0. Что установить

- Python 3.12
- Docker Desktop с Docker Compose
- VS Code (или другой редактор)

Откройте в VS Code именно папку `LR7_Scaling`.

## I. Подготовка PostgreSQL

Из корневой папки проекта выполните:

```powershell
docker compose -f docker-compose.local.yml up -d
docker compose -f docker-compose.local.yml ps
```

Проверить таблицы можно так:

```powershell
docker exec -it lr7-postgres-local psql -U postgres -d scaling_db
```

Внутри `psql`:

```sql
\dt
SELECT * FROM counters;
SELECT * FROM job_runs;
\q
```

Локальный PostgreSQL опубликован на `localhost:5432`, чтобы к нему могли
подключаться приложения, запущенные непосредственно из Python.

## II. Локальный запуск трёх экземпляров

Откройте три отдельных терминала VS Code. В каждом перейдите в папку `app`:

```powershell
cd app
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Если виртуальное окружение уже создано, повторно создавать его не нужно.
Запустите экземпляры в трёх терминалах, задавая разные переменные окружения.

Терминал 1:

```powershell
$env:INSTANCE_ID="instance-1"
$env:PORT="5001"
$env:COUNTER_MODE="memory"
$env:ENABLE_JOBS="false"
python app.py
```

Терминал 2:

```powershell
$env:INSTANCE_ID="instance-2"
$env:PORT="5002"
$env:COUNTER_MODE="memory"
$env:ENABLE_JOBS="false"
python app.py
```

Терминал 3:

```powershell
$env:INSTANCE_ID="instance-3"
$env:PORT="5003"
$env:COUNTER_MODE="memory"
$env:ENABLE_JOBS="false"
python app.py
```

## III. Локальный запуск балансировщика

Откройте четвёртый терминал:

```powershell
cd balancer
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python balancer.py
```

Балансировщик доступен по адресу `http://localhost:8000`.

Проверка 9 запросов Round Robin:

```powershell
1..9 | ForEach-Object { Invoke-RestMethod http://localhost:8000/process }
```

Посмотреть состояния экземпляров:

```powershell
Invoke-RestMethod http://localhost:8000/instances
```

Остановите один из трёх терминалов сочетанием Ctrl+C, подождите не менее
5 секунд и снова посмотрите `/instances`. Затем выполните несколько запросов
`/process`: остановленный экземпляр не должен получать запросы.
Запустите его снова и дождитесь очередной проверки.

Добавить экземпляр:

```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:8000/instances `
  -ContentType "application/json" -Body '{"host":"127.0.0.1","port":5004}'
```

Удалить экземпляр:

```powershell
Invoke-RestMethod -Method Delete http://localhost:8000/instances/127.0.0.1:5004
```

## IV. Счётчик посещений: память и PostgreSQL

### Проверка счётчика в памяти

Выполните 30 POST-запросов через балансировщик:

```powershell
1..30 | ForEach-Object {
  Invoke-RestMethod -Method Post http://localhost:8000/visits
}
```

Затем три раза запросите:

```powershell
1..3 | ForEach-Object { Invoke-RestMethod http://localhost:8000/visits }
```

В режиме `memory` значения будут различаться в зависимости от того,
на какой экземпляр попал запрос: память у каждого процесса своя.

### Переключение на PostgreSQL

Остановите три экземпляра (Ctrl+C). Запустите их снова, заменив для каждого
`COUNTER_MODE` на `postgres`, например:

```powershell
$env:COUNTER_MODE="postgres"
```

Перед повторной проверкой обнулите общий счётчик:

```powershell
docker exec -it lr7-postgres-local psql -U postgres -d scaling_db -c "UPDATE counters SET value = 0 WHERE name = 'visits';"
```

Выполните 30 POST-запросов и три GET-запроса, как выше. Теперь все экземпляры
должны показывать общее значение 30.

Перезапустите экземпляры и снова выполните GET `/visits`: значение должно
сохраниться, поскольку оно находится в PostgreSQL, а не в памяти Python.

## V. Периодическая задача и Advisory Lock

Остановите локальные экземпляры. Запустите каждый с:

```powershell
$env:COUNTER_MODE="postgres"
$env:ENABLE_JOBS="true"
```

Оставьте все три экземпляра работающими на 2 минуты. В логах будут сообщения
о выполнении задачи и о пропуске запуска из-за занятой блокировки или уже
обработанного интервала.

Посмотреть записи:

```powershell
docker exec -it lr7-postgres-local psql -U postgres -d scaling_db -c "SELECT slot, instance_id, started_at FROM job_runs ORDER BY slot;"
```

Для каждого `slot` должна быть одна запись. Чтобы проверить переключение,
определите экземпляр из последней записи, остановите соответствующий терминал
Ctrl+C и подождите следующий интервал. В новых строках должен появиться другой
работающий `instance_id`.

## VI. Запуск всей системы в Docker

Остановите локальные процессы Flask и локальный контейнер PostgreSQL:

```powershell
docker compose -f docker-compose.local.yml down
```

Из корневой папки проекта соберите и запустите весь проект:

```powershell
docker compose up --build -d
docker compose ps
```

В браузере откройте `http://localhost:8000/instances`.

Проверки через PowerShell:

```powershell
1..9 | ForEach-Object { Invoke-RestMethod http://localhost:8000/process }

1..30 | ForEach-Object {
  Invoke-RestMethod -Method Post http://localhost:8000/visits
}

1..3 | ForEach-Object { Invoke-RestMethod http://localhost:8000/visits }
```

Посмотреть логи:

```powershell
docker compose logs -f app1 app2 app3
docker compose logs -f balancer
```

Посмотреть таблицу периодических запусков:

```powershell
docker compose exec postgres psql -U postgres -d scaling_db -c "SELECT slot, instance_id, started_at FROM job_runs ORDER BY slot;"
```

Проверить отказоустойчивость экземпляра:

```powershell
docker compose stop app2
```

Подождите минимум 5 секунд, проверьте `/instances` и `/process`.
Затем восстановите экземпляр:

```powershell
docker compose start app2
```

После восстановления дождитесь health check и проверьте `/instances`.

В финальном Docker Compose на хост опубликован только порт балансировщика
`8000`. Порты экземпляров и PostgreSQL доступны внутри сети Docker.

## Полезные команды

Остановить контейнеры, сохранив данные PostgreSQL:

```powershell
docker compose down
```

Полностью удалить контейнеры и том с данными (счётчик и журнал задач будут
удалены):

```powershell
docker compose down -v
```

## Что приложить к отчёту

Сделайте скриншоты:
1. Структура проекта в VS Code.
2. Запущенный PostgreSQL и таблицы `counters`, `job_runs`.
3. Три локальных экземпляра с разными `INSTANCE_ID`.
4. Девять ответов `/process`, показывающих Round Robin.
5. `/instances` до и после остановки экземпляра и после восстановления.
6. Результаты 30 POST и трёх GET в режиме `memory`.
7. Результаты 30 POST и трёх GET в режиме `postgres` (все значения 30).
8. Строки `job_runs` после двух минут работы и логи экземпляров.
9. `docker compose ps`, `/instances` и проверки после запуска в Docker.

К отчёту по методичке приложите исходный код проекта. Перед сдачей проверьте,
что в архиве нет виртуальных окружений `.venv` и секретных паролей от реальной БД.
