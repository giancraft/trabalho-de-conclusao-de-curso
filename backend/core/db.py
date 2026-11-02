"""Persistência em PostgreSQL (SQLModel + asyncpg).

Substitui a conexão SQLite única sob lock global do protótipo: ali todo request era
serializado, o que não sobrevive a concorrência real nem ao RAG de setembro.

Cada função recebe a `AsyncSession` de quem chama — as rotas injetam a da request por
`Depends(get_session)`. O schema é criado pelo Alembic, não aqui.
"""

import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from sqlalchemy import func, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, delete, select

from core import config
from models import (
    CasoClinico,
    CasoFonte,
    ChamadaIA,
    ConfiguracaoIA,
    FonteReferencia,
    Resposta,
    Sessao,
    Simulado,
    Usuario,
    agora,
)

engine = create_async_engine(config.DATABASE_URL, pool_pre_ping=True)

abrir_sessao = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session():
    """Dependency do FastAPI: uma sessão por request, fechada no fim."""
    async with abrir_sessao() as sessao:
        yield sessao


# --- usuários e sessões de autenticação ---


async def criar_usuario(
    s: AsyncSession, nome: str, email: str, senha_hash: bytes, consentiu: bool = False
) -> int:
    usuario = Usuario(
        nome=nome, email=email.lower(), senha_hash=senha_hash, consentiu_em=agora() if consentiu else None
    )
    s.add(usuario)
    await s.commit()
    return usuario.id


async def buscar_usuario_por_email(s: AsyncSession, email: str) -> Usuario | None:
    return (
        await s.execute(select(Usuario).where(Usuario.email == email.lower()))
    ).scalar_one_or_none()


async def atualizar_usuario(s: AsyncSession, usuario_id: int, nome: str, email: str) -> None:
    usuario = await s.get(Usuario, usuario_id)
    usuario.nome, usuario.email = nome, email.lower()
    await s.commit()


async def registrar_consentimento(s: AsyncSession, usuario_id: int) -> None:
    usuario = await s.get(Usuario, usuario_id)
    usuario.consentiu_em = agora()
    await s.commit()


async def definir_papel(s: AsyncSession, email: str, papel: str) -> bool:
    """Promove ou rebaixa pelo email (CLI `auth.admin`); False se não existe."""
    usuario = await buscar_usuario_por_email(s, email)
    if usuario is None:
        return False
    usuario.papel = papel
    await s.commit()
    return True


async def apagar_usuario(s: AsyncSession, usuario_id: int) -> None:
    """Exclusão da conta (LGPD): sessões, casos, simulados e chamadas vão junto, pelas FKs
    em CASCADE; versões de configuração que ele salvou ficam, sem o autor."""
    await s.execute(delete(Usuario).where(Usuario.id == usuario_id))
    await s.commit()


async def dados_do_usuario(s: AsyncSession, usuario_id: int) -> dict:
    """Tudo o que o sistema guarda do usuário, legível (LGPD, direito de acesso)."""
    usuario = await s.get(Usuario, usuario_id)
    casos = await listar_casos(s, usuario_id)
    respostas = defaultdict(list)
    for r in (await s.execute(
        select(Resposta).where(Resposta.caso_id.in_([c.id for c in casos])).order_by(Resposta.id)
    )).scalars():
        respostas[r.caso_id].append({"papel": r.role, "texto": r.content, "em": r.criada_em.isoformat()})
    return {
        "conta": {"nome": usuario.nome, "email": usuario.email, "criada_em": usuario.criado_em.isoformat(),
                  "consentiu_em": usuario.consentiu_em.isoformat() if usuario.consentiu_em else None},
        "casos": [
            {"id": c.id, "titulo": c.titulo, "especialidade": c.especialidade, "ciclo": c.ciclo, "status": c.status,
             "criado_em": c.criada_em.isoformat(), "feedback": c.feedback, "mensagens": respostas[c.id]}
            for c in casos
        ],
    }


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
    ciclo: str,
    gabarito: dict,
    fontes: list[UsoFonte] = (),
    simulado_id: str | None = None,
    ordem: int | None = None,
) -> str:
    """Cria o caso e registra as fontes da geração na mesma transação (RF14)."""
    caso = CasoClinico(
        id=uuid.uuid4().hex,
        usuario_id=usuario_id,
        titulo=titulo,
        especialidade=especialidade,
        ciclo=ciclo,
        gabarito=gabarito,
        simulado_id=simulado_id,
        ordem=ordem,
    )
    s.add(caso)
    await s.flush()  # o caso precisa existir antes dos vínculos (FK)
    s.add_all(_usos(caso.id, "caso", fontes))
    await s.commit()
    return caso.id


async def criar_simulado(s: AsyncSession, usuario_id: int, ciclo: str, selecao: list[str], fila: list[int]) -> str:
    simulado = Simulado(id=uuid.uuid4().hex, usuario_id=usuario_id, ciclo=ciclo, selecao=selecao, fila=fila)
    s.add(simulado)
    await s.commit()
    return simulado.id


