"""Autenticação: registro, login/logout e sessão por cookie httpOnly.

Padrões adotados:
- senha com bcrypt (hash forte, salt automático) — RNF03 do TCC;
- token de sessão opaco (secrets), armazenado HASHEADO (sha256) no banco;
- cookie httpOnly/samesite=lax: o token nunca é legível por JavaScript;
- `secure` ligado em produção: o cookie não trafega fora de HTTPS.
"""

import hashlib
import re
import secrets

import bcrypt
from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core import config, db
from models import Ok, Usuario, UsuarioPublico

router = APIRouter(prefix="/api/auth", tags=["auth"])

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


async def usuario_atual(
    sessao: str | None = Cookie(default=None, alias=_COOKIE),
    s: AsyncSession = Depends(db.get_session),
) -> Usuario:
    """Dependency: resolve o cookie de sessão para o usuário, ou 401."""
    usuario = await db.usuario_da_sessao(s, _hash_token(sessao)) if sessao else None
    if usuario is None:
        raise HTTPException(401, "Não autenticado.")
    return usuario


async def _abrir_sessao(s: AsyncSession, response: Response, usuario_id: int) -> None:
    token = secrets.token_urlsafe(32)
    await db.criar_sessao(s, _hash_token(token), usuario_id, _DIAS_VALIDADE)
    response.set_cookie(
        _COOKIE,
        token,
        httponly=True,
        samesite="lax",
        max_age=_DIAS_VALIDADE * 24 * 3600,
        # Em dev o app roda em http://localhost; `secure` ali impediria o navegador de
        # mandar o cookie de volta e o login nunca fecharia. Em produção é obrigatório.
        secure=config.PRODUCAO,
    )


@router.post("/registro", status_code=201, response_model=UsuarioPublico)
async def registro(
    corpo: Registro, response: Response, s: AsyncSession = Depends(db.get_session)
):
    nome = corpo.nome.strip()
    email = corpo.email.strip().lower()
    if not nome:
        raise HTTPException(422, "Informe seu nome.")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(422, "Email inválido.")
    if len(corpo.senha) < 8:
        raise HTTPException(422, "A senha deve ter pelo menos 8 caracteres.")
    if await db.buscar_usuario_por_email(s, email):
        raise HTTPException(409, "Já existe uma conta com este email.")

    senha_hash = bcrypt.hashpw(corpo.senha.encode(), bcrypt.gensalt())
    usuario_id = await db.criar_usuario(s, nome, email, senha_hash)
    await _abrir_sessao(s, response, usuario_id)  # registro já loga
    return UsuarioPublico(nome=nome, email=email)


@router.post("/login", response_model=UsuarioPublico)
async def login(corpo: Login, response: Response, s: AsyncSession = Depends(db.get_session)):
    usuario = await db.buscar_usuario_por_email(s, corpo.email.strip())
    # Mesma mensagem para email inexistente e senha errada: não vaza quais emails existem.
    if usuario is None or not bcrypt.checkpw(corpo.senha.encode(), usuario.senha_hash):
        raise HTTPException(401, "Email ou senha incorretos.")
    await _abrir_sessao(s, response, usuario.id)
    return usuario


@router.post("/logout", response_model=Ok)
async def logout(
    response: Response,
    sessao: str | None = Cookie(default=None, alias=_COOKIE),
    s: AsyncSession = Depends(db.get_session),
):
    if sessao:
        await db.apagar_sessao(s, _hash_token(sessao))  # revogação real no servidor
    response.delete_cookie(_COOKIE)
    return Ok(ok=True)


@router.get("/eu", response_model=UsuarioPublico)
async def eu(usuario: Usuario = Depends(usuario_atual)):
    return usuario
