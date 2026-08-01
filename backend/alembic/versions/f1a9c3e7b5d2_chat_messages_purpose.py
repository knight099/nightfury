"""chat_messages_purpose

Revision ID: f1a9c3e7b5d2
Revises: a3f7c1d9e6b2
Create Date: 2026-08-02 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1a9c3e7b5d2"
down_revision: Union[str, None] = "a3f7c1d9e6b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chat_messages",
        sa.Column("purpose", sa.String(30), nullable=False, server_default="qa"),
    )
    op.create_index(
        "ix_chat_messages_camera_purpose_created",
        "chat_messages",
        ["camera_id", "purpose", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_chat_messages_camera_purpose_created", table_name="chat_messages")
    op.drop_column("chat_messages", "purpose")
