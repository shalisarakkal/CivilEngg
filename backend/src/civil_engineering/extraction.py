import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


@dataclass
class SourceReference:
    file_name: str
    page: int | None = None
    layer: str | None = None
    entity_type: str | None = None
    entity_id: str | None = None
    bounds: list[float] | None = None


@dataclass
class NormalizedItem:
    item_type: str
    value: Any
    source: SourceReference


@dataclass
class NormalizedDocument:
    parser_name: str
    text: list[str] = field(default_factory=list)
    items: list[NormalizedItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "parser_name": self.parser_name,
            "text": self.text,
            "items": [
                {"item_type": item.item_type, "value": item.value, "source": item.source.__dict__}
                for item in self.items
            ],
            "warnings": self.warnings,
            "metadata": self.metadata,
        }


class ExtractionError(ValueError):
    pass


# Civil-engineering terms worth surfacing as searchable annotations when they appear in
# narrative text, drawn from Requirements.md's own examples ("setback", "finished floor
# elevation") plus closely related terms used elsewhere in this app (ai_service.py's
# drainage/utility keyword summaries, RISK_REGISTER.md's setback/slope attention flags).
KEY_PHRASES = (
    "setback",
    "finished floor elevation",
    "property line",
    "right-of-way",
    "easement",
    "zoning",
    "curb cut",
    "top of curb",
    "detention",
    "retention",
    "drainage",
    "grading",
    "utility",
)


def _find_key_phrases(text: str) -> list[str]:
    lowered = text.lower()
    return [phrase for phrase in KEY_PHRASES if re.search(rf"\b{re.escape(phrase)}\b", lowered)]


def _key_phrase_items(
    lines: list[str], file_name: str, page: int | None = None
) -> list[NormalizedItem]:
    items: list[NormalizedItem] = []
    for index, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        for phrase in _find_key_phrases(stripped):
            items.append(
                NormalizedItem(
                    "key_phrase",
                    {"phrase": phrase, "context": stripped},
                    SourceReference(file_name=file_name, page=page, entity_id=str(index)),
                )
            )
    return items


def parse_file(path: Path, original_name: str | None = None) -> NormalizedDocument:
    suffix = path.suffix.lower()
    source_name = original_name or path.name
    if suffix == ".txt":
        return parse_text(path.read_bytes(), source_name)
    if suffix == ".csv":
        return parse_csv(path.read_bytes(), source_name)
    if suffix == ".pdf":
        return parse_pdf(path.read_bytes(), source_name)
    if suffix == ".dxf":
        return parse_dxf(path.read_text(encoding="utf-8", errors="replace"), source_name)
    if suffix in {".tif", ".tiff"}:
        return parse_tiff(path.read_bytes(), source_name)
    if suffix == ".xml":
        return parse_landxml(path.read_text(encoding="utf-8", errors="replace"), source_name)
    raise ExtractionError(f"Unsupported extraction type: {suffix or 'unknown'}")


def parse_text(data: bytes, file_name: str) -> NormalizedDocument:
    text, encoding = _decode(data)
    delimited = _parse_delimited_text(text, file_name, encoding)
    if delimited is not None:
        return delimited
    document = NormalizedDocument(parser_name="text", text=text.splitlines())
    document.metadata = {"encoding": encoding, "line_count": len(document.text)}
    document.items = [
        NormalizedItem(
            "text_line", line, SourceReference(file_name=file_name, entity_id=str(index))
        )
        for index, line in enumerate(document.text, start=1)
        if line.strip()
    ]
    document.items.extend(_key_phrase_items(document.text, file_name))
    return document


def _parse_delimited_text(text: str, file_name: str, encoding: str) -> NormalizedDocument | None:
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return None
    delimiter = _detect_text_delimiter(lines[:20])
    if delimiter is None:
        return None
    rows = [_split_delimited_line(line, delimiter) for line in lines]
    if any(len(row) < 2 for row in rows):
        return None
    width = len(rows[0])
    if any(len(row) != width for row in rows):
        return None
    headers = _headers_for_rows(rows[0], rows[1:])
    data_rows = rows[1:] if any(not _is_number(value) for value in rows[0]) else rows
    items = [
        NormalizedItem(
            "table_row",
            dict(zip(headers, row, strict=True)),
            SourceReference(file_name=file_name, entity_id=str(index)),
        )
        for index, row in enumerate(data_rows, start=2)
    ]
    return NormalizedDocument(
        parser_name="text_table",
        text=lines,
        items=items,
        metadata={
            "encoding": encoding,
            "delimiter": delimiter,
            "columns": headers,
            "row_count": len(items),
        },
    )


