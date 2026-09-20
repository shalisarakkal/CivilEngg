"""PLAN.md Phase 14 (Question-Answering Coverage Expansion) regression tests.

Each test exercises one gap found via the TestQuestions audit: building
dimensions/orientation from a bounding rectangle, a deterministic
building-to-parcel setback clearance, counting classified entities by role,
wiring the drainage/utility keyword rollups into the question endpoint, and
looking up a specific labeled spot elevation (or the difference between two).
See RISK_REGISTER.md and the Phase 14 section of PLAN.md.
"""

from collections.abc import Generator
from pathlib import Path
from typing import Any

import ezdxf
from auth_helpers import override_user_factory
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from civil_engineering.auth import get_current_user
from civil_engineering.database import Base, get_db
from civil_engineering.main import app


def _client(tmp_path: Path, monkeypatch: MonkeyPatch) -> TestClient:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db() -> Generator[Session, None, None]:
        database = sessions()
        try:
            yield database
        finally:
            database.close()

    monkeypatch.setenv("LOCAL_STORAGE_PATH", str(tmp_path))
    from civil_engineering.config import get_settings

    get_settings.cache_clear()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_user_factory(sessions)
    return TestClient(app)


def _revision_from_dxf(
    client: TestClient, tmp_path: Path, drawing: Any, file_name: str, project_name: str
) -> tuple[str, str]:
    """Upload, process, and accept a DXF drawing into a site-model revision.
    Returns (project_id, revision_id)."""
    dxf_path = tmp_path / file_name
    drawing.saveas(dxf_path)
    project = client.post("/projects", json={"name": project_name}).json()
    uploaded = client.post(
        f"/projects/{project['id']}/files",
        files={"file": (file_name, dxf_path.read_bytes(), "application/dxf")},
    ).json()
    processed = client.post(f"/projects/{project['id']}/files/{uploaded['id']}/process").json()
    assert processed["status"] == "completed"
    revision = client.post(
        f"/projects/{project['id']}/site-model/revisions/from-extraction/{uploaded['id']}"
    ).json()
    return project["id"], revision["id"]


def _ask(client: TestClient, project_id: str, revision_id: str, question: str) -> dict[str, Any]:
    response = client.post(
        f"/projects/{project_id}/questions",
        json={"question": question, "revision_ids": [revision_id]},
    )
    assert response.status_code == 200
    return dict(response.json())


