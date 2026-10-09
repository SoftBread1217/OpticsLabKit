"""One processing pipeline for browser analysis, exports, and session validation."""

from .analysis import optical_summary, suggest_identity
from .plotting import curve_style, figure_settings
from .processing import process_curve, processing_settings


def analyze_selection(datasets: dict, payload: dict) -> tuple[list[dict], dict]:
    selected = payload.get("curves", [])
    if not isinstance(selected, list) or not 1 <= len(selected) <= 12:
        raise ValueError("请选择 1–12 条曲线。")
    options, result = processing_settings(payload.get("processing", {})), []
    seen = set()
    figure_settings(payload.get("figure", {}))
    for index, spec in enumerate(selected):
        if not isinstance(spec, dict):
            raise ValueError("曲线配置格式无效。")
        view = spec.get("view", "base")
        if not isinstance(view, str) or not 1 <= len(view) <= 80:
            raise ValueError("曲线视图标识无效。")
        identity = (spec.get("id"), spec.get("x"), spec.get("y"), view)
        if identity in seen:
            raise ValueError("曲线视图重复，请使用不同的视图标识。")
        seen.add(identity)
        dataset = datasets.get(spec.get("id"))
        if dataset is None:
            raise ValueError("数据会话已失效，请重新导入。")
        label = spec.get("label", "")
        group = spec.get("group", "")
        if not isinstance(label, str) or len(label) > 200 or not isinstance(group, str) \
                or len(group) > 100:
            raise ValueError("曲线名称最长 200 字符，分组名称最长 100 字符。")
        polarization = spec.get("polarization", suggest_identity(spec.get("y", ""))[
            "polarization"])
        if polarization not in {"TE", "TM", "unknown"}:
            raise ValueError("偏振标记无效。")
        overrides = spec.get("processing")
        effective = processing_settings({**options, **overrides}) if isinstance(overrides, dict) \
            else options
        if overrides is not None and not isinstance(overrides, dict):
            raise ValueError("独立处理参数必须是对象，或为空以跟随共享设置。")
        curve = process_curve(dataset, spec.get("x", ""), spec.get("y", ""), label=label,
                              **effective,
                              branch=spec.get("branch", "all"))
        curve.update(style=curve_style(spec.get("style", {}), index), group=group.strip(),
                     polarization=polarization, view=view,
                     processing_scope="independent" if overrides is not None else "shared")
        result.append(curve)
    analysis_options = payload.get("analysis", {})
    for value in analysis_options.values():
        if not isinstance(value, bool):
            raise ValueError("分析开关设置无效。")
    summary = optical_summary(result, repeats=analysis_options.get("repeats", False),
                              units_confirmed=analysis_options.get("units_confirmed", False))
    return result, summary
