"""API do simulador de casos clínicos (FastAPI).

Conversas persistem em SQLite e pertencem a um usuário autenticado (cookie httpOnly).
O gabarito de cada caso fica apenas no servidor até o estudante fechar o diagnóstico —
o frontend nunca o recebe antes disso.
"""

import sqlite3

from dotenv import load_dotenv

load_dotenv()  # antes de importar ai (que lê GROQ_MODEL no import)

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import ai
import auth
import db

app = FastAPI(title="Simulador de Casos Clínicos")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # dev server do Vite
    allow_credentials=True,  # cookie de sessão
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
db.init_db()


class NovoCaso(BaseModel):
    especialidade: str
    dificuldade: str


class Mensagem(BaseModel):
    mensagem: str


class Diagnostico(BaseModel):
    diagnostico: str


def _conversa_do_usuario(conversa_id: str, usuario_id: int) -> dict:
    conversa = db.carregar_conversa(conversa_id, usuario_id)
    if conversa is None:
        raise HTTPException(404, "Conversa não encontrada.")
    return conversa


@app.get("/api/especialidades")
def especialidades():
    return {"especialidades": ai.ESPECIALIDADES, "dificuldades": ai.DIFICULDADES}


@app.get("/api/conversas")
def listar(usuario: sqlite3.Row = Depends(auth.usuario_atual)):
    return {"conversas": db.listar_conversas(usuario["id"])}


@app.get("/api/conversas/{conversa_id}")
def abrir(conversa_id: str, usuario: sqlite3.Row = Depends(auth.usuario_atual)):
    conversa = _conversa_do_usuario(conversa_id, usuario["id"])
    return {  # gabarito omitido: encerradas já o expõem via feedback.diagnostico_correto
        "id": conversa["id"],
        "titulo": conversa["titulo"],
        "especialidade": conversa["especialidade"],
        "status": conversa["status"],
        "mensagens": conversa["mensagens"],
        "feedback": conversa["feedback"],
    }


@app.delete("/api/conversas/{conversa_id}", status_code=204)
def apagar(conversa_id: str, usuario: sqlite3.Row = Depends(auth.usuario_atual)):
    if not db.apagar_conversa(conversa_id, usuario["id"]):
        raise HTTPException(404, "Conversa não encontrada.")


@app.post("/api/casos")
def criar_caso(corpo: NovoCaso, usuario: sqlite3.Row = Depends(auth.usuario_atual)):
    if corpo.especialidade not in ai.ESPECIALIDADES:
        raise HTTPException(422, f"Especialidade inválida: {corpo.especialidade}")
    if corpo.dificuldade not in ai.DIFICULDADES:
        raise HTTPException(422, f"Dificuldade inválida: {corpo.dificuldade}")
    try:
        caso = ai.novo_caso(corpo.especialidade, corpo.dificuldade)
    except Exception as e:  # noqa: BLE001 — erro amigável, sem stack trace no cliente
        raise HTTPException(502, f"Falha ao gerar o caso: {e}")

    conversa_id = db.criar_conversa(
        usuario["id"], caso["titulo"], corpo.especialidade, corpo.dificuldade, caso["gabarito"]
    )
    db.adicionar_mensagem(conversa_id, "assistant", caso["apresentacao"])
    return {"caso_id": conversa_id, "titulo": caso["titulo"], "apresentacao": caso["apresentacao"]}


@app.post("/api/casos/{conversa_id}/mensagens")
def conversar(
    conversa_id: str, corpo: Mensagem, usuario: sqlite3.Row = Depends(auth.usuario_atual)
):
    conversa = _conversa_do_usuario(conversa_id, usuario["id"])
    if conversa["status"] != "aberta":
        raise HTTPException(409, "Este caso já foi encerrado.")

    # gravada antes do stream: a pergunta existe mesmo que o cliente desconecte no meio
    db.adicionar_mensagem(conversa_id, "user", corpo.mensagem)

    def gerar():
        partes = []
        try:
            for chunk in ai.responder_chat(
                conversa["especialidade"],
                conversa["gabarito"],
                conversa["mensagens"],
                corpo.mensagem,
            ):
                partes.append(chunk)
                yield chunk
        except Exception as e:  # noqa: BLE001 — stream já aberto; erro vira texto no chat
            yield f"\n\n*Erro ao consultar a IA: {e}*"
        finally:
            # ponytail: em desconexão do cliente o Starlette pode não fechar o gerador
            # síncrono (finally não roda) — nesse caso perde-se só a resposta parcial.
            db.adicionar_mensagem(conversa_id, "assistant", "".join(partes))

    return StreamingResponse(gerar(), media_type="text/plain; charset=utf-8")


@app.post("/api/casos/{conversa_id}/diagnostico")
def diagnosticar(
    conversa_id: str, corpo: Diagnostico, usuario: sqlite3.Row = Depends(auth.usuario_atual)
):
    conversa = _conversa_do_usuario(conversa_id, usuario["id"])
    if conversa["status"] != "aberta":
        raise HTTPException(409, "Este caso já foi encerrado.")
    try:
        feedback = ai.avaliar_diagnostico(
            conversa["especialidade"],
            conversa["gabarito"],
            conversa["mensagens"],
            corpo.diagnostico,
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Falha ao avaliar o diagnóstico: {e}")
    db.adicionar_mensagem(conversa_id, "user", f"Diagnóstico final: {corpo.diagnostico}")
    db.encerrar_conversa(conversa_id, feedback)
    return feedback
