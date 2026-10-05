"""Optical comparison helpers, with explicit grouping instead of guessed physics."""

import re
from collections import defaultdict

import numpy as np


def suggest_identity(name: str) -> dict:
    tokens = list(re.finditer(r"(?<![a-zA-Z0-9])(TE|TM)(?![a-zA-Z0-9])", name, re.I))
    polarizations = {match.group().upper() for match in tokens}
    polarization = next(iter(polarizations)) if len(polarizations) == 1 else "unknown"
    return {"polarization": polarization}


def optical_summary(curves: list[dict], *, repeats: bool = False,
                    units_confirmed: bool = False) -> dict:
    """Group names are user declarations of matching experimental conditions.

    TE/TM pairing is an inventory check, not a ratio or interpolation operation.
    Repeats require strict monotonicity, same direction and distinct measurements.
    Their shared grid is the first run's points within the common overlap only.
    """
    groups, pairs, statistics, warnings = defaultdict(list), [], [], []
    for index, curve in enumerate(curves):
        group = str(curve.get("group", "")).strip()
        if group:
            groups[group].append((index, curve))
    for name, members in groups.items():
        te = [i for i, c in members if c.get("polarization") == "TE"]
        tm = [i for i, c in members if c.get("polarization") == "TM"]
        pairs.append({"group": name, "te": te, "tm": tm,
                      "status": "paired" if len(te) == len(tm) == 1 else "check"})
        if not repeats:
            continue
        for pol in ("TE", "TM", "unknown"):
            runs = [(i, c) for i, c in members if c.get("polarization", "unknown") == pol]
            if len(runs) < 2:
                continue
            prefix = f"{name} / {pol}"
            if not units_confirmed:
                warnings.append(f"{prefix}：请先确认各次测量的 X/Y 单位和条件一致。")
                continue
            identities = [(c["source"]["sha256"], c["source"].get("sheet"),
                           c["x_column"], c["y_column"], c["settings"]["branch"])
                          for _, c in runs]
            if len(set(identities)) != len(identities):
                warnings.append(f"{prefix}：包含重复选择的同一数据，不计为独立重复测量。")
                continue
            direction, grids, values = set(), [], []
            for _, curve in runs:
                x, y = np.array(curve["x"]), np.array(curve["y"])
                delta = np.diff(x)
                if np.all(delta > 0):
                    direction.add("up")
                elif np.all(delta < 0):
                    direction.add("down")
                    x, y = x[::-1], y[::-1]
                else:
                    direction.add("ambiguous")
                grids.append(x)
                values.append(y)
            if "ambiguous" in direction or len(direction) != 1:
                warnings.append(f"{prefix}：需要同方向、无重复 X 的单调分支；不能混合往返扫描。")
                continue
            low, high = max(x[0] for x in grids), min(x[-1] for x in grids)
            grid = grids[0][(grids[0] >= low) & (grids[0] <= high)]
            if len(grid) < 2:
                warnings.append(f"{prefix}：共同区间内不足两个参考采样点，无法汇总。")
                continue
            aligned = np.array([np.interp(grid, x, y) for x, y in zip(grids, values, strict=True)])
            mean, sd = aligned.mean(axis=0), aligned.std(axis=0, ddof=1)
            if not np.isfinite(mean).all() or not np.isfinite(sd).all():
                warnings.append(f"{prefix}：统计发生数值溢出，未生成均值或标准差。")
                continue
            statistics.append({"label": f"{prefix} · mean ± SD (n={len(runs)})",
                               "group": name, "polarization": pol, "n": len(runs),
                               "members": [i for i, _ in runs], "x": grid.tolist(),
                               "y": mean.tolist(), "sd": sd.tolist(),
                               "direction": next(iter(direction)),
                               "interpolated": any(not np.array_equal(grid, x) for x in grids),
                               "method": "first-run grid in common overlap; linear interpolation; "
                                         "sample SD (ddof=1), not SEM or confidence interval"})
    return {"pairs": pairs, "statistics": statistics, "warnings": warnings}
