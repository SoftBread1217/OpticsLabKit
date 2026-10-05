"""Portable sessions contain original bytes plus explicit UI/analysis settings."""

import base64
import json

from . import __version__
from .data import MAX_FILE_BYTES, Dataset, demo_data, read_data, workflow_demo
from .plotting import figure_settings, render_figure
from .workflow import analyze_selection

SCHEMA = "opticslabkit-session/1"
MAX_SESSION_BYTES = 29 * 1024 * 1024


def save_session(datasets: dict[str, Dataset], payload: dict) -> bytes:
    selections = payload.get("datasets", [])
    if not isinstance(selections, list) or not 1 <= len(selections) <= 40:
        raise ValueError("请先导入数据再保存会话。")
    records, total, seen = [], 0, set()
    for selection in selections:
        key = selection["id"]
        if key in seen or key not in datasets:
            raise ValueError("会话包含重复或已失效的数据。")
        seen.add(key)
        dataset = datasets[key]
        total += len(dataset.raw)
        if not dataset.raw or total > MAX_FILE_BYTES:
            raise ValueError("可保存会话的原始文件合计最大 20 MB，请减少文件。")
        records.append({"key": key, "name": dataset.name,
                        "data": base64.b64encode(dataset.raw).decode("ascii"),
                        "sha256": dataset.source["sha256"], "parsing": dataset.parsing,
                        "selection": {"x": selection["x"], "ys": selection["ys"]}})
    state = {key: payload.get(key, {}) for key in ("processing", "figure", "analysis")}
    state["curves"] = payload.get("curves", [])
    session = {"schema": SCHEMA, "version": __version__, "datasets": records, "state": state,
               "notice": "Contains exact original uploaded files. Review before sharing."}
    raw = json.dumps(session, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(raw) > MAX_SESSION_BYTES:
        raise ValueError("会话超过 29 MB，请减少文件。")
    # Validate exactly the bytes that a later load will consume.
    load_session(raw)
    return raw


def load_session(raw: bytes) -> tuple[list[dict], dict]:
    if len(raw) > MAX_SESSION_BYTES:
        raise ValueError("会话最大 29 MB。")
    document = json.loads(raw)
    if not isinstance(document, dict) or document.get("schema") != SCHEMA:
        raise ValueError("不支持的会话格式，请选择 .olksession.json 文件。")
    records = document.get("datasets")
    if not isinstance(records, list) or not 1 <= len(records) <= 40:
        raise ValueError("会话需要包含 1–40 个数据文件。")
    result, datasets, total = [], {}, 0
    known_demo = [demo_data()] + [raw for kind in ("scan", "repeats")
                                 for _, raw in workflow_demo(kind)]
    for record in records:
        key = record["key"]
        if not isinstance(key, str) or key in datasets:
            raise ValueError("会话数据标识无效或重复。")
        data = base64.b64decode(record["data"], validate=True)
        total += len(data)
        if total > MAX_FILE_BYTES:
            raise ValueError("会话原始文件合计最大 20 MB。")
        dataset = read_data(record["name"], data, **record["parsing"])
        if dataset.source["sha256"] != record["sha256"]:
            raise ValueError("会话数据哈希不一致，文件可能已损坏。")
        if data in known_demo:
            dataset.source["data_kind"] = "synthetic demonstration"
        selection = record["selection"]
        if selection["x"] not in dataset.frame or not isinstance(selection["ys"], list) \
                or any(y not in dataset.frame or y == selection["x"] for y in selection["ys"]):
            raise ValueError("会话选列无效。")
        datasets[key] = dataset
        result.append({"key": key, "dataset": dataset, "selection": selection})
    state = document["state"]
    if not isinstance(state, dict):
        raise ValueError("会话参数格式无效。")
    expected = [(r["key"], r["selection"]["x"], y) for r in result
                for y in r["selection"]["ys"]]
    actual = [(c["id"], c["x"], c["y"]) for c in state.get("curves", [])]
    if sorted(expected) != sorted(actual) or len(set(actual)) != len(actual):
        raise ValueError("会话曲线与选列不一致。")
    curves, summary = analyze_selection(datasets, state)
    state["figure"] = figure_settings(state.get("figure", {}))
    state["processing"] = {key: curves[0]["settings"][key]
                           for key in ("baseline", "smoothing", "normalization")}
    state["analysis"] = {"repeats": state.get("analysis", {}).get("repeats", False),
                         "units_confirmed": state.get("analysis", {}).get("units_confirmed", False)}
    for spec, curve in zip(state["curves"], curves, strict=True):
        spec.update({key: curve[key] for key in ("style", "group", "polarization", "label")})
        spec["branch"] = curve["settings"]["branch"]
    render_figure(curves, state["figure"], "svg", summary["statistics"])
    return result, state
