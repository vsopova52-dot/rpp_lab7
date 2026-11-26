import os
import psycopg2
from psycopg2.extras import RealDictCursor


def get_connection():
    """Создаёт новое соединение с PostgreSQL."""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "scaling_db"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "postgres"),
        connect_timeout=3
    )


def increment_visits_db():
    """Увеличивает общий счётчик одним SQL UPDATE и возвращает новое значение."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE counters SET value = value + 1 "
                "WHERE name = 'visits' RETURNING value"
            )
            row = cur.fetchone()
            if row is None:
                raise RuntimeError("Строка visits отсутствует в таблице counters")
            return row[0]


def get_visits_db():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT value FROM counters WHERE name = 'visits'")
            row = cur.fetchone()
            if row is None:
                raise RuntimeError("Строка visits отсутствует в таблице counters")
            return row[0]


def run_periodic_job(instance_id, slot, lock_key):
    """
    В одной транзакции получает advisory lock, проверяет slot и записывает
    факт выполнения. Возвращает True только экземпляру, который записал задачу.
    """
    conn = get_connection()
    try:
        conn.autocommit = False
        with conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_xact_lock(%s)", (lock_key,))
            lock_acquired = cur.fetchone()[0]

            if not lock_acquired:
                conn.rollback()
                return False

            cur.execute("SELECT 1 FROM job_runs WHERE slot = %s", (slot,))
            already_done = cur.fetchone() is not None

            if already_done:
                conn.commit()
                return False

            # Здесь располагается сама периодическая работа.
            # Для лабораторной фиксируем её выполнение записью в job_runs.
            cur.execute(
                """
                INSERT INTO job_runs (slot, instance_id, started_at)
                VALUES (%s, %s, %s)
                """,
                (slot, instance_id, __import__("datetime").datetime.now(__import__("datetime").timezone.utc))
            )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
