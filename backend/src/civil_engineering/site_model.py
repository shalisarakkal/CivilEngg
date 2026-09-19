from typing import Any

from pyproj import CRS, Transformer
from shapely.geometry import LineString, Point, Polygon, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform


class SiteModelError(ValueError):
    pass


def _parsed_crs(crs: str | None) -> CRS | None:
    if not crs:
        return None
    try:
        return CRS.from_user_input(crs)
    except Exception:
        return None


def is_geographic_crs(crs: str | None) -> bool:
    """True when `crs` measures position in angular units (lat/lon degrees).

    Every measurement in calculations.py is planar (Euclidean, via Shapely), so a
    geographic CRS would produce numbers in degrees while labelling them with a
    linear unit. An unrecognized or absent CRS is not reported as geographic: the
    project is then simply assumed to use planar coordinates, as it always has.
    """
    parsed = _parsed_crs(crs)
    return bool(parsed is not None and parsed.is_geographic)


def ensure_projected_crs(crs: str | None) -> None:
    if is_geographic_crs(crs):
        raise SiteModelError(
            f"{crs} is a geographic (lat/lon degree) coordinate reference system; "
            "distance, area, and perimeter are measured on a plane, so the project "
            "must use a projected CRS"
        )


def crs_linear_unit_meters(crs: str | None) -> float | None:
    """Metres in one horizontal coordinate unit of `crs`.

    None when the CRS is absent, unrecognized, or geographic — in those cases the
    size of a coordinate unit is unknown (or not a length at all) and the caller
    has to fall back to the project's declared unit system.
    """
    parsed = _parsed_crs(crs)
    if parsed is None or parsed.is_geographic:
        return None
    axis = parsed.axis_info[0] if parsed.axis_info else None
    factor = getattr(axis, "unit_conversion_factor", None)
    if not isinstance(factor, (int, float)) or factor <= 0:
        return None
    return float(factor)


def normalize_geometry(
    value: dict[str, Any], source_crs: str | None = None, target_crs: str | None = None
) -> dict[str, Any]:
    geometry = _geometry_from_value(value)
    if source_crs and target_crs and source_crs != target_crs:
        try:
            transformer = Transformer.from_crs(
                CRS.from_user_input(source_crs), CRS.from_user_input(target_crs), always_xy=True
            )
            geometry = transform(transformer.transform, geometry)
        except Exception as error:
            raise SiteModelError(f"Coordinate transformation failed: {error}") from error
    if geometry.is_empty or not geometry.is_valid:
        raise SiteModelError("Geometry is empty or invalid")
    return mapping(geometry)


def validate_geometry(geometry_data: dict[str, Any]) -> dict[str, Any]:
    try:
        geometry = shape(geometry_data)
    except Exception as error:
        raise SiteModelError(f"Geometry could not be parsed: {error}") from error
    if geometry.is_empty or not geometry.is_valid:
        raise SiteModelError("Geometry is empty or invalid")
    return {"type": geometry.geom_type, "is_valid": True, "bounds": list(geometry.bounds)}


def _geometry_from_value(value: dict[str, Any]) -> BaseGeometry:
    if "start" in value and "end" in value:
        return LineString([value["start"], value["end"]])
    if "point" in value:
        return Point(value["point"])
    if "points" in value:
        points = value["points"]
        if len(points) < 2:
            raise SiteModelError("A line requires at least two points")
        if points[0] == points[-1] and len(points) >= 4:
            return Polygon(points)
        return LineString(points)
    raise SiteModelError("Extracted item does not contain supported geometry")
