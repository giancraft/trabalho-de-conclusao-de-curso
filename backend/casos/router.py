"""Rotas de casos clínicos e do histórico de conversas (RF03, RF05–RF07, RF13).

As rotas mantêm o prefixo /api/conversas do protótipo; no banco a entidade se chama
`caso_clinico`, conforme a modelagem do TCC (ver models.py).
"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from auth.router import usuario_atual
from casos import ai
from core import db
from models import (
    CasoAberto,
    CasoClinico,
    CasoLeitura,
    CasoResumo,
    ListaCasos,
    Opcoes,
    Resposta,
    Usuario,
)

router = APIRouter(prefix="/api", tags=["casos"])


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
    return CasoLeitura(
        id=caso.id,
        titulo=caso.titulo,
        especialidade=caso.especialidade,
        status=caso.status,
        mensagens=_historico(respostas),
        feedback=caso.feedback,
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
    try:
        caso = await ai.novo_caso(corpo.especialidade, corpo.dificuldade)
    except Exception as e:  # noqa: BLE001 — erro amigável, sem stack trace no cliente
        raise HTTPException(502, f"Falha ao gerar o caso: {e}")

    caso_id = await db.criar_caso(
        s,
        usuario.id,
        caso.titulo,
        corpo.especialidade,
        corpo.dificuldade,
        caso.gabarito.model_dump(),
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
            yield f"\n\n*Erro ao consultar a IA: {e}*"
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
    try:
        feedback = await ai.avaliar_diagnostico(
            caso.especialidade, caso.gabarito, _historico(respostas), corpo.diagnostico
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Falha ao avaliar o diagnóstico: {e}")
    await db.adicionar_resposta(s, caso_id, "user", f"Diagnóstico final: {corpo.diagnostico}")
    await db.encerrar_caso(s, caso_id, feedback.model_dump())
    return feedback
