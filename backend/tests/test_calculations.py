import pytest

from civil_engineering.calculations import (
    CalculationError,
    calculate_area,
    calculate_distance,
    calculate_slope,
    convert_distance,
)


def test_distance_and_unit_conversion() -> None:
    assert convert_distance(1, "m", "ft") == pytest.approx(3.28084, rel=1e-5)
    result = calculate_distance(
        {"type": "Point", "coordinates": [0, 0]},
        {"type": "Point", "coordinates": [3, 4]},
        "m",
    )
    assert result["result"] == pytest.approx(5)
    assert result["unit"] == "m"


def test_area_and_slope() -> None:
    area = calculate_area(
        {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 20], [0, 20], [0, 0]]]},
        "m",
    )
    assert area["result"] == pytest.approx(200)

    slope = calculate_slope(100, 104, 100, "ft")
    assert slope["result"] == pytest.approx(4)
    assert slope["direction"] == "uphill"


def test_calculations_reject_invalid_inputs() -> None:
    with pytest.raises(CalculationError, match="greater than zero"):
        calculate_slope(100, 104, 0, "ft")
    with pytest.raises(CalculationError, match="Unsupported distance unit"):
        convert_distance(1, "yards", "m")
