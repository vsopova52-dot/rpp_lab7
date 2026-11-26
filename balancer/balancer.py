import logging
import os
import threading
import time
from urllib.parse import urlparse

import requests
from flask import Flask, jsonify, request, Response

app = Flask(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [balancer] %(message)s"
)
logger = logging.getLogger("balancer")

# Для локального запуска используется значение по умолчанию.
# В Docker Compose оно переопределяется именами контейнеров.
raw_instances = os.getenv(
    "INSTANCES",
    "http://127.0.0.1:5001,http://127.0.0.1:5002,http://127.0.0.1:5003"
)

pool_lock = threading.Lock()
instances = []
for item in raw_instances.split(","):
    item = item.strip().rstrip("/")
    if item:
        instances.append({"url": item, "available": True})

next_index = 0
CHECK_INTERVAL = 5
HEALTH_TIMEOUT = 1


def instance_host_port(url):
    parsed = urlparse(url)
    return parsed.hostname, parsed.port


def health_check_loop():
    """Фоновая проверка всех экземпляров каждые пять секунд."""
    while True:
        with pool_lock:
            snapshot = list(instances)

        for instance in snapshot:
            try:
                response = requests.get(
                    instance["url"] + "/health",
                    timeout=HEALTH_TIMEOUT
                )
                available = response.status_code == 200
            except requests.RequestException:
                available = False

            with pool_lock:
                # Обновляем состояние только если экземпляр всё ещё есть в пуле.
                for current in instances:
                    if current["url"] == instance["url"]:
                        old_state = current["available"]
                        current["available"] = available
                        if old_state != available:
                            logger.info(
                                "%s изменил состояние: %s",
                                current["url"],
                                "доступен" if available else "недоступен"
                            )
                        break

        time.sleep(CHECK_INTERVAL)


def start_health_checker():
    thread = threading.Thread(target=health_check_loop, daemon=True)
    thread.start()


def get_next_instance():
    """Выбирает следующий доступный экземпляр по Round Robin."""
    global next_index
    with pool_lock:
        active = [item for item in instances if item["available"]]
        if not active:
            return None

        selected = active[next_index % len(active)]
        next_index = (next_index + 1) % len(active)
        return selected["url"]


@app.get("/instances")
def list_instances():
    with pool_lock:
        result = []
        for item in instances:
            host, port = instance_host_port(item["url"])
            result.append({
                "host": host,
                "port": port,
                "url": item["url"],
                "status": "доступен" if item["available"] else "недоступен",
                "available": item["available"]
            })
    return jsonify(result), 200


@app.post("/instances")
def add_instance():
    data = request.get_json(silent=True) or {}
    host = data.get("host")
    port = data.get("port")

    if not host or not port:
        return jsonify({"error": "Нужны параметры host и port"}), 400

    try:
        port = int(port)
        if not 1 <= port <= 65535:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "port должен быть числом от 1 до 65535"}), 400

    url = f"http://{host}:{port}"
    with pool_lock:
        if any(item["url"] == url for item in instances):
            return jsonify({"message": "Экземпляр уже есть в пуле", "url": url}), 200
        instances.append({"url": url, "available": False})

    return jsonify({"message": "Экземпляр добавлен; ожидается health check", "url": url}), 201


@app.delete("/instances/<path:host_port>")
def delete_instance(host_port):
    if ":" not in host_port:
        return jsonify({"error": "Формат должен быть host:port"}), 400

    host, port = host_port.rsplit(":", 1)
    url = f"http://{host}:{port}"
    with pool_lock:
        before = len(instances)
        instances[:] = [item for item in instances if item["url"] != url]
        removed = len(instances) < before

    if not removed:
        return jsonify({"error": "Экземпляр не найден", "url": url}), 404
    return jsonify({"message": "Экземпляр удалён", "url": url}), 200


def proxy_request(path=""):
    target = get_next_instance()
    if target is None:
        return jsonify({"error": "Нет доступных экземпляров сервиса"}), 503

    url = target + ("/" + path if path else "/")
    if request.query_string:
        url += "?" + request.query_string.decode("utf-8")

    excluded = {"host", "content-length", "connection"}
    headers = {
        key: value for key, value in request.headers
        if key.lower() not in excluded
    }

    try:
        upstream = requests.request(
            method=request.method,
            url=url,
            headers=headers,
            data=request.get_data(),
            cookies=request.cookies,
            allow_redirects=False,
            timeout=10
        )
        response_headers = [
            (key, value) for key, value in upstream.headers.items()
            if key.lower() not in {"content-length", "transfer-encoding", "connection"}
        ]
        return Response(
            upstream.content,
            status=upstream.status_code,
            headers=response_headers
        )
    except requests.RequestException as error:
        logger.warning("Ошибка обращения к %s: %s", url, error)
        return jsonify({"error": "Ошибка обращения к экземпляру", "instance": target}), 502


@app.route("/", defaults={"path": ""}, methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
@app.route("/<path:path>", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
def catch_all(path):
    # Служебные маршруты /instances обрабатываются отдельными функциями Flask.
    return proxy_request(path)


if __name__ == "__main__":
    start_health_checker()
    app.run(host="0.0.0.0", port=int(os.getenv("BALANCER_PORT", "8000")),
            debug=False, use_reloader=False, threaded=True)
