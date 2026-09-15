import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Protocol

from civil_engineering.calculations import CalculationError, calculate_distance, calculate_slope

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
# routes.py's _classify_entity). Longer, more specific phrases are not required to come
# first: every synonym for a role maps to the same semantic_type.
ROLE_TO_SEMANTIC_TYPE = {
    "property line": "parcel_boundary",
    "property boundary": "parcel_boundary",
    "parcel boundary": "parcel_boundary",
    "parcel": "parcel_boundary",
    "building footprint": "building_footprint",
    "building": "building_footprint",
    "footprint": "building_footprint",
    "driveway": "driveway_road",
    "road": "driveway_road",
    "curb cut": "curb_cut",
}

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
    if "setback" in normalized or "distance" in normalized:
        return "distance"
    if "slope" in normalized:
        return "slope"
    if "elevation" in normalized:
        return "elevation"
    return "summary"


def _parse_directional_question(question: str) -> tuple[str, str] | None:
    normalized = question.lower()
    direction = next((word for word in DIRECTION_AXES if word in normalized), None)
    if direction is None:
        return None
    role = next((phrase for phrase in ROLE_TO_SEMANTIC_TYPE if phrase in normalized), None)
    if role is None:
        return None
    return direction, ROLE_TO_SEMANTIC_TYPE[role]


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
        ring = coordinates[0]
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
        warnings = context.get("warnings", [])
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
        if intent == "directional_distance":
            return _answer_directional(question, entities)
        if intent == "distance":
            return _answer_distance(_comparable_geometries(entities))
        if intent == "slope":
            return _answer_slope(entities)
        if intent == "elevation":
            return _answer_elevation(entities)
        return _answer_summary(entities)
