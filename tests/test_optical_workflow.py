import copy
import io
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

import numpy as np
import pandas as pd
import pytest

from opticslabkit.analysis import optical_summary, suggest_identity
from opticslabkit.data import read_data
from opticslabkit.export import export_bundle
from opticslabkit.plotting import figure_settings, render_figure
from opticslabkit.processing import process_curve, scan_branches
from opticslabkit.session import load_session, save_session
from opticslabkit.workflow import analyze_selection


def curve(raw, name="run.csv", pol="TE", group="same condition", branch="all"):
    result = process_curve(read_data(name, raw), "x", "y", branch=branch, label=name)
    result.update(polarization=pol, group=group)
    return result


def runs():
    return [curve(b"x,y\n0,0\n1,2\n2,4\n3,6\n", "run1.csv"),
            curve(b"x,y\n0.5,2\n1.5,4\n2.5,6\n", "run2.csv")]


def test_turning_point_shared_and_source_order_retained():
    data = read_data("loop.csv", b"x,y\n0,0\n1,2\n2,4\n2,5\n1,3\n0,1\n")
    up = process_curve(data, "x", "y", branch="0")
    down = process_curve(data, "x", "y", branch="1")
    assert up["x"] == [0, 1, 2, 2]
    assert down["x"] == [2, 1, 0]
    assert up["source_rows"][-1] == down["source_rows"][0] == 4
    assert down["y"] == [5, 3, 1]
    assert [b["direction"] for b in up["branches"]] == ["up", "down"]
    assert scan_branches(np.array([0, 1, 0, 1, 0]))[-1]["start"] == 3
    assert scan_branches(np.array([1, 1, 1]))[0]["direction"] == "constant"


def test_branch_selected_before_processing():
    data = read_data("loop.csv", b"x,y\n0,10\n1,13\n2,10\n1,3\n0,1\n")
    with pytest.raises(ValueError, match="单个分支"):
        process_curve(data, "x", "y", smoothing=3)
    result = process_curve(data, "x", "y", branch="0", smoothing=3, baseline="minimum")
    assert result["raw_y"] == [10, 13, 10]
    assert result["y"] == [1, 1, 1]
    with pytest.raises(ValueError, match="分支已失效"):
        process_curve(data, "x", "y", branch="99")


@pytest.mark.parametrize("name,expected", [("TE (a.u.)", "TE"), ("2000nm_TM.txt", "TM"),
                                           ("temperature", "unknown"), ("TE_TM", "unknown")])
def test_polarization_hints_are_tokens_not_substrings(name, expected):
    assert suggest_identity(name)["polarization"] == expected


def test_pair_inventory_never_claims_ambiguous_pair():
    curves = runs()
    curves[1]["polarization"] = "TM"
    assert optical_summary(curves)["pairs"][0]["status"] == "paired"
    assert optical_summary(curves + [curves[0]])["pairs"][0]["status"] == "check"


def test_repeat_mean_sample_sd_overlap_no_extrapolation():
    result = optical_summary(runs(), repeats=True, units_confirmed=True)
    summary = result["statistics"][0]
    assert summary["x"] == [1, 2]
    assert summary["n"] == 2
    assert summary["interpolated"] is True
    np.testing.assert_allclose(summary["y"], [2.5, 4.5])
    np.testing.assert_allclose(summary["sd"], [np.sqrt(.5), np.sqrt(.5)])
    assert "not SEM" in summary["method"]
    assert not optical_summary(runs(), repeats=True)["statistics"]


@pytest.mark.parametrize("second,match", [
    (b"x,y\n0,0\n1,2\n2,4\n3,6\n", "同一数据"),
    (b"x,y\n0,1\n1,2\n1,3\n2,4\n", "无重复 X"),
    (b"x,y\n2,4\n1,3\n0,1\n", "同方向"),
    (b"x,y\n0,1\n1,2\n0,3\n", "单调分支"),
    (b"x,y\n5,2\n6,3\n", "共同区间"),
])
def test_unsafe_repeat_groups_are_reported_not_averaged(second, match):
    curves = [runs()[0], curve(second, "run2.csv")]
    result = optical_summary(curves, repeats=True, units_confirmed=True)
    assert not result["statistics"]
    assert match in result["warnings"][0]


def test_decreasing_repeats_use_common_grid_without_mutating_input():
    curves = [curve(b"x,y\n2,4\n1,2\n0,0\n", "first.csv"),
              curve(b"x,y\n2,6\n1,4\n0,2\n", "second.csv")]
    before = copy.deepcopy(curves)
    summary = optical_summary(curves, repeats=True, units_confirmed=True)["statistics"][0]
    assert summary["direction"] == "down"
    assert summary["x"] == [0, 1, 2]
    assert summary["y"] == [1, 3, 5]
    assert curves == before


