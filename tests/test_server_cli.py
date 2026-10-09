import base64
import io
import json
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import pytest

from opticslabkit.data import read_data
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


def test_reparse_preserves_old_data_on_failure_then_replaces_atomically(local_server):
    raw = b"instrument,metadata\nx,y\n0,2\n1,3\n"
    with post(local_server + "/api/import", {"name": "instrument.csv",
              "data": base64.b64encode(raw).decode(), "settings": {"skip_rows": 1}}) as response:
        original = json.load(response)
    with pytest.raises(urllib.error.HTTPError):
        post(local_server + "/api/reparse", {"id": original["id"],
                                               "settings": {"skip_rows": 999}})
    payload = {"curves": [{"id": original["id"], "x": "x", "y": "y"}]}
    with post(local_server + "/api/analyze", payload) as response:
        assert json.load(response)["curves"][0]["y"] == [2, 3]
    with post(local_server + "/api/reparse", {"id": original["id"],
              "settings": {"skip_rows": 2, "header": "no"}}) as response:
        replacement = json.load(response)
    assert replacement["id"] != original["id"]
    assert replacement["parsing"]["skip_rows"] == 2
    assert replacement["columns"] == ["Column 1", "Column 2"]
    assert replacement["source"]["sha256"] == original["source"]["sha256"]
    with pytest.raises(urllib.error.HTTPError):
        post(local_server + "/api/analyze", payload)


def test_forget_frees_only_requested_in_memory_dataset(local_server):
    with post(local_server + "/api/demo", {}) as response:
        first = json.load(response)
    with post(local_server + "/api/demo", {}) as response:
        second = json.load(response)
    with post(local_server + "/api/forget", {"ids": [first["id"]]}) as response:
        assert json.load(response)["ok"]
    with pytest.raises(urllib.error.HTTPError):
        post(local_server + "/api/analyze", {"curves": [{"id": first["id"],
              "x": "Wavelength (nm)", "y": "TE (a.u.)"}]})
    with post(local_server + "/api/analyze", {"curves": [{"id": second["id"],
              "x": "Wavelength (nm)", "y": "TE (a.u.)"}]}) as response:
        assert json.load(response)["curves"][0]["stats"]["points"] == 401


def test_batch_replacement_capacity_is_atomic():
    server = LabServer(0)
    try:
        data = read_data("synthetic.csv", b"x,y\n0,1\n1,2\n")
        original = server.remember_many([data] * 39)
        before = dict(server.datasets)
        with pytest.raises(ValueError, match="40"):
            server.remember_many([data, data])
        assert server.datasets == before
        new = server.remember_many([data, data], [original[0]["id"]])
        assert len(server.datasets) == 40
        assert original[0]["id"] not in server.datasets
        assert new[0]["id"] in server.datasets
        with pytest.raises(ValueError, match="格式"):
            server.remember_many([data], "not-a-list")
        assert len(server.datasets) == 40
    finally:
        server.server_close()


@pytest.mark.skipif(shutil.which("node") is None, reason="Client integration requires Node.js")
def test_client_model_events_against_real_api(local_server):
    script = Path(__file__).with_name("frontend_workflow.cjs")
    result = subprocess.run([shutil.which("node"), str(script), local_server],
                            capture_output=True, timeout=45)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert b"session, reparse, removal OK" in result.stdout


@pytest.mark.skipif(shutil.which("node") is None, reason="Client integration requires Node.js")
def test_old_backend_is_detected_by_client(local_server):
    script = Path(__file__).with_name("frontend_workflow.cjs")
    result = subprocess.run([shutil.which("node"), str(script), local_server, "legacy-health"],
                            capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert b"restart guidance OK" in result.stdout
