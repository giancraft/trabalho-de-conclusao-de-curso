"""Entidades persistidas e schemas de leitura da API.

Os nomes das tabelas seguem a modelagem conceitual do TCC (seção 4.7): `caso_clinico`
é o que o código chamava de "conversa" e `resposta` é o que chamava de "mensagem". As
rotas HTTP continuam em /api/conversas — renomear a API é mexida no frontend sem ganho.

Das 10 entidades da modelagem, só as 4 com dados hoje existem aqui. Flashcard, Métrica
de Desempenho, Recomendação de Estudo, Fonte de Referência e Perfil Acadêmico nascem
junto dos módulos que as usam (set–out); tabela vazia é andaime.

⚠️ Nenhum model de tabela deve virar `response_model` de rota: `CasoClinico` carrega o
gabarito, que o estudante não pode ver antes de fechar o diagnóstico. Para isso existem
os schemas de leitura no fim do arquivo.
"""

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import Column, DateTime, LargeBinary
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from casos.ai import Feedback


# Nos schemas de leitura, não nas tabelas: é daqui que o OpenAPI (e os tipos do
# frontend) tiram a união literal, em vez de um `string` que aceita qualquer coisa.
Status = Literal["aberta", "encerrada"]
Papel = Literal["user", "assistant"]


def agora() -> datetime:
    return datetime.now(timezone.utc)


def _coluna_data() -> Column:
    # timezone=True → TIMESTAMPTZ. Sem isso o Postgres descarta o offset e as datas
    # voltam do banco ingênuas, quebrando qualquer comparação com `agora()`.
    return Column(DateTime(timezone=True), nullable=False)


# --- tabelas ---


class Usuario(SQLModel, table=True):
    __tablename__ = "usuario"

    id: int | None = Field(default=None, primary_key=True)
    nome: str
    email: str = Field(unique=True, index=True)
    # bcrypt.hashpw/checkpw trabalham com bytes: como `str` o login quebra só na hora
    # de conferir a senha.
    senha_hash: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    criado_em: datetime = Field(default_factory=agora, sa_column=_coluna_data())


class Sessao(SQLModel, table=True):
    __tablename__ = "sessao"

    # Guardamos o sha256 do token, nunca o token em si (ver auth/router.py).
    token_hash: str = Field(primary_key=True)
    usuario_id: int = Field(foreign_key="usuario.id", ondelete="CASCADE", index=True)
    expira_em: datetime = Field(sa_column=_coluna_data())


class CasoClinico(SQLModel, table=True):
    __tablename__ = "caso_clinico"

    # uuid4().hex (sem hífen): o id viaja na URL e no estado do frontend. UUID nativo
    # serializaria com hífen e invalidaria os ids já emitidos.
    id: str = Field(primary_key=True)
    usuario_id: int = Field(foreign_key="usuario.id", ondelete="CASCADE", index=True)
    titulo: str
    especialidade: str
    dificuldade: str
    # JSONB: o driver entrega dict direto, sem json.dumps/loads à mão.
    gabarito: dict = Field(sa_column=Column(JSONB, nullable=False))
    status: str = Field(default="aberta")  # aberta | encerrada
    feedback: dict | None = Field(default=None, sa_column=Column(JSONB, nullable=True))
    criada_em: datetime = Field(default_factory=agora, sa_column=_coluna_data())


class Resposta(SQLModel, table=True):
    __tablename__ = "resposta"

    id: int | None = Field(default=None, primary_key=True)
    caso_id: str = Field(foreign_key="caso_clinico.id", ondelete="CASCADE", index=True)
    role: str  # user | assistant
    content: str
    criada_em: datetime = Field(default_factory=agora, sa_column=_coluna_data())


# --- schemas de leitura (o que a API devolve) ---
#
# Pydantic puro, não SQLModel table: são o contrato do OpenAPI, de onde o frontend gera
# os tipos. O que não estiver declarado aqui não chega ao cliente.


class UsuarioPublico(BaseModel):
    nome: str
    email: str


class Ok(BaseModel):
    ok: bool


class Opcoes(BaseModel):
    especialidades: list[str]
    dificuldades: list[str]


class CasoResumo(BaseModel):
    id: str
    titulo: str
    especialidade: str
    status: Status
    criada_em: datetime


class ListaCasos(BaseModel):
    conversas: list[CasoResumo]


class MensagemLeitura(BaseModel):
    role: Papel
    content: str


class CasoLeitura(BaseModel):
    """Caso como o estudante pode vê-lo.

    ⚠️ Sem `gabarito` — é o que garante a RN06. Casos encerrados expõem o diagnóstico
    correto por `feedback.diagnostico_correto`, e só então.
    """

    id: str
    titulo: str
    especialidade: str
    status: Status
    mensagens: list[MensagemLeitura]
    feedback: Feedback | None


class CasoAberto(BaseModel):
    caso_id: str
    titulo: str
    apresentacao: str
