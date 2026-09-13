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


def test_parser_rejects_unsupported_or_malformed_input(tmp_path: Path) -> None:
    with pytest.raises(ExtractionError, match="CSV file has no header"):
        parse_csv(b"", "empty.csv")
    with pytest.raises(ExtractionError, match="Unsupported extraction type"):
        parse_file(tmp_path / "plan.exe", "plan.exe")
    with pytest.raises(ExtractionError, match="DXF could not be read"):
        parse_dxf("not a dxf", "broken.dxf")
