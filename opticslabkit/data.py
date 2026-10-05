"""Read data without modifying source files or guessing physical units."""

import csv
import hashlib
import io
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_ROWS = 200_000


@dataclass
class Dataset:
    name: str
    frame: pd.DataFrame
    source: dict
    sheets: list[str]
    raw: bytes = b""
    parsing: dict | None = None

    def describe(self) -> dict:
        numeric = [
            str(col) for col in self.frame.columns
            if pd.to_numeric(self.frame[col], errors="coerce").notna().any()
        ]
        def safe_value(value):
            if pd.isna(value):
                return None
            if isinstance(value, float | np.floating):
                return float(value) if np.isfinite(value) else None
            if isinstance(value, int | np.integer):
                return int(value)
            if isinstance(value, str | bool):
                return value
            return str(value)

        preview = [[safe_value(value) for value in row]
                   for row in self.frame.head(8).itertuples(index=False, name=None)]
        return {
            "name": self.name, "rows": len(self.frame), "columns": list(self.frame.columns),
            "numeric_columns": numeric, "preview": preview,
            "sheets": self.sheets, "source": self.source,
        }


def _decode(raw: bytes) -> tuple[str, str]:
    encodings = ("utf-16",) if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else (
        "utf-8-sig", "gb18030"
    )
    for encoding in encodings:
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise ValueError("无法读取文本编码，请将文件另存为 UTF-8。")


def _split(line: str, delimiter: str) -> list[str]:
    if delimiter == r"\s+":
        return re.split(r"\s+", line.strip())
    return next(csv.reader([line], delimiter=delimiter))


def _numeric(token: str, decimal: str) -> bool:
    try:
        float(token.strip().replace(decimal, "."))
        return True
    except ValueError:
        return False


def read_data(name: str, raw: bytes, *, sheet: str | None = None,
              skip_rows: int = 0, header: str = "auto", delimiter: str = "auto",
              decimal: str = ".") -> Dataset:
    """Load TXT/CSV/TSV/XLSX, with editable parsing settings and source hash."""
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError("单个文件最大 20 MB。")
    if not raw:
        raise ValueError("文件为空。")
    if not isinstance(skip_rows, int) or not 0 <= skip_rows <= MAX_ROWS:
        raise ValueError("跳过行数应为非负整数。")
    if header not in {"auto", "yes", "no"} or decimal not in {".", ","}:
        raise ValueError("表头或小数符号设置无效。")
    suffix = Path(name).suffix.lower()
    info = {
        "filename": Path(name).name, "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw), "skip_rows": skip_rows, "header_setting": header,
        "decimal": decimal,
    }
    sheets: list[str] = []
    if suffix == ".xlsx":
        with pd.ExcelFile(io.BytesIO(raw), engine="openpyxl") as workbook:
            sheets = workbook.sheet_names
            selected = sheet or sheets[0]
            if selected not in sheets:
                raise ValueError("找不到指定工作表。")
            sample = pd.read_excel(workbook, sheet_name=selected, header=None,
                                   skiprows=skip_rows, nrows=1)
            if sample.empty:
                raise ValueError("跳过表头后没有数据。")
            first = sample.iloc[0].dropna().astype(str).tolist()
            has_header = header == "yes" or (
                header == "auto" and not all(_numeric(v, decimal) for v in first)
            )
            frame = pd.read_excel(workbook, sheet_name=selected,
                                  header=0 if has_header else None, skiprows=skip_rows,
                                  nrows=MAX_ROWS + 1, decimal=decimal)
            info.update(sheet=selected, header_detected=has_header, encoding=None,
                        delimiter=None)
    elif suffix in {".txt", ".csv", ".tsv", ".dat"}:
        text, encoding = _decode(raw)
        lines = text.splitlines()[skip_rows:]
        usable = [line for line in lines if line.strip() and not line.lstrip().startswith(
            ("#", "%", "//")
        )]
        if not usable:
            raise ValueError("没有可读取的数据行，请检查跳过行数。")
        choices = {"comma": ",", "tab": "\t", "semicolon": ";", "space": r"\s+"}
        if delimiter == "auto":
            first_line = usable[0]
            if "\t" in first_line:
                sep = "\t"
            elif ";" in first_line:
                sep = ";"
            elif "," in first_line and decimal == ".":
                sep = ","
            else:
                sep = r"\s+"
        elif delimiter in choices:
            sep = choices[delimiter]
        else:
            raise ValueError("分隔符设置无效。")
        first = _split(usable[0], sep)
        has_header = header == "yes" or (
            header == "auto" and not all(_numeric(v, decimal) for v in first)
        )
        frame = pd.read_csv(io.StringIO("\n".join(usable)), sep=sep, engine="python",
                            header=0 if has_header else None, decimal=decimal,
                            nrows=MAX_ROWS + 1)
        info.update(encoding=encoding, delimiter=sep, header_detected=has_header, sheet=None)
    else:
        raise ValueError("支持 .txt / .csv / .tsv / .dat / .xlsx；旧版 .xls 请先另存为 .xlsx。")
    if len(frame) > MAX_ROWS:
        raise ValueError(f"文件超过 {MAX_ROWS:,} 行，请拆分数据。")
    if frame.empty or len(frame.columns) < 2:
        raise ValueError("需要至少两列数据；请调整分隔符、表头或跳过行数。")
    if not has_header:
        frame.columns = [f"Column {i + 1}" for i in range(len(frame.columns))]
    else:
        # Use stable, unique string keys even when Excel headers repeat or are numbers.
        keys, seen = [], set()
        for index, column in enumerate(frame.columns):
            base = str(column).strip() or f"Column {index + 1}"
            key, count = base, 2
            while key in seen:
                key = f"{base} ({count})"
                count += 1
            keys.append(key)
            seen.add(key)
        frame.columns = keys
    info["row_count"] = len(frame)
    return Dataset(Path(name).name, frame, info, sheets, raw, {
        "sheet": sheet, "skip_rows": skip_rows, "header": header,
        "delimiter": delimiter, "decimal": decimal,
    })


