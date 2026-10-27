"""Recuperação no corpus — a superfície que `casos/router.py` consome (RF04).

- sortear_fonte():   a condição sai do corpus (RN01): PCDT, manual do MS ou relato, sorteados
                     pelo peso (relevância) e sem repetir para o mesmo estudante até
                     esgotar a área
- fontes_de_apoio(): PCDT/diretriz ligados à condição por conceito MeSH exato
                     (`rag/apoio.py`) — é o que puxa a diretriz para junto do relato
- material():        os trechos de uma fonte para uma etapa (geração ou feedback)
- contexto():        fontes numeradas [1], [2]... → bloco do prompt; o mesmo número volta
                     na citação do feedback
- buscar():          kNN sobre todos os trechos (avaliação da recuperação)

    python -m rag.busca                       # self-check num schema descartável
    python -m rag.busca "dor torácica em aperto..."   # consulta real no corpus ingerido
"""

import random
from functools import cache

from sqlalchemy import func, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from models import CasoClinico, CasoFonte, FonteReferencia, Trecho
from rag.embeddings import embedar

# Seções do PCDT que alimentam cada etapa: a geração precisa do quadro clínico, o
# feedback dos critérios diagnósticos, do diferencial e da conduta do SUS.
SECOES_CASO = ["Introdução", "Diagnóstico", "Aspectos clínicos"]
SECOES_FEEDBACK = ["Diagnóstico", "Tratamento", "Abordagem terapêutica"]
# No relato de caso, a apresentação do paciente é o que mais vale para gerar o caso.
SECOES_RELATO = ["Case", "Relato", "Caso", "Clinical case", "Apresenta", "Presentation"]
# Artigo não tem seções padronizadas: o que interessa é achado por kNN dentro dele.
CONSULTA = {
    "caso": "apresentação clínica do paciente: idade, sexo, queixa, história, exame físico e exames",
    "feedback": "critérios diagnósticos, diagnóstico diferencial e tratamento",
}
TRECHOS_POR_SECAO = 5  # PCDT: ~400 palavras por seção
TRECHOS_PRINCIPAL = 8  # artigo sorteado
TRECHOS_APOIO = 4  # cada fonte de apoio — o total cabe no limite de tokens/min da Groq
# Internato cobra a conduta com doses: os primeiros trechos de "Tratamento" costumam ser a
# parte geral, então o feedback leva também os mais próximos de posologia.
CONSULTA_DOSES = (
    "esquema de administração, posologia, dose, via de administração, diluição, volume, "
    "velocidade de infusão, duração do tratamento"
)
TRECHOS_DOSES = 6
# Fração dos sorteios que sai de relato de caso. São 2.940 relatos contra 141 PCDT: só com
# peso, os relatos somados levariam mais da metade dos casos — e relato é publicado por
# ser atípico. Primeiro decide o grupo, depois sorteia pelo peso dentro dele.
PROB_RELATO = 0.15
APOIO = 2



