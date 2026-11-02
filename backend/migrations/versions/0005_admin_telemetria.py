"""Papéis e consentimento do usuário; telemetria e configuração da IA.

O administrador vê o desempenho da IA e muda os parâmetros técnicos dela (RF12). Cada
chamada ao LLM fica registrada com a configuração em vigor (RNF02, RNF08), e o aceite do
termo de uso e tratamento de dados passa a ser gravado (LGPD).

Revision ID: 0005_admin_telemetria
Revises: 0004_simulados
Create Date: 2026-10-28

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0005_admin_telemetria"
down_revision: str | None = "0004_simulados"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("usuario", sa.Column("papel", sa.String(), nullable=False, server_default="estudante"))
    op.add_column("usuario", sa.Column("consentiu_em", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "configuracao_ia",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dados", JSONB(), nullable=False),
        sa.Column("criado_por", sa.Integer(), sa.ForeignKey("usuario.id", ondelete="SET NULL"), nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "chamada_ia",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("caso_id", sa.String(), sa.ForeignKey("caso_clinico.id", ondelete="CASCADE"), nullable=True),
        sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuario.id", ondelete="CASCADE"), nullable=True),
        sa.Column("etapa", sa.String(), nullable=False),
        sa.Column("modelo", sa.String(), nullable=False),
        sa.Column(
            "configuracao_id", sa.Integer(), sa.ForeignKey("configuracao_ia.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("tokens_entrada", sa.Integer(), nullable=False),
        sa.Column("tokens_cache", sa.Integer(), nullable=False),
        sa.Column("tokens_saida", sa.Integer(), nullable=False),
        sa.Column("custo", sa.Float(), nullable=True),
        sa.Column("latencia_ms", sa.Integer(), nullable=False),
        sa.Column("tentativas", sa.Integer(), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("erro", sa.String(), nullable=True),
        sa.Column("criada_em", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_chamada_ia_caso_id", "chamada_ia", ["caso_id"])
    op.create_index("ix_chamada_ia_usuario_id", "chamada_ia", ["usuario_id"])


def downgrade() -> None:
    op.drop_index("ix_chamada_ia_usuario_id", "chamada_ia")
    op.drop_index("ix_chamada_ia_caso_id", "chamada_ia")
    op.drop_table("chamada_ia")
    op.drop_table("configuracao_ia")
    op.drop_column("usuario", "consentiu_em")
    op.drop_column("usuario", "papel")
