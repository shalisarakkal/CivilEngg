from pathlib import Path

import ezdxf
from ezdxf.addons.drawing import Frontend, RenderContext  # type: ignore[attr-defined]
from ezdxf.addons.drawing.config import BackgroundPolicy, ColorPolicy, Configuration
from ezdxf.addons.drawing.layout import Page
from ezdxf.addons.drawing.svg import SVGBackend


class PlanSnippetError(ValueError):
    pass


# AutoCAD Color Index 1 = red; used to highlight the target entity against the
# white-background, black-line rendering set up below.
_HIGHLIGHT_ACI_COLOR = 1

_SNIPPET_CONFIG = Configuration(
    background_policy=BackgroundPolicy.WHITE, color_policy=ColorPolicy.COLOR_SWAP_BW
)


def render_dxf_snippet(stored_path: Path, entity_id: str) -> str:
    """Render a DXF file to SVG with one entity highlighted in red.

    entity_id must be the 1-based modelspace index that extraction.py's parse_dxf()
    assigns as each entity's SourceReference.entity_id, so this highlights the same
    entity a site-model entity's source_reference points back to.
    """
    try:
        drawing = ezdxf.readfile(stored_path)  # type: ignore[attr-defined]
    except Exception as error:
        raise PlanSnippetError(f"DXF could not be read: {error}") from error
    modelspace = drawing.modelspace()
    highlighted = False
    for index, entity in enumerate(modelspace, start=1):
        if str(index) == entity_id:
            entity.dxf.color = _HIGHLIGHT_ACI_COLOR
            highlighted = True
            break
    if not highlighted:
        raise PlanSnippetError(f"Entity {entity_id} was not found in {stored_path.name}")
    backend = SVGBackend()
    context = RenderContext(drawing)
    frontend = Frontend(context, backend, config=_SNIPPET_CONFIG)
    frontend.draw_layout(modelspace, finalize=True)
    return backend.get_string(page=Page(0, 0))