def _detect_text_delimiter(lines: list[str]) -> str | None:
    candidates = ["\t", "|", " "]
    for delimiter in candidates:
        counts = [len(_split_delimited_line(line, delimiter)) for line in lines if line.strip()]
        if counts and counts[0] >= 2 and len(set(counts)) == 1:
            return delimiter
    numeric_rows = [re.split(r"\s+", line.strip()) for line in lines if line.strip()]
    if numeric_rows and all(
        len(row) == 4 and all(_is_number(value) for value in row) for row in numeric_rows
    ):
        return " "
    return None


def _split_delimited_line(line: str, delimiter: str) -> list[str]:
    if delimiter == " ":
        parts = [part for part in re.split(r"\s+", line.strip()) if part]
        if len(parts) == 4 and all(_is_number(part) for part in parts):
            return parts
        return [part for part in re.split(r"\s{2,}", line.strip()) if part]
    return [part.strip() for part in line.split(delimiter)]


def _headers_for_rows(first_row: list[str], remaining_rows: list[list[str]]) -> list[str]:
    normalized = [value.strip().lower() for value in first_row]
    has_header = any(not _is_number(value) for value in first_row)
    if has_header:
        return [value or f"column_{index}" for index, value in enumerate(normalized, start=1)]
    if len(first_row) == 4 and all(
        _is_number(value) for row in remaining_rows[:3] for value in row
    ):
        return ["point_id", "x", "y", "elevation"]
    return [f"column_{index}" for index in range(1, len(first_row) + 1)]


def _is_number(value: str) -> bool:
    try:
        float(value)
        return True
    except ValueError:
        return False


def parse_csv(data: bytes, file_name: str) -> NormalizedDocument:
    text, encoding = _decode(data)
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ExtractionError("CSV file has no header row")
    rows = list(reader)
    document = NormalizedDocument(
        parser_name="csv", metadata={"encoding": encoding, "columns": reader.fieldnames}
    )
    document.items = [
        NormalizedItem("table_row", row, SourceReference(file_name=file_name, entity_id=str(index)))
        for index, row in enumerate(rows, start=2)
    ]
    return document


def parse_pdf(data: bytes, file_name: str) -> NormalizedDocument:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
    except Exception as error:
        raise ExtractionError(f"PDF could not be read: {error}") from error
    document = NormalizedDocument(parser_name="pdf", metadata={"page_count": len(reader.pages)})
    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        document.text.append(text)
        if not text.strip():
            document.warnings.append(f"Page {page_number} contains no extractable text")
        else:
            document.items.append(
                NormalizedItem(
                    "page_text", text, SourceReference(file_name=file_name, page=page_number)
                )
            )
            document.items.extend(_key_phrase_items(text.splitlines(), file_name, page=page_number))
    return document


def parse_dxf(data: str, file_name: str) -> NormalizedDocument:
    try:
        import ezdxf

        drawing = ezdxf.read(io.StringIO(data))  # type: ignore[attr-defined]
    except Exception as error:
        raise ExtractionError(f"DXF could not be read: {error}") from error
    document = NormalizedDocument(parser_name="dxf")
    for index, entity in enumerate(drawing.modelspace(), start=1):
        entity_any: Any = entity
        entity_type = entity.dxftype()
        source = SourceReference(
            file_name=file_name,
            layer=entity.dxf.layer,
            entity_type=entity_type,
            entity_id=str(index),
        )
        value: dict[str, Any] = {}
        if entity_type == "LINE":
            value = {"start": list(entity.dxf.start), "end": list(entity.dxf.end)}
        elif entity_type == "LWPOLYLINE":
            value = {"points": [list(point[:2]) for point in entity_any.get_points()]}
        elif entity_type == "POINT":
            value = {"point": list(entity.dxf.location)}
        elif entity_type == "TEXT":
            value = {"text": entity.dxf.text, "location": list(entity.dxf.insert)}
            document.text.append(entity.dxf.text)
        elif entity_type == "DIMENSION":
            value = {"text": entity.dxf.get("text", "")}
        else:
            document.warnings.append(f"Unsupported DXF entity {entity_type} at entity {index}")
            continue
        document.items.append(NormalizedItem(entity_type.lower(), value, source))
    document.metadata = {"entity_count": len(document.items)}
    return document


