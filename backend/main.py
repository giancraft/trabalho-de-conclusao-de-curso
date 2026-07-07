"""API do simulador de casos clínicos (FastAPI).

O gabarito de cada caso fica apenas no servidor (sessão em memória) até o estudante
fechar o diagnóstico — o frontend nunca o recebe antes disso.

ponytail: sessões em dict na memória do processo; no TCC isso vira banco (persistência,
histórico longitudinal e múltiplas instâncias).
"""

import uuid

from dotenv import load_dotenv

load_dotenv()  # antes de importar ai (que lê GROQ_MODEL no import)

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import ai

app = FastAPI(title="Simulador de Casos Clínicos")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # dev server do Vite
    allow_methods=["*"],
    allow_headers=["*"],
)

_sessoes: dict[str, dict] = {}


class NovoCaso(BaseModel):
    especialidade: str
    dificuldade: str


class Mensagem(BaseModel):
    mensagem: str


class Diagnostico(BaseModel):
    diagnostico: str


def _sessao(caso_id: str) -> dict:
    if caso_id not in _sessoes:
        raise HTTPException(404, "Caso não encontrado. Inicie um novo caso.")
    return _sessoes[caso_id]


@app.get("/api/especialidades")
def especialidades():
    return {"especialidades": ai.ESPECIALIDADES, "dificuldades": ai.DIFICULDADES}


@app.post("/api/casos")
def criar_caso(corpo: NovoCaso):
    if corpo.especialidade not in ai.ESPECIALIDADES:
        raise HTTPException(422, f"Especialidade inválida: {corpo.especialidade}")
    if corpo.dificuldade not in ai.DIFICULDADES:
        raise HTTPException(422, f"Dificuldade inválida: {corpo.dificuldade}")
    try:
        caso = ai.novo_caso(corpo.especialidade, corpo.dificuldade)
    except Exception as e:  # noqa: BLE001 — erro amigável, sem stack trace no cliente
        raise HTTPException(502, f"Falha ao gerar o caso: {e}")

    caso_id = uuid.uuid4().hex
    _sessoes[caso_id] = {
        "especialidade": corpo.especialidade,
        "gabarito": caso["gabarito"],  # nunca enviado ao cliente antes do diagnóstico
        "historico": [{"role": "assistant", "content": caso["apresentacao"]}],
    }
    return {"caso_id": caso_id, "apresentacao": caso["apresentacao"]}


@app.post("/api/casos/{caso_id}/mensagens")
def conversar(caso_id: str, corpo: Mensagem):
    sessao = _sessao(caso_id)

    def gerar():
        partes = []
        try:
            for chunk in ai.responder_chat(
                sessao["especialidade"], sessao["gabarito"], sessao["historico"], corpo.mensagem
            ):
                partes.append(chunk)
                yield chunk
        except Exception as e:  # noqa: BLE001 — stream já aberto; erro vira texto no chat
            yield f"\n\n*Erro ao consultar a IA: {e}*"
        # histórico só é gravado após a resposta completa
        sessao["historico"] += [
            {"role": "user", "content": corpo.mensagem},
            {"role": "assistant", "content": "".join(partes)},
        ]

    return StreamingResponse(gerar(), media_type="text/plain; charset=utf-8")


@app.post("/api/casos/{caso_id}/diagnostico")
def diagnosticar(caso_id: str, corpo: Diagnostico):
    sessao = _sessao(caso_id)
    try:
        feedback = ai.avaliar_diagnostico(
            sessao["especialidade"], sessao["gabarito"], sessao["historico"], corpo.diagnostico
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Falha ao avaliar o diagnóstico: {e}")
    del _sessoes[caso_id]  # caso encerrado
    return feedback