async def carregar_simulado(
    s: AsyncSession, simulado_id: str, usuario_id: int
) -> tuple[Simulado, list[CasoClinico]] | None:
    """Simulado do usuário com seus casos em ordem; None se não for dele (isolamento)."""
    simulado = (
        await s.execute(select(Simulado).where(Simulado.id == simulado_id, Simulado.usuario_id == usuario_id))
    ).scalar_one_or_none()
    if simulado is None:
        return None
    casos = (
        await s.execute(select(CasoClinico).where(CasoClinico.simulado_id == simulado_id).order_by(CasoClinico.ordem))
    ).scalars()
    return simulado, list(casos)


async def totais_dos_simulados(s: AsyncSession, usuario_id: int) -> dict[str, int]:
    """{simulado_id: número de casos da fila}, para o "2/5" da lista de conversas."""
    linhas = await s.execute(
        select(Simulado.id, func.cardinality(Simulado.fila)).where(Simulado.usuario_id == usuario_id)
    )
    return dict(linhas.all())


async def historico_de_desempenho(s: AsyncSession, usuario_id: int | None = None) -> list[dict]:
    """Casos com a condição sorteada (a fonte [1]) e o horário de cada mensagem — a
    entrada de `casos.metricas`. Sem `usuario_id`, de todos (exportação da pesquisa)."""
    consulta = (
        select(CasoClinico, FonteReferencia)
        .outerjoin(
            CasoFonte,
            (CasoFonte.caso_id == CasoClinico.id) & (CasoFonte.etapa == "caso") & (CasoFonte.numero == 1),
        )
        .outerjoin(FonteReferencia, FonteReferencia.id == CasoFonte.fonte_id)
    )
    if usuario_id is not None:
        consulta = consulta.where(CasoClinico.usuario_id == usuario_id)
    linhas = (await s.execute(consulta)).all()
    mensagens = defaultdict(list)
    for caso_id, papel, instante in await s.execute(
        select(Resposta.caso_id, Resposta.role, Resposta.criada_em)
        .where(Resposta.caso_id.in_([c.id for c, _ in linhas]))
        .order_by(Resposta.id)
    ):
        mensagens[caso_id].append((papel, instante))
    return [
        {
            "usuario_id": c.usuario_id, "criada_em": c.criada_em, "ciclo": c.ciclo, "status": c.status,
            "feedback": c.feedback, "mensagens": mensagens[c.id], "especialidade": c.especialidade,
            "grande_area": f.grande_area if f else "", "tema": f.tema if f else "", "tipo": f.tipo if f else "",
        }
        for c, f in linhas
    ]


# --- telemetria e configuração da IA ---


async def registrar_chamadas(
    s: AsyncSession, chamadas: list[dict], caso_id: str | None, usuario_id: int | None
) -> None:
    """Grava as chamadas ao LLM coletadas numa requisição (`casos.ai.coletar`)."""
    if chamadas:
        s.add_all(ChamadaIA(**c, caso_id=caso_id, usuario_id=usuario_id) for c in chamadas)
        await s.commit()


async def chamadas_desde(s: AsyncSession, desde: datetime) -> list[dict]:
    """Telemetria do período, como dicts para `casos.qualidade.desempenho`."""
    linhas = (await s.execute(select(ChamadaIA).where(ChamadaIA.criada_em >= desde))).scalars()
    return [c.model_dump() for c in linhas]


async def casos_para_qualidade(s: AsyncSession) -> list[dict]:
    """Casos encerrados com o gabarito, a fonte sorteada ([1]) e os números das fontes que
    foram ao prompt da avaliação — a entrada de `casos.qualidade.avaliar`."""
    linhas = (await s.execute(
        select(CasoClinico, FonteReferencia)
        .outerjoin(CasoFonte, (CasoFonte.caso_id == CasoClinico.id) & (CasoFonte.etapa == "caso") & (CasoFonte.numero == 1))
        .outerjoin(FonteReferencia, FonteReferencia.id == CasoFonte.fonte_id)
        .where(CasoClinico.status == "encerrada")
    )).all()
    numeros = defaultdict(set)
    for caso_id, numero in await s.execute(
        select(CasoFonte.caso_id, CasoFonte.numero).where(
            CasoFonte.etapa == "feedback", CasoFonte.caso_id.in_([c.id for c, _ in linhas])
        )
    ):
        numeros[caso_id].add(numero)
    return [
        {"feedback": c.feedback, "gabarito": c.gabarito, "ciclo": c.ciclo, "tipo": f.tipo if f else "",
         "titulo_fonte": f.titulo if f else "", "fontes_feedback": numeros[c.id]}
        for c, f in linhas
    ]


async def configuracao_atual(s: AsyncSession) -> ConfiguracaoIA | None:
    return (
        await s.execute(select(ConfiguracaoIA).order_by(ConfiguracaoIA.id.desc()).limit(1))
    ).scalar_one_or_none()


async def salvar_configuracao(s: AsyncSession, dados: dict, usuario_id: int | None) -> ConfiguracaoIA:
    versao = ConfiguracaoIA(dados=dados, criado_por=usuario_id)
    s.add(versao)
    await s.commit()
    return versao