def test_building_dimensions_and_orientation_from_bounding_rectangle(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    # Regression test (PLAN.md Phase 14): "What are the building dimensions?" and
    # similar questions had no intent at all before this and fell through to the
    # generic text-retrieval summary, even though the geometry to compute them from
    # was already in the site model.
    client = _client(tmp_path, monkeypatch)
    try:
        drawing = ezdxf.new("R2010")  # type: ignore[attr-defined]
        modelspace = drawing.modelspace()
        # 80 x 50, matching TestQuestions' "Building area" worked example.
        modelspace.add_lwpolyline(
            [(0, 0), (80, 0), (80, 50), (0, 50)], close=True, dxfattribs={"layer": "BUILDING"}
        )
        project_id, revision_id = _revision_from_dxf(
            client, tmp_path, drawing, "building.dxf", "Building Dimensions Site"
        )

        dimensions = _ask(client, project_id, revision_id, "What are the building dimensions?")
        assert dimensions["answer"]["width"] == 50.0
        assert dimensions["answer"]["length"] == 80.0
        assert dimensions["answer"]["confidence"] == 0.8

        width = _ask(client, project_id, revision_id, "What is the building's width?")
        assert width["answer"]["result"] == 50.0

        length = _ask(client, project_id, revision_id, "What is the building's length?")
        assert length["answer"]["result"] == 80.0

        orientation = _ask(
            client, project_id, revision_id, "What is the orientation of the building?"
        )
        assert orientation["intent"] == "orientation"
        assert orientation["answer"]["result"] == 90.0
        assert orientation["answer"]["unit"] == "degrees"
    finally:
        app.dependency_overrides.clear()
        from civil_engineering.config import get_settings

        get_settings.cache_clear()


def test_setback_compliance_measures_building_to_parcel_clearance(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    # Regression test (PLAN.md Phase 14): a building-setback question used to route
    # to the generic "exactly two mapped geometries in the whole model" distance
    # answer, which becomes "ambiguous" the moment a real site model has more than
    # two mapped geometries (as any real one does, e.g. an additional driveway or
    # utility entity). It also measured distance between the filled polygons
    # themselves, which is 0 whenever one is nested inside the other.
    client = _client(tmp_path, monkeypatch)
    try:
        drawing = ezdxf.new("R2010")  # type: ignore[attr-defined]
        modelspace = drawing.modelspace()
        modelspace.add_lwpolyline(
            [(0, 0), (100, 0), (100, 100), (0, 100)],
            close=True,
            dxfattribs={"layer": "PROPERTY LINE"},
        )
        # Offset 40 units in from every parcel edge -> clearance is exactly 40.
        modelspace.add_lwpolyline(
            [(40, 40), (50, 40), (50, 50), (40, 50)],
            close=True,
            dxfattribs={"layer": "BUILDING FOOTPRINT"},
        )
        # A third mapped geometry, so the old "exactly two geometries" distance
        # answer would have gone ambiguous rather than resolving anything.
        modelspace.add_line((0, 0), (0, -20), dxfattribs={"layer": "DRIVEWAY"})
        project_id, revision_id = _revision_from_dxf(
            client, tmp_path, drawing, "setback.dxf", "Setback Compliance Site"
        )

        no_threshold = _ask(
            client,
            project_id,
            revision_id,
            "Does the building appear to be within the indicated setbacks?",
        )
        assert no_threshold["intent"] == "setback_compliance"
        assert no_threshold["answer"]["result"] == 40.0
        assert "cannot be determined" in no_threshold["answer"]["answer"]

        compliant = _ask(
            client, project_id, revision_id, "Is the building's setback at least 25 ft?"
        )
        assert compliant["answer"]["result"] == 40.0
        assert "compliant" in compliant["answer"]["answer"]
        assert "not compliant" not in compliant["answer"]["answer"]

        not_compliant = _ask(
            client, project_id, revision_id, "Is the building's setback at least 60 m?"
        )
        assert "not compliant" in not_compliant["answer"]["answer"]
    finally:
        app.dependency_overrides.clear()
        from civil_engineering.config import get_settings

        get_settings.cache_clear()


def test_setback_compliance_does_not_convert_the_stated_threshold_to_a_different_unit(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    # Regression test found via code review: _answer_setback_compliance used to
    # convert only the *stated threshold* to true metres (via convert_distance)
    # while leaving the measured `clearance` in whatever unit the project's raw
    # coordinates actually are -- silently comparing mismatched units. A project
    # with feet-based coordinates (the app's own default_unit_system, and every
    # worked example in TestQuestions) and a real 20 ft clearance would have had
    # "at least 25 ft" converted to 7.62 (true metres) and wrongly reported
    # "compliant" (20 >= 7.62), the opposite of the correct answer.
    client = _client(tmp_path, monkeypatch)
    try:
        drawing = ezdxf.new("R2010")  # type: ignore[attr-defined]
        modelspace = drawing.modelspace()
        modelspace.add_lwpolyline(
            [(0, 0), (100, 0), (100, 100), (0, 100)],
            close=True,
            dxfattribs={"layer": "PROPERTY LINE"},
        )
        # Offset 20 units in from every parcel edge -> clearance is exactly 20.
        modelspace.add_lwpolyline(
            [(20, 20), (30, 20), (30, 30), (20, 30)],
            close=True,
            dxfattribs={"layer": "BUILDING FOOTPRINT"},
        )
        project_id, revision_id = _revision_from_dxf(
            client, tmp_path, drawing, "setback_units.dxf", "Setback Unit Mismatch Site"
        )

        answer = _ask(client, project_id, revision_id, "Is the building's setback at least 25 ft?")
        assert answer["answer"]["result"] == 20.0
        # 20 < 25: not compliant. The pre-fix bug reported this as compliant by
        # comparing the raw clearance (20) against the threshold converted to true
        # metres (25 ft -> 7.62).
        assert "not compliant" in answer["answer"]["answer"]
        assert answer["answer"]["unit"] == "ft"
    finally:
        app.dependency_overrides.clear()
        from civil_engineering.config import get_settings

        get_settings.cache_clear()


def test_count_question_counts_entities_classified_by_role(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    # Regression test (PLAN.md Phase 14): "How many X are shown?" had no intent at
    # all before this, even for entities that already carried the right
    # semantic_type from PARKING_TYPE_KEYWORDS/TREE_TYPE_KEYWORDS classification.
    client = _client(tmp_path, monkeypatch)
    try:
        drawing = ezdxf.new("R2010")  # type: ignore[attr-defined]
        modelspace = drawing.modelspace()
        modelspace.add_lwpolyline(
            [(0, 0), (10, 0), (10, 20), (0, 20)], close=True, dxfattribs={"layer": "PARKING"}
        )
        modelspace.add_lwpolyline(
            [(20, 0), (30, 0), (30, 20), (20, 20)], close=True, dxfattribs={"layer": "PARKING"}
        )
        modelspace.add_point((50, 50), dxfattribs={"layer": "TREE"})
        project_id, revision_id = _revision_from_dxf(
            client, tmp_path, drawing, "count.dxf", "Count Site"
        )

        parking = _ask(client, project_id, revision_id, "How many parking spaces are shown?")
        assert parking["intent"] == "count"
        assert parking["answer"]["result"] == 2.0
        assert len(parking["answer"]["source_references"]) == 2

        trees = _ask(client, project_id, revision_id, "How many existing trees are shown?")
        assert trees["answer"]["result"] == 1.0

        # A role with no classified entities at all reports insufficient data,
        # never an affirmative "zero" -- an unclassified feature is
        # indistinguishable from an absent one (see RISK_REGISTER.md).
        sidewalks = _ask(client, project_id, revision_id, "How many sidewalks are shown?")
        assert sidewalks["answer"]["confidence"] == 0.0
    finally:
        app.dependency_overrides.clear()
        from civil_engineering.config import get_settings

        get_settings.cache_clear()


def test_drainage_and_utility_questions_are_routed_and_answered(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    # Regression test (PLAN.md Phase 14): the drainage/utility keyword rollups
    # already existed for the summary endpoint (_keyword_summary), but the question
    # endpoint had no way to reach them -- "Is a utility easement shown?" fell all
    # the way through to the generic text fallback.
    client = _client(tmp_path, monkeypatch)
    try:
        drawing = ezdxf.new("R2010")  # type: ignore[attr-defined]
        modelspace = drawing.modelspace()
        modelspace.add_lwpolyline(
            [(0, 0), (20, 0), (20, 20), (0, 20)],
            close=True,
            dxfattribs={"layer": "DETENTION BASIN"},
        )
        modelspace.add_lwpolyline(
            [(30, 0), (40, 0), (40, 20), (30, 20)],
            close=True,
            dxfattribs={"layer": "UTILITY EASEMENT"},
        )
        project_id, revision_id = _revision_from_dxf(
            client, tmp_path, drawing, "drainage.dxf", "Drainage Utility Site"
        )

        drainage = _ask(client, project_id, revision_id, "Is a stormwater detention basin shown?")
        assert drainage["intent"] == "drainage"
        assert drainage["answer"]["result"] == 1.0

        utility = _ask(client, project_id, revision_id, "Is a utility easement shown?")
        assert utility["intent"] == "utility"
        assert utility["answer"]["result"] == 1.0

        # "hydrant" is in the same UTILITY_KEYWORDS bucket as "easement" -> the
        # utility_easement entity above legitimately matches this too (the
        # rollup is bucket-level, matching the existing summary-endpoint
        # behavior it reuses, not per-keyword). A true zero-match needs a
        # revision with nothing drainage/utility-related in it at all.
        empty_drawing = ezdxf.new("R2010")  # type: ignore[attr-defined]
        empty_drawing.modelspace().add_lwpolyline(
            [(0, 0), (10, 0), (10, 10), (0, 10)], close=True, dxfattribs={"layer": "BUILDING"}
        )
        empty_project_id, empty_revision_id = _revision_from_dxf(
            client, tmp_path, empty_drawing, "no_utilities.dxf", "No Utilities Site"
        )
        no_match = _ask(client, empty_project_id, empty_revision_id, "Is a fire hydrant shown?")
        assert no_match["intent"] == "utility"
        assert no_match["answer"]["confidence"] == 0.0
    finally:
        app.dependency_overrides.clear()
        from civil_engineering.config import get_settings

        get_settings.cache_clear()


def test_elevation_lookup_finds_labeled_spot_elevations_and_their_difference(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    # Regression test (PLAN.md Phase 14): only the overall min/max/average
    # elevation could be answered before this; a question naming a specific
    # labeled spot elevation (e.g. "EL 102.5", straight from TestQuestions) had no
    # way to be resolved to that label at all.
    client = _client(tmp_path, monkeypatch)
    try:
        drawing = ezdxf.new("R2010")  # type: ignore[attr-defined]
        modelspace = drawing.modelspace()
        modelspace.add_text("EL 103.2", dxfattribs={"layer": "ELEVATIONS", "insert": (12.0, 30.0)})
        modelspace.add_text("EL 101.0", dxfattribs={"layer": "ELEVATIONS", "insert": (45.0, 10.0)})
        project_id, revision_id = _revision_from_dxf(
            client, tmp_path, drawing, "elevations.dxf", "Elevation Lookup Site"
        )

        location = _ask(client, project_id, revision_id, "Where is EL 103.2 located?")
        assert location["intent"] == "elevation_lookup"
        assert location["answer"]["result"] == 103.2
        assert "12.00" in location["answer"]["answer"]
        assert "30.00" in location["answer"]["answer"]

        # Matches TestQuestions category 7's worked example exactly: 103.2 - 101.0 = 2.2.
        difference = _ask(
            client,
            project_id,
            revision_id,
            "What is the elevation difference between EL 103.2 and EL 101.0?",
        )
        assert round(difference["answer"]["result"], 2) == 2.2

        missing = _ask(client, project_id, revision_id, "Where is EL 999.9 located?")
        assert missing["answer"]["confidence"] == 0.0
        assert "No plan label" in missing["answer"]["limitations"][0]
    finally:
        app.dependency_overrides.clear()
        from civil_engineering.config import get_settings

        get_settings.cache_clear()


def test_elevation_lookup_flags_ambiguity_instead_of_silently_picking_a_duplicate_label(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    # Regression test found via code review: a real plan can repeat the same
    # rounded spot elevation at two different benchmarks (e.g. two separate "EL
    # 100.00" callouts). _find_labeled_elevation used to silently return the
    # first match via next(), unlike every sibling resolver added in this same
    # phase (_answer_area/_answer_dimensions/_answer_setback_compliance etc.),
    # which all explicitly flag more than one candidate as ambiguous rather than
    # guessing which one the question meant.
    client = _client(tmp_path, monkeypatch)
    try:
        drawing = ezdxf.new("R2010")  # type: ignore[attr-defined]
        modelspace = drawing.modelspace()
        modelspace.add_text("EL 100.00", dxfattribs={"layer": "ELEVATIONS", "insert": (5.0, 5.0)})
        modelspace.add_text("EL 100.00", dxfattribs={"layer": "ELEVATIONS", "insert": (50.0, 50.0)})
        modelspace.add_text("EL 95.00", dxfattribs={"layer": "ELEVATIONS", "insert": (0.0, 0.0)})
        project_id, revision_id = _revision_from_dxf(
            client, tmp_path, drawing, "duplicate_elevations.dxf", "Duplicate Elevation Site"
        )

        location = _ask(client, project_id, revision_id, "Where is EL 100.00 located?")
        assert location["answer"]["method"] == "clarification needed"
        assert len(location["answer"]["source_references"]) == 2

        difference = _ask(
            client,
            project_id,
            revision_id,
            "What is the elevation difference between EL 100.00 and EL 95.00?",
        )
        assert difference["answer"]["method"] == "clarification needed"
    finally:
        app.dependency_overrides.clear()
        from civil_engineering.config import get_settings

        get_settings.cache_clear()
