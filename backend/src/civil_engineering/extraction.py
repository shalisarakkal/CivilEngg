import csv
import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


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
    raise ExtractionError(f"Unsupported extraction type: {suffix or 'unknown'}")


def parse_text(data: bytes, file_name: str) -> NormalizedDocument:
    text, encoding = _decode(data)
    document = NormalizedDocument(parser_name="text", text=text.splitlines())
    document.metadata = {"encoding": encoding, "line_count": len(document.text)}
    document.items = [
        NormalizedItem(
            "text_line", line, SourceReference(file_name=file_name, entity_id=str(index))
        )
        for index, line in enumerate(document.text, start=1)
        if line.strip()
    ]
    return document


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