async def sortear_fonte(
    s: AsyncSession, especialidade: str, usuario_id: int | None = None, relato: bool | None = None
) -> FonteReferencia | None:
    """Fonte sorteável da especialidade, com chance proporcional ao `peso`.

    O ciclo do caso não entra aqui: ele muda o que se cobra, não a doença. Ordena primeiro
    pelo número de vezes que este estudante já recebeu a fonte — a área inteira passa
    antes de qualquer repetição — e, entre as menos vistas, sorteia pelo peso: a chave
    -ln(1 - u)/peso (Efraimidis–Spirakis) dá a cada fonte chance proporcional ao peso, em
    uma linha de SQL. `relato` escolhe o grupo (padrão: relato em PROB_RELATO dos casos);
    grupo vazio cai para a área inteira.
    """
    if relato is None:
        relato = random.random() < PROB_RELATO
    vistos = (
        select(CasoFonte.fonte_id, func.count().label("n"))
        .join(CasoClinico, CasoClinico.id == CasoFonte.caso_id)
        .where(CasoClinico.usuario_id == usuario_id, CasoFonte.etapa == "caso")
        .group_by(CasoFonte.fonte_id)
        .subquery()
    )
    vezes = func.coalesce(vistos.c.n, 0)
    da_area = (
        select(FonteReferencia)
        .outerjoin(vistos, vistos.c.fonte_id == FonteReferencia.id)
        .where(FonteReferencia.sorteavel, FonteReferencia.especialidade == especialidade)
    )
    # 1 - random() ∈ (0, 1]: ln(0) daria erro no Postgres.
    base = da_area.order_by(vezes, -func.ln(1 - func.random()) / FonteReferencia.peso).limit(1)
    # O grupo só vale entre as menos vistas da área: com o único relato já visto, sai um
    # PCDT ainda inédito em vez de repetir o relato.
    menos_vistas = da_area.with_only_columns(func.min(vezes)).scalar_subquery()
    eh_relato = FonteReferencia.tipo == "Relato de caso"
    grupo = (eh_relato if relato else ~eh_relato) & (vezes == menos_vistas)
    return (await s.execute(base.where(grupo))).scalar_one_or_none() or (
        await s.execute(base)
    ).scalar_one_or_none()


@cache
def _ligacoes() -> dict:
    from rag import apoio

    return apoio.carregar()


async def fontes_de_apoio(
    s: AsyncSession, fonte: FonteReferencia, ligacoes: dict | None = None
) -> list[FonteReferencia]:
    """Fontes de apoio da condição, na ordem de autoridade gravada em `apoio.json`.

    Não há busca semântica aqui de propósito: medido no corpus, o kNN ligava febre
    maculosa à doença de Chagas. A ligação é por descritor MeSH, feita e auditada offline.
    """
    chaves = [a["chave"] for a in (ligacoes if ligacoes is not None else _ligacoes()).get(fonte.chave, [])]
    if not chaves:
        return []
    achadas = {
        f.chave: f
        for f in (await s.execute(select(FonteReferencia).where(FonteReferencia.chave.in_(chaves)))).scalars()
    }
    return [achadas[c] for c in chaves if c in achadas]


async def trechos_da_fonte(
    s: AsyncSession, fonte_id: int, secoes: list[str], k: int = TRECHOS_POR_SECAO
) -> list[Trecho]:
    """Até `k` trechos de cada seção pedida, na ordem do documento.

    Casa por prefixo: "Diagnóstico" pega "Diagnóstico e classificação". O limite é por seção
    para uma seção longa não esconder a seguinte.
    """
    trechos = []
    for secao in secoes:
        trechos += (
            await s.execute(
                select(Trecho)
                .where(Trecho.fonte_id == fonte_id, Trecho.secao.ilike(f"{secao}%"))
                .order_by(Trecho.ordem)
                .limit(k)
            )
        ).scalars()
    return sorted({t.id: t for t in trechos}.values(), key=lambda t: t.ordem)


async def trechos_relevantes(s: AsyncSession, fonte_id: int, consulta: str, k: int) -> list[Trecho]:
    """Os `k` trechos de UMA fonte mais próximos da consulta, devolvidos na ordem do texto.

    Busca exata dentro da fonte (um documento tem dezenas de trechos): a CTE materializada
    impede o planejador de trocar o filtro por fonte pelo HNSW global.
    """
    [vetor] = await embedar([consulta])
    da_fonte = select(Trecho).where(Trecho.fonte_id == fonte_id).cte("da_fonte").prefix_with(
        "MATERIALIZED", dialect="postgresql"
    )
    ids = (
        await s.execute(
            select(da_fonte.c.id).order_by(da_fonte.c.embedding.cosine_distance(vetor)).limit(k)
        )
    ).scalars().all()
    trechos = (await s.execute(select(Trecho).where(Trecho.id.in_(ids)))).scalars()
    return sorted(trechos, key=lambda t: t.ordem)


