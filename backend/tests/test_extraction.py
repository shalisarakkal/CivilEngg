from pathlib import Path

import ezdxf
import pytest
from PIL import Image
from pypdf import PdfWriter

from civil_engineering.extraction import (
    ExtractionError,
    _bearing_to_azimuth,
    _key_phrase_items,
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


def test_text_parser_extracts_key_phrases_from_narrative_lines() -> None:
    document = parse_text(
        b"The required setback is 25 feet from the property line.\n"
        b"Finished Floor Elevation shown on the plan.\n"
        b"This site is currently upgrading its access road.\n",
        "notes.txt",
    )
    key_phrases = [item for item in document.items if item.item_type == "key_phrase"]
    phrases_found = {item.value["phrase"] for item in key_phrases}
    assert phrases_found == {"setback", "property line", "finished floor elevation"}
    setback_item = next(item for item in key_phrases if item.value["phrase"] == "setback")
    assert (
        setback_item.value["context"] == "The required setback is 25 feet from the property line."
    )
    assert setback_item.source.file_name == "notes.txt"
    # "upgrading" must not spuriously match the "grading" key phrase.
    assert "grading" not in phrases_found


def test_key_phrase_items_helper_attaches_page_reference() -> None:
    items = _key_phrase_items(
        ["A drainage easement runs along the rear property line.", "", "No key terms here."],
        "plan.pdf",
        page=3,
    )
    assert {item.value["phrase"] for item in items} == {"drainage", "easement", "property line"}
    assert all(item.source.page == 3 for item in items)
    assert all(item.source.file_name == "plan.pdf" for item in items)


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


def test_dxf_text_is_scanned_for_key_phrases(tmp_path: Path) -> None:
    # Regression test: DXF TEXT content was stored as a plain "text" item but,
    # unlike parse_text/parse_pdf, was never scanned for key phrases -- the
    # same wording on a DXF annotation was silently less searchable than on a
    # PDF or TXT page.
    drawing = ezdxf.new("R2010")  # type: ignore[attr-defined]
    modelspace = drawing.modelspace()
    modelspace.add_text("25' REAR SETBACK", dxfattribs={"layer": "ANNOTATIONS"})
    path = tmp_path / "annotated.dxf"
    drawing.saveas(path)

    document = parse_file(path, "annotated.dxf")
    key_phrases = [item for item in document.items if item.item_type == "key_phrase"]
    assert len(key_phrases) == 1
    assert key_phrases[0].value == {"phrase": "setback", "context": "25' REAR SETBACK"}
    assert key_phrases[0].source.layer == "ANNOTATIONS"


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


def test_landxml_parser_accepts_comma_decimal_coordinates() -> None:
    data = """<?xml version="1.0"?>
<LandXML xmlns="http://www.landxml.org/schema/LandXML-1.1">
  <CgPoints>
    <CgPoint name="1">3394639,42776972 5580312,09152585 184,95</CgPoint>
    <CgPoint name="2">3394643,238154 5580331,58458437 184,76196</CgPoint>
  </CgPoints>
</LandXML>
"""
    document = parse_landxml(data, "cross_section_points.xml")
    assert document.warnings == []
    points = [item for item in document.items if item.item_type == "point"]
    assert {tuple(item.value["point"]) for item in points} == {
        (5580312.09152585, 3394639.42776972, 184.95),
        (5580331.58458437, 3394643.238154, 184.76196),
    }


def test_landxml_parser_extracts_align_pis_and_skips_curved_segments() -> None:
    data = """<?xml version="1.0"?>
<LandXML>
  <Alignments>
    <Alignment name="Test Rd">
      <AlignPIs>
        <AlignPI><PI>1000.00 5000.00</PI></AlignPI>
        <AlignPI><PI>1000.00 5100.00</PI><InSpiral/><Curve1/><OutSpiral/></AlignPI>
        <AlignPI><PI>1000.00 5200.00</PI></AlignPI>
        <AlignPI><PI>1000.00 5300.00</PI></AlignPI>
      </AlignPIs>
    </Alignment>
  </Alignments>
</LandXML>
"""
    document = parse_landxml(data, "road.xml")
    points = [item for item in document.items if item.item_type == "point"]
    lines = [item for item in document.items if item.item_type == "line"]
    assert len(points) == 4
    assert {item.source.entity_type for item in points} == {"align_pi"}

    # Only the PI-3-to-PI-4 segment has neither endpoint curved.
    assert len(lines) == 1
    assert lines[0].value == {"start": [5200.0, 1000.0], "end": [5300.0, 1000.0]}
    assert lines[0].source.entity_type == "align_pi_line"
    assert sum("was not extracted" in warning for warning in document.warnings) == 2


def test_landxml_parser_resolves_pntref_and_extracts_parcel_boundaries() -> None:
    data = """<?xml version="1.0"?>
<LandXML>
  <CgPoints>
    <CgPoint name="A">1000.00 5000.00</CgPoint>
    <CgPoint name="B">1000.00 5100.00</CgPoint>
  </CgPoints>
  <Parcels>
    <Parcel name="Lot1">
      <CoordGeom>
        <Line>
          <Start pntRef="A"/>
          <End pntRef="B"/>
        </Line>
        <Line>
          <Start pntRef="A"/>
          <End>1000.00 5200.00</End>
        </Line>
      </CoordGeom>
    </Parcel>
  </Parcels>
</LandXML>
"""
    document = parse_landxml(data, "plat.xml")
    lines = [item for item in document.items if item.item_type == "line"]
    assert len(lines) == 2
    assert all(item.source.entity_type == "parcel_line" for item in lines)
    assert lines[0].value == {"start": [5000.0, 1000.0], "end": [5100.0, 1000.0]}
    # A pntRef and an inline coordinate can both appear on the same Line.
    assert lines[1].value == {"start": [5000.0, 1000.0], "end": [5200.0, 1000.0]}
    assert document.warnings == []


def test_landxml_parser_resolves_point_level_pntref_and_consolidates_unresolved_refs() -> None:
    data = """<?xml version="1.0"?>
<LandXML>
  <CgPoints>
    <CgPoint name="1" code="GRND">1000.00 5000.00</CgPoint>
    <CgPoint pntRef="1"></CgPoint>
    <CgPoint pntRef="missing-a"></CgPoint>
    <CgPoint pntRef="missing-b"></CgPoint>
  </CgPoints>
</LandXML>
"""
    document = parse_landxml(data, "features.xml")
    points = [item for item in document.items if item.item_type == "point"]
    # The real point plus its resolved reference; the two unresolvable refs are skipped.
    assert len(points) == 2
    assert all(item.value["point"] == [5000.0, 1000.0] for item in points)
    assert len(document.warnings) == 1
    assert "2 point reference(s)" in document.warnings[0]
    assert "missing-a" in document.warnings[0]
    assert "missing-b" in document.warnings[0]


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


def test_bearing_to_azimuth_covers_all_quadrants() -> None:
    assert _bearing_to_azimuth("N45.00E") == pytest.approx(45.0)
    assert _bearing_to_azimuth("S45.00E") == pytest.approx(135.0)
    assert _bearing_to_azimuth("S45.00W") == pytest.approx(225.0)
    assert _bearing_to_azimuth("N45.00W") == pytest.approx(315.0)
    assert _bearing_to_azimuth("N45-30-00E") == pytest.approx(45.5)
    assert _bearing_to_azimuth("not a bearing") is None
    assert _bearing_to_azimuth("N95.00E") is None  # out of the 0-90 degree range


def test_csv_parser_chains_bearing_distance_courses_from_a_starting_point() -> None:
    document = parse_csv(
        b"point_id,x,y,bearing,distance\n1,1000,5000,,\n2,,,N90.00E,100.00\n3,,,N45.00E,50.00\n",
        "boundary.csv",
    )
    courses = [item for item in document.items if item.item_type == "cogo_line"]
    assert len(courses) == 2

    first = courses[0].value
    assert first["start"] == [1000.0, 5000.0]
    assert first["end"] == pytest.approx([1100.0, 5000.0])
    assert first["bearing"] == "N90.00E"
    assert first["distance"] == 100.0

    second = courses[1].value
    assert second["start"] == pytest.approx([1100.0, 5000.0])
    assert second["end"] == pytest.approx([1135.35534, 5035.35534], abs=1e-4)


def test_csv_parser_ignores_invalid_or_incomplete_courses() -> None:
    document = parse_csv(
        b"x,y,bearing,distance\n0,0,,\n,,gibberish,10\n,,N45.00E,\n",
        "invalid.csv",
    )
    assert [item for item in document.items if item.item_type == "cogo_line"] == []


def test_parser_rejects_unsupported_or_malformed_input(tmp_path: Path) -> None:
    with pytest.raises(ExtractionError, match="CSV file has no header"):
        parse_csv(b"", "empty.csv")
    with pytest.raises(ExtractionError, match="Unsupported extraction type"):
        parse_file(tmp_path / "plan.exe", "plan.exe")
    with pytest.raises(ExtractionError, match="DXF could not be read"):
        parse_dxf("not a dxf", "broken.dxf")
