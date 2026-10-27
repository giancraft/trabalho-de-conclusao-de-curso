"""Ciclos do curso no lugar da dificuldade do caso; peso de sorteio nas fontes.

O nível do caso deixa de escolher a doença e passa a escolher o que se cobra: ciclo
básico (fisiologia e fisiopatologia), clínico (+ diagnóstico e tratamento) e internato
(+ conduta detalhada). A doença sai de um sorteio ponderado pela relevância (`peso`).

Revision ID: 0003_ciclos
Revises: 0002_rag
Create Date: 2026-10-24

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_ciclos"
down_revision: str | None = "0002_rag"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Casos antigos: o nível de dificuldade mais próximo do ciclo.
_PARA_CICLO = {"básico": "básico", "intermediário": "clínico", "avançado": "internato"}


def _converter(de: dict[str, str]) -> None:
    for antigo, novo in de.items():
        op.execute(
            sa.text("UPDATE caso_clinico SET ciclo = :novo WHERE ciclo = :antigo").bindparams(
                novo=novo, antigo=antigo
            )
        )


def upgrade() -> None:
    op.alter_column("caso_clinico", "dificuldade", new_column_name="ciclo")
    _converter(_PARA_CICLO)
    op.add_column(
        "fonte_referencia",
        sa.Column("peso", sa.Float(), nullable=False, server_default=sa.text("1")),
    )


def downgrade() -> None:
    op.drop_column("fonte_referencia", "peso")
    _converter({v: k for k, v in _PARA_CICLO.items()})
    op.alter_column("caso_clinico", "ciclo", new_column_name="dificuldade")
