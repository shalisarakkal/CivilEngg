from pathlib import Path

from civil_engineering.extraction import parse_text


def test_text_extraction_preserves_lines_for_aggregation() -> None:
    document = parse_text(b"line one\nline two\n", "notes.txt")

    assert len(document.items) == 2
    assert [item.item_type for item in document.items] == ["text_line", "text_line"]
    assert Path(document.items[0].source.file_name).name == "notes.txt"
