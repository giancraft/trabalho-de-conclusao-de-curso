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

from casos.ai import FeedbackLeitura
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
    ciclo: str  # básico | clínico | internato — define o que se cobra (casos/ai.py)
    # JSONB: o driver entrega dict direto, sem json.dumps/loads à mão.
    gabarito: dict = Field(sa_column=Column(JSONB, nullable=False))
    status: str = Field(default="aberta")  # aberta | encerrada
    feedback: dict | None = Field(default=None, sa_column=Column(JSONB, nullable=True))
    criada_em: datetime = Field(default_factory=agora, sa_column=_coluna_data())
    # Posição no simulado (1, 2, ...); casos de antes dos simulados ficam sem.
    simulado_id: str | None = Field(default=None, foreign_key="simulado.id", ondelete="CASCADE", index=True)
    ordem: int | None = None


class Simulado(SQLModel, table=True):
    """Sequência de N casos sorteados dos temas que o estudante marcou.

    A fila de fontes é sorteada na criação; cada caso só é gerado quando o estudante
    chega nele — gerar os N de uma vez estouraria o limite de tokens/min do provedor.
    """

    __tablename__ = "simulado"

    id: str = Field(primary_key=True)
    usuario_id: int = Field(foreign_key="usuario.id", ondelete="CASCADE", index=True)
    ciclo: str
    selecao: list[str] = Field(sa_column=Column(JSONB, nullable=False))  # ids dos nós (rag/temas.py)
    fila: list[int] = Field(sa_column=Column(ARRAY(Integer), nullable=False))  # fonte_referencia.id
    criado_em: datetime = Field(default_factory=agora, sa_column=_coluna_data())


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
    # Complexidade pela regra do catálogo (ICSAP/SIH): dado de catálogo, fora do sorteio.
    dificuldade: str
    # Relevância no sorteio (rag/ingestao.py: internações SIH + temas de residência).
    peso: float = 1.0
    # Lugar na árvore de temas do simulado (rag/temas.py); "" fora da árvore.
    grande_area: str = ""
    tema: str = Field(default="", index=True)


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


class NoTema(BaseModel):
    """Nó da árvore de temas: grande área, especialidade ou tema (rag/temas.py)."""

    id: str
    nome: str
    disponiveis: int  # fontes sorteáveis no nó
    respondidos: int  # casos encerrados do estudante cuja condição está no nó
    filhos: list["NoTema"]


class Opcoes(BaseModel):
    arvore: list[NoTema]
    ciclos: list[str]


class CasoResumo(BaseModel):
    id: str
    titulo: str
    especialidade: str
    status: Status
    criada_em: datetime
    ordem: int | None = None  # posição no simulado
    total: int | None = None  # casos do simulado


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
    ciclo: str
    status: Status
    mensagens: list[MensagemLeitura]
    feedback: FeedbackLeitura | None
    fontes: list[FonteLeitura]
    simulado_id: str | None = None
    ordem: int | None = None
    total: int | None = None


class CasoAberto(BaseModel):
    caso_id: str
    titulo: str
    ciclo: str
    apresentacao: str
    simulado_id: str
    ordem: int
    total: int


class ItemSimulado(BaseModel):
    caso_id: str
    ordem: int
    titulo: str
    status: Status
    acertou: bool | None  # só com o caso encerrado
    diagnostico_correto: str | None


class SimuladoLeitura(BaseModel):
    id: str
    ciclo: str
    total: int
    casos: list[ItemSimulado]


# --- painel de desempenho (casos/metricas.py) ---


class Kpis(BaseModel):
    casos_concluidos: int
    casos_abertos: int
    taxa_acerto: float | None  # 0–1; None sem caso encerrado
    taxa_acerto_recente: float | None  # últimas 4 semanas
    taxa_acerto_anterior: float | None  # antes disso
    minutos_por_caso: float | None  # mediana do tempo ativo
    perguntas_por_caso: float | None
    lacunas_por_caso: float | None


class PontoEvolucao(BaseModel):
    ordem: int
    data: datetime
    acertou: bool
    acerto_movel: float  # acerto dos últimos casos até este


class Semana(BaseModel):
    semana: date  # segunda-feira
    casos: int
    acertos: int


class Grupo(BaseModel):
    """Recorte do desempenho: uma especialidade, um tema, um ciclo..."""

    id: str | None  # nó da árvore de temas, para treinar de novo
    nome: str
    detalhe: str | None  # grande área da especialidade; especialidade do tema
    casos: int
    acertos: int
    ultimo: datetime | None


class LacunaPorEtapa(BaseModel):
    etapa: str
    total: int
    por_caso: float


class Recomendacao(BaseModel):
    tipo: Literal["fragil", "nao_praticado", "etapa"]
    no: str | None  # nó para o "Treinar agora"; None na etapa da investigação
    titulo: str
    motivo: str


class Desempenho(BaseModel):
    kpis: Kpis
    evolucao: list[PontoEvolucao]
    por_semana: list[Semana]
    por_especialidade: list[Grupo]
    por_tema: list[Grupo]
    por_ciclo: list[Grupo]
    por_apresentacao: list[Grupo]
    lacunas: list[LacunaPorEtapa]
    recomendacoes: list[Recomendacao]
