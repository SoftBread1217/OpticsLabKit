"""Scientific figure and processed data exports with provenance."""

import io
import json
import zipfile
from datetime import datetime, timezone
from importlib.resources import files

import matplotlib
import pandas as pd

from . import __version__
from .analysis import optical_summary
from .plotting import COLORS, figure_settings, render_figure  # noqa: F401

REDRAW = '''"""Run: python redraw.py (requires matplotlib and pandas; no OpticsLabKit needed)."""
import json
from pathlib import Path
import pandas as pd
from plot_style import render_figure

root = Path(__file__).resolve().parent
manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
curves = []
for i, meta in enumerate(manifest["curves"], 1):
    frame = pd.read_csv(root / f"curve_{i:02d}.csv", float_precision="round_trip")
    curves.append({**meta, "x": frame.x.tolist(), "y": frame.y_processed.tolist(),
                   "raw_y": frame.y_raw.tolist()})
statistics = []
for i, meta in enumerate(manifest["analysis"]["statistics"], 1):
    frame = pd.read_csv(root / f"repeat_{i:02d}.csv", float_precision="round_trip")
    statistics.append({**meta, "x": frame.x.tolist(), "y": frame["mean"].tolist(),
                       "sd": frame.sd.tolist()})
for extension in ("svg", "png", "pdf"):
    target = root / f"redrawn.{extension}"
    if target.exists():
        raise SystemExit(f"Refusing to overwrite {target}; rename or remove it first.")
for extension in ("svg", "png", "pdf"):
    (root / f"redrawn.{extension}").write_bytes(
        render_figure(curves, manifest["figure"], extension, statistics))
print("Saved redrawn.svg, redrawn.png, redrawn.pdf; originals were not modified.")
'''


def export_bundle(curves: list[dict], settings: dict, analysis: dict | None = None) -> bytes:
    if not curves:
        raise ValueError("请先选择至少一条曲线。")
    settings = figure_settings(settings)
    analysis = analysis or optical_summary(curves)
    statistics = analysis["statistics"]
    manifest = {
        "tool": "OpticsLabKit", "version": __version__,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "processing_order": ["pairwise numeric filtering", "branch selection", "baseline",
                             "moving average", "normalization"],
        "figure": settings,
        "curves": [{k: v for k, v in curve.items() if k not in {
            "x", "raw_y", "y", "baseline_values", "source_rows"
        }} for curve in curves],
        "analysis": {**analysis, "statistics": [{k: v for k, v in summary.items()
                                                 if k not in {"x", "y", "sd"}}
                                                for summary in statistics]},
        "versions": {"numpy": __import__("numpy").__version__,
                     "pandas": pd.__version__, "matplotlib": matplotlib.__version__},
        "notes": ["Raw source files are not included. Hashes identify their exact bytes.",
                  "source_data_row is 1-based within the parsed table, not the file line.",
                  "Sample maximum is not fitted peak position or FWHM.",
                  "Individually normalized curves do not preserve absolute TE/TM ratios.",
                  "TE/TM pairing is user-confirmed grouping, not a physical ratio calculation.",
                  "SD bands show sample spread, not SEM or confidence intervals."],
    }
    output, origin = io.BytesIO(), {}
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for extension in ("png", "svg", "pdf"):
            archive.writestr(f"figure.{extension}",
                             render_figure(curves, settings, extension, statistics))
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        archive.writestr("redraw.py", REDRAW)
        archive.writestr("plot_style.py",
                         files("opticslabkit").joinpath("plotting.py").read_bytes())
        archive.writestr("EDITING.txt", "OpticsLabKit renderer is MIT licensed.\n"
                         "Open figure.svg in a vector editor; text stays text.\n"
                         "For data editing in Origin, import origin_xy.csv and assign each\n"
                         "X_01/Y_01 pair as X/Y. Blank cells are missing, not zero.\n"
                         "Column labels and units: see manifest.json curves and figure.\n"
                         "Edit manifest.json figure/curve style, then run python redraw.py.\n"
                         "Python requires matplotlib and pandas; software/font differences\n"
                         "can change layout. No original data files are in this ZIP.\n")
        for i, curve in enumerate(curves, 1):
            frame = pd.DataFrame({"source_data_row": curve["source_rows"],
                                  "x": curve["x"], "y_raw": curve["raw_y"],
                                  "baseline": curve["baseline_values"],
                                  "y_processed": curve["y"]})
            archive.writestr(f"curve_{i:02d}.csv", frame.to_csv(index=False))
            origin[f"X_{i:02d}"] = pd.Series(curve["x"])
            origin[f"Y_{i:02d}"] = pd.Series(curve["y"])
        archive.writestr("origin_xy.csv", pd.DataFrame(origin).to_csv(index=False))
        for i, summary in enumerate(statistics, 1):
            archive.writestr(f"repeat_{i:02d}.csv", pd.DataFrame({
                "x": summary["x"], "mean": summary["y"], "sd": summary["sd"], "n": summary["n"],
            }).to_csv(index=False))
    return output.getvalue()
