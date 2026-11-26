import logging
import os
import threading
import time
from datetime import datetime, timezone

from flask import Flask, jsonify
from db import get_connection, increment_visits_db, get_visits_db, run_periodic_job

app = Flask(__name__)

INSTANCE_ID = os.getenv("INSTANCE_ID", "local-1")
PORT = int(os.getenv("PORT", "5001"))
COUNTER_MODE = os.getenv("COUNTER_MODE", "memory").lower()
ENABLE_JOBS = os.getenv("ENABLE_JOBS", "false").lower() == "true"
JOB_INTERVAL = 10
JOB_LOCK_KEY = 7001

logging.basicConfig(
    level=logging.INFO,
    format=f"%(asctime)s [%(levelname)s] [%(name)s] [instance={INSTANCE_ID}] %(message)s"
)
logger = logging.getLogger("service")

# Этот счётчик существует только в памяти конкретного процесса.
memory_visits = 0
memory_lock = threading.Lock()


@app.get("/health")
def health():
    return jsonify({
        "status": "ok",
        "instance_id": INSTANCE_ID
    }), 200


@app.get("/process")
def process():
    return jsonify({
        "message": "Запрос обработан",
        "instance_id": INSTANCE_ID
    }), 200


@app.post("/visits")
def add_visit():
    global memory_visits

    if COUNTER_MODE == "postgres":
        try:
            value = increment_visits_db()
            return jsonify({
                "message": "Посещение учтено",
                "visits": value,
                "instance_id": INSTANCE_ID,
                "storage": "postgresql"
            }), 200
        except Exception:
            logger.exception("Не удалось увеличить счётчик в PostgreSQL")
            return jsonify({"error": "Ошибка базы данных"}), 500

    with memory_lock:
        memory_visits += 1
        value = memory_visits

    return jsonify({
        "message": "Посещение учтено",
        "visits": value,
        "instance_id": INSTANCE_ID,
        "storage": "memory"
    }), 200


@app.get("/visits")
def get_visits():
    if COUNTER_MODE == "postgres":
        try:
            value = get_visits_db()
            return jsonify({
                "visits": value,
                "instance_id": INSTANCE_ID,
                "storage": "postgresql"
            }), 200
        except Exception:
            logger.exception("Не удалось прочитать счётчик из PostgreSQL")
            return jsonify({"error": "Ошибка базы данных"}), 500

    with memory_lock:
        value = memory_visits

    return jsonify({
        "visits": value,
        "instance_id": INSTANCE_ID,
        "storage": "memory"
    }), 200


def periodic_job_loop():
    """Каждый экземпляр пытается выполнить общую задачу раз в 10 секунд."""
    logger.info("Фоновая периодическая задача запущена; интервал=%s сек.", JOB_INTERVAL)

    # Первая попытка выполняется сразу, далее — каждые 10 секунд.
    while True:
        try:
            slot = int(time.time()) // JOB_INTERVAL * JOB_INTERVAL
            executed = run_periodic_job(
                instance_id=INSTANCE_ID,
                slot=slot,
                lock_key=JOB_LOCK_KEY
            )
            if executed:
                logger.info("Задача выполнена для интервала slot=%s", slot)
            else:
                logger.info("Запуск пропущен: задача уже выполняется/выполнена; slot=%s", slot)
        except Exception:
            logger.exception("Ошибка фоновой периодической задачи")

        time.sleep(JOB_INTERVAL)


if __name__ == "__main__":
    if ENABLE_JOBS:
        # daemon=True: поток завершится вместе с процессом приложения.
        threading.Thread(target=periodic_job_loop, daemon=True).start()

    logger.info(
        "Запуск экземпляра: id=%s, port=%s, counter_mode=%s, jobs=%s",
        INSTANCE_ID, PORT, COUNTER_MODE, ENABLE_JOBS
    )
    app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False, threaded=True)
