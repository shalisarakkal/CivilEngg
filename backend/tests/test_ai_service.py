from civil_engineering.ai_service import MockAIProvider, route_question


def test_question_routing_and_mock_provider_are_deterministic() -> None:
    assert route_question("What is the setback distance?") == "distance"
    assert route_question("Summarize the site") == "summary"
    answer = MockAIProvider().answer("What is the setback distance?", {})
    assert answer["confidence"] == 0.0
    assert "Insufficient data" in answer["answer"]
