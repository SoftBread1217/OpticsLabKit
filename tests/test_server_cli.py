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
