# OpticsLabKit

[![CI](https://github.com/SoftBread1217/OpticsLabKit/actions/workflows/ci.yml/badge.svg)](https://github.com/SoftBread1217/OpticsLabKit/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**A local workbench for optical lab data: import, compare, process, and export.**

[中文使用说明](docs/quickstart_zh.md) · [Releases](https://github.com/SoftBread1217/OpticsLabKit/releases) · [Report an issue](https://github.com/SoftBread1217/OpticsLabKit/issues)

OpticsLabKit helps turn instrument TXT/CSV files and Excel worksheets into comparison
figures without writing a new script for every experiment. Choose the X/Y columns,
compare TE/TM or repeated runs, apply explicit processing, and download a result bundle.
The browser interface is in Chinese. All processing runs on your computer.

![Local workbench with synthetic TE/TM curves](docs/images/workbench.png)

## Try it

Python 3.10 or newer:

```bash
git clone https://github.com/SoftBread1217/OpticsLabKit.git
cd OpticsLabKit
python -m venv .venv
# Windows PowerShell
.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m opticslabkit serve
```

On macOS/Linux, activate the environment with `source .venv/bin/activate`.

Open **http://127.0.0.1:8766** and click **先体验 TE / TM 示例**.
On Windows, `launch.ps1` starts the app using the local virtual environment, or your
default Python if no environment exists. Dependencies must already be installed.
You can also double-click `start.cmd` and then open the local address.

The example is a deterministic synthetic spectrum, not experimental or paper data.
Drag in your own file when ready. Use the reading settings for metadata lines,
headerless files, separators, and decimal commas. XLSX workbooks expose a sheet selector.

## What v0.1.0 does

- TXT/CSV/TSV/DAT import: UTF-8/BOM, UTF-16 BOM, GB18030; comma, tab, whitespace, semicolon.
- XLSX import, worksheet selection, editable header and skipped-row settings.
- Select multiple Y columns and overlay curves from multiple files.
- Retain acquisition order, including descending or returning scans and duplicate X values.
- Pairwise removal of invalid X/Y rows, with a visible count.
- Optional minimum or endpoint-linear baseline subtraction, moving average,
  Min-Max or maximum-absolute normalization.
- Raw/processed overlay, range summary, sampled maximum position.
- Download 300 dpi PNG, editable-text SVG, processed CSVs, and a JSON provenance record.
- Python API and CLI for repeatable use.

Exports record source filenames, SHA-256 hashes, parsing options, selected columns,
processing order, software versions, dropped-row counts, and warnings. They do not
include copies of the original files. CSV `source_data_row` refers to the parsed table.

## CLI

```bash
python -m opticslabkit inspect experiment.csv
python -m opticslabkit process experiment.csv --x "Wavelength (nm)" --y "TE" --y "TM" --normalization minmax --smoothing 5 --x-label "Wavelength (nm)" --y-label "Normalized response" --output outputs/comparison.zip
python -m opticslabkit demo --output outputs/demo.zip
```

`process` and `demo` require a new output filename and do not overwrite an existing ZIP.

## Python API

```python
from pathlib import Path
from opticslabkit.data import read_data
from opticslabkit.processing import process_curve
from opticslabkit.export import export_bundle

path = Path("experiment.csv")
dataset = read_data(path.name, path.read_bytes())
print(dataset.describe())
curve = process_curve(dataset, "wavelength_nm", "transmission", normalization="minmax")
bundle = export_bundle([curve], {
    "title": "Transmission", "x_label": "Wavelength (nm)",
    "y_label": "Normalized transmission", "show_raw": False,
})
Path("results.zip").write_bytes(bundle)
```

## Interpretation

Units are user-supplied. Values are never converted between linear power and dB automatically.
Individual normalization removes absolute intensity ratios between TE/TM curves.
Moving averages use point counts and edge-value padding, not a fixed wavelength width.
Endpoint-linear baseline assumes the first and last points describe the background.
Sample maxima are not fitted peak positions or FWHM. Preserve separate scan branches
when the physical interpretation requires them.

This first version supports `.xlsx`, not `.xls`, and static figures, not instrument control.
Maximums: 20 MB per file, 200,000 rows, 40 imports per session, 12 curves per comparison.
Uploads stay in server memory until the process stops. No network API, CDN, analytics,
or remote upload is used. The service binds to `127.0.0.1` only.

## Development

```bash
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check .
```

See [中文入门](docs/quickstart_zh.md) and [Roadmap](ROADMAP.md).
License: MIT.
