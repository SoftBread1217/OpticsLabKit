"""Scientific figure and processed data exports with provenance."""

import io
import json
import threading
import zipfile
from datetime import datetime, timezone

import matplotlib
import pandas as pd

from . import __version__

matplotlib.use("Agg")
from matplotlib.backends.backend_agg import FigureCanvasAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

PLOT_LOCK = threading.Lock()
COLORS = ["#176b82", "#d78736", "#735ab8", "#3d8b63", "#c3536b", "#556878"]


def render_figure(curves: list[dict], settings: dict, format: str = "png") -> bytes:
    if format not in {"png", "svg"}:
        raise ValueError("支持 PNG 或 SVG 图片。")
    with PLOT_LOCK, matplotlib.rc_context({
        "font.family": "sans-serif",
        "font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"],
        "axes.unicode_minus": False, "svg.fonttype": "none",
    }):
        fig = Figure(figsize=(7.5, 4.8), layout="constrained")
        FigureCanvasAgg(fig)
        ax = fig.subplots()
        for i, curve in enumerate(curves):
            color = COLORS[i % len(COLORS)]
            if settings.get("show_raw", True):
                ax.plot(curve["x"], curve["raw_y"], color=color, alpha=0.25,
                        linewidth=1, linestyle="--", label=f"{curve['label']} (raw)")
            ax.plot(curve["x"], curve["y"], color=color, linewidth=1.8, label=curve["label"])
        ax.set_xlabel(str(settings.get("x_label", "X")))
        ax.set_ylabel(str(settings.get("y_label", "Y")))
        ax.set_title(str(settings.get("title", "Optical response")), loc="left", pad=14)
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(alpha=0.16)
        ax.legend(frameon=False, fontsize=8)
        output = io.BytesIO()
        fig.savefig(output, format=format, dpi=300)
        return output.getvalue()


def export_bundle(curves: list[dict], settings: dict) -> bytes:
    if not curves:
        raise ValueError("请先选择至少一条曲线。")
    manifest = {
        "tool": "OpticsLabKit", "version": __version__,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "processing_order": ["pairwise numeric filtering", "baseline", "moving average",
                             "normalization"],
        "figure": settings,
        "curves": [{k: v for k, v in curve.items() if k not in {
            "x", "raw_y", "y", "baseline_values", "source_rows"
        }} for curve in curves],
        "versions": {"numpy": __import__("numpy").__version__,
                     "pandas": pd.__version__, "matplotlib": matplotlib.__version__},
        "notes": ["Raw source files are not included. Hashes identify their exact bytes.",
                  "source_data_row is 1-based within the parsed table, not the file line.",
                  "Sample maximum is not fitted peak position or FWHM.",
                  "Individually normalized curves do not preserve absolute TE/TM ratios."],
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("figure.png", render_figure(curves, settings, "png"))
        archive.writestr("figure.svg", render_figure(curves, settings, "svg"))
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for i, curve in enumerate(curves, 1):
            frame = pd.DataFrame({"source_data_row": curve["source_rows"],
                                  "x": curve["x"], "y_raw": curve["raw_y"],
                                  "baseline": curve["baseline_values"],
                                  "y_processed": curve["y"]})
            archive.writestr(f"curve_{i:02d}.csv", frame.to_csv(index=False))
    return output.getvalue()
