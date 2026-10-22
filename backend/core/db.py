"""Persistência em PostgreSQL (SQLModel + asyncpg).

Substitui a conexão SQLite única sob lock global do protótipo: ali todo request era
serializado, o que não sobrevive a concorrência real nem ao RAG de setembro.

Cada função recebe a `AsyncSession` de quem chama — as rotas injetam a da request por
`Depends(get_session)`. O schema é criado pelo Alembic, não aqui.
"""

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, delete, select

from core import config
from models import CasoClinico, CasoFonte, FonteReferencia, Resposta, Sessao, Usuario, agora

engine = create_async_engine(config.DATABASE_URL, pool_pre_ping=True)

abrir_sessao = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session():
    """Dependency do FastAPI: uma sessão por request, fechada no fim."""
    async with abrir_sessao() as sessao:
        yield sessao


# --- usuários e sessões de autenticação ---


async def criar_usuario(s: AsyncSession, nome: str, email: str, senha_hash: bytes) -> int:
    usuario = Usuario(nome=nome, email=email.lower(), senha_hash=senha_hash)
    s.add(usuario)
    await s.commit()
    return usuario.id


async def buscar_usuario_por_email(s: AsyncSession, email: str) -> Usuario | None:
    return (
        await s.execute(select(Usuario).where(Usuario.email == email.lower()))
    ).scalar_one_or_none()


async def criar_sessao(
    s: AsyncSession, token_hash: str, usuario_id: int, dias_validade: int = 7
) -> None:
    s.add(
        Sessao(
            token_hash=token_hash,
            usuario_id=usuario_id,
            expira_em=agora() + timedelta(days=dias_validade),
        )
    )
    await s.commit()


async def usuario_da_sessao(s: AsyncSession, token_hash: str) -> Usuario | None:
    """Usuário da sessão válida, ou None. Sessões expiradas são apagadas."""
    linha = (
        await s.execute(
            select(Usuario, Sessao.expira_em)
            .join(Sessao, Sessao.usuario_id == Usuario.id)
            .where(Sessao.token_hash == token_hash)
        )
    ).first()
    if linha is None:
        return None
    usuario, expira_em = linha
    # A expiração é comparada aqui e não no WHERE de propósito: é o que permite apagar
    # a sessão vencida em vez de só ignorá-la.
    if expira_em < agora():
        await apagar_sessao(s, token_hash)
        return None
    return usuario


async def apagar_sessao(s: AsyncSession, token_hash: str) -> None:
    await s.execute(delete(Sessao).where(Sessao.token_hash == token_hash))
    await s.commit()


# --- casos clínicos e respostas ---


# Uso de uma fonte numa etapa: (fonte_id, número da referência [n], ids dos trechos).
UsoFonte = tuple[int, int, list[int]]


def _usos(caso_id: str, etapa: str, fontes: list[UsoFonte]) -> list[CasoFonte]:
    return [CasoFonte(caso_id=caso_id, fonte_id=f, etapa=etapa, numero=n, trechos=t) for f, n, t in fontes]


async def criar_caso(
    s: AsyncSession,
    usuario_id: int,
    titulo: str,
    especialidade: str,
    dificuldade: str,
    gabarito: dict,
    fontes: list[UsoFonte] = (),
) -> str:
    """Cria o caso e registra as fontes da geração na mesma transação (RF14)."""
    caso = CasoClinico(
        id=uuid.uuid4().hex,
        usuario_id=usuario_id,
        titulo=titulo,
        especialidade=especialidade,
        dificuldade=dificuldade,
        gabarito=gabarito,
    )
    s.add(caso)
    await s.flush()  # o caso precisa existir antes dos vínculos (FK)
    s.add_all(_usos(caso.id, "caso", fontes))
    await s.commit()
    return caso.id


