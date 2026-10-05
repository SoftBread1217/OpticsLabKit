"""Shared preview/export renderer; also shipped in result bundles (MIT license)."""

import io
import math
import re
import threading

import matplotlib

matplotlib.use("Agg")
from matplotlib.backends.backend_agg import FigureCanvasAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.ticker import AutoMinorLocator, MaxNLocator  # noqa: E402

PLOT_LOCK = threading.Lock()
COLORS = ["#176b82", "#d78736", "#735ab8", "#3d8b63", "#c3536b", "#556878"]
DEFAULTS = {
    "width_mm": 180, "height_mm": 110, "font_size": 9, "tick_size": 8,
    "line_width": 1.5, "legend_size": 8, "dpi": 300, "font": "DejaVu Sans",
    "title": "Optical response", "x_label": "X", "y_label": "Y", "show_raw": True,
    "legend": "best", "grid": False, "box": True, "minor_ticks": True,
    "x_scale": "linear", "y_scale": "linear", "x_limits": None, "y_limits": None,
}


def figure_settings(settings: dict) -> dict:
    result = {key: settings.get(key, default) for key, default in DEFAULTS.items()}
    for key, low, high in (("width_mm", 40, 250), ("height_mm", 40, 250),
                           ("font_size", 5, 24), ("tick_size", 5, 24),
                           ("legend_size", 5, 24), ("line_width", .2, 5), ("dpi", 72, 600)):
        value = float(result[key])
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"{key} 应在 {low}–{high} 之间。")
        result[key] = value
    if result["width_mm"] * result["height_mm"] * (result["dpi"] / 25.4) ** 2 > 35e6:
        raise ValueError("图片像素过多，请减小尺寸或 DPI。")
    if result["font"] not in {"DejaVu Sans", "Arial", "Microsoft YaHei", "DejaVu Serif"}:
        raise ValueError("字体设置无效。")
    if result["legend"] not in {"best", "upper right", "upper left", "lower right",
                                 "lower left", "outside", "none"}:
        raise ValueError("图例位置无效。")
    for axis in ("x", "y"):
        if result[f"{axis}_scale"] not in {"linear", "log"}:
            raise ValueError("坐标轴支持 linear 或 log。")
        limits = result[f"{axis}_limits"]
        if limits is not None:
            if not isinstance(limits, list) or len(limits) != 2:
                raise ValueError("坐标范围需填写上下限，或两格都留空。")
            limits = [float(value) for value in limits]
            if not all(math.isfinite(v) for v in limits) or limits[0] >= limits[1]:
                raise ValueError("坐标下限必须小于上限，且均为有限数值。")
            if result[f"{axis}_scale"] == "log" and limits[0] <= 0:
                raise ValueError("对数坐标范围必须大于零。")
            result[f"{axis}_limits"] = limits
    for key in ("title", "x_label", "y_label"):
        if not isinstance(result[key], str) or len(result[key]) > 200:
            raise ValueError("图片文字应不超过 200 字符。")
    for key in ("show_raw", "grid", "box", "minor_ticks"):
        if not isinstance(result[key], bool):
            raise ValueError("图片开关参数无效。")
    return result


def curve_style(style: dict, index: int) -> dict:
    result = {"color": style.get("color", COLORS[index % len(COLORS)]),
              "line": style.get("line", "-"), "marker": style.get("marker", "none")}
    if not isinstance(result["color"], str) or not re.fullmatch(r"#[0-9a-fA-F]{6}",
                                                               result["color"]):
        raise ValueError("曲线颜色需为六位十六进制颜色。")
    if result["line"] not in {"-", "--", "-.", ":"}:
        raise ValueError("曲线线型无效。")
    if result["marker"] not in {"none", "o", "s", "^", "D"}:
        raise ValueError("曲线标记无效。")
    return result


