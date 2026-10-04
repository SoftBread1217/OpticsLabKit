"""Explicit signal processing in acquisition order."""

import numpy as np
import pandas as pd

from .data import Dataset


def process_curve(dataset: Dataset, x_column: str, y_column: str, *,
                  label: str = "", normalization: str = "none", baseline: str = "none",
                  smoothing: int = 1) -> dict:
    if x_column not in dataset.frame or y_column not in dataset.frame:
        raise ValueError("请选择有效的 X/Y 数据列。")
    if x_column == y_column:
        raise ValueError("X 和 Y 需要选择不同的数据列。")
    if normalization not in {"none", "minmax", "maxabs"}:
        raise ValueError("归一化设置无效。")
    if baseline not in {"none", "minimum", "edge_linear"}:
        raise ValueError("基线设置无效。")
    if not isinstance(smoothing, int) or smoothing < 1 or smoothing % 2 != 1:
        raise ValueError("平滑窗口必须是正奇数；1 表示不平滑。")
    x_all = pd.to_numeric(dataset.frame[x_column], errors="coerce").to_numpy(dtype=float)
    y_all = pd.to_numeric(dataset.frame[y_column], errors="coerce").to_numpy(dtype=float)
    valid = np.isfinite(x_all) & np.isfinite(y_all)
    rows = np.flatnonzero(valid)
    x, raw_y = x_all[valid], y_all[valid]
    if len(x) < 2:
        raise ValueError("所选数据列至少需要两个有效数值点。")
    if smoothing > len(x):
        raise ValueError("平滑窗口不能超过有效数据点数。")
    warnings = []
    dropped = int((~valid).sum())
    if dropped:
        warnings.append(f"已排除 {dropped} 行非数值、空值或无穷值；原文件未修改。")
    if len(np.unique(x)) != len(x):
        warnings.append("X 存在重复值，已保留原扫描顺序和所有有效点。")
    delta = np.diff(x)
    if not (np.all(delta >= 0) or np.all(delta <= 0)):
        warnings.append("X 非单调，按采集顺序连线；适用于往返扫描。")
    y = raw_y.copy()
    baseline_values = np.zeros_like(y)
    if baseline == "minimum":
        baseline_values[:] = np.min(y)
    elif baseline == "edge_linear":
        if x[-1] == x[0]:
            raise ValueError("首尾 X 相同，无法用两端点估计线性基线。")
        baseline_values = y[0] + (y[-1] - y[0]) * (x - x[0]) / (x[-1] - x[0])
        warnings.append("线性基线由首尾两个点估计，请确认两端适合表示背景。")
    y -= baseline_values
    if smoothing > 1:
        y = np.convolve(np.pad(y, smoothing // 2, mode="edge"),
                        np.ones(smoothing) / smoothing, mode="valid")
        warnings.append("移动平均按点数计算；不等间隔采样不等于固定物理宽度平滑。")
    if normalization == "minmax":
        low, span = float(y.min()), float(y.max() - y.min())
        if span == 0:
            raise ValueError("常数曲线无法执行 Min-Max 归一化。")
        y = (y - low) / span
    elif normalization == "maxabs":
        scale = float(np.max(np.abs(y)))
        if scale == 0:
            raise ValueError("全零曲线无法按最大绝对值归一化。")
        y /= scale
    if not np.isfinite(y).all():
        raise ValueError("处理产生非有限数值，请检查数据范围和参数。")
    peak = int(np.argmax(y))
    return {
        "label": label or f"{dataset.name} · {y_column}",
        "x": x.tolist(), "raw_y": raw_y.tolist(), "y": y.tolist(),
        "baseline_values": baseline_values.tolist(), "source_rows": (rows + 1).tolist(),
        "source": dataset.source, "x_column": x_column, "y_column": y_column,
        "settings": {"baseline": baseline, "smoothing": smoothing,
                     "normalization": normalization, "order": "acquisition"},
        "stats": {"points": len(x), "dropped_rows": dropped,
                  "x_min": float(x.min()), "x_max": float(x.max()),
                  "y_min": float(y.min()), "y_max": float(y.max()),
                  "sample_max_x": float(x[peak]), "sample_max_y": float(y[peak])},
        "warnings": warnings,
    }
