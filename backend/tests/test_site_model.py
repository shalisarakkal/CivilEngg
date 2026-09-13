import pytest

from civil_engineering.site_model import SiteModelError, normalize_geometry, validate_geometry


def test_normalize_line_geometry_and_validate_bounds() -> None:
    geometry = normalize_geometry({"start": [0, 0], "end": [10, 5]})

    assert geometry["type"] == "LineString"
    validation = validate_geometry(geometry)
    assert validation["is_valid"] is True
    assert validation["bounds"] == [0.0, 0.0, 10.0, 5.0]


def test_transform_geometry_between_coordinate_systems() -> None:
    geometry = normalize_geometry({"point": [0, 0]}, source_crs="EPSG:4326", target_crs="EPSG:3857")

    assert geometry["type"] == "Point"
    assert geometry["coordinates"] == (0.0, 0.0)


def test_invalid_geometry_is_rejected() -> None:
    with pytest.raises(SiteModelError, match="at least two points"):
        normalize_geometry({"points": [[0, 0]]})

    with pytest.raises(SiteModelError, match="invalid"):
        validate_geometry(
            {
                "type": "Polygon",
                "coordinates": [[[0, 0], [1, 1], [0, 1], [1, 0], [0, 0]]],
            }
        )
