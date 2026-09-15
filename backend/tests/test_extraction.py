from pathlib import Path

import ezdxf
import pytest
from PIL import Image
from pypdf import PdfWriter

from civil_engineering.extraction import (
    ExtractionError,
    parse_csv,
    parse_dxf,
    parse_file,
    parse_landxml,
    parse_pdf,
    parse_text,
    parse_tiff,
)


def test_text_and_csv_parsers_preserve_source_references() -> None:
    text = parse_text(b"FF=102.50\nTop of curb 101.80\n", "survey.txt")
    assert text.metadata["encoding"] == "utf-8"
    assert text.items[0].source.file_name == "survey.txt"

    table = parse_csv(b"point,elevation\nA,102.5\n", "points.csv")
    assert table.items[0].value == {"point": "A", "elevation": "102.5"}
    assert table.items[0].source.entity_id == "2"


def test_delimited_txt_parsers_support_tab_pipe_and_space() -> None:
    for delimiter in ("\t", "|", "  "):
        data = delimiter.join(("1", "5000.2", "1000.2", "25.071"))
        document = parse_text(
            (data + "\n" + delimiter.join(("2", "5000.4", "1000.4", "25.109"))).encode(),
            "points.txt",
        )
        assert document.parser_name == "text_table"
        assert document.metadata["delimiter"] == (" " if delimiter == "  " else delimiter)
        assert document.items[0].value["x"] == "5000.2"
        assert document.items[0].value["y"] == "1000.2"


def test_single_space_numeric_txt_rows_are_points() -> None:
    document = parse_text(
        b"1 5000.2 1000.2 25.071\n2 5000.4 1000.4 25.109\n",
        "points_space.txt",
    )

    assert document.parser_name == "text_table"
    assert document.items[0].value == {
        "point_id": "1",
        "x": "5000.2",
        "y": "1000.2",
        "elevation": "25.071",
    }


def test_pdf_parser_extracts_page_text(tmp_path: Path) -> None:
    path = tmp_path / "plan.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with path.open("wb") as output:
        writer.write(output)

    document = parse_pdf(path.read_bytes(), "plan.pdf")
    assert document.metadata["page_count"] == 1
    assert document.items == []
    assert document.warnings == ["Page 1 contains no extractable text"]


def test_dxf_parser_extracts_entities_and_layers(tmp_path: Path) -> None:
    drawing = ezdxf.new("R2010")  # type: ignore[attr-defined]
    modelspace = drawing.modelspace()
    modelspace.add_line((0, 0), (10, 0), dxfattribs={"layer": "PROPERTY"})
    modelspace.add_text("FF=102.50", dxfattribs={"layer": "ELEVATIONS"})
    path = tmp_path / "site.dxf"
    drawing.saveas(path)

    document = parse_file(path, "site.dxf")
    assert document.parser_name == "dxf"
    assert {item.source.layer for item in document.items} == {"PROPERTY", "ELEVATIONS"}
    assert any(item.item_type == "line" for item in document.items)


def test_tiff_parser_extracts_raster_metadata(tmp_path: Path) -> None:
    path = tmp_path / "survey.tif"
    Image.new("L", (640, 480), color=255).save(path, format="TIFF")

    document = parse_tiff(path.read_bytes(), "survey.tif")
    assert document.parser_name == "tiff"
    assert document.metadata["width"] == 640
    assert document.metadata["height"] == 480
    assert document.warnings == ["OCR is not enabled for TIFF images"]


def test_landxml_parser_extracts_points_and_alignment_lines() -> None:
    data = """<?xml version="1.0"?>
<LandXML xmlns="http://www.landxml.org/schema/LandXML-1.2">
  <CgPoints>
    <CgPoint name="1">1000.00 5000.00 100.00</CgPoint>
    <CgPoint name="2">1000.00 5100.00 101.00</CgPoint>
  </CgPoints>
  <Surfaces>
    <Surface name="EG">
      <Definition surfType="TIN">
        <Pnts>
          <P id="3">1002.00 5002.00 102.00</P>
        </Pnts>
      </Definition>
    </Surface>
  </Surfaces>
  <Alignments>
    <Alignment name="Centerline">
      <CoordGeom>
        <Line>
          <Start>1000.00 5000.00</Start>
          <End>1000.00 5100.00</End>
        </Line>
        <Curve>
          <Start>1000.00 5100.00</Start>
          <End>1010.00 5150.00</End>
        </Curve>
      </CoordGeom>
    </Alignment>
  </Alignments>
</LandXML>
"""
    document = parse_landxml(data, "corridor.xml")
    assert document.parser_name == "landxml"
    assert document.metadata == {"point_count": 3, "alignment_line_count": 1}

    points = [item for item in document.items if item.item_type == "point"]
    assert {tuple(item.value["point"]) for item in points} == {
        (5000.0, 1000.0, 100.0),
        (5100.0, 1000.0, 101.0),
        (5002.0, 1002.0, 102.0),
    }
    cg_point = next(item for item in points if item.source.entity_type == "CgPoint")
    assert cg_point.source.entity_id == "1"
    surface_point = next(item for item in points if item.source.entity_type == "P")
    assert surface_point.source.entity_id == "3"

    line = next(item for item in document.items if item.item_type == "line")
    assert line.value == {"start": [5000.0, 1000.0], "end": [5100.0, 1000.0]}
    assert line.source.entity_type == "alignment_line"
    assert any("Curve" in warning for warning in document.warnings)


def test_landxml_parser_rejects_malformed_or_non_landxml_input() -> None:
    with pytest.raises(ExtractionError, match="LandXML could not be read"):
        parse_landxml("not xml", "broken.xml")
    with pytest.raises(ExtractionError, match="not a LandXML document"):
        parse_landxml("<Other/>", "other.xml")
    with pytest.raises(ExtractionError, match="no supported"):
        parse_landxml("<LandXML/>", "empty.xml")


def test_parse_file_dispatches_landxml_by_extension(tmp_path: Path) -> None:
    path = tmp_path / "site.xml"
    path.write_text(
        '<LandXML><CgPoints><CgPoint name="1">10 20 30</CgPoint></CgPoints></LandXML>',
        encoding="utf-8",
    )
    document = parse_file(path, "site.xml")
    assert document.parser_name == "landxml"
    assert document.items[0].value["point"] == [20.0, 10.0, 30.0]


def test_parser_rejects_unsupported_or_malformed_input(tmp_path: Path) -> None:
    with pytest.raises(ExtractionError, match="CSV file has no header"):
        parse_csv(b"", "empty.csv")
    with pytest.raises(ExtractionError, match="Unsupported extraction type"):
        parse_file(tmp_path / "plan.exe", "plan.exe")
    with pytest.raises(ExtractionError, match="DXF could not be read"):
        parse_dxf("not a dxf", "broken.dxf")
