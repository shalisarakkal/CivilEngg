import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Protocol

import shapely
from shapely.geometry import Polygon, shape

from civil_engineering.calculations import (
    CalculationError,
    calculate_area,
    calculate_distance,
    calculate_perimeter,
    calculate_slope,
)
from civil_engineering.site_model import is_geographic_crs

DRAINAGE_KEYWORDS = ("storm", "drain", "culvert", "swale", "detention", "retention")
UTILITY_KEYWORDS = ("water", "sewer", "gas", "electric", "utility", "manhole", "hydrant")

# Compass direction -> (coordinate axis, sign) for picking the entity furthest in that
# direction; north/south compare y (northing), east/west compare x (easting), matching
# the coordinate convention used throughout the app (see extraction.py's LandXML note).
DIRECTION_AXES: dict[str, tuple[int, float]] = {
    "north": (1, 1.0),
    "south": (1, -1.0),
    "east": (0, 1.0),
    "west": (0, -1.0),
}

# Question-language role -> the semantic_type classification it refers to (see
# routes.py's _classify_entity). Matched as whole words (see _question_role), so
# ordering between phrases for different roles doesn't matter here -- unlike a bare
# substring match, "parking" and "parking lot" can't collide with an unrelated role's
# phrase the way "lot" would collide with the ordinary English phrase "a lot of" (a
# bare "lot" role phrase was tried and dropped for exactly that reason).
ROLE_TO_SEMANTIC_TYPE = {
    "property line": "parcel_boundary",
    "property boundary": "parcel_boundary",
    "property": "parcel_boundary",
    "parcel boundary": "parcel_boundary",
    "parcel": "parcel_boundary",
    "building footprint": "building_footprint",
    "building": "building_footprint",
    "footprint": "building_footprint",
    "driveway": "driveway_road",
    "road": "driveway_road",
    "curb cut": "curb_cut",
    # PLAN.md Phase 14: roles TestQuestions asks about that had no semantic_type or
    # role phrase at all before this (see the matching keyword vocabulary in
    # routes.py's _semantic_type_from_text).
    "utility easement": "utility_easement",
    "easement": "utility_easement",
    "parking lot": "parking",
    "parking space": "parking",
    "parking": "parking",
    "tree": "tree",
    "sidewalk": "sidewalk",
    "walkway": "sidewalk",
    "detention basin": "detention_basin",
    "retention basin": "detention_basin",
    "detention pond": "detention_basin",
    "basin": "detention_basin",
}

# Question intents answered by measuring positions on a plane. They need a projected
# CRS to mean anything (see routes.py's PLANAR_CALCULATION_TYPES); "elevation" is left
# out because it only summarizes z values, and "summary" is degraded with a flag rather
# than refused, since most of what it reports is not a measurement.
PLANAR_INTENTS = frozenset(
    {
        "directional_distance",
        "distance",
        "slope",
        "area",
        "perimeter",
        "dimensions",
        "orientation",
        "setback_compliance",
    }
)

GEOGRAPHIC_CRS_FLAG = (
    "Project coordinates are geographic (lat/lon degrees); distances, slopes, and "
    "clearances derived from them are not reliable measurements."
)

# Heuristic thresholds for attention flags, not engineering code requirements.
STEEP_SLOPE_PERCENT = 15.0
TIGHT_SETBACK_UNITS = 5.0
UNUSUAL_ELEVATION_RANGE = 100.0

PROMPT_INJECTION_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"ignore (all|any)?\s*(previous|prior|above)\s*instructions",
        r"disregard (the )?(above|previous|all)",
        r"you are now",
        r"system prompt",
        r"new instructions\s*:",
        r"act as (an|a)\s",
    )
]


class AIProvider(Protocol):
    def summarize(self, context: dict[str, Any]) -> dict[str, Any]: ...

    def answer(self, question: str, context: dict[str, Any]) -> dict[str, Any]: ...


def sanitize_source_text(lines: list[str]) -> tuple[list[str], list[str]]:
    """Strip suspected prompt-injection content from untrusted extracted text.

    Extracted document text is data, never instructions. Lines matching known
    injection phrasing are redacted and reported as flags instead of being
    passed on to summaries or answers.
    """
    cleaned: list[str] = []
    flags: list[str] = []
    for line in lines:
        if any(pattern.search(line) for pattern in PROMPT_INJECTION_PATTERNS):
            cleaned.append("[REDACTED: suspected prompt-injection content removed]")
            flags.append(
                f"Removed suspected prompt-injection content from source text: {line[:80]!r}"
            )
        else:
            cleaned.append(line)
    return cleaned, flags


def route_question(question: str) -> str:
    normalized = question.lower()
    if _parse_directional_question(question) is not None:
        return "directional_distance"
    if _extract_el_tokens(question):
        # More specific than the bare "elevation" catch below: the question names
        # an actual labeled spot elevation (e.g. "EL 102.5"), so it can be answered
        # by looking that label up rather than only reporting the overall range.
        return "elevation_lookup"
    if "setback" in normalized and _question_role(question) == "building_footprint":
        # More specific than the generic setback/distance catch below: a question
        # about whether *the building* meets its setbacks needs the building's
        # actual clearance from the parcel boundary, not an arbitrary pair of
        # "the only two mapped geometries in the model" (PLAN.md Phase 14).
        return "setback_compliance"
    if "setback" in normalized or "distance" in normalized:
        return "distance"
    if "slope" in normalized:
        return "slope"
    if "elevation" in normalized:
        return "elevation"
    if "perimeter" in normalized:
        return "perimeter"
    if "area" in normalized:
        return "area"
    if "how many" in normalized and _question_role(question) is not None:
        return "count"
    if "orientation" in normalized and _question_role(question) is not None:
        return "orientation"
    if (
        any(keyword in normalized for keyword in ("dimensions", "width", "length"))
        and _question_role(question) is not None
    ):
        return "dimensions"
    if any(keyword in normalized for keyword in DRAINAGE_KEYWORDS):
        return "drainage"
    if any(keyword in normalized for keyword in UTILITY_KEYWORDS):
        return "utility"
    return "summary"