async def historico_configuracao(s: AsyncSession, limite: int = 20) -> list[tuple[ConfiguracaoIA, str | None]]:
    """Versões, da mais nova para a mais antiga, com o nome de quem salvou."""
    return list(
        await s.execute(
            select(ConfiguracaoIA, Usuario.nome)
            .outerjoin(Usuario, Usuario.id == ConfiguracaoIA.criado_por)
            .order_by(ConfiguracaoIA.id.desc())
            .limit(limite)
        )
    )


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

            # Simulado: fila de fontes; os casos entram com a posição e voltam em ordem.
            sid = await criar_simulado(s, uid, "clínico", ["t:pcdt-ic"], [fonte.id, fonte.id, fonte.id])
            for ordem in (2, 1):
                await criar_caso(s, uid, f"caso {ordem}", "Cardiologia", "clínico", {}, simulado_id=sid, ordem=ordem)
            simulado, casos_sim = await carregar_simulado(s, sid, uid)
            assert simulado.fila == [fonte.id] * 3 and [c.titulo for c in casos_sim] == ["caso 1", "caso 2"]
            assert await carregar_simulado(s, sid, usuario_id=999) is None, "não vaza simulado de outro usuário"
            assert await totais_dos_simulados(s, uid) == {sid: 3}

            # Histórico do painel: a fonte [1] de cada caso e o horário das mensagens.
            fonte.tema, fonte.grande_area = "pcdt-ic", "Clínica Médica"
            hid = await criar_caso(s, uid, "h", "Cardiologia", "clínico", {}, fontes=[(fonte.id, 1, [])])
            await adicionar_resposta(s, hid, "assistant", "a")
            await adicionar_resposta(s, hid, "user", "b")
            hist = {h["tema"]: h for h in await historico_de_desempenho(s, uid)}
            assert [p for p, _ in hist["pcdt-ic"]["mensagens"]] == ["assistant", "user"]
            assert hist["pcdt-ic"]["grande_area"] == "Clínica Médica" and "" in hist, "caso sem fonte entra vazio"
            assert await historico_de_desempenho(s, usuario_id=999) == []

            # Conta: edição, consentimento, papel e exportação dos dados.
            assert (await s.get(Usuario, uid)).consentiu_em is None, "sem aceite por padrão"
            await registrar_consentimento(s, uid)
            await atualizar_usuario(s, uid, "Novo Nome", "Novo@Exemplo.com")
            u = await s.get(Usuario, uid)
            assert (u.nome, u.email, u.papel) == ("Novo Nome", "novo@exemplo.com", "estudante") and u.consentiu_em
            assert await definir_papel(s, "NOVO@exemplo.com", "admin") and (await s.get(Usuario, uid)).papel == "admin"
            assert not await definir_papel(s, "ninguem@x", "admin")
            dados = await dados_do_usuario(s, uid)
            assert dados["conta"]["email"] == "novo@exemplo.com" and dados["casos"][0]["mensagens"]

            # Telemetria e configuração: versões em ordem, a mais nova vale.
            v1 = await salvar_configuracao(s, {"modelo": "a"}, uid)
            v2 = await salvar_configuracao(s, {"modelo": "b"}, uid)
            assert (await configuracao_atual(s)).id == v2.id
            assert [(v.id, autor) for v, autor in await historico_configuracao(s)] == [(v2.id, "Novo Nome"), (v1.id, "Novo Nome")]
            chamada = {"etapa": "chat", "modelo": "m", "configuracao_id": v2.id, "tokens_entrada": 10, "tokens_cache": 0,
                       "tokens_saida": 5, "custo": 0.01, "latencia_ms": 900, "tentativas": 1, "ok": True, "erro": None}
            await registrar_chamadas(s, [chamada, {**chamada, "etapa": "feedback"}], hid, uid)
            assert {c["etapa"] for c in await chamadas_desde(s, agora() - timedelta(hours=1))} == {"chat", "feedback"}
            encerrado = await criar_caso(s, uid, "q", "Cardiologia", "clínico", {"diagnostico": "IC"}, fontes=[(fonte.id, 1, [])])
            await encerrar_caso(s, encerrado, {"acertou": True}, fontes=[(fonte.id, 1, [])])
            [q] = [c for c in await casos_para_qualidade(s) if c["gabarito"] == {"diagnostico": "IC"}]
            assert q["titulo_fonte"] == "Insuficiência cardíaca" and q["fontes_feedback"] == {1}

            # Exclusão da conta (LGPD): casos, chamadas e sessões vão junto; a configuração fica.
            await criar_sessao(s, "tok3", uid)
            await apagar_usuario(s, uid)
            s.expire_all()
            assert await s.get(Usuario, uid) is None and await listar_casos(s, uid) == []
            assert await chamadas_desde(s, agora() - timedelta(hours=1)) == [], "chamadas apagadas em cascata"
            assert await usuario_da_sessao(s, "tok3") is None
            assert (await configuracao_atual(s)).criado_por is None, "versão fica, sem o autor"

        print("OK: CRUD de usuários, sessões, casos, simulados, respostas, conta, telemetria e configuração.")

    asyncio.run(principal())
