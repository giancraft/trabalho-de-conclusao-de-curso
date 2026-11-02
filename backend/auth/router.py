"""Autenticação: registro, login/logout e sessão por cookie httpOnly.

Padrões adotados:
- senha com bcrypt (hash forte, salt automático) — RNF03 do TCC;
- token de sessão opaco (secrets), armazenado HASHEADO (sha256) no banco;
- cookie httpOnly/samesite=lax: o token nunca é legível por JavaScript;
- `secure` ligado em produção: o cookie não trafega fora de HTTPS.

A conta do próprio usuário também mora aqui: editar nome e email, aceitar o termo,
baixar os dados e excluir a conta (LGPD, RNF04).
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
    aceite: bool = False  # termo de uso e tratamento de dados


class EdicaoConta(BaseModel):
    nome: str
    email: str


class Confirmacao(BaseModel):
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


async def admin_atual(usuario: Usuario = Depends(usuario_atual)) -> Usuario:
    """Dependency das rotas de administração: 403 para quem não é admin. A interface
    esconde os itens, mas quem protege é isto."""
    if usuario.papel != "admin":
        raise HTTPException(403, "Acesso restrito ao administrador.")
    return usuario


def _publico(u: Usuario) -> UsuarioPublico:
    return UsuarioPublico(nome=u.nome, email=u.email, papel=u.papel, consentiu=u.consentiu_em is not None)


def _validar(nome: str, email: str) -> tuple[str, str]:
    nome, email = nome.strip(), email.strip().lower()
    if not nome:
        raise HTTPException(422, "Informe seu nome.")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(422, "Email inválido.")
    return nome, email


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
    nome, email = _validar(corpo.nome, corpo.email)
    if not corpo.aceite:
        raise HTTPException(422, "É preciso aceitar o termo de uso para criar a conta.")
    if len(corpo.senha) < 8:
        raise HTTPException(422, "A senha deve ter pelo menos 8 caracteres.")
    if await db.buscar_usuario_por_email(s, email):
        raise HTTPException(409, "Já existe uma conta com este email.")

    senha_hash = bcrypt.hashpw(corpo.senha.encode(), bcrypt.gensalt())
    usuario_id = await db.criar_usuario(s, nome, email, senha_hash, consentiu=True)
    await _abrir_sessao(s, response, usuario_id)  # registro já loga
    return UsuarioPublico(nome=nome, email=email)


@router.post("/login", response_model=UsuarioPublico)
async def login(corpo: Login, response: Response, s: AsyncSession = Depends(db.get_session)):
    usuario = await db.buscar_usuario_por_email(s, corpo.email.strip())
    # Mesma mensagem para email inexistente e senha errada: não vaza quais emails existem.
    if usuario is None or not bcrypt.checkpw(corpo.senha.encode(), usuario.senha_hash):
        raise HTTPException(401, "Email ou senha incorretos.")
    await _abrir_sessao(s, response, usuario.id)
    return _publico(usuario)


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
    return _publico(usuario)


@router.patch("/eu", response_model=UsuarioPublico)
async def editar_conta(
    corpo: EdicaoConta, usuario: Usuario = Depends(usuario_atual), s: AsyncSession = Depends(db.get_session)
):
    nome, email = _validar(corpo.nome, corpo.email)
    dono = await db.buscar_usuario_por_email(s, email)
    if dono and dono.id != usuario.id:
        raise HTTPException(409, "Já existe uma conta com este email.")
    await db.atualizar_usuario(s, usuario.id, nome, email)
    return _publico(await s.get(Usuario, usuario.id))


@router.post("/consentimento", response_model=UsuarioPublico)
async def consentir(usuario: Usuario = Depends(usuario_atual), s: AsyncSession = Depends(db.get_session)):
    """Contas criadas antes do termo aceitam no próximo acesso."""
    await db.registrar_consentimento(s, usuario.id)
    return _publico(await s.get(Usuario, usuario.id))


@router.get("/meus-dados")
async def meus_dados(usuario: Usuario = Depends(usuario_atual), s: AsyncSession = Depends(db.get_session)):
    """Tudo o que o sistema guarda do usuário, em JSON (LGPD, art. 18, II)."""
    return await db.dados_do_usuario(s, usuario.id)


@router.delete("/conta", status_code=204)
async def excluir_conta(
    corpo: Confirmacao,
    response: Response,
    usuario: Usuario = Depends(usuario_atual),
    s: AsyncSession = Depends(db.get_session),
):
    """Exclui a conta e tudo o que é dela (LGPD, art. 18, VI). Pede a senha de novo: um
    cookie esquecido num computador compartilhado não basta para apagar tudo."""
    if not bcrypt.checkpw(corpo.senha.encode(), usuario.senha_hash):
        raise HTTPException(401, "Senha incorreta.")
    await db.apagar_usuario(s, usuario.id)
    response.delete_cookie(_COOKIE)
