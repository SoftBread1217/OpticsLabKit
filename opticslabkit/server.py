"""A loopback-only application with in-memory uploads and browser downloads."""

import base64
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from urllib.parse import urlparse

from .data import Dataset, demo_data, read_data
from .export import export_bundle
from .processing import process_curve

MAX_REQUEST_BYTES = 30 * 1024 * 1024


class LabServer(ThreadingHTTPServer):
    def __init__(self, port: int):
        super().__init__(("127.0.0.1", port), Handler)
        self.datasets: dict[str, Dataset] = {}
        self.exports: dict[str, bytes] = {}
        self.store_lock = threading.Lock()

    def remember(self, dataset: Dataset) -> dict:
        with self.store_lock:
            if len(self.datasets) >= 40:
                raise ValueError("本次会话已导入 40 个文件，请重启服务清空会话。")
            key = secrets.token_urlsafe(16)
            self.datasets[key] = dataset
        return {"id": key, **dataset.describe()}


class Handler(BaseHTTPRequestHandler):
    server: LabServer

    def _send(self, body: bytes, content_type: str, status: int = 200,
              filename: str | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; "
                         "script-src 'self'; style-src 'self'; img-src 'self' blob:; "
                         "connect-src 'self'; object-src 'none'; frame-ancestors 'none'")
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(body)

    def _json(self, value: dict, status: int = 200) -> None:
        self._send(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"),
                   "application/json; charset=utf-8", status)

    def _same_origin(self) -> bool:
        host = self.headers.get("Host", "")
        expected = f"127.0.0.1:{self.server.server_port}"
        if host not in {expected, f"localhost:{self.server.server_port}"}:
            return False
        origin = self.headers.get("Origin")
        return origin is None or origin in {f"http://{expected}",
                                            f"http://localhost:{self.server.server_port}"}

    def do_GET(self) -> None:  # noqa: N802
        if not self._same_origin():
            self._json({"error": "请通过本地地址访问。"}, 403)
            return
        path = urlparse(self.path).path
        resources = {"/": ("index.html", "text/html; charset=utf-8"),
                     "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                     "/style.css": ("style.css", "text/css; charset=utf-8")}
        if path in resources:
            name, content_type = resources[path]
            self._send(files("opticslabkit").joinpath("static", name).read_bytes(), content_type)
        elif path == "/api/template":
            self._send(demo_data(), "text/csv; charset=utf-8", filename="synthetic_TE_TM.csv")
        elif path == "/api/health":
            self._json({"ok": True, "app": "OpticsLabKit"})
        elif path.startswith("/api/download/"):
            key = path.removeprefix("/api/download/")
            with self.server.store_lock:
                bundle = self.server.exports.get(key)
            if bundle is None:
                self._json({"error": "下载已过期，请重新导出。"}, 404)
            else:
                self._send(bundle, "application/zip", filename="opticslabkit-results.zip")
        else:
            self._json({"error": "页面不存在。"}, 404)

    def _curves(self, payload: dict) -> list[dict]:
        selected = payload.get("curves", [])
        if not isinstance(selected, list) or not 1 <= len(selected) <= 12:
            raise ValueError("请选择 1–12 条曲线。")
        options = payload.get("processing", {})
        result = []
        for spec in selected:
            dataset = self.server.datasets.get(spec.get("id"))
            if dataset is None:
                raise ValueError("数据会话已失效，请重新导入。")
            result.append(process_curve(
                dataset, spec.get("x", ""), spec.get("y", ""), label=spec.get("label", ""),
                normalization=options.get("normalization", "none"),
                baseline=options.get("baseline", "none"), smoothing=options.get("smoothing", 1),
            ))
        return result

    def do_POST(self) -> None:  # noqa: N802
        if not self._same_origin():
            self._json({"error": "仅允许本地页面发起操作。"}, 403)
            return
        if not self.headers.get("Content-Type", "").startswith("application/json"):
            self._json({"error": "需要 JSON 请求。"}, 415)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_REQUEST_BYTES:
                raise ValueError("请求为空或超过 30 MB。")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("请求格式无效。")
            path = urlparse(self.path).path
            if path == "/api/import":
                raw = base64.b64decode(payload.get("data", ""), validate=True)
                dataset = read_data(payload.get("name", ""), raw,
                                    **payload.get("settings", {}))
                self._json(self.server.remember(dataset))
            elif path == "/api/demo":
                dataset = read_data("synthetic_TE_TM.csv", demo_data())
                dataset.source["data_kind"] = "synthetic demonstration"
                self._json(self.server.remember(dataset))
            elif path == "/api/analyze":
                self._json({"curves": self._curves(payload)})
            elif path == "/api/export":
                body = export_bundle(self._curves(payload), payload.get("figure", {}))
                self._send(body, "application/zip", filename="opticslabkit-results.zip")
            elif path == "/api/prepare-export":
                body = export_bundle(self._curves(payload), payload.get("figure", {}))
                key = secrets.token_urlsafe(24)
                with self.server.store_lock:
                    if len(self.server.exports) >= 5:
                        self.server.exports.pop(next(iter(self.server.exports)))
                    self.server.exports[key] = body
                self._json({"download_url": f"/api/download/{key}"})
            else:
                self._json({"error": "接口不存在。"}, 404)
        except (ValueError, KeyError, TypeError, OverflowError) as error:
            self._json({"error": str(error)}, 400)
        except Exception:
            # No uploaded values or local paths are sent to logs or error pages.
            self._json({"error": "文件解析失败，请检查工作表、分隔符和表头设置。"}, 400)

    def log_message(self, format: str, *args: object) -> None:
        pass


def serve(port: int = 8766) -> None:
    server = LabServer(port)
    print(f"OpticsLabKit: http://127.0.0.1:{server.server_port}", flush=True)
    print("文件保留在本机内存中。按 Ctrl+C 停止。", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
