"""Rotas de casos clínicos e do histórico de conversas (RF03–RF07, RF13, RF14).

As rotas mantêm o prefixo /api/conversas do protótipo; no banco a entidade se chama
`caso_clinico`, conforme a modelagem do TCC (ver models.py).
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from auth.router import usuario_atual
from casos import ai, metricas
from core import db
from models import (
    CasoAberto,
    CasoClinico,
    CasoLeitura,
    CasoFonte,
    CasoResumo,
    Desempenho,
    FonteLeitura,
    FonteReferencia,
    ItemSimulado,
    ListaCasos,
    Opcoes,
    Resposta,
    SecaoConsultada,
    Simulado,
    SimuladoLeitura,
    Trecho,
    Usuario,
    agora,
)
from rag import busca, temas
from rag.citacao import citacao_abnt, leitura_fisiologia, url_secao

router = APIRouter(prefix="/api", tags=["casos"])

# O logger do uvicorn já sai formatado no stdout do container: o detalhe do erro fica no
# log, e o estudante só vê a mensagem de `_falha_ia`.
log = logging.getLogger("uvicorn.error")


def _falha_ia(e: Exception, acao: str) -> str:
    """Loga o erro completo e devolve só a mensagem que o estudante pode ver.

    O texto da exceção do provedor traz id da organização, limites e link de billing:
    nada disso é para a tela.
    """
    log.exception("Falha da IA ao %s", acao)
    # 402: sem créditos; 413/429: limite de tokens do provedor. `getattr` evita importar
    # o cliente de IA aqui.
    if getattr(e, "status_code", None) in (402, 413, 429):
        return "O serviço de IA está no limite de uso agora. Aguarde um minuto e tente de novo."
    return f"Não foi possível {acao} agora. Tente novamente em instantes."


class NovoSimulado(BaseModel):
    selecao: list[str] = Field(min_length=1)  # ids dos nós da árvore (rag/temas.py)
    ciclo: str
    quantidade: int = Field(ge=1, le=10)


class Mensagem(BaseModel):
    mensagem: str


class RespostaFinal(BaseModel):
    """Entrega final do caso; os campos obrigatórios dependem do ciclo (ai.CAMPOS_POR_CICLO)."""

    diagnostico: str
    fisiologia: str = ""
    fisiopatologia: str = ""
    conduta: str = ""


# Linha acrescentada à abertura quando a condição sorteada vem de relato de caso.
AVISO_RELATO = "*Caso baseado em relato publicado: a apresentação pode ser menos típica.*"


async def _caso_do_usuario(
    s: AsyncSession, caso_id: str, usuario_id: int
) -> tuple[CasoClinico, list[Resposta]]:
    par = await db.carregar_caso(s, caso_id, usuario_id)
    if par is None:
        raise HTTPException(404, "Conversa não encontrada.")
    return par


def _historico(respostas: list[Resposta]) -> list[dict]:
    """Respostas no formato de mensagens que o cliente da IA consome."""
    return [{"role": r.role, "content": r.content} for r in respostas]


# Referências às gravações em voo. Sem isto o coletor de lixo pode recolher a task antes
# de ela terminar — asyncio só guarda referências fracas.
_gravacoes: set[asyncio.Task] = set()


def _gravar_resposta_em_background(caso_id: str, texto: str) -> None:
    """Persiste a resposta do assistente fora da task da request.

    Quando o cliente desconecta no meio do stream, o Starlette cancela a task da
    request. O `finally` do gerador chega a rodar, mas qualquer `await` ali dentro é
    cancelado imediatamente — inclusive abrir a conexão com o banco. Testado: a
    resposta parcial se perdia com um CancelledError no connect do asyncpg.

    Uma task própria não herda esse cancelamento e completa a gravação.
    """

    async def gravar() -> None:
        async with db.abrir_sessao() as sessao:
            await db.adicionar_resposta(sessao, caso_id, "assistant", texto)

    tarefa = asyncio.create_task(gravar())
    _gravacoes.add(tarefa)
    tarefa.add_done_callback(_gravacoes.discard)


async def _referencias(s: AsyncSession, caso_id: str) -> list[FonteLeitura]:
    """Lista de referências do caso, numerada como no texto do feedback (RF14).

    Junta as duas etapas: cada fonte aparece uma vez, com as seções de onde saíram os
    trechos que foram ao prompt — na geração do caso e na avaliação.
    """
    por_fonte: dict[int, tuple[int, object, set[int]]] = {}
    for uso, fonte in await db.fontes_do_caso(s, caso_id):
        por_fonte.setdefault(fonte.id, (uso.numero, fonte, set()))[2].update(uso.trechos)
    ids = {i for _, _, usados in por_fonte.values() for i in usados}
    trechos = {t.id: t for t in (await s.execute(select(Trecho).where(Trecho.id.in_(ids)))).scalars()}

    referencias = []
    for numero, fonte, usados in sorted(por_fonte.values(), key=lambda x: x[0]):
        secoes = dict.fromkeys(
            (trechos[i].secao, trechos[i].secao_id)
            for i in sorted(usados & trechos.keys(), key=lambda i: trechos[i].ordem)
        )
        citacao, destaque = citacao_abnt(fonte, fonte.recuperada_em.date())
        referencias.append(
            FonteLeitura(
                numero=numero,
                tipo=fonte.tipo,
                citacao=citacao,
                destaque=destaque,
                url=fonte.url,
                licenca=fonte.licenca,
                secoes=[SecaoConsultada(titulo=t, url=url_secao(fonte.url, sid)) for t, sid in secoes],
            )
        )
    return referencias


@router.get("/temas", response_model=Opcoes)
async def arvore_de_temas(
    usuario: Usuario = Depends(usuario_atual), s: AsyncSession = Depends(db.get_session)
):
    """Árvore grande área → especialidade → tema, com o que há para sortear em cada nó e
    quantos casos o estudante já encerrou nele (pela condição sorteada, a fonte [1])."""
    F = FonteReferencia
    nivel = (F.grande_area, F.especialidade, F.tema)
    disponiveis = {
        tuple(l[:3]): l[3]
        for l in await s.execute(select(*nivel, func.count()).where(F.sorteavel, F.tema != "").group_by(*nivel))
    }
    respondidos = {
        tuple(l[:3]): l[3]
        for l in await s.execute(
            select(*nivel, func.count())
            .join(CasoFonte, CasoFonte.fonte_id == F.id)
            .join(CasoClinico, CasoClinico.id == CasoFonte.caso_id)
            .where(
                CasoClinico.usuario_id == usuario.id,
                CasoClinico.status == "encerrada",
                CasoFonte.etapa == "caso",
                CasoFonte.numero == 1,
            )
            .group_by(*nivel)
        )
    }
    nomes = dict((await s.execute(select(F.chave, F.titulo).where(F.chave.in_({k[2] for k in disponiveis})))).all())
    return Opcoes(arvore=temas.arvore(disponiveis, respondidos, nomes), ciclos=ai.CICLOS)


@router.get("/desempenho", response_model=Desempenho)
async def desempenho(
    usuario: Usuario = Depends(usuario_atual), s: AsyncSession = Depends(db.get_session)
):
    """Painel do estudante: KPIs, evolução, recortes e o que estudar a seguir (RF10, RF11)."""
    F = FonteReferencia
    casos = await db.historico_de_desempenho(s, usuario.id)
    # Temas sorteáveis do mais ao menos importante: base do "ainda não praticado".
    importantes = [
        {"id": f"t:{chave}", "nome": titulo}
        for chave, titulo in await s.execute(
            select(F.chave, F.titulo).where(F.sorteavel, F.tipo.in_(temas.CONDICOES)).order_by(F.peso.desc()).limit(40)
        )
    ]
    nomes = dict((await s.execute(select(F.chave, F.titulo).where(F.chave.in_({c["tema"] for c in casos})))).all())
    return Desempenho(**metricas.resumir(casos, importantes, nomes, agora()))


@router.get("/conversas", response_model=ListaCasos)
async def listar(
    usuario: Usuario = Depends(usuario_atual), s: AsyncSession = Depends(db.get_session)
):
    casos = await db.listar_casos(s, usuario.id)
    totais = await db.totais_dos_simulados(s, usuario.id)
    return ListaCasos(
        conversas=[
            CasoResumo.model_validate(c, from_attributes=True).model_copy(update={"total": totais.get(c.simulado_id)})
            for c in casos
        ]
    )


@router.get("/conversas/{caso_id}", response_model=CasoLeitura)
async def abrir(
    caso_id: str,
    usuario: Usuario = Depends(usuario_atual),
    s: AsyncSession = Depends(db.get_session),
):
    caso, respostas = await _caso_do_usuario(s, caso_id, usuario.id)
    # O gabarito fica de fora, e `CasoLeitura` não tem o campo — mesmo que alguém o
    # acrescente aqui por engano, o response_model não o deixa passar (RN06).
    # Casos encerrados expõem o diagnóstico por feedback.diagnostico_correto.
    # As fontes seguem o mesmo critério do feedback: o título do capítulo É o
    # diagnóstico, então num caso aberto elas não saem daqui.
    fontes = await _referencias(s, caso_id) if caso.status == "encerrada" else []
    simulado = await s.get(Simulado, caso.simulado_id) if caso.simulado_id else None
    return CasoLeitura(
        id=caso.id,
        titulo=caso.titulo,
        especialidade=caso.especialidade,
        ciclo=caso.ciclo,
        status=caso.status,
        mensagens=_historico(respostas),
        feedback=caso.feedback,
        fontes=fontes,
        simulado_id=caso.simulado_id,
        ordem=caso.ordem,
        total=len(simulado.fila) if simulado else None,
    )


@router.delete("/conversas/{caso_id}", status_code=204)
async def apagar(
    caso_id: str,
    usuario: Usuario = Depends(usuario_atual),
    s: AsyncSession = Depends(db.get_session),
):
    if not await db.apagar_caso(s, caso_id, usuario.id):
        raise HTTPException(404, "Conversa não encontrada.")


async def _abrir_caso(
    s: AsyncSession, usuario_id: int, fonte: FonteReferencia, ciclo: str, simulado: Simulado, ordem: int
) -> CasoAberto:
    """Gera o caso da fonte sorteada e o grava na posição `ordem` do simulado.

    A condição vem do corpus antes de o LLM escrever qualquer coisa (RN01). Junto vêm as
    fontes de apoio — o PCDT ou a diretriz brasileira mais próximos —, numeradas [1],
    [2]... (RF04). O ciclo não muda a doença, só o que se cobra.
    """
    relato = fonte.tipo == "Relato de caso"
    blocos = [(fonte, await busca.material(s, fonte, "caso"))]
    for apoio in await busca.fontes_de_apoio(s, fonte):
        if trechos := await busca.material(s, apoio, "caso", principal=False):
            blocos.append((apoio, trechos))
    numerados = [(n, f, ts) for n, (f, ts) in enumerate(blocos, 1)]
    try:
        caso = await ai.novo_caso(fonte.especialidade, ciclo, fonte.titulo, busca.contexto(numerados), relato=relato)
    except Exception as e:  # noqa: BLE001 — erro amigável, sem stack trace no cliente
        raise HTTPException(502, _falha_ia(e, "gerar o caso"))

    caso_id = await db.criar_caso(
        s,
        usuario_id,
        caso.titulo,
        fonte.especialidade,
        ciclo,
        caso.gabarito.model_dump(),
        fontes=[(f.id, n, [t.id for t in ts]) for n, f, ts in numerados],
        simulado_id=simulado.id,
        ordem=ordem,
    )
    apresentacao = f"{caso.apresentacao}\n\n{AVISO_RELATO}" if relato else caso.apresentacao
    await db.adicionar_resposta(s, caso_id, "assistant", apresentacao)
    return CasoAberto(
        caso_id=caso_id, titulo=caso.titulo, ciclo=ciclo, apresentacao=apresentacao,
        simulado_id=simulado.id, ordem=ordem, total=len(simulado.fila),
    )


async def _simulado_do_usuario(s: AsyncSession, simulado_id: str, usuario_id: int):
    par = await db.carregar_simulado(s, simulado_id, usuario_id)
    if par is None:
        raise HTTPException(404, "Simulado não encontrado.")
    return par


@router.post("/simulados", response_model=CasoAberto)
async def criar_simulado(
    corpo: NovoSimulado,
    usuario: Usuario = Depends(usuario_atual),
    s: AsyncSession = Depends(db.get_session),
):
    """Sorteia a fila de N casos dos temas marcados e já abre o primeiro.

    Os outros são gerados um a um (`/proximo`): gerar todos agora estouraria o limite de
    tokens/min do provedor e faria o estudante esperar por casos que talvez nem abra.
    """
    if corpo.ciclo not in ai.CICLOS:
        raise HTTPException(422, f"Ciclo inválido: {corpo.ciclo}")
    fila = await busca.sortear_fila(s, corpo.selecao, corpo.quantidade, usuario.id)
    if not fila:
        raise HTTPException(422, "Nenhum caso disponível nos temas marcados.")
    simulado_id = await db.criar_simulado(s, usuario.id, corpo.ciclo, corpo.selecao, [f.id for f in fila])
    simulado = await s.get(Simulado, simulado_id)
    try:
        return await _abrir_caso(s, usuario.id, fila[0], corpo.ciclo, simulado, 1)
    except HTTPException:
        # Sem o 1º caso o simulado não existe para o estudante: não fica órfão no banco.
        await s.delete(simulado)
        await s.commit()
        raise


@router.post("/simulados/{simulado_id}/proximo", response_model=CasoAberto)
async def proximo_caso(
    simulado_id: str,
    usuario: Usuario = Depends(usuario_atual),
    s: AsyncSession = Depends(db.get_session),
):
    simulado, casos = await _simulado_do_usuario(s, simulado_id, usuario.id)
    if any(c.status == "aberta" for c in casos):
        raise HTTPException(409, "Termine o caso atual antes de passar ao próximo.")
    ordem = max((c.ordem for c in casos), default=0) + 1
    if ordem > len(simulado.fila):
        raise HTTPException(409, "Este simulado já terminou.")
    fonte = await s.get(FonteReferencia, simulado.fila[ordem - 1])
    return await _abrir_caso(s, usuario.id, fonte, simulado.ciclo, simulado, ordem)


@router.get("/simulados/{simulado_id}", response_model=SimuladoLeitura)
async def ler_simulado(
    simulado_id: str,
    usuario: Usuario = Depends(usuario_atual),
    s: AsyncSession = Depends(db.get_session),
):
    """Progresso e resumo. O diagnóstico só aparece nos casos encerrados (RN06)."""
    simulado, casos = await _simulado_do_usuario(s, simulado_id, usuario.id)
    return SimuladoLeitura(
        id=simulado.id,
        ciclo=simulado.ciclo,
        total=len(simulado.fila),
        casos=[
            ItemSimulado(
                caso_id=c.id,
                ordem=c.ordem,
                titulo=c.titulo,
                status=c.status,
                acertou=(c.feedback or {}).get("acertou"),
                diagnostico_correto=(c.feedback or {}).get("diagnostico_correto"),
            )
            for c in casos
        ],
    )


@router.post(
    "/casos/{caso_id}/mensagens",
    # Streaming não tem response_model; sem isto a rota fica sem corpo no OpenAPI e os
    # tipos gerados no frontend não sabem o que ela devolve. O `application/json: None`
    # remove o content-type que o FastAPI assume por padrão e que esta rota não usa.
    responses={
        200: {"content": {"text/plain": {"schema": {"type": "string"}}, "application/json": None}}
    },
)
async def conversar(
    caso_id: str,
    corpo: Mensagem,
    usuario: Usuario = Depends(usuario_atual),
    s: AsyncSession = Depends(db.get_session),
):
    caso, respostas = await _caso_do_usuario(s, caso_id, usuario.id)
    if caso.status != "aberta":
        raise HTTPException(409, "Este caso já foi encerrado.")

    # gravada antes do stream: a pergunta existe mesmo que o cliente desconecte no meio
    await db.adicionar_resposta(s, caso_id, "user", corpo.mensagem)

    # Valores extraídos agora, enquanto a sessão da request está viva: o gerador roda
    # depois que ela fecha e tocar o objeto ORM ali levantaria erro.
    especialidade, gabarito = caso.especialidade, caso.gabarito
    historico = _historico(respostas)

    async def gerar():
        partes = []
        try:
            async for chunk in ai.responder_chat(
                especialidade, gabarito, historico, corpo.mensagem
            ):
                partes.append(chunk)
                yield chunk
        except Exception as e:  # noqa: BLE001 — stream já aberto; erro vira texto no chat
            yield f"\n\n*{_falha_ia(e, 'responder')}*"
        finally:
            # Sem `await` aqui: numa desconexão este bloco roda com a task já cancelada,
            # e qualquer espera seria interrompida na hora. Ver a docstring de
            # _gravar_resposta_em_background.
            if partes:
                _gravar_resposta_em_background(caso_id, "".join(partes))

    return StreamingResponse(gerar(), media_type="text/plain; charset=utf-8")


@router.post("/casos/{caso_id}/diagnostico", response_model=ai.FeedbackLeitura)
async def diagnosticar(
    caso_id: str,
    corpo: RespostaFinal,
    usuario: Usuario = Depends(usuario_atual),
    s: AsyncSession = Depends(db.get_session),
):
    caso, respostas = await _caso_do_usuario(s, caso_id, usuario.id)
    if caso.status != "aberta":
        raise HTTPException(409, "Este caso já foi encerrado.")
    resposta = corpo.model_dump()
    if faltando := [ai.ROTULOS[c] for c in ai.CAMPOS_POR_CICLO[caso.ciclo] if not resposta[c].strip()]:
        raise HTTPException(422, f"Preencha: {', '.join(faltando)}.")
    # As fontes do caso já são conhecidas, com os mesmos números: o feedback cita [n]
    # e o estudante acha a referência certa na lista. Puxar critérios, diferencial e
    # conduta delas é mais preciso que refazer a busca.
    fontes_caso = await db.fontes_do_caso(s, caso_id, etapa="caso")
    blocos = [
        (uso.numero, fonte, await busca.material(s, fonte, "feedback", principal=uso.numero == 1, ciclo=caso.ciclo))
        for uso, fonte in fontes_caso
    ]
    try:
        avaliado = await ai.avaliar_diagnostico(
            caso.especialidade,
            caso.ciclo,
            caso.gabarito,
            _historico(respostas),
            resposta,
            busca.contexto(blocos),
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, _falha_ia(e, "avaliar o diagnóstico"))
    # Ciclo básico: indica onde aprofundar a fisiologia (só a referência; ver rag/fisiologia.json).
    leitura = ""
    if caso.ciclo == "básico":
        principal = fontes_caso[0][1] if fontes_caso else None
        leitura = leitura_fisiologia(principal.cid10 if principal else [], caso.especialidade)
    feedback = ai.FeedbackLeitura(**avaliado.model_dump(), leitura_indicada=leitura)
    await db.adicionar_resposta(s, caso_id, "user", ai.texto_resposta(resposta))
    await db.encerrar_caso(
        s, caso_id, feedback.model_dump(), fontes=[(f.id, n, [t.id for t in ts]) for n, f, ts in blocos if ts]
    )
    return feedback
