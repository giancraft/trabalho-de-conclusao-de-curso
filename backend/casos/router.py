"""Rotas de casos clínicos e do histórico de conversas (RF03–RF07, RF13, RF14).

As rotas mantêm o prefixo /api/conversas do protótipo; no banco a entidade se chama
`caso_clinico`, conforme a modelagem do TCC (ver models.py).
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from auth.router import usuario_atual
from casos import ai
from core import db
from models import (
    CasoAberto,
    CasoClinico,
    CasoLeitura,
    CasoResumo,
    FonteLeitura,
    ListaCasos,
    Opcoes,
    Resposta,
    SecaoConsultada,
    Trecho,
    Usuario,
)
from rag import busca
from rag.citacao import citacao_abnt, url_secao

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


class NovoCaso(BaseModel):
    especialidade: str
    dificuldade: str


class Mensagem(BaseModel):
    mensagem: str


class Diagnostico(BaseModel):
    diagnostico: str


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


@router.get("/especialidades", response_model=Opcoes)
async def especialidades():
    return Opcoes(especialidades=ai.ESPECIALIDADES, dificuldades=ai.DIFICULDADES)


@router.get("/conversas", response_model=ListaCasos)
async def listar(
    usuario: Usuario = Depends(usuario_atual), s: AsyncSession = Depends(db.get_session)
):
    casos = await db.listar_casos(s, usuario.id)
    return ListaCasos(conversas=[CasoResumo.model_validate(c, from_attributes=True) for c in casos])


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
    return CasoLeitura(
        id=caso.id,
        titulo=caso.titulo,
        especialidade=caso.especialidade,
        status=caso.status,
        mensagens=_historico(respostas),
        feedback=caso.feedback,
        fontes=fontes,
    )


@router.delete("/conversas/{caso_id}", status_code=204)
async def apagar(
    caso_id: str,
    usuario: Usuario = Depends(usuario_atual),
    s: AsyncSession = Depends(db.get_session),
):
    if not await db.apagar_caso(s, caso_id, usuario.id):
        raise HTTPException(404, "Conversa não encontrada.")


@router.post("/casos", response_model=CasoAberto)
async def criar_caso(
    corpo: NovoCaso,
    usuario: Usuario = Depends(usuario_atual),
    s: AsyncSession = Depends(db.get_session),
):
    if corpo.especialidade not in ai.ESPECIALIDADES:
        raise HTTPException(422, f"Especialidade inválida: {corpo.especialidade}")
    if corpo.dificuldade not in ai.DIFICULDADES:
        raise HTTPException(422, f"Dificuldade inválida: {corpo.dificuldade}")
    # A condição sai do corpus antes de o LLM escrever qualquer coisa (RN01): PCDT ou
    # relato de caso, sem repetir para este estudante. Junto vêm as fontes de apoio —
    # o PCDT ou a diretriz brasileira mais próximos —, numeradas [1], [2]... (RF04).
    # Corpus vazio → nenhuma fonte → caso sem ancoragem: o sistema degrada, não quebra.
    blocos = []
    fonte = await busca.sortear_fonte(s, corpo.especialidade, corpo.dificuldade, usuario.id)
    if fonte:
        blocos.append((fonte, await busca.material(s, fonte, "caso")))
        for apoio in await busca.fontes_de_apoio(s, fonte):
            if trechos := await busca.material(s, apoio, "caso", principal=False):
                blocos.append((apoio, trechos))
    numerados = [(n, f, ts) for n, (f, ts) in enumerate(blocos, 1)]
    try:
        caso = await ai.novo_caso(
            corpo.especialidade,
            corpo.dificuldade,
            fonte.titulo if fonte else "",
            busca.contexto(numerados),
        )
    except Exception as e:  # noqa: BLE001 — erro amigável, sem stack trace no cliente
        raise HTTPException(502, _falha_ia(e, "gerar o caso"))

    caso_id = await db.criar_caso(
        s,
        usuario.id,
        caso.titulo,
        corpo.especialidade,
        corpo.dificuldade,
        caso.gabarito.model_dump(),
        fontes=[(f.id, n, [t.id for t in ts]) for n, f, ts in numerados],
    )
    await db.adicionar_resposta(s, caso_id, "assistant", caso.apresentacao)
    return CasoAberto(caso_id=caso_id, titulo=caso.titulo, apresentacao=caso.apresentacao)


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


@router.post("/casos/{caso_id}/diagnostico", response_model=ai.Feedback)
async def diagnosticar(
    caso_id: str,
    corpo: Diagnostico,
    usuario: Usuario = Depends(usuario_atual),
    s: AsyncSession = Depends(db.get_session),
):
    caso, respostas = await _caso_do_usuario(s, caso_id, usuario.id)
    if caso.status != "aberta":
        raise HTTPException(409, "Este caso já foi encerrado.")
    # As fontes do caso já são conhecidas, com os mesmos números: o feedback cita [n]
    # e o estudante acha a referência certa na lista. Puxar critérios, diferencial e
    # conduta delas é mais preciso que refazer a busca.
    blocos = [
        (uso.numero, fonte, await busca.material(s, fonte, "feedback", principal=uso.numero == 1))
        for uso, fonte in await db.fontes_do_caso(s, caso_id, etapa="caso")
    ]
    try:
        feedback = await ai.avaliar_diagnostico(
            caso.especialidade,
            caso.gabarito,
            _historico(respostas),
            corpo.diagnostico,
            busca.contexto(blocos),
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, _falha_ia(e, "avaliar o diagnóstico"))
    await db.adicionar_resposta(s, caso_id, "user", f"Diagnóstico final: {corpo.diagnostico}")
    await db.encerrar_caso(
        s, caso_id, feedback.model_dump(), fontes=[(f.id, n, [t.id for t in ts]) for n, f, ts in blocos if ts]
    )
    return feedback