async def material(
    s: AsyncSession, fonte: FonteReferencia, etapa: str, principal: bool = True, ciclo: str = ""
) -> list[Trecho]:
    """Trechos de uma fonte para uma etapa ("caso" ou "feedback")."""
    k = TRECHOS_PRINCIPAL if principal else TRECHOS_APOIO
    if fonte.tipo in ("PCDT", "Manual MS"):
        if fonte.tipo == "PCDT":
            secoes = SECOES_CASO if etapa == "caso" else SECOES_FEEDBACK
            trechos = await trechos_da_fonte(s, fonte.id, secoes, TRECHOS_POR_SECAO if principal else 2)
        else:  # manual: capítulos com nomes livres, então o kNN acha o que serve
            trechos = await trechos_relevantes(s, fonte.id, CONSULTA[etapa], k)
        if etapa == "feedback" and ciclo == "internato":
            k = TRECHOS_DOSES if principal else TRECHOS_DOSES // 2
            doses = await trechos_relevantes(s, fonte.id, CONSULTA_DOSES, k)
            trechos = sorted({t.id: t for t in trechos + doses}.values(), key=lambda t: t.ordem)
        return trechos
    if fonte.tipo == "Relato de caso" and etapa == "caso":
        if trechos := await trechos_da_fonte(s, fonte.id, SECOES_RELATO, k):
            return trechos
    return await trechos_relevantes(s, fonte.id, CONSULTA[etapa], k)


def contexto(blocos: list[tuple[int, FonteReferencia, list[Trecho]]]) -> str:
    """Fontes numeradas, cada uma com tipo, título e trechos agrupados por seção."""
    partes = []
    for numero, fonte, trechos in blocos:
        if not trechos:
            continue
        ano = fonte.publicado_em.year if fonte.publicado_em else "s.d."
        partes.append(f"[{numero}] {fonte.tipo} — {fonte.titulo} ({fonte.orgao}, {ano})")
        atual = None
        for t in trechos:
            if t.secao != atual:
                partes.append(f"## {t.secao}")
                atual = t.secao
            partes.append(t.texto)
    return "\n\n".join(partes)


async def buscar(s: AsyncSession, consulta: str, k: int = 5) -> list[tuple[Trecho, FonteReferencia]]:
    """Os `k` trechos mais próximos da consulta (distância de cosseno, índice HNSW)."""
    [vetor] = await embedar([consulta])
    return list(
        await s.execute(
            select(Trecho, FonteReferencia)
            .join(FonteReferencia, FonteReferencia.id == Trecho.fonte_id)
            .order_by(Trecho.embedding.cosine_distance(vetor))
            .limit(k)
        )
    )


