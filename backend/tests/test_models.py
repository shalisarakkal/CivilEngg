from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from civil_engineering.database import Base
from civil_engineering.models import (
    Client,
    ProcessingJob,
    Project,
    ProjectRevision,
    SourceFile,
    Tenant,
    User,
)


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


def test_tenant_scopes_users_clients_and_projects() -> None:
    # PLAN.md Phase 16 / DECISIONS.md ADR-010: schema-only foundation for the
    # hybrid dedicated/shared-instance deployment model. Nothing yet enforces
    # tenant_id on any query -- this only proves the column exists, is
    # nullable (a pre-existing row without one is valid), and round-trips
    # through the ORM on every scoped table.
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        tenant = Tenant(name="Acme Engineering")
        user = User(username="acme_user", password_hash="hash", role="power_user", tenant=tenant)
        client = Client(name="Acme's Client", tenant=tenant)
        project = Project(name="Acme Site", tenant=tenant)
        # A row with no tenant at all is still valid -- the dedicated-install
        # bootstrap backfills these, but nothing requires it at the DB level.
        untenanted_project = Project(name="Untenanted Site")
        session.add_all([tenant, user, client, project, untenanted_project])
        session.commit()

        loaded_tenant = session.get(Tenant, tenant.id)
        assert loaded_tenant is not None
        assert loaded_tenant.name == "Acme Engineering"

        loaded_user = session.get(User, user.id)
        loaded_client = session.get(Client, client.id)
        loaded_project = session.get(Project, project.id)
        loaded_untenanted_project = session.get(Project, untenanted_project.id)
        assert loaded_user is not None
        assert loaded_client is not None
        assert loaded_project is not None
        assert loaded_untenanted_project is not None
        assert loaded_user.tenant_id == tenant.id
        assert loaded_client.tenant_id == tenant.id
        assert loaded_project.tenant_id == tenant.id
        assert loaded_untenanted_project.tenant_id is None