def _question_role(question: str) -> str | None:
    """The semantic_type a role phrase in the question refers to (see
    ROLE_TO_SEMANTIC_TYPE), or None if the question doesn't name one."""
    normalized = question.lower()
    # Word-boundary match, not a bare substring: a short bare phrase like "tree"
    # is a literal substring of an unrelated word ("street") -- the same hazard
    # fixed for DIRECTION_AXES below. An optional trailing "s" still matches an
    # ordinary plural ("trees", "buildings") without a boundary between the
    # phrase and the "s" defeating the match entirely.
    role = next(
        (
            phrase
            for phrase in ROLE_TO_SEMANTIC_TYPE
            if re.search(rf"\b{re.escape(phrase)}s?\b", normalized)
        ),
        None,
    )
    return ROLE_TO_SEMANTIC_TYPE[role] if role is not None else None


# A labeled spot elevation on a civil plan (e.g. "EL 102.5", "EL=101.0"). Deliberately
# narrower than a bare number: plans use this specific convention (see TestQuestions),
# so requiring the "EL" prefix avoids misrouting an ordinary elevation question that
# happens to contain an unrelated number.
_EL_TOKEN_PATTERN = re.compile(r"\bel\s*[:=]?\s*(\d+(?:\.\d+)?)", re.IGNORECASE)


def _extract_el_tokens(question: str) -> list[float]:
    return [float(match) for match in _EL_TOKEN_PATTERN.findall(question)]


def _parse_directional_question(question: str) -> tuple[str, str] | None:
    normalized = question.lower()
    # Word-boundary match, not a bare substring check: "east" is a substring of
    # ordinary English words like "at least", which would otherwise misroute any
    # threshold-style question ("at least 25 ft") as asking about compass east.
    direction = next(
        (word for word in DIRECTION_AXES if re.search(rf"\b{word}\b", normalized)), None
    )
    if direction is None:
        return None
    semantic_type = _question_role(question)
    if semantic_type is None:
        return None
    return direction, semantic_type


def _point_z(geometry: dict[str, Any] | None) -> float | None:
    if not geometry or geometry.get("type") != "Point":
        return None
    coordinates = geometry.get("coordinates")
    if isinstance(coordinates, (list, tuple)) and len(coordinates) >= 3:
        return float(coordinates[2])
    return None


def _line_endpoints(geometry: dict[str, Any] | None) -> list[tuple[float, float, float]] | None:
    if not geometry or geometry.get("type") != "LineString":
        return None
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list) or len(coordinates) < 2:
        return None
    start, end = coordinates[0], coordinates[-1]
    if len(start) < 3 or len(end) < 3:
        return None
    return [tuple(start[:3]), tuple(end[:3])]


