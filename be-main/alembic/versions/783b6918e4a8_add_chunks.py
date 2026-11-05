"""add chunks

Retrieval passages and their embeddings. On Postgres the embedding column is
pgvector's `vector`, so this also enables the extension — which needs a role
allowed to create extensions (the database owner in compose, `postgres` on
Cloud SQL). SQLite stores the same values as packed float32 bytes.

Revision ID: 783b6918e4a8
Revises: 43795a56c564
Create Date: 2026-11-05 12:32:24.311608

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import VECTOR


# revision identifiers, used by Alembic.
revision: str = '783b6918e4a8'
down_revision: Union[str, Sequence[str], None] = '43795a56c564'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        embedding_type: sa.types.TypeEngine = VECTOR()
    else:
        embedding_type = sa.LargeBinary()

    op.create_table('chunks',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('project_id', sa.String(length=32), nullable=False),
    sa.Column('paper_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('ordinal', sa.Integer(), nullable=False),
    sa.Column('section', sa.String(length=255), nullable=True),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('embedding_model', sa.String(length=255), nullable=False),
    sa.Column('embedding', embedding_type, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['paper_id'], ['papers.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('paper_id', 'embedding_model', 'kind', 'ordinal', name='uq_chunks_position'),
    # Never reuse an id on SQLite either; see the Chunk model.
    sqlite_autoincrement=True,
    )
    with op.batch_alter_table('chunks', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_chunks_paper_id'), ['paper_id'], unique=False)
        batch_op.create_index('ix_chunks_project_model', ['project_id', 'embedding_model'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('chunks', schema=None) as batch_op:
        batch_op.drop_index('ix_chunks_project_model')
        batch_op.drop_index(batch_op.f('ix_chunks_paper_id'))

    op.drop_table('chunks')
    # The vector extension is left installed: dropping it would fail if
    # anything else in the database had come to depend on it.
