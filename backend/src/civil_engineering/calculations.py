import math
from typing import Any

from shapely.geometry import shape


class CalculationError(ValueError):
    pass


DISTANCE_TO_METERS = {
    "m": 1.0,
    "meter": 1.0,
    "meters": 1.0,
    "cm": 0.01,
    "centimeter": 0.01,
    "centimeters": 0.01,
    "ft": 0.3048,
    "foot": 0.3048,
    "feet": 0.3048,
    "in": 0.0254,
    "inch": 0.0254,
    "inches": 0.0254,
}


def convert_distance(value: float, from_unit: str, to_unit: str) -> float:
    if not math.isfinite(value) or value < 0:
        raise CalculationError("Distance must be a finite non-negative number")
    source = DISTANCE_TO_METERS.get(from_unit.lower())
    target = DISTANCE_TO_METERS.get(to_unit.lower())
    if source is None or target is None:
        raise CalculationError("Unsupported distance unit")
    return value * source / target


def calculate_distance(
    first: dict[str, Any], second: dict[str, Any], source_unit: str, output_unit: str
) -> dict[str, Any]:
    try:
        first_geometry = shape(first)
        second_geometry = shape(second)
    except Exception as error:
        raise CalculationError(f"Geometry could not be parsed: {error}") from error
    value = convert_distance(first_geometry.distance(second_geometry), source_unit, output_unit)
    return {
        "calculation_type": "distance",
        "inputs": {"first_geometry": first, "second_geometry": second},
        "formula": "distance(first geometry, second geometry)",
        "result": value,
        "unit": output_unit,
        "assumptions": [f"Input coordinates are measured in {source_unit}"],
    }


def calculate_area(
    geometry_data: dict[str, Any], source_unit: str, output_unit: str
) -> dict[str, Any]:
    if geometry_data.get("type") == "Circle":
        radius = _circle_radius(geometry_data)
        value = convert_distance(radius, source_unit, output_unit) ** 2 * math.pi
        return {
            "calculation_type": "area",
            "inputs": {"geometry": geometry_data},
            "formula": "pi * radius^2",
            "result": value,
            "unit": f"square_{output_unit}",
            "assumptions": [f"Circle radius is measured in {source_unit}"],
        }
    try:
        geometry = shape(geometry_data)
    except Exception as error:
        raise CalculationError(f"Geometry could not be parsed: {error}") from error
    if geometry.geom_type not in {"Polygon", "MultiPolygon"}:
        raise CalculationError(f"{geometry.geom_type} geometry cannot be used for area")
    if geometry.is_empty or not geometry.is_valid:
        raise CalculationError("Geometry is empty or invalid")
    value = convert_distance(1, source_unit, output_unit) ** 2 * geometry.area
    return {
        "calculation_type": "area",
        "inputs": {"geometry": geometry_data},
        "formula": "area(geometry)",
        "result": value,
        "unit": f"square_{output_unit}",
        "assumptions": [f"Input coordinates are measured in {source_unit}"],
    }


def calculate_perimeter(
    geometry_data: dict[str, Any], source_unit: str, output_unit: str
) -> dict[str, Any]:
    if geometry_data.get("type") == "Circle":
        radius = _circle_radius(geometry_data)
        value = convert_distance(radius, source_unit, output_unit) * 2 * math.pi
        return {
            "calculation_type": "perimeter",
            "inputs": {"geometry": geometry_data},
            "formula": "2 * pi * radius",
            "result": value,
            "unit": output_unit,
            "assumptions": [f"Circle radius is measured in {source_unit}"],
        }
    try:
        geometry = shape(geometry_data)
    except Exception as error:
        raise CalculationError(f"Geometry could not be parsed: {error}") from error
    if geometry.geom_type not in {"LineString", "MultiLineString", "Polygon", "MultiPolygon"}:
        raise CalculationError(f"{geometry.geom_type} geometry cannot be used for perimeter")
    if geometry.is_empty or not geometry.is_valid:
        raise CalculationError("Geometry is empty or invalid")
    value = convert_distance(geometry.length, source_unit, output_unit)
    return {
        "calculation_type": "perimeter",
        "inputs": {"geometry": geometry_data},
        "formula": "length(geometry boundary)",
        "result": value,
        "unit": output_unit,
        "assumptions": [f"Input coordinates are measured in {source_unit}"],
    }


def _circle_radius(geometry_data: dict[str, Any]) -> float:
    radius = geometry_data.get("radius")
    if not isinstance(radius, (int, float)) or not math.isfinite(radius) or radius <= 0:
        raise CalculationError("Circle radius must be a finite number greater than zero")
    center = geometry_data.get("center")
    if (
        not isinstance(center, list)
        or len(center) != 2
        or not all(isinstance(value, (int, float)) and math.isfinite(value) for value in center)
    ):
        raise CalculationError("Circle center must contain two finite coordinates")
    return float(radius)


def calculate_slope(
    start_elevation: float,
    end_elevation: float,
    horizontal_distance: float,
    distance_unit: str,
) -> dict[str, Any]:
    if not all(
        math.isfinite(value) for value in (start_elevation, end_elevation, horizontal_distance)
    ):
        raise CalculationError("Slope inputs must be finite numbers")
    if horizontal_distance <= 0:
        raise CalculationError("Horizontal distance must be greater than zero")
    elevation_change = end_elevation - start_elevation
    percent = elevation_change / horizontal_distance * 100
    ratio = abs(horizontal_distance / elevation_change) if elevation_change else None
    return {
        "calculation_type": "slope",
        "inputs": {
            "start_elevation": start_elevation,
            "end_elevation": end_elevation,
            "horizontal_distance": horizontal_distance,
        },
        "formula": "(change in elevation / horizontal distance) * 100",
        "result": percent,
        "unit": "percent",
        "assumptions": [f"Distance input is measured in {distance_unit}"],
        "slope_ratio": ratio,
        "direction": (
            "uphill" if elevation_change > 0 else "downhill" if elevation_change < 0 else "level"
        ),
    }


def calculate_elevation_statistics(values: list[float], unit: str) -> dict[str, Any]:
    if not values or not all(math.isfinite(value) for value in values):
        raise CalculationError("Elevation values must contain at least one finite number")
    statistics = {
        "minimum": min(values),
        "maximum": max(values),
        "average": sum(values) / len(values),
        "count": len(values),
    }
    return {
        "calculation_type": "elevation",
        "inputs": {"elevations": values},
        "formula": "minimum, maximum, and arithmetic average of elevations",
        "result": statistics["average"],
        "unit": unit,
        "assumptions": ["All elevations use the same vertical datum and unit"],
        "statistics": statistics,
    }
