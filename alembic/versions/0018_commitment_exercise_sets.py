"""Add sets column to commitment_exercises; widen unique constraint to (commitment_id, name, sets).

- commitment_exercises.sets INTEGER NULL — target set count per exercise definition
- Drop old unique constraint (commitment_id, name) and replace with (commitment_id, name, sets)
  so the same exercise can appear with different set counts in one plan.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("commitment_exercises") as batch_op:
        batch_op.add_column(sa.Column("sets", sa.Integer(), nullable=True))
        batch_op.drop_constraint("uq_commitment_exercise_name", type_="unique")
        batch_op.create_unique_constraint(
            "uq_commitment_exercise_name_sets",
            ["commitment_id", "name", "sets"],
        )


def downgrade() -> None:
    with op.batch_alter_table("commitment_exercises") as batch_op:
        batch_op.drop_constraint("uq_commitment_exercise_name_sets", type_="unique")
        batch_op.create_unique_constraint(
            "uq_commitment_exercise_name",
            ["commitment_id", "name"],
        )
        batch_op.drop_column("sets")
