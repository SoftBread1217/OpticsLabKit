"""CLI entry points for local UI and reproducible processing."""

import argparse
import json
from pathlib import Path

from . import __version__
from .data import demo_data, read_data
from .export import export_bundle
from .processing import process_curve


def main() -> None:
    parser = argparse.ArgumentParser(description="OpticsLabKit — local optical data tools")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    ui = sub.add_parser("serve", help="Start the local browser interface")
    ui.add_argument("--port", type=int, default=8766)
    for command in ("inspect", "process"):
        item = sub.add_parser(command)
        item.add_argument("file", type=Path)
        item.add_argument("--sheet")
        item.add_argument("--skip-rows", type=int, default=0)
        item.add_argument("--header", choices=["auto", "yes", "no"], default="auto")
        item.add_argument("--delimiter", choices=["auto", "comma", "tab", "space", "semicolon"],
                          default="auto")
        item.add_argument("--decimal", choices=[".", ","], default=".")
        if command == "process":
            item.add_argument("--x", required=True, help="Exact X column name")
            item.add_argument("--y", required=True, action="append", help="Y column, repeatable")
            item.add_argument("--normalization", choices=["none", "minmax", "maxabs"],
                              default="none")
            item.add_argument("--baseline", choices=["none", "minimum", "edge_linear"],
                              default="none")
            item.add_argument("--smoothing", type=int, default=1)
            item.add_argument("--branch", default="all", help="all or a zero-based scan branch ID")
            item.add_argument("--title", default="Optical response")
            item.add_argument("--x-label", default="X")
            item.add_argument("--y-label", default="Y")
            item.add_argument("--width-mm", type=float, default=180)
            item.add_argument("--height-mm", type=float, default=110)
            item.add_argument("--font-size", type=float, default=9)
            item.add_argument("--output", type=Path, required=True, help="New output ZIP path")
    demo = sub.add_parser("demo", help="Export a processed synthetic TE/TM example")
    demo.add_argument("--output", type=Path, default=Path("outputs/demo.zip"))
    args = parser.parse_args()
    try:
        if args.command == "serve":
            from .server import serve
            serve(args.port)
            return
        if args.command == "demo":
            dataset = read_data("synthetic_TE_TM.csv", demo_data())
            dataset.source["data_kind"] = "synthetic demonstration"
            curves = [process_curve(dataset, "Wavelength (nm)", y,
                                    normalization="minmax", smoothing=5)
                      for y in ["TE (a.u.)", "TM (a.u.)"]]
            figure = {"title": "Synthetic TE/TM comparison", "x_label": "Wavelength (nm)",
                      "y_label": "Normalized response", "show_raw": False}
        else:
            dataset = read_data(args.file.name, args.file.read_bytes(), sheet=args.sheet,
                                skip_rows=args.skip_rows, header=args.header,
                                delimiter=args.delimiter, decimal=args.decimal)
            if args.command == "inspect":
                print(json.dumps(dataset.describe(), indent=2, ensure_ascii=False, default=str))
                return
            curves = [process_curve(dataset, args.x, y, normalization=args.normalization,
                                    baseline=args.baseline, smoothing=args.smoothing,
                                    branch=args.branch)
                      for y in args.y]
            figure = {"title": args.title, "x_label": args.x_label, "y_label": args.y_label,
                      "show_raw": args.normalization == "none", "width_mm": args.width_mm,
                      "height_mm": args.height_mm, "font_size": args.font_size}
        if args.output.exists():
            raise ValueError("输出文件已存在，请使用新的文件名。")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(export_bundle(curves, figure))
        print(f"Exported: {args.output.resolve()}")
    except (ValueError, OSError) as error:
        parser.exit(2, f"Error: {error}\n")