_LANDXML_POINT_TAGS = {"CgPoint", "P"}


def parse_landxml(data: str, file_name: str) -> NormalizedDocument:
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as error:
        raise ExtractionError(f"LandXML could not be read: {error}") from error
    if _local_tag(root) != "LandXML":
        raise ExtractionError("File is not a LandXML document")

    document = NormalizedDocument(parser_name="landxml")
    for element in root.iter():
        tag = _local_tag(element)
        if tag not in _LANDXML_POINT_TAGS:
            continue
        coordinates = _landxml_coordinates(element.text)
        if coordinates is None:
            document.warnings.append(
                f"Skipped {tag} with missing or unparsable coordinates: {element.text!r}"
            )
            continue
        point_id = element.get("name") or element.get("id") or ""
        source = SourceReference(file_name=file_name, entity_type=tag, entity_id=point_id)
        document.items.append(NormalizedItem("point", {"point": coordinates}, source))

    for alignment in root.iter():
        if _local_tag(alignment) != "Alignment":
            continue
        _extract_landxml_alignment(alignment, file_name, document)

    point_count = sum(1 for item in document.items if item.item_type == "point")
    line_count = sum(1 for item in document.items if item.item_type == "line")
    if point_count == 0 and line_count == 0:
        raise ExtractionError(
            "LandXML file contains no supported CgPoints, surface points, or alignment lines"
        )
    document.metadata = {"point_count": point_count, "alignment_line_count": line_count}
    return document


def _extract_landxml_alignment(
    alignment: ElementTree.Element, file_name: str, document: NormalizedDocument
) -> None:
    name = alignment.get("name", "")
    for coord_geom in alignment:
        if _local_tag(coord_geom) != "CoordGeom":
            continue
        for index, segment in enumerate(coord_geom, start=1):
            segment_tag = _local_tag(segment)
            if segment_tag == "Line":
                start = end = None
                for child in segment:
                    child_tag = _local_tag(child)
                    if child_tag == "Start":
                        start = _landxml_coordinates(child.text)
                    elif child_tag == "End":
                        end = _landxml_coordinates(child.text)
                if start is None or end is None:
                    document.warnings.append(
                        f"Alignment '{name}' segment {index} (Line) is missing Start/End "
                        "coordinates"
                    )
                    continue
                source = SourceReference(
                    file_name=file_name,
                    entity_type="alignment_line",
                    entity_id=f"{name}:{index}",
                )
                document.items.append(NormalizedItem("line", {"start": start, "end": end}, source))
            elif segment_tag in {"Curve", "Spiral"}:
                document.warnings.append(
                    f"Alignment '{name}' segment {index} ({segment_tag}) was not extracted: "
                    "curved alignment geometry is not supported, only straight Line segments"
                )


def _local_tag(element: ElementTree.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _landxml_coordinates(text: str | None) -> list[float] | None:
    if not text:
        return None
    parts = text.split()
    if len(parts) not in (2, 3):
        return None
    try:
        values = [float(part) for part in parts]
    except ValueError:
        return None
    # LandXML coordinate order is northing, easting, [elevation]; convert to this
    # app's (x=easting, y=northing, [z=elevation]) convention used everywhere else.
    northing, easting, *elevation = values
    return [easting, northing, *elevation]


def parse_tiff(data: bytes, file_name: str) -> NormalizedDocument:
    try:
        from PIL import Image

        image = Image.open(io.BytesIO(data))
        metadata = {
            "format": image.format,
            "width": image.width,
            "height": image.height,
            "mode": image.mode,
            "frame_count": getattr(image, "n_frames", 1),
        }
    except Exception as error:
        raise ExtractionError(f"TIFF could not be read: {error}") from error
    return NormalizedDocument(
        parser_name="tiff",
        items=[
            NormalizedItem(
                "raster_metadata",
                metadata,
                SourceReference(file_name=file_name, entity_type="raster"),
            )
        ],
        metadata=metadata,
        warnings=["OCR is not enabled for TIFF images"],
    )


def _decode(data: bytes) -> tuple[str, str]:
    for encoding in ("utf-8", "utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise ExtractionError("File encoding is not supported")
