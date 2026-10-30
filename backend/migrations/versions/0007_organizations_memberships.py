"""Add organizations, memberships and personal organizations for users.

Revision ID: 0007_organizations_memberships
Revises: 0006_processing_jobs
"""

from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0007_organizations_memberships"
down_revision: Union[str, None] = "0006_processing_jobs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

membership_role = postgresql.ENUM(
    "owner", "admin", "member", name="organization_membership_role", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    membership_role.create(bind, checkfirst=True)

    op.create_table(
        "organizations",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("personal_owner_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["personal_owner_user_id"], ["users.id"], ondelete="CASCADE", name="fk_organizations_personal_owner_user_id_users"),
        sa.PrimaryKeyConstraint("id", name="pk_organizations"),
        sa.UniqueConstraint("personal_owner_user_id", name="uq_organizations_personal_owner_user_id"),
    )
    op.create_table(
        "organization_memberships",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", membership_role, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("role IN ('owner', 'admin', 'member')", name="ck_organization_memberships_role"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE", name="fk_organization_memberships_organization_id_organizations"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE", name="fk_organization_memberships_user_id_users"),
        sa.PrimaryKeyConstraint("organization_id", "user_id", name="pk_organization_memberships"),
    )
    op.create_index("ix_organization_memberships_user_id", "organization_memberships", ["user_id"])

    # Existing organization UUIDs on meetings have no authoritative mapping.
    # Provision personal workspaces only; do not rewrite or grant access to
    # historical meeting organization IDs.
    users = bind.execute(sa.text("SELECT id FROM users ORDER BY id")).scalars().all()
    for user_id in users:
        organization_id = uuid4()
        bind.execute(
            sa.text(
                "INSERT INTO organizations (id, name, personal_owner_user_id) "
                "VALUES (:id, 'Personal workspace', :user_id) "
                "ON CONFLICT (personal_owner_user_id) DO NOTHING"
            ),
            {"id": organization_id, "user_id": user_id},
        )
        resolved_id = bind.execute(
            sa.text("SELECT id FROM organizations WHERE personal_owner_user_id = :user_id"),
            {"user_id": user_id},
        ).scalar_one()
        bind.execute(
            sa.text(
                "INSERT INTO organization_memberships (organization_id, user_id, role) "
                "VALUES (:organization_id, :user_id, 'owner') "
                "ON CONFLICT (organization_id, user_id) DO NOTHING"
            ),
            {"organization_id": resolved_id, "user_id": user_id},
        )


def downgrade() -> None:
    # Downgrade intentionally removes only organization/membership data and
    # schema. It does not alter users or historical meetings.
    op.drop_index("ix_organization_memberships_user_id", table_name="organization_memberships")
    op.drop_table("organization_memberships")
    op.drop_table("organizations")
    membership_role.drop(op.get_bind(), checkfirst=True)
