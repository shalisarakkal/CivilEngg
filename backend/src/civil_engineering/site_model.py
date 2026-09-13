from typing import Any

from pyproj import CRS, Transformer
from shapely.geometry import LineString, Point, Polygon, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform


class SiteModelError(ValueError):
    pass


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
