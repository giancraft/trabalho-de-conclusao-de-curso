"""Autenticação: registro, login/logout e sessão por cookie httpOnly.

Padrões adotados:
- senha com bcrypt (hash forte, salt automático) — RNF03 do TCC;
- token de sessão opaco (secrets), armazenado HASHEADO (sha256) no banco;
- cookie httpOnly/samesite=lax: o token nunca é legível por JavaScript.
"""

import hashlib
import re
import secrets
import sqlite3

import bcrypt
from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel

import db

router = APIRouter(prefix="/api/auth")

_COOKIE = "sessao"
_DIAS_VALIDADE = 7


class Registro(BaseModel):
    nome: str
    email: str
    senha: str


class Login(BaseModel):
    email: str
    senha: str


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def usuario_atual(sessao: str | None = Cookie(default=None, alias=_COOKIE)) -> sqlite3.Row:
    """Dependency: resolve o cookie de sessão para o usuário, ou 401."""
    usuario = db.usuario_da_sessao(_hash_token(sessao)) if sessao else None
    if usuario is None:
        raise HTTPException(401, "Não autenticado.")
    return usuario


def _abrir_sessao(response: Response, usuario_id: int) -> None:
    token = secrets.token_urlsafe(32)
    db.criar_sessao(_hash_token(token), usuario_id, _DIAS_VALIDADE)
    response.set_cookie(
        _COOKIE,
        token,
        httponly=True,
        samesite="lax",
        max_age=_DIAS_VALIDADE * 24 * 3600,
        # ponytail: secure=False para dev local em http; produção exige secure=True
    )


@router.post("/registro", status_code=201)
def registro(corpo: Registro, response: Response):
    nome = corpo.nome.strip()
    email = corpo.email.strip().lower()
    if not nome:
        raise HTTPException(422, "Informe seu nome.")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(422, "Email inválido.")
    if len(corpo.senha) < 8:
        raise HTTPException(422, "A senha deve ter pelo menos 8 caracteres.")
    if db.buscar_usuario_por_email(email):
        raise HTTPException(409, "Já existe uma conta com este email.")

    senha_hash = bcrypt.hashpw(corpo.senha.encode(), bcrypt.gensalt())
    usuario_id = db.criar_usuario(nome, email, senha_hash)
    _abrir_sessao(response, usuario_id)  # registro já loga
    return {"nome": nome, "email": email}


@router.post("/login")
def login(corpo: Login, response: Response):
    usuario = db.buscar_usuario_por_email(corpo.email.strip())
    # Mesma mensagem para email inexistente e senha errada: não vaza quais emails existem.
    if usuario is None or not bcrypt.checkpw(corpo.senha.encode(), usuario["senha_hash"]):
        raise HTTPException(401, "Email ou senha incorretos.")
    _abrir_sessao(response, usuario["id"])
    return {"nome": usuario["nome"], "email": usuario["email"]}


@router.post("/logout")
def logout(response: Response, sessao: str | None = Cookie(default=None, alias=_COOKIE)):
    if sessao:
        db.apagar_sessao(_hash_token(sessao))  # revogação real no servidor
    response.delete_cookie(_COOKIE)
    return {"ok": True}


@router.get("/eu")
def eu(usuario: sqlite3.Row = Depends(usuario_atual)):
    return {"nome": usuario["nome"], "email": usuario["email"]}
