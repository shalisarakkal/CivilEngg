"""Add calculation detail payloads."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_add_calculation_details"
down_revision: Union[str, None] = "0006_add_file_archive_metadata"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("calculation_results", sa.Column("details", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("calculation_results", "details")
