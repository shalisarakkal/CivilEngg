from civil_engineering.config import Settings


def test_cors_allowed_origin_list_defaults_to_the_local_dev_ports() -> None:
    settings = Settings(
        database_url="sqlite://",
        cors_allowed_origins="http://localhost:3000,http://localhost:3001,http://localhost:3002",
    )
    assert settings.cors_allowed_origin_list == [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:3002",
    ]


def test_cors_allowed_origin_list_parses_a_custom_comma_separated_value() -> None:
    settings = Settings(
        database_url="sqlite://",
        cors_allowed_origins=" http://localhost:5173 , https://example.com ,,",
    )
    assert settings.cors_allowed_origin_list == ["http://localhost:5173", "https://example.com"]
