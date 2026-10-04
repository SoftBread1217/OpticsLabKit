import io
import json
import zipfile

import numpy as np
import pytest

from opticslabkit.data import demo_data, read_data
from opticslabkit.export import export_bundle
from opticslabkit.processing import process_curve


def small_workbook() -> bytes:
    """Minimal OOXML fixture; no real lab records are stored in the test suite."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("[Content_Types].xml", '''
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml"
ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml"
ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/worksheets/sheet2.xml"
ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>''')
        archive.writestr("_rels/.rels", '''
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1"
Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
Target="xl/workbook.xml"/></Relationships>''')
        archive.writestr("xl/workbook.xml", '''
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets><sheet name="TE" sheetId="1" r:id="rId1"/>
<sheet name="TM" sheetId="2" r:id="rId2"/></sheets></workbook>''')
        archive.writestr("xl/_rels/workbook.xml.rels", '''
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1"
Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2"
Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
Target="worksheets/sheet2.xml"/></Relationships>''')
        for i in (1, 2):
            archive.writestr(f"xl/worksheets/sheet{i}.xml", f'''
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>
<row r="1"><c r="A1" t="inlineStr"><is><t>wavelength</t></is></c>
<c r="B1" t="inlineStr"><is><t>response</t></is></c></row>
<row r="2"><c r="A2"><v>1530</v></c><c r="B2"><v>{i}</v></c></row>
<row r="3"><c r="A3"><v>1531</v></c><c r="B3"><v>{i + 1}</v></c></row>
</sheetData></worksheet>''')
    return buf.getvalue()


@pytest.mark.parametrize("sep", [",", "\t", " ", ";"])
def test_headerless_preserves_first_point(sep):
    raw = f"1{sep}2\n3{sep}4\n".encode()
    data = read_data("scan.txt", raw)
    assert list(data.frame.columns) == ["Column 1", "Column 2"]
    assert data.frame.iloc[0].tolist() == [1, 2]
    assert data.source["header_detected"] is False


def test_chinese_metadata_and_comments():
    text = "仪器记录\n# 中文注释\n波长,透射率\n1530,0.2\n1531,0.8\n"
    data = read_data("实验.csv", text.encode("gb18030"), skip_rows=1)
    assert data.source["encoding"] == "gb18030"
    assert list(data.frame.columns) == ["波长", "透射率"]
    assert len(data.frame) == 2


def test_utf16_decimal_comma_and_explicit_headers():
    data = read_data("scan.txt", "x;y\n1,5;2,5\n2,5;3,5\n".encode("utf-16"), decimal=",")
    assert data.frame["x"].tolist() == [1.5, 2.5]
    assert data.frame["y"].tolist() == [2.5, 3.5]
    numeric_headers = read_data("scan.csv", b"1,2\n3,4\n", header="yes")
    assert list(numeric_headers.frame.columns) == ["1", "2"]
    assert len(numeric_headers.frame) == 1


def test_excel_sheet_selection_and_source_hash():
    raw = small_workbook()
    data = read_data("scan.xlsx", raw, sheet="TM")
    assert data.sheets == ["TE", "TM"]
    assert data.source["sheet"] == "TM"
    assert data.frame["response"].tolist() == [2, 3]
    assert len(data.source["sha256"]) == 64
    with pytest.raises(ValueError, match="工作表"):
        read_data("scan.xlsx", raw, sheet="missing")


def test_pairwise_cleaning_and_order_preservation():
    data = read_data("loop.csv", b"x,y\n0,0\n1,2\n2,4\n1,3\n0,1\nbad,5\n2,inf\n")
    before = data.frame.copy(deep=True)
    curve = process_curve(data, "x", "y")
    assert curve["x"] == [0, 1, 2, 1, 0]
    assert curve["y"] == [0, 2, 4, 3, 1]
    assert curve["source_rows"] == [1, 2, 3, 4, 5]
    assert curve["stats"]["dropped_rows"] == 2
    assert any("非单调" in warning for warning in curve["warnings"])
    assert data.frame.equals(before)
    json.dumps(data.describe(), allow_nan=False)


def test_processing_order_and_edge_padded_smoothing():
    data = read_data("scan.csv", b"x,y\n0,10\n1,13\n2,10\n")
    curve = process_curve(data, "x", "y", baseline="minimum", smoothing=3,
                          normalization="maxabs")
    np.testing.assert_allclose(curve["baseline_values"], [10, 10, 10])
    np.testing.assert_allclose(curve["y"], [1, 1, 1])
    np.testing.assert_allclose(curve["raw_y"], [10, 13, 10])


def test_endpoint_linear_uses_x_not_row_number():
    data = read_data("scan.csv", b"x,y\n0,2\n1,5\n4,10\n")
    curve = process_curve(data, "x", "y", baseline="edge_linear")
    np.testing.assert_allclose(curve["baseline_values"], [2, 4, 10])
    np.testing.assert_allclose(curve["y"], [0, 1, 0])


@pytest.mark.parametrize("options,match", [
    ({"normalization": "minmax"}, "常数"),
    ({"smoothing": 2}, "奇数"),
    ({"smoothing": 5}, "不能超过"),
    ({"baseline": "missing"}, "基线"),
])
def test_invalid_processing_is_visible(options, match):
    data = read_data("scan.csv", b"x,y\n0,2\n1,2\n")
    with pytest.raises(ValueError, match=match):
        process_curve(data, "x", "y", **options)


def test_closed_loop_rejects_endpoint_baseline():
    data = read_data("scan.csv", b"x,y\n0,1\n1,2\n0,3\n")
    with pytest.raises(ValueError, match="首尾"):
        process_curve(data, "x", "y", baseline="edge_linear")


def test_export_images_csv_and_provenance():
    data = read_data("synthetic.csv", demo_data())
    curve = process_curve(data, "Wavelength (nm)", "TE (a.u.)", normalization="minmax")
    bundle = export_bundle([curve], {"show_raw": False, "x_label": "Wavelength (nm)"})
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        assert archive.read("figure.png").startswith(b"\x89PNG")
        assert b"<svg" in archive.read("figure.svg")
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["curves"][0]["source"]["sha256"] == data.source["sha256"]
        assert manifest["curves"][0]["settings"]["normalization"] == "minmax"
        assert manifest["processing_order"][-1] == "normalization"
        assert "y_processed" in archive.read("curve_01.csv").decode()
        assert not any(name.endswith(".xlsx") for name in archive.namelist())