async def fontes_do_caso(
    s: AsyncSession, caso_id: str, etapa: str | None = None
) -> list[tuple[CasoFonte, FonteReferencia]]:
    """Fontes usadas pelo caso (numa etapa, ou em todas), na ordem das referências."""
    consulta = (
        select(CasoFonte, FonteReferencia)
        .join(FonteReferencia, FonteReferencia.id == CasoFonte.fonte_id)
        .where(CasoFonte.caso_id == caso_id)
        .order_by(CasoFonte.numero, CasoFonte.etapa)
    )
    if etapa:
        consulta = consulta.where(CasoFonte.etapa == etapa)
    return list(await s.execute(consulta))


async def listar_casos(s: AsyncSession, usuario_id: int) -> list[CasoClinico]:
    return list(
        (
            await s.execute(
                select(CasoClinico)
                .where(CasoClinico.usuario_id == usuario_id)
                .order_by(CasoClinico.criada_em.desc())
            )
        ).scalars()
    )


async def carregar_caso(
    s: AsyncSession, caso_id: str, usuario_id: int
) -> tuple[CasoClinico, list[Resposta]] | None:
    """Caso com suas respostas, se pertencer ao usuário; senão None.

    O filtro por `usuario_id` é o que impede um estudante de abrir o caso de outro —
    não é conveniência, é a regra de isolamento (ver o assert no self-check).
    """
    caso = (
        await s.execute(
            select(CasoClinico).where(
                CasoClinico.id == caso_id, CasoClinico.usuario_id == usuario_id
            )
        )
    ).scalar_one_or_none()
    if caso is None:
        return None
    respostas = list(
        (
            await s.execute(
                select(Resposta).where(Resposta.caso_id == caso_id).order_by(Resposta.id)
            )
        ).scalars()
    )
    return caso, respostas


async def adicionar_resposta(s: AsyncSession, caso_id: str, role: str, content: str) -> None:
    s.add(Resposta(caso_id=caso_id, role=role, content=content))
    await s.commit()


async def encerrar_caso(
    s: AsyncSession, caso_id: str, feedback: dict, fontes: list[UsoFonte] = ()
) -> None:
    """Encerra com o feedback e as fontes que o sustentaram, numa transação só."""
    caso = await s.get(CasoClinico, caso_id)
    caso.status = "encerrada"
    caso.feedback = feedback
    s.add_all(_usos(caso_id, "feedback", fontes))
    await s.commit()


async def apagar_caso(s: AsyncSession, caso_id: str, usuario_id: int) -> bool:
    resultado = await s.execute(
        delete(CasoClinico).where(
            CasoClinico.id == caso_id, CasoClinico.usuario_id == usuario_id
        )
    )
    await s.commit()
    return resultado.rowcount > 0


@asynccontextmanager
async def sessao_descartavel(schema: str = "_selfcheck"):
    """Sessão num schema criado e dropado aqui — para os self-checks.

    O protótipo rodava os testes em SQLite `:memory:`; com Postgres o mais próximo é um
    schema próprio, e nada toca os dados de desenvolvimento.
    """

    async def recriar(criar: bool) -> None:
        admin = create_async_engine(config.DATABASE_URL, isolation_level="AUTOCOMMIT")
        async with admin.connect() as con:
            await con.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
            if criar:
                await con.execute(text(f"CREATE SCHEMA {schema}"))
        await admin.dispose()

    await recriar(criar=True)
    # `schema_translate_map` qualifica toda tabela com o schema descartável, sem mexer no
    # código de produção. Não dá para confiar só no search_path: com `public` nele (é lá
    # que vive o tipo `vector`), o create_all vê as tabelas de public como já existentes,
    # não cria nada, e o teste passa a gravar no banco de desenvolvimento — aconteceu.
    teste = create_async_engine(
        config.DATABASE_URL,
        connect_args={"server_settings": {"search_path": f"{schema},public"}},
        execution_options={"schema_translate_map": {None: schema}},
    )
    try:
        async with teste.begin() as con:
            await con.run_sync(SQLModel.metadata.create_all)
            criada = await con.scalar(text(f"SELECT to_regclass('{schema}.usuario')"))
            assert criada, f"as tabelas precisam nascer em {schema}, não em public"
        async with async_sessionmaker(teste, expire_on_commit=False)() as s:
            yield s
    finally:
        await teste.dispose()
        await recriar(criar=False)


