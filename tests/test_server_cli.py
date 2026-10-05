import base64
import io
import json
import subprocess
import sys
import threading
import urllib.error
import urllib.request
import zipfile

import pytest

from opticslabkit.server import LabServer


@pytest.fixture
def local_server():
    server = LabServer(0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def post(url, body, origin=None):
    headers = {"Content-Type": "application/json"}
    if origin:
        headers["Origin"] = origin
    request = urllib.request.Request(url, json.dumps(body).encode(), headers=headers)
    return urllib.request.urlopen(request, timeout=20)


def test_import_analyze_and_download(local_server):
    with post(local_server + "/api/import", {
        "name": "experiment.csv", "data": base64.b64encode(b"x,y\n1,2\n2,4\n").decode(),
    }) as response:
        dataset = json.load(response)
    payload = {"curves": [{"id": dataset["id"], "x": "x", "y": "y"}],
               "processing": {"normalization": "minmax"}, "figure": {"show_raw": False}}
    with post(local_server + "/api/analyze", payload) as response:
        result = json.load(response)
    assert result["curves"][0]["y"] == [0, 1]
    with post(local_server + "/api/export", payload) as response:
        assert response.headers["Content-Type"] == "application/zip"
        with zipfile.ZipFile(io.BytesIO(response.read())) as archive:
            assert "manifest.json" in archive.namelist()
    with urllib.request.urlopen(local_server + "/") as response:
        assert "光学数据工作台" in response.read().decode()
    with post(local_server + "/api/prepare-export", payload) as response:
        download = json.load(response)["download_url"]
    with urllib.request.urlopen(local_server + download) as response:
        assert 'attachment; filename="opticslabkit-results.zip"' in (
            response.headers["Content-Disposition"]
        )
        with zipfile.ZipFile(io.BytesIO(response.read())) as archive:
            assert "figure.svg" in archive.namelist()


def test_invalid_numeric_preview_still_imports(local_server):
    raw = b"x,y\n0,inf\n1,2\n2,4\n"
    with post(local_server + "/api/import", {
        "name": "experiment.csv", "data": base64.b64encode(raw).decode(),
    }) as response:
        dataset = json.load(response)
    assert dataset["preview"][0] == [0, None]


def test_cross_origin_requests_rejected(local_server):
    with pytest.raises(urllib.error.HTTPError) as error:
        post(local_server + "/api/demo", {}, origin="https://example.com")
    assert error.value.code == 403


def test_expired_session_is_clear_error(local_server):
    with pytest.raises(urllib.error.HTTPError) as error:
        post(local_server + "/api/analyze", {"curves": [{"id": "missing", "x": "x", "y": "y"}]})
    assert error.value.code == 400
    assert "会话已失效" in json.load(error.value)["error"]


def test_cli_export_preserves_existing_file(tmp_path):
    target = tmp_path / "results.zip"
    target.write_bytes(b"keep me")
    result = subprocess.run([sys.executable, "-m", "opticslabkit", "demo", "--output",
                             str(target)], capture_output=True)
    assert result.returncode == 2
    assert target.read_bytes() == b"keep me"


def test_preview_is_exact_export_svg_and_restore_session_on_fresh_server(local_server):
    with post(local_server + "/api/demo", {}) as response:
        data = json.load(response)
    payload = {"datasets": [{"id": data["id"], "x": "Wavelength (nm)", "ys": ["TE (a.u.)"]}],
               "curves": [{"id": data["id"], "x": "Wavelength (nm)", "y": "TE (a.u.)",
                           "label": "TE", "group": "A", "polarization": "TE",
                           "style": {"color": "#123456", "line": "--", "marker": "o"}}],
               "processing": {"smoothing": 3},
               "figure": {"width_mm": 85, "height_mm": 65, "show_raw": False},
               "analysis": {"repeats": False, "units_confirmed": True}}
    with post(local_server + "/api/analyze", payload) as response:
        result = json.load(response)
    with urllib.request.urlopen(local_server + result["preview_url"]) as response:
        svg = response.read()
        assert response.headers["Content-Type"] == "image/svg+xml"
    with post(local_server + "/api/export", payload) as response:
        with zipfile.ZipFile(io.BytesIO(response.read())) as archive:
            assert archive.read("figure.svg") == svg
    with post(local_server + "/api/session/save", payload) as response:
        url = json.load(response)["download_url"]
    with urllib.request.urlopen(local_server + url) as response:
        saved = json.load(response)
        assert "comparison.olksession.json" in response.headers["Content-Disposition"]
    # The old dataset IDs have no meaning in this new server; restoring remaps them.
    fresh = LabServer(0)
    thread = threading.Thread(target=fresh.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{fresh.server_port}"
    try:
        with post(endpoint + "/api/session/load", saved) as response:
            restored = json.load(response)
        assert restored["datasets"][0]["id"] != data["id"]
        assert restored["datasets"][0]["source"]["data_kind"] == "synthetic demonstration"
        with post(endpoint + "/api/analyze", restored["state"]) as response:
            restored_result = json.load(response)
        assert restored_result["curves"][0]["y"] == result["curves"][0]["y"]
        with urllib.request.urlopen(endpoint + restored_result["preview_url"]) as response:
            assert response.read() == svg
        saved["datasets"][0]["sha256"] = "corrupt"
        before = set(fresh.datasets)
        with pytest.raises(urllib.error.HTTPError):
            post(endpoint + "/api/session/load", saved)
        assert set(fresh.datasets) == before
    finally:
        fresh.shutdown()
        fresh.server_close()
        thread.join(timeout=2)


def test_browser_repeat_demo_has_stats_and_exported_sd(local_server):
    with post(local_server + "/api/demo-repeats", {}) as response:
        datasets = json.load(response)["datasets"]
    payload = {"curves": [{"id": data["id"], "x": "Wavelength (nm)", "y": "TE (a.u.)",
                           "group": "demo", "polarization": "TE", "label": f"run {i}"}
                          for i, data in enumerate(datasets)],
               "analysis": {"repeats": True, "units_confirmed": True},
               "figure": {"show_raw": False}}
    with post(local_server + "/api/analyze", payload) as response:
        summary = json.load(response)["analysis"]
    assert summary["statistics"][0]["n"] == 3
    assert summary["statistics"][0]["interpolated"] is True
    with post(local_server + "/api/export", payload) as response:
        with zipfile.ZipFile(io.BytesIO(response.read())) as archive:
            assert "repeat_01.csv" in archive.namelist()
