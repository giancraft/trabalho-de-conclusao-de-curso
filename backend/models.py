"""Entidades persistidas e schemas de leitura da API.

Os nomes das tabelas seguem a modelagem conceitual do TCC (seção 4.7): `caso_clinico`
é o que o código chamava de "conversa" e `resposta` é o que chamava de "mensagem". As
rotas HTTP continuam em /api/conversas — renomear a API é mexida no frontend sem ganho.

Das 10 entidades da modelagem, existem aqui as que já têm dados: as 4 da fundação e a
Fonte de Referência do RAG (RF04/RF14), com seus trechos. Flashcard, Métrica de
Desempenho, Recomendação de Estudo e Perfil Acadêmico nascem junto dos módulos que as
usam (outubro); tabela vazia é andaime.

⚠️ Nenhum model de tabela deve virar `response_model` de rota: `CasoClinico` carrega o
gabarito, que o estudante não pode ver antes de fechar o diagnóstico. Para isso existem
os schemas de leitura no fim do arquivo.
"""

from datetime import date, datetime, timezone
from typing import Literal

from pgvector.sqlalchemy import Vector
from pydantic import BaseModel
from sqlalchemy import Column, DateTime, Integer, LargeBinary, String
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlmodel import Field, SQLModel

from casos.ai import Feedback
from rag.embeddings import DIMENSAO


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


class FonteReferencia(SQLModel, table=True):
    """Documento do corpus: PCDT do MS ou artigo do Europe PMC/PMC (RF14).

    `sorteavel` separa os papéis: PCDT e relato de caso são condições que o sorteio pode
    escolher (RN01); diretriz de sociedade e revisão só entram como apoio no contexto.
    `especialidade` e `dificuldade` vêm de `rag/corpus.json` / `rag/literatura.json`.
    """

    __tablename__ = "fonte_referencia"

    id: int | None = Field(default=None, primary_key=True)
    chave: str = Field(unique=True)  # slug do PCDT ou PMCID — a chave da ingestão idempotente
    titulo: str
    orgao: str  # Ministério da Saúde, ou a revista do artigo
    tipo: str  # PCDT | Diretriz | Relato de caso | Revisão
    identificador: str  # a portaria do PCDT, ou "PMID …; PMCID …"
    publicado_em: date | None  # data da portaria: a atualidade da fonte fica visível
    url: str
    licenca: str
    cid10: list[str] = Field(sa_column=Column(ARRAY(String), nullable=False))
    # Artigo: autores, revista, volume, número, páginas, ano, DOI, PMID, PMCID — o que a
    # referência ABNT precisa (rag/citacao.py). None no PCDT.
    bibliografia: dict | None = Field(default=None, sa_column=Column(JSONB, nullable=True))
    sorteavel: bool = True
    recuperada_em: datetime = Field(default_factory=agora, sa_column=_coluna_data())
    especialidade: str
    dificuldade: str


class Trecho(SQLModel, table=True):
    __tablename__ = "trecho"

    id: int | None = Field(default=None, primary_key=True)
    fonte_id: int = Field(foreign_key="fonte_referencia.id", ondelete="CASCADE", index=True)
    ordem: int
    # Seção do documento ("Diagnóstico", "Case report"...): a geração e o feedback puxam
    # seções diferentes da mesma fonte. `secao_id` é o id da <sec> no XML do PMC, que
    # vira âncora no link da citação; None no PCDT.
    secao: str
    secao_id: str | None = None
    texto: str
    embedding: list[float] = Field(sa_column=Column(Vector(DIMENSAO), nullable=False))


class CasoFonte(SQLModel, table=True):
    """O que sustentou cada etapa de um caso (RF14, RNF08).

    Uma linha por fonte e etapa ("caso" = geração, "feedback" = avaliação), com o número
    da referência ([1], [2]...) e os ids exatos dos trechos que foram ao prompt. Gravada
    na hora, exposta só com o caso encerrado (RN06).
    """

    __tablename__ = "caso_fonte"

    caso_id: str = Field(foreign_key="caso_clinico.id", ondelete="CASCADE", primary_key=True)
    fonte_id: int = Field(foreign_key="fonte_referencia.id", primary_key=True)
    etapa: str = Field(primary_key=True)  # caso | feedback
    numero: int
    trechos: list[int] = Field(sa_column=Column(ARRAY(Integer), nullable=False))


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


class SecaoConsultada(BaseModel):
    titulo: str
    url: str  # com âncora para a seção, quando o documento tem (PMC)


class FonteLeitura(BaseModel):
    """Referência numerada do caso (RF14): a citação ABNT, não o trecho.

    `numero` é o mesmo [n] citado no texto do feedback; `secoes` diz de onde, dentro do
    documento, veio o que foi usado.
    """

    numero: int
    tipo: str  # PCDT | Diretriz | Relato de caso | Revisão
    citacao: str  # NBR 6023:2018, montada em rag/citacao.py
    destaque: str  # o trecho da citação que a NBR 6023 manda destacar (negrito)
    url: str
    licenca: str
    secoes: list[SecaoConsultada]


class CasoLeitura(BaseModel):
    """Caso como o estudante pode vê-lo.

    ⚠️ Sem `gabarito` — é o que garante a RN06. Casos encerrados expõem o diagnóstico
    correto por `feedback.diagnostico_correto`, e só então. O mesmo vale para `fontes`:
    o título do capítulo É o diagnóstico, então num caso aberto a lista vem vazia.
    """

    id: str
    titulo: str
    especialidade: str
    status: Status
    mensagens: list[MensagemLeitura]
    feedback: Feedback | None
    fontes: list[FonteLeitura]


class CasoAberto(BaseModel):
    caso_id: str
    titulo: str
    apresentacao: str
