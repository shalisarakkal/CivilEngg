from pathlib import Path

import ezdxf
import pytest

from civil_engineering.plan_snippets import PlanSnippetError, render_dxf_snippet


def _build_dxf(path: Path) -> None:
    drawing = ezdxf.new("R2010")  # type: ignore[attr-defined]
    modelspace = drawing.modelspace()
    modelspace.add_line((0, 0), (10, 0), dxfattribs={"layer": "PROPERTY"})
    modelspace.add_line((0, 0), (0, 10), dxfattribs={"layer": "BUILDING"})
    drawing.saveas(path)


def test_render_dxf_snippet_highlights_the_matching_entity(tmp_path: Path) -> None:
    path = tmp_path / "site.dxf"
    _build_dxf(path)

    svg = render_dxf_snippet(path, "2")
    assert svg.startswith("<?xml")
    assert "#ff0000" in svg  # the highlighted (second) line
    assert "#ffffff" in svg  # white background


def test_render_dxf_snippet_rejects_unknown_entity_id(tmp_path: Path) -> None:
    path = tmp_path / "site.dxf"
    _build_dxf(path)

    with pytest.raises(PlanSnippetError, match="was not found"):
        render_dxf_snippet(path, "99")


def test_render_dxf_snippet_rejects_malformed_dxf(tmp_path: Path) -> None:
    path = tmp_path / "broken.dxf"
    path.write_text("not a dxf", encoding="utf-8")

    with pytest.raises(PlanSnippetError, match="DXF could not be read"):
        render_dxf_snippet(path, "1")
