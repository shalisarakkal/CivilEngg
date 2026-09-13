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


def calculate_distance(first: dict[str, Any], second: dict[str, Any], unit: str) -> dict[str, Any]:
    try:
        first_geometry = shape(first)
        second_geometry = shape(second)
    except Exception as error:
        raise CalculationError(f"Geometry could not be parsed: {error}") from error
    value_meters = first_geometry.distance(second_geometry)
    value = convert_distance(value_meters, "m", unit)
    return {
        "calculation_type": "distance",
        "inputs": {"first_geometry": first, "second_geometry": second},
        "formula": "distance(first geometry, second geometry)",
        "result": value,
        "unit": unit,
        "assumptions": ["Input coordinates use the same projected coordinate system"],
    }


def calculate_area(geometry_data: dict[str, Any], unit: str) -> dict[str, Any]:
    try:
        geometry = shape(geometry_data)
    except Exception as error:
        raise CalculationError(f"Geometry could not be parsed: {error}") from error
    if geometry.is_empty or not geometry.is_valid:
        raise CalculationError("Geometry is empty or invalid")
    value = convert_distance(math.sqrt(geometry.area), "m", unit) ** 2
    return {
        "calculation_type": "area",
        "inputs": {"geometry": geometry_data},
        "formula": "area(geometry)",
        "result": value,
        "unit": f"square_{unit}",
        "assumptions": ["Input coordinates use the same projected coordinate system"],
    }


def calculate_perimeter(geometry_data: dict[str, Any], unit: str) -> dict[str, Any]:
    try:
        geometry = shape(geometry_data)
    except Exception as error:
        raise CalculationError(f"Geometry could not be parsed: {error}") from error
    if geometry.is_empty or not geometry.is_valid:
        raise CalculationError("Geometry is empty or invalid")
    value = convert_distance(geometry.length, "m", unit)
    return {
        "calculation_type": "perimeter",
        "inputs": {"geometry": geometry_data},
        "formula": "length(geometry boundary)",
        "result": value,
        "unit": unit,
        "assumptions": ["Input coordinates use the same projected coordinate system"],
    }


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