def _horizontal_distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _elevation_points(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for entity in entities:
        if entity.get("validation_status") != "valid":
            continue
        geometry = entity.get("geometry")
        z = _point_z(geometry)
        if z is not None and geometry is not None:
            coordinates = geometry["coordinates"]
            points.append(
                {
                    "x": coordinates[0],
                    "y": coordinates[1],
                    "z": z,
                    "source_reference": entity.get("source_reference"),
                }
            )
            continue
        endpoints = _line_endpoints(geometry)
        if endpoints is not None:
            for x, y, z_value in endpoints:
                points.append(
                    {
                        "x": x,
                        "y": y,
                        "z": z_value,
                        "source_reference": entity.get("source_reference"),
                    }
                )
    return points


def _comparable_geometries(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        entity
        for entity in entities
        if entity.get("geometry") and entity.get("validation_status") == "valid"
    ]


def _entity_text(entity: dict[str, Any]) -> str:
    source = entity.get("source_reference") or {}
    properties = entity.get("properties") or {}
    return " ".join(
        str(value)
        for value in (
            entity.get("entity_type", ""),
            source.get("layer") or "",
            properties.get("text", ""),
            # PLAN.md Phase 14: a geometry entity's semantic_type (routes.py's
            # _classify_entity) names its role even when the source layer/text
            # doesn't literally contain a drainage/utility keyword -- e.g. a
            # "detention_basin" polygon should surface in a drainage rollup
            # regardless of what its CAD layer happens to be called.
            properties.get("semantic_type", ""),
        )
    ).lower()


def _keyword_matches(
    entities: list[dict[str, Any]], keywords: tuple[str, ...]
) -> list[dict[str, Any]]:
    return [
        entity
        for entity in entities
        if any(keyword in _entity_text(entity) for keyword in keywords)
    ]


def _grading_summary(entities: list[dict[str, Any]]) -> str:
    values = [point["z"] for point in _elevation_points(entities)]
    if not values:
        return "No grading summary available from the supplied data."
    return (
        f"Elevations range from {min(values):.2f} to {max(values):.2f} across "
        f"{len(values)} referenced points (average {sum(values) / len(values):.2f})."
    )


def _keyword_summary(entities: list[dict[str, Any]], keywords: tuple[str, ...], label: str) -> str:
    matches = _keyword_matches(entities, keywords)
    if not matches:
        return f"No {label} information found in the supplied data."
    layers = sorted(
        {
            str((entity.get("source_reference") or {}).get("layer") or entity.get("entity_type"))
            for entity in matches
        }
    )
    return f"{len(matches)} {label}-related entities identified on: {', '.join(layers)}."


def _answer_keyword_topic(
    entities: list[dict[str, Any]], keywords: tuple[str, ...], label: str
) -> dict[str, Any]:
    """A question-answer version of _keyword_summary (PLAN.md Phase 14): the summary
    endpoint already rolled drainage/utility entities up into a sentence, but the
    question endpoint had no way to reach that rollup at all -- a question like "Is a
    utility easement shown?" fell all the way through to the generic text fallback."""
    matches = _keyword_matches(entities, keywords)
    if not matches:
        return _insufficient(f"No {label}-related entities were found in the extracted data.")
    layers = sorted(
        {
            str((entity.get("source_reference") or {}).get("layer") or entity.get("entity_type"))
            for entity in matches
        }
    )
    return {
        "answer": f"{len(matches)} {label}-related entities identified on: {', '.join(layers)}.",
        "method": "keyword-matched entity retrieval",
        "result": float(len(matches)),
        "unit": "count",
        "source_references": [entity.get("source_reference") for entity in matches],
        "limitations": [
            f"Identifies {label}-related entities by layer name, label text, type "
            "column, or semantic classification keyword; a feature not named or "
            "classified this way would not be found."
        ],
        "confidence": 0.6,
    }


def _attention_flags(entities: list[dict[str, Any]], warnings: list[str]) -> list[str]:
    flags = list(warnings)

    invalid = [
        entity for entity in entities if entity.get("validation_status") not in (None, "valid")
    ]
    if invalid:
        counts = Counter(entity.get("validation_status") for entity in invalid)
        summary = ", ".join(f"{count} {status}" for status, count in counts.items())
        flags.append(f"Entities excluded from spatial summaries: {summary}.")

    for entity in entities:
        endpoints = _line_endpoints(entity.get("geometry"))
        if endpoints is None:
            continue
        start, end = endpoints
        horizontal = _horizontal_distance(start, end)
        if horizontal <= 0:
            continue
        percent = abs((end[2] - start[2]) / horizontal * 100)
        if percent >= STEEP_SLOPE_PERCENT:
            reference = entity.get("source_reference") or {}
            layer = reference.get("layer") or entity.get("entity_type")
            entity_id = reference.get("entity_id", "unknown")
            flags.append(f"Steep slope ({percent:.1f}%) detected on {layer} (entity {entity_id}).")

    elevations = [point["z"] for point in _elevation_points(entities)]
    if elevations and max(elevations) - min(elevations) >= UNUSUAL_ELEVATION_RANGE:
        flags.append(
            f"Unusual elevation range detected: {min(elevations):.2f} to {max(elevations):.2f}."
        )

    comparable = _comparable_geometries(entities)
    if len(comparable) == 2:
        try:
            result = calculate_distance(
                comparable[0]["geometry"], comparable[1]["geometry"], "m", "m"
            )
        except CalculationError:
            result = None
        if result is not None and result["result"] < TIGHT_SETBACK_UNITS:
            clearance = f"{result['result']:.2f} {result['unit']}"
            flags.append(
                f"Tight clearance ({clearance}) detected between two entities; "
                "verify setback compliance."
            )

    if not flags:
        flags.append("No attention items identified from the supplied data.")
    return flags


def _insufficient(reason: str) -> dict[str, Any]:
    return {
        "answer": "Insufficient data to answer this question.",
        "method": "source-grounded mock provider",
        "source_references": [],
        "limitations": [reason],
        "confidence": 0.0,
    }


def _ambiguous(candidates: list[dict[str, Any]], reason: str) -> dict[str, Any]:
    return {
        "answer": "This question is ambiguous given the available data.",
        "method": "clarification needed",
        "source_references": [candidate.get("source_reference") for candidate in candidates],
        "limitations": [reason, "Specify which entities to use, for example by source reference."],
        "confidence": 0.0,
    }


def _answer_distance(comparable: list[dict[str, Any]]) -> dict[str, Any]:
    if len(comparable) < 2:
        return _insufficient(
            "No two mapped geometries are available to measure a distance or setback between."
        )
    if len(comparable) > 2:
        return _ambiguous(
            comparable, "Multiple mapped geometries could define this distance or setback."
        )
    first, second = comparable
    try:
        result = calculate_distance(first["geometry"], second["geometry"], "m", "m")
    except CalculationError as error:
        return _insufficient(f"Distance could not be calculated: {error}")
    return {
        "answer": f"The measured distance is {result['result']:.3f} {result['unit']}.",
        "method": "deterministic geometry calculation",
        "formula": result["formula"],
        "result": result["result"],
        "unit": result["unit"],
        "source_references": [first.get("source_reference"), second.get("source_reference")],
        "limitations": [
            "Assumes both geometries share the same coordinate unit and reference frame."
        ],
        "confidence": 0.9,
    }


def _geometry_type_candidates(
    entities: list[dict[str, Any]], geometry_types: set[str]
) -> list[dict[str, Any]]:
    return [
        entity
        for entity in entities
        if entity.get("validation_status") == "valid"
        and (geometry := entity.get("geometry")) is not None
        and geometry.get("type") in geometry_types
    ]


def _answer_count(question: str, entities: list[dict[str, Any]]) -> dict[str, Any]:
    """ "How many X are shown?" (PLAN.md Phase 14). Zero matches is reported as
    insufficient data rather than an affirmative "none" -- semantic classification is
    deterministic and keyword-based (see RISK_REGISTER.md), so an empty result could
    just as easily mean the feature was never classified as that it's truly absent,
    and this app never guesses which."""
    role = _question_role(question)
    if role is None:
        return _insufficient("Could not identify which feature the question is counting.")
    candidates = [
        entity
        for entity in entities
        if entity.get("validation_status") == "valid"
        and (entity.get("properties") or {}).get("semantic_type") == role
    ]
    role_label = role.replace("_", " ")
    if not candidates:
        return _insufficient(
            f"No entities were classified as {role_label} in the extracted data; this may "
            "mean none are shown, or that none were recognized from the source layer/type."
        )
    return {
        "answer": f"{len(candidates)} {role_label} entities were found.",
        "method": "deterministic entity count",
        "result": float(len(candidates)),
        "unit": "count",
        "source_references": [entity.get("source_reference") for entity in candidates],
        "limitations": [
            "Counts only entities classified from a layer name, label text, or type "
            "column; an unclassified feature of this kind would not be counted."
        ],
        "confidence": 0.8,
    }


def _answer_area(question: str, entities: list[dict[str, Any]]) -> dict[str, Any]:
    # Area is a property of one closed shape, not a relationship between two
    # geometries -- unlike _answer_distance, this needs exactly one candidate.
    candidates = _geometry_type_candidates(entities, {"Polygon", "MultiPolygon", "Circle"})
    role = _question_role(question)
    if role is not None:
        # Narrow to the role the question actually named (e.g. "property" ->
        # parcel_boundary) so a model with both a parcel boundary and a
        # building footprint doesn't collide on the same candidate pool and
        # report "ambiguous" when the question was specific about which one
        # it meant (PLAN.md Phase 14).
        candidates = [
            entity
            for entity in candidates
            if (entity.get("properties") or {}).get("semantic_type") == role
        ]
    if not candidates:
        role_label = f"{role.replace('_', ' ')} " if role is not None else ""
        return _insufficient(
            f"No mapped {role_label}polygon geometry is available to measure an area."
        )
    if len(candidates) > 1:
        return _ambiguous(candidates, "Multiple mapped polygons could define this area.")
    entity = candidates[0]
    try:
        result = calculate_area(entity["geometry"], "m", "m")
    except CalculationError as error:
        return _insufficient(f"Area could not be calculated: {error}")
    return {
        "answer": f"The measured area is {result['result']:.3f} {result['unit']}.",
        "method": "deterministic geometry calculation",
        "formula": result["formula"],
        "result": result["result"],
        "unit": result["unit"],
        "source_references": [entity.get("source_reference")],
        "limitations": ["Assumes the geometry is measured in the requested output unit."],
        "confidence": 0.9,
    }


def _answer_perimeter(question: str, entities: list[dict[str, Any]]) -> dict[str, Any]:
    # Perimeter sums every segment of one shape (open or closed), not a
    # relationship between two geometries -- unlike _answer_distance, this
    # needs exactly one candidate.
    candidates = _geometry_type_candidates(
        entities, {"LineString", "MultiLineString", "Polygon", "MultiPolygon", "Circle"}
    )
    role = _question_role(question)
    if role is not None:
        # See the matching comment in _answer_area: narrow to the role the
        # question named instead of colliding on every candidate (PLAN.md
        # Phase 14).
        candidates = [
            entity
            for entity in candidates
            if (entity.get("properties") or {}).get("semantic_type") == role
        ]
    if not candidates:
        role_label = f"{role.replace('_', ' ')} " if role is not None else ""
        return _insufficient(
            f"No mapped {role_label}line or polygon geometry is available to measure a perimeter."
        )
    if len(candidates) > 1:
        return _ambiguous(candidates, "Multiple mapped geometries could define this perimeter.")
    entity = candidates[0]
    try:
        result = calculate_perimeter(entity["geometry"], "m", "m")
    except CalculationError as error:
        return _insufficient(f"Perimeter could not be calculated: {error}")
    return {
        "answer": f"The measured perimeter is {result['result']:.3f} {result['unit']}.",
        "method": "deterministic geometry calculation",
        "formula": result["formula"],
        "result": result["result"],
        "unit": result["unit"],
        "source_references": [entity.get("source_reference")],
        "limitations": ["Assumes the geometry is measured in the requested output unit."],
        "confidence": 0.9,
    }


def _resolve_role_polygon(
    question: str, entities: list[dict[str, Any]], purpose: str
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Resolve exactly one polygon entity for dimension/orientation questions,
    narrowed by the question's named role when it has one. Returns (entity, None) on
    success, or (None, error_response) with the same insufficient/ambiguous shape
    _answer_area/_answer_perimeter use (PLAN.md Phase 14)."""
    role = _question_role(question)
    candidates = _geometry_type_candidates(entities, {"Polygon", "MultiPolygon"})
    if role is not None:
        candidates = [
            entity
            for entity in candidates
            if (entity.get("properties") or {}).get("semantic_type") == role
        ]
    role_label = f"{role.replace('_', ' ')} " if role is not None else ""
    if not candidates:
        return None, _insufficient(
            f"No mapped {role_label}polygon geometry is available to measure {purpose}."
        )
    if len(candidates) > 1:
        return None, _ambiguous(
            candidates, f"Multiple mapped {role_label}polygons could define this {purpose}."
        )
    return candidates[0], None


def _oriented_rectangle_sides(geometry_data: dict[str, Any]) -> tuple[float, float, float] | None:
    """(width, length, orientation_degrees) of a polygon's minimum-area oriented
    bounding rectangle, or None if the geometry isn't a polygon. width <= length by
    definition; orientation is the compass bearing (0 = north, clockwise) of the
    rectangle's long axis, reduced mod 180 since an axis (unlike a direction) has no
    inherent sense."""
    geometry = shape(geometry_data)
    if geometry.geom_type not in {"Polygon", "MultiPolygon"}:
        return None
    rectangle = shapely.oriented_envelope(geometry)
    if not isinstance(rectangle, Polygon):
        # A degenerate input (e.g. a near-zero-area sliver) can collapse to a
        # Point or LineString instead of a rectangle; there's no width/length to
        # report from that.
        return None
    coordinates = list(rectangle.exterior.coords)
    if len(coordinates) < 4:
        return None
    first, second, third = coordinates[0], coordinates[1], coordinates[2]
    side_a = math.hypot(second[0] - first[0], second[1] - first[1])
    side_b = math.hypot(third[0] - second[0], third[1] - second[1])
    width, length = min(side_a, side_b), max(side_a, side_b)
    long_side = (first, second) if side_a >= side_b else (second, third)
    dx = long_side[1][0] - long_side[0][0]
    dy = long_side[1][1] - long_side[0][1]
    orientation = math.degrees(math.atan2(dx, dy)) % 180
    return width, length, orientation


def _dimension_kind(question: str) -> str:
    normalized = question.lower()
    has_width = "width" in normalized
    has_length = "length" in normalized
    if has_width and not has_length:
        return "width"
    if has_length and not has_width:
        return "length"
    return "both"


def _answer_dimensions(question: str, entities: list[dict[str, Any]]) -> dict[str, Any]:
    entity, error = _resolve_role_polygon(question, entities, "dimensions")
    if error is not None:
        return error
    assert entity is not None
    sides = _oriented_rectangle_sides(entity["geometry"])
    if sides is None:
        return _insufficient(
            "The resolved geometry is not a polygon; dimensions require an enclosed shape."
        )
    width, length, orientation = sides
    kind = _dimension_kind(question)
    if kind == "width":
        answer = f"The measured width (shorter side of the bounding rectangle) is {width:.3f} m."
        result = width
    elif kind == "length":
        answer = f"The measured length (longer side of the bounding rectangle) is {length:.3f} m."
        result = length
    else:
        answer = f"The measured dimensions are approximately {length:.3f} m by {width:.3f} m."
        result = length
    return {
        "answer": answer,
        "method": "deterministic minimum-area bounding-rectangle calculation",
        "formula": "minimum-area oriented bounding rectangle of the polygon",
        "result": result,
        "unit": "m",
        "width": width,
        "length": length,
        "orientation_degrees": orientation,
        "source_references": [entity.get("source_reference")],
        "limitations": [
            "The bounding rectangle approximates the shape's footprint; an irregular "
            "(non-rectangular) polygon's true width/length may differ.",
            "Assumes the geometry is measured in metres.",
        ],
        "confidence": 0.8,
    }


def _answer_orientation(question: str, entities: list[dict[str, Any]]) -> dict[str, Any]:
    entity, error = _resolve_role_polygon(question, entities, "orientation")
    if error is not None:
        return error
    assert entity is not None
    sides = _oriented_rectangle_sides(entity["geometry"])
    if sides is None:
        return _insufficient(
            "The resolved geometry is not a polygon; orientation requires an enclosed shape."
        )
    _width, _length, orientation = sides
    return {
        "answer": (
            f"The shape's long axis is oriented approximately {orientation:.1f} degrees from north."
        ),
        "method": "deterministic minimum-area bounding-rectangle calculation",
        "formula": "compass bearing of the long side of the polygon's oriented bounding rectangle",
        "result": orientation,
        "unit": "degrees",
        "source_references": [entity.get("source_reference")],
        "limitations": [
            "The bounding rectangle approximates the shape's footprint; an irregular "
            "(non-rectangular) polygon's true orientation may differ.",
            "Reported as an axis (0-180 degrees), since a rectangle's long side has no "
            "inherent direction.",
        ],
        "confidence": 0.75,
    }


# A required setback distance stated directly in the question (e.g. "at least 25 ft").
# Requires an explicit unit so an unrelated number in the question (a year, a sheet
# number) is never mistaken for one -- never guessed from anywhere else, since the
# project has no general way to read a stated setback requirement back out of
# extracted text (see RISK_REGISTER.md's key-phrase/label-linking limitations).
_SETBACK_THRESHOLD_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*(ft|feet|foot|m|meters?|metres?)\b", re.IGNORECASE
)


def _question_setback_threshold(question: str) -> tuple[float, str] | None:
    match = _SETBACK_THRESHOLD_PATTERN.search(question)
    if match is None:
        return None
    value = float(match.group(1))
    unit = match.group(2).lower()
    unit = "ft" if unit in ("ft", "feet", "foot") else "m"
    return value, unit


def _answer_setback_compliance(question: str, entities: list[dict[str, Any]]) -> dict[str, Any]:
    """Whether a building footprint clears the parcel boundary by at least a stated
    setback (PLAN.md Phase 14), replacing the previous behavior of routing any
    building-setback question to the generic "exactly two mapped geometries in the
    whole model" distance answer, which collides in any site model with more than two
    mapped geometries. Measures the actual clearance from the building's edge to the
    property line (boundary-to-boundary, not polygon-to-polygon, since two nested
    filled polygons are always "touching" and would otherwise measure zero)."""
    buildings = [
        entity
        for entity in _geometry_type_candidates(entities, {"Polygon", "MultiPolygon"})
        if (entity.get("properties") or {}).get("semantic_type") == "building_footprint"
    ]
    if not buildings:
        return _insufficient("No mapped building footprint is available to check its setback.")
    if len(buildings) > 1:
        return _ambiguous(buildings, "Multiple mapped building footprints could be meant.")
    parcels = [
        entity
        for entity in _geometry_type_candidates(entities, {"Polygon", "MultiPolygon"})
        if (entity.get("properties") or {}).get("semantic_type") == "parcel_boundary"
    ]
    if not parcels:
        return _insufficient(
            "No mapped parcel boundary is available to measure the building's clearance against."
        )
    if len(parcels) > 1:
        return _ambiguous(parcels, "Multiple mapped parcel boundaries could be meant.")
    building_entity, parcel_entity = buildings[0], parcels[0]
    clearance = shape(building_entity["geometry"]).boundary.distance(
        shape(parcel_entity["geometry"]).boundary
    )
    source_references = [
        building_entity.get("source_reference"),
        parcel_entity.get("source_reference"),
    ]
    threshold = _question_setback_threshold(question)
    if threshold is None:
        return {
            "answer": (
                f"The building footprint is approximately {clearance:.3f} coordinate units "
                "from the parcel boundary. No specific required setback distance was stated "
                "in the question, so compliance cannot be determined automatically."
            ),
            "method": "deterministic geometry calculation",
            "formula": "distance(building footprint boundary, parcel boundary)",
            "result": clearance,
            "unit": "coordinate units",
            "source_references": source_references,
            "limitations": [
                "No required setback value was supplied in the question; only the "
                "measured clearance is reported."
            ],
            "confidence": 0.75,
        }
    threshold_value, threshold_unit = threshold
    # Compared directly, not converted: this function has no way to know what real
    # unit the project's raw coordinates are actually in (that lives on the
    # Project, never passed down here), so converting only the *threshold* to true
    # metres while leaving `clearance` in whatever unit the coordinates happen to
    # be would silently compare mismatched units -- e.g. a real 20 ft clearance
    # against a stated "at least 25 ft" setback would wrongly convert 25 ft to
    # 7.62 (true metres) and report "compliant" (20 >= 7.62) when it is not. The
    # honest alternative is the same assumption already used throughout this file
    # (e.g. _answer_distance): the caller's stated unit is taken to match the
    # project's own coordinate unit.
    compliant = clearance >= threshold_value
    return {
        "answer": (
            f"The building footprint is approximately {clearance:.3f} {threshold_unit} from "
            f"the parcel boundary, which is {'at least' if compliant else 'less than'} the "
            f"stated {threshold_value:g} {threshold_unit} setback "
            f"({'compliant' if compliant else 'not compliant'})."
        ),
        "method": "deterministic geometry calculation",
        "formula": "distance(building footprint boundary, parcel boundary) >= stated setback",
        "result": clearance,
        "unit": threshold_unit,
        "source_references": source_references,
        "limitations": [
            "Assumes the project's coordinates are already measured in the same unit as "
            "the stated setback; no unit conversion is applied.",
            "Checks clearance from the parcel boundary itself; does not account for a "
            "separate setback line that differs from the property line.",
        ],
        "confidence": 0.85,
    }


def _entity_centroid(entity: dict[str, Any]) -> tuple[float, float] | None:
    geometry = entity.get("geometry")
    if not geometry:
        return None
    geom_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if geom_type == "Point":
        return (coordinates[0], coordinates[1])
    if geom_type == "LineString":
        xs, ys = zip(*[(point[0], point[1]) for point in coordinates], strict=True)
        return (sum(xs) / len(xs), sum(ys) / len(ys))
    if geom_type == "Polygon":
        # GeoJSON/Shapely rings repeat the first point as the last to close the
        # ring; drop it so the average isn't skewed by double-counting that
        # one vertex.
        ring = coordinates[0][:-1]
        xs, ys = zip(*[(point[0], point[1]) for point in ring], strict=True)
        return (sum(xs) / len(xs), sum(ys) / len(ys))
    return None


def _answer_directional(question: str, entities: list[dict[str, Any]]) -> dict[str, Any]:
    parsed = _parse_directional_question(question)
    if parsed is None:
        return _insufficient("Could not identify a compass direction and entity role.")
    direction, semantic_type = parsed
    role_label = semantic_type.replace("_", " ")
    axis, sign = DIRECTION_AXES[direction]
    candidates = [
        (entity, centroid)
        for entity in entities
        if entity.get("validation_status") == "valid"
        and (entity.get("properties") or {}).get("semantic_type") == semantic_type
        and (centroid := _entity_centroid(entity)) is not None
    ]
    if not candidates:
        return _insufficient(f"No {role_label} entities were found to resolve '{direction}'.")
    chosen, _ = max(candidates, key=lambda pair: sign * pair[1][axis])
    others = _comparable_geometries(
        [
            entity
            for entity in entities
            if entity is not chosen
            and (entity.get("properties") or {}).get("semantic_type") != semantic_type
        ]
    )
    if not others:
        return _insufficient(
            f"Resolved the {direction} {role_label}, but no other mapped geometry is "
            "available to measure a distance to it."
        )
    if len(others) > 1:
        return _ambiguous(
            others,
            f"Multiple other mapped geometries could define the distance to the "
            f"{direction} {role_label}.",
        )
    return _answer_distance([chosen, others[0]])


def _answer_slope(entities: list[dict[str, Any]]) -> dict[str, Any]:
    points = _elevation_points(entities)
    if len(points) < 2:
        return _insufficient("No two elevation-bearing points are available to compute a slope.")
    if len(points) > 2:
        return _ambiguous(points, "Multiple elevation-bearing points could define this slope.")
    start, end = points
    horizontal = _horizontal_distance(
        (start["x"], start["y"], start["z"]), (end["x"], end["y"], end["z"])
    )
    try:
        result = calculate_slope(start["z"], end["z"], horizontal, "coordinate units")
    except CalculationError as error:
        return _insufficient(f"Slope could not be calculated: {error}")
    slope_text = f"{result['result']:.2f}{result['unit']} ({result['direction']})"
    return {
        "answer": f"The measured slope is {slope_text}.",
        "method": "deterministic geometry calculation",
        "formula": result["formula"],
        "result": result["result"],
        "unit": result["unit"],
        "source_references": [start.get("source_reference"), end.get("source_reference")],
        "limitations": [
            "Assumes horizontal distance is measured in the same coordinate units as elevation."
        ],
        "confidence": 0.9,
    }


def _answer_elevation(entities: list[dict[str, Any]]) -> dict[str, Any]:
    values = [point["z"] for point in _elevation_points(entities)]
    if not values:
        return _insufficient("No elevation-bearing entities are available to answer this question.")
    return {
        "answer": (
            f"Elevations range from {min(values):.2f} to {max(values):.2f} "
            f"(average {sum(values) / len(values):.2f}) across {len(values)} points."
        ),
        "method": "deterministic geometry calculation",
        "formula": "minimum, maximum, and arithmetic average of elevations",
        "result": sum(values) / len(values),
        "source_references": [
            point.get("source_reference") for point in _elevation_points(entities)
        ],
        "limitations": ["Assumes all elevations use the same vertical datum and unit."],
        "confidence": 0.9,
    }


def _label_elevation_entities(entities: list[dict[str, Any]]) -> list[tuple[float, dict[str, Any]]]:
    """(elevation_value, text_entity) for every plan label carrying an "EL <n>"-style
    spot-elevation callout, extending the existing DXF label-to-geometry proximity
    linking to elevation lookups specifically (PLAN.md Phase 14, RISK_REGISTER.md)."""
    labeled: list[tuple[float, dict[str, Any]]] = []
    for entity in entities:
        if entity.get("entity_type") != "text":
            continue
        text = str((entity.get("properties") or {}).get("text", ""))
        labeled.extend((float(value), entity) for value in _extract_el_tokens(text))
    return labeled


def _find_labeled_elevations(entities: list[dict[str, Any]], value: float) -> list[dict[str, Any]]:
    """Every plan label matching `value` -- deliberately not just the first, unlike
    an earlier version of this function: a real plan can repeat the same rounded
    spot elevation (e.g. two separate "EL 100.00" benchmarks), and picking one
    silently (extraction-order-dependent) would be exactly the kind of unflagged
    ambiguity every sibling resolver in this file (_answer_area, _answer_dimensions,
    _answer_setback_compliance, etc.) explicitly refuses to do."""
    return [
        entity
        for label_value, entity in _label_elevation_entities(entities)
        if math.isclose(label_value, value, abs_tol=0.01)
    ]


def _answer_elevation_lookup(question: str, entities: list[dict[str, Any]]) -> dict[str, Any]:
    """A specific labeled spot elevation (e.g. "Where is EL 102.5 located?") or the
    difference between two of them (e.g. "elevation difference between EL 102.5 and EL
    101.0"), grounded in an actual matching plan label rather than trusting whatever
    number the question happens to contain (PLAN.md Phase 14)."""
    values = _extract_el_tokens(question)
    if len(values) >= 2:
        first_value, second_value = values[0], values[1]
        first_matches = _find_labeled_elevations(entities, first_value)
        second_matches = _find_labeled_elevations(entities, second_value)
        missing = [
            f"EL {value:g}"
            for value, matches in ((first_value, first_matches), (second_value, second_matches))
            if not matches
        ]
        if missing:
            return _insufficient(
                f"No plan label matching {' and '.join(missing)} was found in the extracted data."
            )
        ambiguous_values = [
            f"EL {value:g}"
            for value, matches in ((first_value, first_matches), (second_value, second_matches))
            if len(matches) > 1
        ]
        if ambiguous_values:
            return _ambiguous(
                first_matches + second_matches,
                f"Multiple plan labels match {' and '.join(ambiguous_values)}.",
            )
        first_label, second_label = first_matches[0], second_matches[0]
        difference = abs(first_value - second_value)
        return {
            "answer": (
                f"The elevation difference between EL {first_value:g} and EL {second_value:g} "
                f"is {difference:.2f}."
            ),
            "method": "deterministic label lookup",
            "formula": "abs(first labeled elevation - second labeled elevation)",
            "result": difference,
            "source_references": [
                first_label.get("source_reference"),
                second_label.get("source_reference"),
            ],
            "limitations": [
                "Assumes both labels share the same unit and vertical datum.",
                "The value comes from the plan label text itself, not a separately "
                "surveyed measurement.",
            ],
            "confidence": 0.85,
        }
    if len(values) == 1:
        target = values[0]
        matches = _find_labeled_elevations(entities, target)
        if not matches:
            return _insufficient(
                f"No plan label matching 'EL {target:g}' was found in the extracted data."
            )
        if len(matches) > 1:
            return _ambiguous(matches, f"Multiple plan labels match 'EL {target:g}'.")
        label = matches[0]
        location = (label.get("properties") or {}).get("location")
        located_at = (
            f"at coordinates ({location[0]:.2f}, {location[1]:.2f})"
            if isinstance(location, list) and len(location) >= 2
            else "at an unrecorded location"
        )
        return {
            "answer": f"EL {target:g} is labeled {located_at}.",
            "method": "source-grounded label lookup",
            "result": target,
            "location": location,
            "source_references": [label.get("source_reference")],
            "limitations": ["Location is the plan label's position, not a surveyed coordinate."],
            "confidence": 0.85,
        }
    return _insufficient(
        "Could not identify a labeled elevation value (e.g. 'EL 102.5') in the question."
    )


def _answer_summary(entities: list[dict[str, Any]]) -> dict[str, Any]:
    text_entities = [entity for entity in entities if entity.get("entity_type") == "text"]
    excerpts: list[str] = []
    flags: list[str] = []
    for entity in text_entities:
        lines = (entity.get("properties") or {}).get("sample_lines", [])
        cleaned, entity_flags = sanitize_source_text(lines)
        excerpts.extend(cleaned[:5])
        flags.extend(entity_flags)
    if not excerpts:
        return _insufficient(
            "No relevant extracted text or geometry was found to answer this question."
        )
    return {
        "answer": (
            "Relevant extracted text is provided; no numeric measurement was computed "
            "for this question."
        ),
        "method": "source text retrieval",
        "source_references": [entity.get("source_reference") for entity in text_entities],
        "source_excerpts": excerpts,
        "limitations": flags
        or [
            "This answer is descriptive; verify against source documents for engineering decisions."
        ],
        "confidence": 0.4,
    }


@dataclass
class MockAIProvider:
    """Deterministic provider used locally and in tests; never invents measurements."""

    def summarize(self, context: dict[str, Any]) -> dict[str, Any]:
        entities = context.get("entities", [])
        warnings = list(context.get("warnings", []))
        if is_geographic_crs(context.get("coordinate_reference_system")):
            warnings.append(GEOGRAPHIC_CRS_FLAG)
        return {
            "summary": f"Site model contains {len(entities)} extracted entities.",
            "grading": _grading_summary(entities),
            "drainage": _keyword_summary(entities, DRAINAGE_KEYWORDS, "drainage"),
            "utilities": _keyword_summary(entities, UTILITY_KEYWORDS, "utility"),
            "attention_flags": _attention_flags(entities, warnings),
            "limitations": ["Mock provider used; no unsupported engineering claims are generated."],
        }

    def answer(self, question: str, context: dict[str, Any]) -> dict[str, Any]:
        entities = context.get("entities", [])
        intent = context.get("intent") or route_question(question)
        crs = context.get("coordinate_reference_system")
        if intent in PLANAR_INTENTS and is_geographic_crs(crs):
            return _insufficient(
                f"This project's coordinate reference system ({crs}) is geographic "
                "(lat/lon degrees); this question needs a planar measurement, which "
                "requires a projected CRS."
            )
        if intent == "directional_distance":
            return _answer_directional(question, entities)
        if intent == "distance":
            return _answer_distance(_comparable_geometries(entities))
        if intent == "setback_compliance":
            return _answer_setback_compliance(question, entities)
        if intent == "slope":
            return _answer_slope(entities)
        if intent == "elevation_lookup":
            return _answer_elevation_lookup(question, entities)
        if intent == "elevation":
            return _answer_elevation(entities)
        if intent == "area":
            return _answer_area(question, entities)
        if intent == "perimeter":
            return _answer_perimeter(question, entities)
        if intent == "count":
            return _answer_count(question, entities)
        if intent == "orientation":
            return _answer_orientation(question, entities)
        if intent == "dimensions":
            return _answer_dimensions(question, entities)
        if intent == "drainage":
            return _answer_keyword_topic(entities, DRAINAGE_KEYWORDS, "drainage")
        if intent == "utility":
            return _answer_keyword_topic(entities, UTILITY_KEYWORDS, "utility")
        return _answer_summary(entities)
