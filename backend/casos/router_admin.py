"""Área do administrador: desempenho, qualidade e configuração da IA (RF12, RNF02, RNF05).

Toda rota exige `admin_atual` (403 para estudante). O papel só se ganha pelo CLI
(`python -m auth.admin promover <email>`).
"""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from auth.router import admin_atual
from casos import ai, qualidade
from core import db
from models import (
    AvaliacaoRAG,
    ConfiguracaoIA,
    ConfiguracaoLeitura,
    DesempenhoIA,
    QualidadeIA,
    Usuario,
    VersaoConfig,
    agora,
)

router = APIRouter(prefix="/api/admin/ia", tags=["admin"], dependencies=[Depends(admin_atual)])


@router.get("/desempenho", response_model=DesempenhoIA)
async def desempenho(dias: int = Query(30, ge=1, le=365), s: AsyncSession = Depends(db.get_session)):
    return qualidade.desempenho(await db.chamadas_desde(s, agora() - timedelta(days=dias)))


@router.get("/qualidade", response_model=QualidadeIA)
async def qualidade_da_saida(s: AsyncSession = Depends(db.get_session)):
    return qualidade.avaliar(await db.casos_para_qualidade(s))


@router.post("/avaliacao-rag", response_model=AvaliacaoRAG)
async def avaliacao_rag():
    """Acerto@5 da recuperação no corpus ingerido (`rag/avaliacao.py`). Leva segundos."""
    from rag import avaliacao

    return AvaliacaoRAG(acertos=await avaliacao.no_banco(), consultas=len(avaliacao.CONSULTAS), k=avaliacao.K)


async def _leitura(s: AsyncSession) -> ConfiguracaoLeitura:
    historico = []
    for versao, autor in await db.historico_configuracao(s):
        try:
            historico.append(VersaoConfig(id=versao.id, criado_em=versao.criado_em, autor=autor, dados=versao.dados))
        except ValueError:  # versão gravada com um schema antigo: não dá para restaurar
            continue
    return ConfiguracaoLeitura(atual=ai.config(), versao_id=ai._config_id, padrao=ai.PADRAO, historico=historico)


@router.get("/configuracao", response_model=ConfiguracaoLeitura)
async def ler_configuracao(s: AsyncSession = Depends(db.get_session)):
    return await _leitura(s)


@router.put("/configuracao", response_model=ConfiguracaoLeitura)
async def salvar_configuracao(
    corpo: ai.ConfigIA, usuario: Usuario = Depends(admin_atual), s: AsyncSession = Depends(db.get_session)
):
    """Grava uma versão nova e passa a valer na hora. As chamadas seguintes registram o
    id dela (`chamada_ia.configuracao_id`)."""
    versao = await db.salvar_configuracao(s, corpo.model_dump(), usuario.id)
    ai.aplicar_config(versao.dados, versao.id)
    return await _leitura(s)


@router.post("/configuracao/{versao_id}/restaurar", response_model=ConfiguracaoLeitura)
async def restaurar(versao_id: int, usuario: Usuario = Depends(admin_atual), s: AsyncSession = Depends(db.get_session)):
    """Restaurar é salvar de novo os dados de uma versão antiga: o histórico não se perde."""
    antiga = await s.get(ConfiguracaoIA, versao_id)
    if antiga is None:
        raise HTTPException(404, "Versão não encontrada.")
    versao = await db.salvar_configuracao(s, ai.ConfigIA.model_validate(antiga.dados).model_dump(), usuario.id)
    ai.aplicar_config(versao.dados, versao.id)
    return await _leitura(s)