def demo_data() -> bytes:
    """A deterministic synthetic spectrum, not a measured optical response."""
    x = np.linspace(1525, 1545, 401)
    te = 0.08 + 0.85 * np.exp(-0.5 * ((x - 1534.8) / 1.15) ** 2)
    tm = 0.12 + 0.65 * np.exp(-0.5 * ((x - 1537.1) / 1.65) ** 2)
    te += 0.008 * np.sin(x * 8)
    tm += 0.006 * np.cos(x * 7)
    return pd.DataFrame({"Wavelength (nm)": x, "TE (a.u.)": te,
                         "TM (a.u.)": tm}).to_csv(index=False).encode("utf-8")


def workflow_demo(kind: str) -> list[tuple[str, bytes]]:
    """Deterministic synthetic fixtures for branch and repeat workflows."""
    if kind == "scan":
        x = np.linspace(0, 4, 101)
        rising = .2 + .8 / (1 + np.exp(-4 * (x - 2.4)))
        falling = .2 + .8 / (1 + np.exp(-4 * (x - 1.6)))
        frame = pd.DataFrame({"Input (a.u.)": np.r_[x, x[-2::-1]],
                              "Response (a.u.)": np.r_[rising, falling[-2::-1]]})
        return [("synthetic_return_scan.csv", frame.to_csv(index=False).encode())]
    if kind == "repeats":
        result = []
        for i in range(3):
            x = np.linspace(1525 + i * .1, 1545 - i * .1, 201)
            y = .1 + (.8 + .03 * i) * np.exp(-.5 * ((x - 1535 - .08 * i) / 1.2) ** 2)
            y += .008 * np.sin(7 * x + i)
            frame = pd.DataFrame({"Wavelength (nm)": x, "TE (a.u.)": y})
            result.append((f"synthetic_TE_run{i + 1}.csv", frame.to_csv(index=False).encode()))
        return result
    raise ValueError("未知合成示例。")
