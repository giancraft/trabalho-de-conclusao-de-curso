"""Fundação: extensão vector e as 4 entidades com dados.

As tabelas seguem a modelagem conceitual do TCC (seção 4.7). As outras 6 entidades
(Flashcard, Métrica de Desempenho, Recomendação de Estudo, Fonte de Referência, Perfil
Acadêmico) entram nas migrações dos módulos que as usam.

Revision ID: 0001_fundacao
Revises:
Create Date: 2026-09-21

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001_fundacao"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Habilitada aqui para que o RF04 (RAG, setembro) encontre o terreno pronto. Nada
    # nesta migração usa o tipo vector.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "usuario",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nome", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        # bytes, não texto: é o que bcrypt.hashpw devolve e o que checkpw exige.
        sa.Column("senha_hash", sa.LargeBinary(), nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_usuario_email"), "usuario", ["email"], unique=True)

    op.create_table(
        "sessao",
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("expira_em", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuario.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("token_hash"),
    )
    op.create_index(op.f("ix_sessao_usuario_id"), "sessao", ["usuario_id"])

    op.create_table(
        "caso_clinico",
        # uuid4().hex como texto: o id já viaja na URL e no estado do frontend sem hífen.
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("titulo", sa.String(), nullable=False),
        sa.Column("especialidade", sa.String(), nullable=False),
        sa.Column("dificuldade", sa.String(), nullable=False),
        # JSONB em vez de TEXT com json.dumps: o driver entrega dict e o módulo de
        # métricas (RF10) poderá consultar campos internos sem parsear em Python.
        sa.Column("gabarito", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("feedback", postgresql.JSONB(), nullable=True),
        sa.Column("criada_em", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuario.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_caso_clinico_usuario_id"), "caso_clinico", ["usuario_id"])

    op.create_table(
        "resposta",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("caso_id", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("criada_em", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["caso_id"], ["caso_clinico.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_resposta_caso_id"), "resposta", ["caso_id"])


def downgrade() -> None:
    op.drop_table("resposta")
    op.drop_table("caso_clinico")
    op.drop_table("sessao")
    op.drop_table("usuario")
    # A extensão não é removida: outros schemas do mesmo banco podem depender dela.
