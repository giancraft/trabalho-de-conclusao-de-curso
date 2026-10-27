"""Árvore de temas nas fontes e simulados de N casos.

O estudante marca nós de uma árvore (grande área → especialidade → tema) e recebe uma
sequência de casos sorteados deles. A posição de cada fonte na árvore é gravada pela
ingestão (`rag/temas.py`); o simulado guarda a seleção e a fila sorteada.

Revision ID: 0004_simulados
Revises: 0003_ciclos
Create Date: 2026-10-27

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

from alembic import op

revision: str = "0004_simulados"
down_revision: str | None = "0003_ciclos"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("fonte_referencia", sa.Column("grande_area", sa.String(), nullable=False, server_default=""))
    op.add_column("fonte_referencia", sa.Column("tema", sa.String(), nullable=False, server_default=""))
    op.create_index("ix_fonte_referencia_tema", "fonte_referencia", ["tema"])
    op.create_table(
        "simulado",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuario.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ciclo", sa.String(), nullable=False),
        sa.Column("selecao", JSONB(), nullable=False),
        sa.Column("fila", ARRAY(sa.Integer()), nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_simulado_usuario_id", "simulado", ["usuario_id"])
    op.add_column(
        "caso_clinico",
        sa.Column("simulado_id", sa.String(), sa.ForeignKey("simulado.id", ondelete="CASCADE"), nullable=True),
    )
    op.add_column("caso_clinico", sa.Column("ordem", sa.Integer(), nullable=True))
    op.create_index("ix_caso_clinico_simulado_id", "caso_clinico", ["simulado_id"])


def downgrade() -> None:
    op.drop_index("ix_caso_clinico_simulado_id", "caso_clinico")
    op.drop_column("caso_clinico", "ordem")
    op.drop_column("caso_clinico", "simulado_id")
    op.drop_index("ix_simulado_usuario_id", "simulado")
    op.drop_table("simulado")
    op.drop_index("ix_fonte_referencia_tema", "fonte_referencia")
    op.drop_column("fonte_referencia", "tema")
    op.drop_column("fonte_referencia", "grande_area")
