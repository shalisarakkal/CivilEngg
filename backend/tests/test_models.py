from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from civil_engineering.database import Base
from civil_engineering.models import Client, ProcessingJob, Project, ProjectRevision, SourceFile


def test_project_entities_persist_relationships() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        client = Client(name="Example Engineering")
        project = Project(name="Oak Street Site", client=client)
        source_file = SourceFile(
            project=project,
            original_name="site-plan.pdf",
            stored_path="projects/oak-street/site-plan.pdf",
            media_type="application/pdf",
            size_bytes=1024,
            checksum="a" * 64,
            document_group_id="site-plan-group",
        )
        job = ProcessingJob(project=project, source_file=source_file)
        ProjectRevision(project=project, revision_number=1, source_job_ids=[job.id])
        session.add(client)
        session.commit()

        loaded = session.get(Project, project.id)
        assert loaded is not None
        assert loaded.client is not None
        assert loaded.client.name == "Example Engineering"
        assert loaded.source_files[0].original_name == "site-plan.pdf"
        assert loaded.processing_jobs[0].status == "queued"
        assert loaded.revisions[0].revision_number == 1
