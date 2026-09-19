import pytest

from civil_engineering.site_model import (
    SiteModelError,
    crs_linear_unit_meters,
    ensure_projected_crs,
    is_geographic_crs,
    normalize_geometry,
    validate_geometry,
)


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


def test_geographic_coordinate_systems_are_detected_and_rejected() -> None:
    # Every calculation in calculations.py is planar, so a lat/lon CRS has to be
    # recognized before it can be attached to a project (see RISK_REGISTER.md).
    assert is_geographic_crs("EPSG:4326") is True
    assert is_geographic_crs("EPSG:9518") is True  # geographic + vertical compound
    assert is_geographic_crs("EPSG:2263") is False
    # An unknown or absent CRS keeps the project's long-standing assumption that
    # its coordinates are already planar, rather than guessing.
    assert is_geographic_crs(None) is False
    assert is_geographic_crs("not a crs") is False

    with pytest.raises(SiteModelError, match="geographic"):
        ensure_projected_crs("EPSG:4326")
    ensure_projected_crs("EPSG:2263")
    ensure_projected_crs(None)


def test_linear_unit_of_a_projected_coordinate_system() -> None:
    assert crs_linear_unit_meters("EPSG:32618") == pytest.approx(1.0)  # UTM, metres
    assert crs_linear_unit_meters("EPSG:2263") == pytest.approx(0.3048, abs=1e-5)  # US ft
    # No length can be read from a geographic, unknown, or missing CRS.
    assert crs_linear_unit_meters("EPSG:4326") is None
    assert crs_linear_unit_meters("not a crs") is None
    assert crs_linear_unit_meters(None) is None
