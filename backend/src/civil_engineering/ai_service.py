from dataclasses import dataclass
from typing import Any, Protocol


class AIProvider(Protocol):
    def summarize(self, context: dict[str, Any]) -> dict[str, Any]: ...

    def answer(self, question: str, context: dict[str, Any]) -> dict[str, Any]: ...


@dataclass
class MockAIProvider:
    """Deterministic provider used locally and in tests; never invents measurements."""

    def summarize(self, context: dict[str, Any]) -> dict[str, Any]:
        entities = context.get("entities", [])
        warnings = context.get("warnings", [])
        return {
            "summary": f"Site model contains {len(entities)} extracted entities.",
            "grading": "No grading summary available from the supplied data.",
            "drainage": "No drainage summary available from the supplied data.",
            "utilities": "No utilities summary available from the supplied data.",
            "attention_flags": warnings or ["Review extracted entities and source references."],
            "limitations": ["Mock provider used; no unsupported engineering claims are generated."],
        }

    def answer(self, question: str, context: dict[str, Any]) -> dict[str, Any]:
        return {
            "answer": "Insufficient data to answer this question.",
            "method": "source-grounded mock provider",
            "source_references": context.get("source_references", []),
            "limitations": ["No deterministic calculation was available for this question."],
            "confidence": 0.0,
        }


def route_question(question: str) -> str:
    normalized = question.lower()
    if "setback" in normalized or "distance" in normalized:
        return "distance"
    if "slope" in normalized:
        return "slope"
    if "elevation" in normalized:
        return "elevation"
    return "summary"