if __name__ == "__main__":
    import asyncio
    import sys

    async def consultar(texto: str) -> None:
        from core import db

        async with db.abrir_sessao() as s:
            for trecho, fonte in await buscar(s, texto, k=8):
                print(f"[{fonte.tipo} · {fonte.titulo[:50]} · {trecho.secao}] {trecho.texto[:110]}…")

    async def selfcheck() -> None:
        from core.db import sessao_descartavel
        from models import Usuario
        from rag.embeddings import DIMENSAO

        def eixo(*pesos: tuple[int, float]) -> list[float]:
            v = [0.0] * DIMENSAO
            for i, p in pesos:
                v[i] = p
            return v

        async with sessao_descartavel() as s:
            comum = dict(orgao="MS", url="u", licenca="l", publicado_em=None, cid10=[])
            iam = FonteReferencia(chave="iam", tipo="PCDT", identificador="P1", titulo="Infarto agudo do miocárdio",
                                  especialidade="Cardiologia", dificuldade="básico", peso=9, **comum)
            fa = FonteReferencia(chave="fa", tipo="PCDT", identificador="P2", titulo="Fibrilação atrial",
                                 especialidade="Cardiologia", dificuldade="intermediário", peso=1, **comum)
            relato = FonteReferencia(chave="PMC1", tipo="Relato de caso", identificador="PMCID PMC1",
                                     titulo="Kounis syndrome", especialidade="Cardiologia", dificuldade="avançado", **comum)
            diretriz = FonteReferencia(chave="PMC2", tipo="Diretriz", identificador="PMCID PMC2", sorteavel=False,
                                       titulo="Diretriz SBC de síndromes coronarianas", especialidade="Cardiologia",
                                       dificuldade="", **comum)
            longe = FonteReferencia(chave="PMC3", tipo="Revisão", identificador="PMCID PMC3", sorteavel=False,
                                    titulo="Dermatite atópica", especialidade="Dermatologia", dificuldade="", **comum)
            s.add_all([iam, fa, relato, diretriz, longe, Usuario(nome="u", email="u@x", senha_hash=b"x")])
            await s.flush()
            s.add_all([
                Trecho(fonte_id=iam.id, ordem=0, secao="Introdução", texto="e", embedding=eixo((0, 1))),
                Trecho(fonte_id=iam.id, ordem=1, secao="Diagnóstico", texto="h1", embedding=eixo((1, 1))),
                Trecho(fonte_id=iam.id, ordem=2, secao="Diagnóstico", texto="h2", embedding=eixo((2, 1))),
                Trecho(fonte_id=iam.id, ordem=3, secao="Diagnóstico e classificação", texto="ev", embedding=eixo((3, 1))),
                Trecho(fonte_id=iam.id, ordem=4, secao="Tratamento", texto="tx", embedding=eixo((4, 1))),
                Trecho(fonte_id=fa.id, ordem=0, secao="Diagnóstico", texto="fa", embedding=eixo((5, 1))),
                Trecho(fonte_id=relato.id, ordem=0, secao="Introduction", texto="ri", embedding=eixo((6, 1))),
                Trecho(fonte_id=relato.id, ordem=1, secao="Case report", texto="rc", secao_id="sec2", embedding=eixo((7, 1))),
                Trecho(fonte_id=relato.id, ordem=2, secao="Discussion", texto="rd", embedding=eixo((8, 1))),
                Trecho(fonte_id=diretriz.id, ordem=0, secao="Recomendações", texto="dr", embedding=eixo((10, 1))),
                Trecho(fonte_id=longe.id, ordem=0, secao="Introdução", texto="lg", embedding=eixo((11, 1))),
            ])
            await s.commit()

            # Sorteio: só sorteáveis da área; apoio nunca sai; o grupo (relato ou não) manda.
            for _ in range(5):
                assert (await sortear_fonte(s, "Cardiologia", relato=True)).chave == "PMC1"
                assert (await sortear_fonte(s, "Cardiologia", relato=False)).chave in {"iam", "fa"}
            assert await sortear_fonte(s, "Dermatologia") is None, "revisão não é sorteável"
            assert await sortear_fonte(s, "Pediatria") is None, "sem corpus → None"
            # Peso: IAM (9) sai ~9x mais que FA (1). Em 400 sorteios, esperado ~360 x 40.
            n_iam = sum([(await sortear_fonte(s, "Cardiologia", relato=False)).chave == "iam" for _ in range(400)])
            assert 320 < n_iam < 395, n_iam

            # Sem repetição: com as 3 sorteáveis da área já vistas uma vez cada, exceto
            # uma, o próximo sorteio (balde vazio → área inteira) traz a que falta.
            from models import CasoClinico, CasoFonte
            uid = (await s.execute(select(Usuario.id))).scalar_one()
            for i, f in enumerate([iam, relato]):
                s.add(CasoClinico(id=f"c{i}", usuario_id=uid, titulo="t", especialidade="Cardiologia",
                                  ciclo="básico", gabarito={}))
                await s.flush()
                s.add(CasoFonte(caso_id=f"c{i}", fonte_id=f.id, etapa="caso", numero=1, trechos=[]))
            await s.commit()
            for _ in range(5):
                assert (await sortear_fonte(s, "Cardiologia", uid, relato=False)).chave == "fa", "a não vista vem antes"
                assert (await sortear_fonte(s, "Cardiologia", uid, relato=True)).chave == "fa", (
                    "relato já visto: a não vista de outro grupo ganha"
                )

            # Seções do PCDT e material por tipo de fonte.
            ts = await trechos_da_fonte(s, iam.id, SECOES_CASO)
            assert [t.texto for t in ts] == ["e", "h1", "h2", "ev"], "prefixo casa 'Diagnóstico e ...'"
            assert [t.texto for t in await material(s, iam, "feedback")] == ["h1", "h2", "ev", "tx"]
            assert [t.texto for t in await material(s, relato, "caso")] == ["rc"], "relato: seção do caso"

            # contexto(): numerado, com tipo e seções.
            blocos = [(1, iam, ts[:2]), (2, relato, [t for t in await material(s, relato, "caso")])]
            ctx = contexto(blocos)
            assert ctx.startswith("[1] PCDT — Infarto agudo do miocárdio (MS, s.d.)\n\n## Introdução\n\ne\n\n## Diagnóstico")
            assert "[2] Relato de caso — Kounis syndrome (MS, s.d.)\n\n## Case report\n\nrc" in ctx
            assert contexto([(1, iam, [])]) == "", "fonte sem trecho não entra"

            # kNN e apoio, com embedar trocado por um vetor fixo — sem modelo.
            global embedar

            async def falso(textos):
                # Distâncias de cosseno: diretriz (eixo 10) 0,36; PCDT (eixo 1) 0,38;
                # relato (7) 0,54; revisão de dermatologia (11) 0,95.
                return [eixo((7, 0.45), (10, 0.62), (1, 0.6), (11, 0.05)) for _ in textos]

            embedar = falso
            # Dentro do relato, o trecho mais próximo de (7) é "rc".
            assert [t.texto for t in await trechos_relevantes(s, relato.id, "x", 1)] == ["rc"]
            # Internato: o feedback soma os trechos mais próximos de posologia, sem duplicar.
            # O IAM tem 5 trechos e o kNN pede 6: entra a Introdução ("e"), sem repetir os da
            # seção e na ordem do documento.
            internato = [t.texto for t in await material(s, iam, "feedback", ciclo="internato")]
            assert internato == ["e", "h1", "h2", "ev", "tx"], internato
            # Manual do MS: capítulos de nome livre — o material vem do kNN, não de seção.
            manual = FonteReferencia(chave="tb", tipo="Manual MS", identificador="ISBN", titulo="Tuberculose",
                                     especialidade="Infectologia", dificuldade="básico", **comum)
            s.add(manual)
            await s.flush()
            s.add_all([
                Trecho(fonte_id=manual.id, ordem=0, secao="Espectro clínico", texto="m0", embedding=eixo((7, 1))),
                Trecho(fonte_id=manual.id, ordem=1, secao="Adesão", texto="m1", embedding=eixo((11, 1))),
            ])
            await s.commit()
            assert [t.texto for t in await material(s, manual, "caso", principal=False)] == ["m0", "m1"]
            # Apoio: vem das ligações gravadas, na ordem delas; chave que não está no banco
            # (fonte descartada depois) some sem quebrar.
            ligacoes = {"PMC1": [{"chave": "iam"}, {"chave": "sumiu"}, {"chave": "PMC2"}]}
            assert [f.chave for f in await fontes_de_apoio(s, relato, ligacoes)] == ["iam", "PMC2"]
            assert await fontes_de_apoio(s, fa, ligacoes) == [], "sem ligação, sem apoio"
            achados = await buscar(s, "qualquer", k=2)
            assert [(t.texto, f.chave) for t, f in achados] == [("dr", "PMC2"), ("h1", "iam")]
        print("OK: sorteio ponderado sem repetição, apoio por autoridade, material por tipo e ciclo, contexto e kNN.")

    asyncio.run(consultar(sys.argv[1]) if len(sys.argv) > 1 else selfcheck())
