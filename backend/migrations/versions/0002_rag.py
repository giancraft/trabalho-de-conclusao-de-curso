"""RAG: fonte de referência, trechos com embedding e vínculo caso ↔ fonte (RF04/RF14).

Revision ID: 0002_rag
Revises: 0001_fundacao
Create Date: 2026-09-24

"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002_rag"
down_revision: str | None = "0001_fundacao"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fonte_referencia",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chave", sa.String(), nullable=False),
        sa.Column("titulo", sa.String(), nullable=False),
        sa.Column("orgao", sa.String(), nullable=False),
        sa.Column("tipo", sa.String(), nullable=False),
        sa.Column("identificador", sa.String(), nullable=False),
        sa.Column("publicado_em", sa.Date(), nullable=True),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("licenca", sa.String(), nullable=False),
        sa.Column("cid10", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("bibliografia", postgresql.JSONB(), nullable=True),
        sa.Column("sorteavel", sa.Boolean(), nullable=False),
        sa.Column("recuperada_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("especialidade", sa.String(), nullable=False),
        sa.Column("dificuldade", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chave"),
    )

    # O sorteio filtra por papel e balde a cada caso: com milhares de artigos, isso não
    # pode ser varredura.
    op.create_index(
        "ix_fonte_sorteio", "fonte_referencia", ["especialidade", "dificuldade"],
        postgresql_where=sa.text("sorteavel"),
    )

    op.create_table(
        "trecho",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fonte_id", sa.Integer(), nullable=False),
        sa.Column("ordem", sa.Integer(), nullable=False),
        sa.Column("secao", sa.String(), nullable=False),
        sa.Column("secao_id", sa.String(), nullable=True),
        sa.Column("texto", sa.String(), nullable=False),
        # 384 = paraphrase-multilingual-MiniLM-L12-v2 (rag/embeddings.py).
        sa.Column("embedding", Vector(384), nullable=False),
        sa.ForeignKeyConstraint(["fonte_id"], ["fonte_referencia.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_trecho_fonte_id"), "trecho", ["fonte_id"])
    # Sem HNSW a busca kNN é varredura completa sobre ~10⁵ trechos. Criado com a tabela
    # vazia, o índice cresce a cada insert da ingestão — sem build gigante de uma vez.
    op.execute("CREATE INDEX ix_trecho_embedding ON trecho USING hnsw (embedding vector_cosine_ops)")

    op.create_table(
        "caso_fonte",
        sa.Column("caso_id", sa.String(), nullable=False),
        sa.Column("fonte_id", sa.Integer(), nullable=False),
        # "caso" (geração) ou "feedback": cada etapa registra as próprias fontes.
        sa.Column("etapa", sa.String(), nullable=False),
        # O [n] citado no texto do feedback e os ids exatos dos trechos que foram ao
        # prompt — a rastreabilidade do RF14/RNF08 vai até o parágrafo.
        sa.Column("numero", sa.Integer(), nullable=False),
        sa.Column("trechos", postgresql.ARRAY(sa.Integer()), nullable=False),
        sa.ForeignKeyConstraint(["caso_id"], ["caso_clinico.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["fonte_id"], ["fonte_referencia.id"]),
        sa.PrimaryKeyConstraint("caso_id", "fonte_id", "etapa"),
    )


def downgrade() -> None:
    op.drop_table("caso_fonte")
    op.drop_table("trecho")
    op.drop_table("fonte_referencia")
