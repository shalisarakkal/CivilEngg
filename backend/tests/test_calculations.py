import pytest

from civil_engineering.calculations import (
    CalculationError,
    calculate_area,
    calculate_distance,
    calculate_perimeter,
    calculate_slope,
    convert_distance,
)


def test_distance_and_unit_conversion() -> None:
    assert convert_distance(1, "m", "ft") == pytest.approx(3.28084, rel=1e-5)
    result = calculate_distance(
        {"type": "Point", "coordinates": [0, 0]},
        {"type": "Point", "coordinates": [3, 4]},
        "m",
        "m",
    )
    assert result["result"] == pytest.approx(5)
    assert result["unit"] == "m"

    feet_result = calculate_distance(
        {"type": "Point", "coordinates": [10, 0]},
        {"type": "Point", "coordinates": [5, 0]},
        "ft",
        "ft",
    )
    assert feet_result["result"] == pytest.approx(5)


def test_area_and_slope() -> None:
    area = calculate_area(
        {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 20], [0, 20], [0, 0]]]},
        "m",
        "m",
    )
    assert area["result"] == pytest.approx(200)

    slope = calculate_slope(100, 104, 100, "ft")
    assert slope["result"] == pytest.approx(4)
    assert slope["direction"] == "uphill"


def test_circle_area_and_perimeter_use_radius_units() -> None:
    circle = {"type": "Circle", "center": [100, 200], "radius": 25}

    area = calculate_area(circle, "ft", "ft")
    perimeter = calculate_perimeter(circle, "ft", "ft")

    assert area["result"] == pytest.approx(25 * 25 * 3.141592653589793)
    assert perimeter["result"] == pytest.approx(2 * 3.141592653589793 * 25)
    assert area["formula"] == "pi * radius^2"


def test_circle_rejects_invalid_radius_and_center() -> None:
    with pytest.raises(CalculationError, match="radius"):
        calculate_area({"type": "Circle", "center": [0, 0], "radius": 0}, "ft", "ft")
    with pytest.raises(CalculationError, match="center"):
        calculate_perimeter({"type": "Circle", "center": [0], "radius": 10}, "ft", "ft")


def test_elevation_statistics() -> None:
    from civil_engineering.calculations import calculate_elevation_statistics

    result = calculate_elevation_statistics([100, 102, 104], "ft")
    assert result["result"] == pytest.approx(102)
    assert result["statistics"] == {"minimum": 100, "maximum": 104, "average": 102, "count": 3}


def test_calculations_reject_invalid_inputs() -> None:
    with pytest.raises(CalculationError, match="greater than zero"):
        calculate_slope(100, 104, 0, "ft")
    with pytest.raises(CalculationError, match="Unsupported distance unit"):
        convert_distance(1, "yards", "m")
    with pytest.raises(CalculationError, match="Point geometry cannot be used for area"):
        calculate_area({"type": "Point", "coordinates": [0, 0]}, "ft", "ft")
    with pytest.raises(CalculationError, match="Point geometry cannot be used for perimeter"):
        calculate_perimeter({"type": "Point", "coordinates": [0, 0]}, "ft", "ft")
    with pytest.raises(CalculationError, match="LineString geometry cannot be used for area"):
        calculate_area({"type": "LineString", "coordinates": [[0, 0], [10, 0]]}, "ft", "ft")