def render_figure(curves: list[dict], settings: dict, format: str = "png",
                  statistics: list[dict] | None = None) -> bytes:
    if format not in {"png", "svg", "pdf"}:
        raise ValueError("支持 PNG、SVG 或 PDF 图片。")
    options = figure_settings(settings)
    statistics = statistics or []
    # Reject invalid logarithmic data rather than silently hiding samples.
    for axis in ("x", "y"):
        if options[f"{axis}_scale"] == "log":
            series = [c[axis] for c in curves] + [c[axis] for c in statistics]
            if axis == "y" and options["show_raw"]:
                series += [c["raw_y"] for c in curves]
            if axis == "y":
                series += [[y - sd for y, sd in zip(c["y"], c["sd"], strict=True)]
                           for c in statistics]
            if any(value <= 0 for values in series for value in values):
                raise ValueError(f"{axis.upper()} 含零/负数（或 SD 下界≤0），不能使用对数轴。")
    with PLOT_LOCK, matplotlib.rc_context({
        "font.family": [options["font"], "Microsoft YaHei", "DejaVu Sans"],
        "font.size": options["font_size"], "axes.unicode_minus": False,
        "svg.fonttype": "none", "svg.hashsalt": "opticslabkit", "pdf.fonttype": 42,
        "axes.linewidth": .8,
    }):
        fig = Figure(figsize=(options["width_mm"] / 25.4, options["height_mm"] / 25.4),
                     layout="constrained")
        FigureCanvasAgg(fig)
        ax = fig.subplots()
        for i, curve in enumerate(curves):
            style = curve_style(curve.get("style", {}), i)
            if options["show_raw"]:
                ax.plot(curve["x"], curve["raw_y"], color=style["color"], alpha=.25,
                        linewidth=.7, linestyle="--", label=f"{curve['label']} (raw)")
            ax.plot(curve["x"], curve["y"], color=style["color"], linestyle=style["line"],
                    marker=style["marker"], markersize=3,
                    markevery=max(1, len(curve["x"]) // 25),
                    linewidth=options["line_width"], label=curve["label"])
        for i, summary in enumerate(statistics):
            color = COLORS[i % len(COLORS)]
            ax.fill_between(summary["x"], [y - sd for y, sd in
                            zip(summary["y"], summary["sd"], strict=True)],
                            [y + sd for y, sd in zip(summary["y"], summary["sd"], strict=True)],
                            color=color, alpha=.15, linewidth=0)
            ax.plot(summary["x"], summary["y"], color=color,
                    linewidth=options["line_width"] + .4, label=summary["label"])
        ax.set_xlabel(options["x_label"])
        ax.set_ylabel(options["y_label"])
        ax.set_title(options["title"], loc="left", pad=8)
        ax.spines[["top", "right"]].set_visible(options["box"])
        for axis in ("x", "y"):
            getattr(ax, f"set_{axis}scale")(options[f"{axis}_scale"])
            if options[f"{axis}_limits"] is not None:
                getattr(ax, f"set_{axis}lim")(options[f"{axis}_limits"])
            obj = getattr(ax, f"{axis}axis")
            if options[f"{axis}_scale"] == "linear":
                obj.set_major_locator(MaxNLocator(nbins=5))
                if options["minor_ticks"]:
                    obj.set_minor_locator(AutoMinorLocator(2))
        if not options["minor_ticks"]:
            ax.minorticks_off()
        ax.tick_params(which="both", direction="in", labelsize=options["tick_size"],
                       top=options["box"], right=options["box"])
        if options["grid"]:
            ax.grid(alpha=.16, linewidth=.5)
        if options["legend"] != "none":
            legend_options = {"frameon": False, "fontsize": options["legend_size"]}
            if options["legend"] == "outside":
                legend_options.update(loc="upper left", bbox_to_anchor=(1, 1))
            else:
                legend_options["loc"] = options["legend"]
            ax.legend(**legend_options)
        output = io.BytesIO()
        metadata = {"Date": None} if format == "svg" else None
        fig.savefig(output, format=format, dpi=options["dpi"], metadata=metadata)
        fig.clear()
        return output.getvalue()