def session_fixture():
    data = read_data("试验.txt", "仪器元数据\nx;y\n0,5;2,5\n1,5;3,5\n".encode("utf-16"),
                     skip_rows=1, decimal=",")
    payload = {"datasets": [{"id": "original", "x": "x", "ys": ["y"]}],
               "curves": [{"id": "original", "x": "x", "y": "y", "label": "实验 A",
                           "group": "condition 1", "polarization": "TE", "branch": "0",
                           "style": {"color": "#123456", "line": "--", "marker": "o"}}],
               "processing": {"normalization": "minmax", "baseline": "minimum", "smoothing": 1},
               "figure": {"width_mm": 85, "height_mm": 65, "show_raw": False,
                          "x_limits": [0, 2], "title": "Transmission"},
               "analysis": {"repeats": False, "units_confirmed": False}}
    return data, payload


def test_session_roundtrip_original_bytes_parsing_and_all_controls():
    data, payload = session_fixture()
    raw = save_session({"original": data}, payload)
    records, state = load_session(raw)
    restored = records[0]["dataset"]
    assert restored.raw == data.raw
    assert restored.source == data.source
    assert restored.parsing == data.parsing
    assert restored.frame.equals(data.frame)
    assert state["curves"] == payload["curves"]
    assert state["processing"] == payload["processing"]
    assert state["figure"]["width_mm"] == 85
    assert state["figure"]["x_limits"] == [0, 2]
    assert state["analysis"] == payload["analysis"]
    assert "original uploaded files" in json.loads(raw)["notice"]


@pytest.mark.parametrize("mutation,match", [
    (lambda s: s.update(schema="unknown"), "会话格式"),
    (lambda s: s["datasets"][0].update(sha256="wrong"), "哈希"),
    (lambda s: s["state"]["curves"][0].update(y="missing"), "不一致"),
    (lambda s: s["state"]["figure"].update(width_mm=float("inf")), "width_mm"),
])
def test_session_rejects_corruption_and_invalid_state(mutation, match):
    data, payload = session_fixture()
    document = json.loads(save_session({"original": data}, payload))
    mutation(document)
    with pytest.raises(ValueError, match=match):
        load_session(json.dumps(document).encode())


@pytest.mark.parametrize("settings", [{"width_mm": 0}, {"x_limits": [2, 1]},
                                      {"y_limits": [0, 1], "y_scale": "log"},
                                      {"line_width": "nan"}, {"font": "unknown"},
                                      {"legend": "unknown"}, {"grid": "yes"}])
def test_invalid_figure_settings_rejected(settings):
    with pytest.raises(ValueError):
        figure_settings(settings)


def test_svg_has_editable_text_physical_dimensions_custom_style_and_pdf():
    c = runs()[0]
    c["style"] = {"color": "#123456", "line": "--", "marker": "o"}
    settings = {"width_mm": 85, "height_mm": 65, "show_raw": False, "title": "TE study"}
    raw = render_figure([c], settings, "svg")
    svg = ET.fromstring(raw)
    assert float(svg.attrib["width"].removesuffix("pt")) == pytest.approx(85 / 25.4 * 72)
    assert float(svg.attrib["height"].removesuffix("pt")) == pytest.approx(65 / 25.4 * 72)
    assert "TE study" in " ".join(svg.itertext())
    assert svg.findall(".//{http://www.w3.org/2000/svg}text")
    assert b"#123456" in raw and b"stroke-dasharray" in raw
    assert render_figure([c], settings, "pdf").startswith(b"%PDF")
    with pytest.raises(ValueError, match="零/负数"):
        render_figure([c], {"x_scale": "log"}, "svg")


def test_origin_independent_xy_grids_and_standalone_redraw(tmp_path):
    curves = runs()
    statistics = optical_summary(curves, repeats=True, units_confirmed=True)
    bundle = export_bundle(curves, {"show_raw": False, "width_mm": 85,
                                   "height_mm": 65}, statistics)
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        frame = pd.read_csv(io.BytesIO(archive.read("origin_xy.csv")))
        assert list(frame.columns) == ["X_01", "Y_01", "X_02", "Y_02"]
        assert frame.X_02.iloc[:3].tolist() == [.5, 1.5, 2.5]
        assert pd.isna(frame.X_02.iloc[3])
        assert "repeat_01.csv" in archive.namelist()
        archive.extractall(tmp_path)  # Only our own fixed-name generated bundle.
    result = subprocess.run([sys.executable, str(tmp_path / "redraw.py")], cwd=tmp_path,
                            capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert (tmp_path / "redrawn.svg").read_bytes() == (tmp_path / "figure.svg").read_bytes()
    assert (tmp_path / "redrawn.pdf").read_bytes().startswith(b"%PDF")
    before = (tmp_path / "redrawn.svg").read_bytes()
    result = subprocess.run([sys.executable, str(tmp_path / "redraw.py")], cwd=tmp_path,
                            capture_output=True, timeout=30)
    assert result.returncode != 0
    assert (tmp_path / "redrawn.svg").read_bytes() == before


def test_pipeline_preserves_metadata():
    data, payload = session_fixture()
    curves, summary = analyze_selection({"original": data}, payload)
    assert curves[0]["group"] == "condition 1"
    assert curves[0]["style"]["color"] == "#123456"
    assert summary["pairs"][0]["te"] == [0]
