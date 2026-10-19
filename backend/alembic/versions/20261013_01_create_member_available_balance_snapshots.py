from alembic import op
import sqlalchemy as sa


revision = "20261016_01"
down_revision = "20261013_01"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    cols = [c["name"] for c in sa.inspect(bind).get_columns("users")]
    if "bank_balance" in cols:
        return
    op.add_column(
        "users",
        sa.Column("bank_balance", sa.Numeric(18, 2), nullable=False, server_default="0"),
    )


def downgrade():
    bind = op.get_bind()
    cols = [c["name"] for c in sa.inspect(bind).get_columns("users")]
    if "bank_balance" in cols:
        op.drop_column("users", "bank_balance")