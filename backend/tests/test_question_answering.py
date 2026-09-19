from collections.abc import Generator
from pathlib import Path

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


def _upload_and_build_revision(client: TestClient, project_id: str, csv_content: bytes) -> str:
    uploaded = client.post(
        f"/projects/{project_id}/files",
        files={"file": ("points.csv", csv_content, "text/csv")},
    ).json()
    processed = client.post(f"/projects/{project_id}/files/{uploaded['id']}/process").json()
    assert processed["status"] == "completed"
    revision = client.post(
        f"/projects/{project_id}/site-model/revisions/from-extraction/{uploaded['id']}"
    ).json()
    return str(revision["id"])


def test_setback_distance_question_answers_from_two_point_entities(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    try:
        project = client.post("/projects", json={"name": "Setback Site"}).json()
        revision_id = _upload_and_build_revision(client, project["id"], b"x,y\n0,0\n3,4\n")

        question = client.post(
            f"/projects/{project['id']}/questions",
            json={"question": "What is the setback distance?", "revision_ids": [revision_id]},
        )
        assert question.status_code == 200
        answer = question.json()["answer"]
        assert answer["result"] == 5.0
        assert answer["confidence"] == 0.9
        assert len(answer["source_references"]) == 2
        assert all(
            reference["file_name"] == "points.csv" for reference in answer["source_references"]
        )
    finally:
        app.dependency_overrides.clear()
        from civil_engineering.config import get_settings

        get_settings.cache_clear()


def test_setback_distance_question_is_ambiguous_with_three_point_entities(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    try:
        project = client.post("/projects", json={"name": "Ambiguous Site"}).json()
        revision_id = _upload_and_build_revision(client, project["id"], b"x,y\n0,0\n3,4\n10,10\n")

        question = client.post(
            f"/projects/{project['id']}/questions",
            json={"question": "What is the setback distance?", "revision_ids": [revision_id]},
        )
        assert question.status_code == 200
        answer = question.json()["answer"]
        assert answer["confidence"] == 0.0
        assert "ambiguous" in answer["answer"].lower()
        assert len(answer["source_references"]) == 3
    finally:
        app.dependency_overrides.clear()
        from civil_engineering.config import get_settings

        get_settings.cache_clear()


def test_question_without_revision_refuses_to_invent_a_measurement(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    try:
        project = client.post("/projects", json={"name": "No Data Site"}).json()
        question = client.post(
            f"/projects/{project['id']}/questions",
            json={"question": "What is the setback distance?"},
        )
        assert question.status_code == 200
        answer = question.json()["answer"]
        assert answer["confidence"] == 0.0
        assert "Insufficient data" in answer["answer"]
        assert "result" not in answer
    finally:
        app.dependency_overrides.clear()
        from civil_engineering.config import get_settings

        get_settings.cache_clear()


def _upload_process_accept(
    client: TestClient, project_id: str, file_name: str, csv_content: bytes
) -> dict:
    uploaded = client.post(
        f"/projects/{project_id}/files",
        files={"file": (file_name, csv_content, "text/csv")},
    ).json()
    processed = client.post(f"/projects/{project_id}/files/{uploaded['id']}/process").json()
    assert processed["status"] == "completed"
    revision = client.post(
        f"/projects/{project_id}/site-model/revisions/from-extraction/{uploaded['id']}"
    ).json()
    return {"file_id": uploaded["id"], "revision_id": revision["id"]}


def test_project_boundary_default_aggregates_across_multiple_files(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    try:
        project = client.post("/projects", json={"name": "Multi-File Site"}).json()
        # Each file contributes exactly one point; alone, neither has enough
        # geometry to answer a distance question. Only aggregating both (the
        # project-boundary default) yields the two points needed for 3-4-5.
        _upload_process_accept(client, project["id"], "a.csv", b"x,y\n0,0\n")
        _upload_process_accept(client, project["id"], "b.csv", b"x,y\n3,4\n")

        question = client.post(
            f"/projects/{project['id']}/questions",
            json={"question": "What is the setback distance?"},
        )
        assert question.status_code == 200
        body = question.json()
        answer = body["answer"]
        assert answer["confidence"] == 0.9
        assert answer["result"] == 5.0
        assert len(body["revision_ids"]) == 2
    finally:
        app.dependency_overrides.clear()
        from civil_engineering.config import get_settings

        get_settings.cache_clear()


def test_archiving_a_file_excludes_its_revision_from_project_boundary(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    # Regression test: _resolve_revision_ids (the default "whole project" scope
    # for summaries/questions) selected source files with no deleted_at filter,
    # unlike list_site_model_revisions which does. So archiving a file removed
    # its revision from GET .../site-model/revisions (and the UI), but a
    # default-scope summary/question would still silently pull it in.
    client = _client(tmp_path, monkeypatch)
    try:
        project = client.post("/projects", json={"name": "Archived File Site"}).json()
        first = _upload_process_accept(client, project["id"], "a.csv", b"x,y\n0,0\n")
        _upload_process_accept(client, project["id"], "b.csv", b"x,y\n3,4\n")

        # Before archiving: both files' points are in scope, giving the 3-4-5 answer.
        before = client.post(
            f"/projects/{project['id']}/questions",
            json={"question": "What is the setback distance?"},
        ).json()
        assert before["answer"]["result"] == 5.0
        assert len(before["revision_ids"]) == 2

        archived = client.delete(f"/projects/{project['id']}/files/{first['file_id']}")
        assert archived.status_code == 204

        # GET .../site-model/revisions already correctly excludes the archived
        # file's revision.
        revisions = client.get(f"/projects/{project['id']}/site-model/revisions").json()
        assert len(revisions) == 1

        after = client.post(
            f"/projects/{project['id']}/questions",
            json={"question": "What is the setback distance?"},
        )
        assert after.status_code == 200
        after_body = after.json()
        # Only b.csv's single point remains in scope: not enough geometry to
        # measure a distance, and the archived file's revision must not appear.
        assert after_body["revision_ids"] == [revisions[0]["id"]]
        assert after_body["answer"]["confidence"] == 0.0
        assert "No two mapped geometries" in " ".join(after_body["answer"]["limitations"])
    finally:
        app.dependency_overrides.clear()
        from civil_engineering.config import get_settings

        get_settings.cache_clear()


def test_replacing_a_file_excludes_the_superseded_revision_from_project_boundary(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    try:
        project = client.post("/projects", json={"name": "Versioned Site"}).json()
        original = _upload_process_accept(client, project["id"], "survey.csv", b"x,y\n0,0\n")

        replaced = client.post(
            f"/projects/{project['id']}/files/{original['file_id']}/replace",
            files={"file": ("survey.csv", b"x,y\n3,4\n", "text/csv")},
        )
        assert replaced.status_code == 201
        new_file = replaced.json()
        assert new_file["document_group_id"] == original["file_id"]
        processed = client.post(f"/projects/{project['id']}/files/{new_file['id']}/process").json()
        assert processed["status"] == "completed"
        new_revision = client.post(
            f"/projects/{project['id']}/site-model/revisions/from-extraction/{new_file['id']}"
        ).json()

        # If the superseded file's revision were still included, this would see
        # both points (the old at 0,0 and the new at 3,4) and answer 5.0 instead.
        question = client.post(
            f"/projects/{project['id']}/questions",
            json={"question": "What is the setback distance?"},
        )
        assert question.status_code == 200
        body = question.json()
        assert body["revision_ids"] == [new_revision["id"]]
        answer = body["answer"]
        assert answer["confidence"] == 0.0
        assert "No two mapped geometries" in " ".join(answer["limitations"])

        original_file = client.get(f"/projects/{project['id']}/files").json()
        replaced_entry = next(f for f in original_file if f["id"] == original["file_id"])
        assert replaced_entry["superseded_by_id"] == new_file["id"]

        second_replace_attempt = client.post(
            f"/projects/{project['id']}/files/{original['file_id']}/replace",
            files={"file": ("survey.csv", b"x,y\n1,1\n", "text/csv")},
        )
        assert second_replace_attempt.status_code == 409
    finally:
        app.dependency_overrides.clear()
        from civil_engineering.config import get_settings

        get_settings.cache_clear()


def test_area_and_perimeter_questions_are_routed_and_answered(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    # Regression test: "area"/"perimeter" questions previously fell through
    # route_question's default "summary" intent (which only looks for
    # extracted text) and always reported insufficient data, even though both
    # calculations already worked fine through POST /calculations directly.
    client = _client(tmp_path, monkeypatch)
    try:
        drawing = ezdxf.new("R2010")  # type: ignore[attr-defined]
        modelspace = drawing.modelspace()
        modelspace.add_lwpolyline(
            [(0, 0), (10, 0), (10, 10), (0, 10)], close=True, dxfattribs={"layer": "BUILDING"}
        )
        dxf_path = tmp_path / "building.dxf"
        drawing.saveas(dxf_path)

        project = client.post("/projects", json={"name": "Area Perimeter Site"}).json()
        uploaded = client.post(
            f"/projects/{project['id']}/files",
            files={"file": ("building.dxf", dxf_path.read_bytes(), "application/dxf")},
        ).json()
        processed = client.post(f"/projects/{project['id']}/files/{uploaded['id']}/process").json()
        assert processed["status"] == "completed"
        revision = client.post(
            f"/projects/{project['id']}/site-model/revisions/from-extraction/{uploaded['id']}"
        ).json()

        area = client.post(
            f"/projects/{project['id']}/questions",
            json={
                "question": "What is the area of the building?",
                "revision_ids": [revision["id"]],
            },
        ).json()
        assert area["intent"] == "area"
        assert area["answer"]["confidence"] == 0.9
        assert area["answer"]["result"] == 100.0

        perimeter = client.post(
            f"/projects/{project['id']}/questions",
            json={
                "question": "What is the perimeter of the building?",
                "revision_ids": [revision["id"]],
            },
        ).json()
        assert perimeter["intent"] == "perimeter"
        assert perimeter["answer"]["confidence"] == 0.9
        assert perimeter["answer"]["result"] == 40.0
    finally:
        app.dependency_overrides.clear()
        from civil_engineering.config import get_settings

        get_settings.cache_clear()


def test_area_and_perimeter_questions_pick_the_named_role_instead_of_colliding(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    # Regression test (PLAN.md Phase 14 / RISK_REGISTER.md): with both a
    # parcel boundary and a building footprint polygon in the model,
    # _answer_area/_answer_perimeter used to match every polygon regardless
    # of what the question named, so "What is the property area?" and "What
    # is the building footprint area?" collided on the same candidate pool
    # and both returned "ambiguous" instead of picking the one the question
    # actually asked about.
    client = _client(tmp_path, monkeypatch)
    try:
        drawing = ezdxf.new("R2010")  # type: ignore[attr-defined]
        modelspace = drawing.modelspace()
        # Parcel: 100x100 -> area 10000, perimeter 400.
        modelspace.add_lwpolyline(
            [(0, 0), (100, 0), (100, 100), (0, 100)],
            close=True,
            dxfattribs={"layer": "PROPERTY LINE"},
        )
        # Building footprint: 10x10 -> area 100, perimeter 40.
        modelspace.add_lwpolyline(
            [(0, 0), (10, 0), (10, 10), (0, 10)],
            close=True,
            dxfattribs={"layer": "BUILDING FOOTPRINT"},
        )
        dxf_path = tmp_path / "parcel_and_building.dxf"
        drawing.saveas(dxf_path)

        project = client.post("/projects", json={"name": "Role Filtering Site"}).json()
        uploaded = client.post(
            f"/projects/{project['id']}/files",
            files={"file": ("parcel_and_building.dxf", dxf_path.read_bytes(), "application/dxf")},
        ).json()
        processed = client.post(f"/projects/{project['id']}/files/{uploaded['id']}/process").json()
        assert processed["status"] == "completed"
        revision = client.post(
            f"/projects/{project['id']}/site-model/revisions/from-extraction/{uploaded['id']}"
        ).json()

        def ask(question: str) -> dict:
            return client.post(
                f"/projects/{project['id']}/questions",
                json={"question": question, "revision_ids": [revision["id"]]},
            ).json()

        property_area = ask("What is the parcel area?")
        assert property_area["answer"]["result"] == 10000.0
        assert property_area["answer"]["confidence"] == 0.9

        building_area = ask("What is the building footprint area?")
        assert building_area["answer"]["result"] == 100.0
        assert building_area["answer"]["confidence"] == 0.9

        property_perimeter = ask("What is the parcel perimeter?")
        assert property_perimeter["answer"]["result"] == 400.0

        building_perimeter = ask("What is the building footprint perimeter?")
        assert building_perimeter["answer"]["result"] == 40.0

        # No role named in the question -- both polygons still match, so this
        # stays ambiguous rather than silently guessing one.
        generic_area = ask("What is the area?")
        assert generic_area["answer"]["method"] == "clarification needed"
        assert len(generic_area["answer"]["source_references"]) == 2
    finally:
        app.dependency_overrides.clear()
        from civil_engineering.config import get_settings

        get_settings.cache_clear()
