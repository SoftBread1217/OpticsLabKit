"""A loopback-only application with in-memory uploads and browser downloads."""

import base64
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from urllib.parse import urlparse

from . import __version__
from .data import Dataset, demo_data, read_data, workflow_demo
from .export import export_bundle
from .plotting import render_figure
from .session import load_session, save_session
from .workflow import analyze_selection

MAX_REQUEST_BYTES = 30 * 1024 * 1024


class LabServer(ThreadingHTTPServer):
    def __init__(self, port: int):
        super().__init__(("127.0.0.1", port), Handler)
        self.datasets: dict[str, Dataset] = {}
        self.exports: dict[str, tuple] = {}
        self.previews: dict[str, bytes] = {}
        self.store_lock = threading.Lock()

    def remember(self, dataset: Dataset) -> dict:
        return self.remember_many([dataset])[0]

    def remember_many(self, datasets: list[Dataset], replace_ids: list | None = None) -> list[dict]:
        replace_ids = replace_ids or []
        if not isinstance(replace_ids, list) or len(replace_ids) > 40 \
                or any(not isinstance(key, str) for key in replace_ids):
            raise ValueError("待替换的数据标识格式无效。")
        records = [{"id": secrets.token_urlsafe(16), **data.describe()} for data in datasets]
        with self.store_lock:
            removing = set(replace_ids) & self.datasets.keys()
            if len(self.datasets) - len(removing) + len(datasets) > 40:
                raise ValueError("当前最多保留 40 个文件，请移除不用的数据后再导入。")
            # Descriptions/parsing/capacity have all passed before old memory is released.
            for key in removing:
                del self.datasets[key]
            for record, data in zip(records, datasets, strict=True):
                self.datasets[record["id"]] = data
        return records

    def download(self, body: bytes, filename: str, content_type: str) -> str:
        key = secrets.token_urlsafe(24)
        with self.store_lock:
            if len(self.exports) >= 5:
                self.exports.pop(next(iter(self.exports)))
            self.exports[key] = (body, filename, content_type)
        return f"/api/download/{key}"


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
            self._json({"ok": True, "app": "OpticsLabKit", "version": __version__})
        elif path.startswith("/api/preview/"):
            with self.server.store_lock:
                body = self.server.previews.get(path.removeprefix("/api/preview/"))
            if body is None:
                self._json({"error": "预览已过期，请更新曲线。"}, 404)
            else:
                self._send(body, "image/svg+xml")
        elif path.startswith("/api/download/"):
            key = path.removeprefix("/api/download/")
            with self.server.store_lock:
                bundle = self.server.exports.get(key)
            if bundle is None:
                self._json({"error": "下载已过期，请重新导出。"}, 404)
            else:
                body, filename, content_type = bundle
                self._send(body, content_type, filename=filename)
        else:
            self._json({"error": "页面不存在。"}, 404)

    def _curves(self, payload: dict) -> list[dict]:
        return analyze_selection(self.server.datasets, payload)[0]

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
                self._json(self.server.remember_many([dataset], payload.get("replace_ids"))[0])
            elif path in {"/api/demo-repeats", "/api/demo-scan"}:
                datasets = []
                for name, raw in workflow_demo(path.removeprefix("/api/demo-")):
                    dataset = read_data(name, raw)
                    dataset.source["data_kind"] = "synthetic demonstration"
                    datasets.append(dataset)
                self._json({"datasets": self.server.remember_many(
                    datasets, payload.get("replace_ids"))})
            elif path in {"/api/sheet", "/api/reparse"}:
                original = self.server.datasets.get(payload.get("id"))
                if original is None:
                    raise ValueError("数据会话已失效，请重新导入。")
                options = {"sheet": payload.get("sheet")} if path == "/api/sheet" \
                    else payload.get("settings", {})
                if not isinstance(options, dict):
                    raise ValueError("读取设置格式无效。")
                dataset = read_data(original.name, original.raw, **{**original.parsing, **options})
                if "data_kind" in original.source:
                    dataset.source["data_kind"] = original.source["data_kind"]
                self._json(self.server.remember_many([dataset], [payload.get("id")])[0])
            elif path == "/api/forget":
                ids = payload.get("ids")
                if not isinstance(ids, list) or len(ids) > 40 \
                        or any(not isinstance(key, str) for key in ids):
                    raise ValueError("待移除的数据标识格式无效。")
                with self.server.store_lock:
                    for key in ids:
                        self.server.datasets.pop(key, None)
                self._json({"ok": True})
            elif path == "/api/analyze":
                curves, summary = analyze_selection(self.server.datasets, payload)
                body = render_figure(curves, payload.get("figure", {}), "svg",
                                     summary["statistics"])
                key = secrets.token_urlsafe(24)
                with self.server.store_lock:
                    if len(self.server.previews) >= 5:
                        self.server.previews.pop(next(iter(self.server.previews)))
                    self.server.previews[key] = body
                self._json({"curves": curves, "analysis": summary,
                            "preview_url": f"/api/preview/{key}"})
            elif path == "/api/branches":
                # Discovery must work even when current smoothing/figure settings are invalid.
                selected = payload.get("curves", [])
                if not isinstance(selected, list) or not 1 <= len(selected) <= 12:
                    raise ValueError("请选择 1–12 条曲线。")
                raw_curves = self._curves({"curves": [
                    {key: spec[key] for key in ("id", "x", "y", "view") if key in spec}
                    for spec in selected]})
                self._json({"branches": [curve["branches"] for curve in raw_curves]})
            elif path == "/api/export":
                curves, summary = analyze_selection(self.server.datasets, payload)
                body = export_bundle(curves, payload.get("figure", {}), summary)
                self._send(body, "application/zip", filename="opticslabkit-results.zip")
            elif path == "/api/prepare-export":
                curves, summary = analyze_selection(self.server.datasets, payload)
                body = export_bundle(curves, payload.get("figure", {}), summary)
                self._json({"download_url": self.server.download(
                    body, "opticslabkit-results.zip", "application/zip")})
            elif path == "/api/session/save":
                body = save_session(self.server.datasets, payload)
                self._json({"download_url": self.server.download(
                    body, "comparison.olksession.json", "application/json; charset=utf-8")})
            elif path == "/api/session/load":
                # Validate everything before changing server state. No scripts are executed.
                # Transport-only replace_ids is not part of the portable session document.
                records, state = load_session(json.dumps(payload).encode("utf-8"))
                restored, remap = [], {}
                descriptions = self.server.remember_many(
                    [r["dataset"] for r in records], payload.get("replace_ids"))
                for record, description in zip(records, descriptions, strict=True):
                    remap[record["key"]] = description["id"]
                    restored.append({**description, **record["selection"]})
                for curve in state["curves"]:
                    curve["id"] = remap[curve["id"]]
                self._json({"datasets": restored, "state": state})
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