if __name__ == "__main__":
    # Self-check do CRUD contra o Postgres real, num schema descartável.
    #
    #   docker compose exec backend python -m core.db
    import asyncio

    async def principal() -> None:
        async with sessao_descartavel() as s:
            uid = await criar_usuario(s, "Teste", "Teste@Exemplo.com", b"hash-falso")
            achado = await buscar_usuario_por_email(s, "teste@exemplo.com")
            assert achado.id == uid, "email case-insensitive"

            await criar_sessao(s, "tok1", uid)
            assert (await usuario_da_sessao(s, "tok1")).id == uid
            assert await usuario_da_sessao(s, "inexistente") is None
            await apagar_sessao(s, "tok1")
            assert await usuario_da_sessao(s, "tok1") is None, "logout revoga a sessão"

            # Sessão vencida: some do banco em vez de só ser ignorada.
            await criar_sessao(s, "tok2", uid, dias_validade=-1)
            assert await usuario_da_sessao(s, "tok2") is None, "sessão expirada não vale"
            assert await s.get(Sessao, "tok2") is None, "sessão expirada é apagada"

            fonte = FonteReferencia(
                chave="pcdt-ic", titulo="Insuficiência cardíaca", orgao="MS", tipo="PCDT",
                identificador="P", publicado_em=None, url="u", licenca="l", cid10=["I50"],
                especialidade="Cardiologia", dificuldade="básico",
            )
            s.add(fonte)
            await s.flush()
            cid = await criar_caso(
                s, uid, "Dispneia aos esforços", "Cardiologia", "básico", {"d": "IC"},
                fontes=[(fonte.id, 1, [10, 11])],
            )
            [(uso, f)] = await fontes_do_caso(s, cid)
            assert (uso.etapa, uso.numero, uso.trechos, f.chave) == ("caso", 1, [10, 11], "pcdt-ic")
            await adicionar_resposta(s, cid, "assistant", "Apresentação do caso")
            await adicionar_resposta(s, cid, "user", "Peço um ECG")
            caso, respostas = await carregar_caso(s, cid, uid)
            assert caso.gabarito == {"d": "IC"} and len(respostas) == 2
            assert [r.content for r in respostas] == ["Apresentação do caso", "Peço um ECG"], (
                "respostas em ordem cronológica"
            )
            assert caso.status == "aberta" and caso.feedback is None
            assert await carregar_caso(s, cid, usuario_id=999) is None, (
                "não vaza caso de outro usuário"
            )

            await encerrar_caso(s, cid, {"acertou": True}, fontes=[(fonte.id, 1, [12])])
            assert [(u.etapa, u.trechos) for u, _ in await fontes_do_caso(s, cid)] == [
                ("caso", [10, 11]), ("feedback", [12])
            ], "cada etapa registra os próprios trechos"
            assert len(await fontes_do_caso(s, cid, etapa="feedback")) == 1
            caso, _ = await carregar_caso(s, cid, uid)
            assert caso.status == "encerrada" and caso.feedback == {"acertou": True}

            assert isinstance(caso.criada_em, datetime) and caso.criada_em.tzinfo, (
                "TIMESTAMPTZ: a data volta com offset, não ingênua"
            )

            assert [c.id for c in await listar_casos(s, uid)] == [cid]
            assert not await apagar_caso(s, cid, usuario_id=999), (
                "não apaga caso de outro usuário"
            )
            assert await apagar_caso(s, cid, uid) and await listar_casos(s, uid) == []
            assert not await apagar_caso(s, cid, uid), "apagar de novo retorna False"

        print("OK: CRUD de usuários, sessões, casos clínicos e respostas passa.")

    asyncio.run(principal())
