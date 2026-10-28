"""Métricas de desempenho do estudante e recomendações de estudo (RF10, RF11, RN04).

    python -m casos.metricas                       # self-check das regras, sem banco
    python -m casos.metricas --exportar dados.csv  # um caso por linha, anonimizado (pesquisa)

Tudo sai do que o sistema já grava — caso, feedback, mensagens com horário e a fonte
sorteada — por regra, sem LLM: o mesmo histórico dá sempre o mesmo painel. As métricas
são calculadas na leitura (não há tabela de métricas para ficar defasada).
"""

import re
import statistics
from collections import Counter
from datetime import datetime, timedelta

from casos.ai import CICLOS
from rag.temas import OUTROS

# Intervalo entre mensagens acima disto é pausa (o caso ficou aberto na aba): não conta
# como tempo de estudo.
PAUSA = timedelta(minutes=10)
JANELA_EVOLUCAO = 5  # acerto móvel: últimos N casos
MINIMO_FRAGIL = 2  # casos para chamar um tema de frágil — 1 erro isolado não é padrão
LIMITE_FRAGIL = 0.5
RECENTE = timedelta(days=28)

# Etapa da investigação de cada lacuna do feedback, pela palavra-chave. A ordem importa:
# "Não perguntou sobre exames anteriores" é anamnese, não exame complementar.
ETAPAS = [
    ("Exame físico", r"exame f[íi]sico|ausculta|palpa|percu|fundo de olho|fundoscop|sinais vitais|aferi|oximetr|"
                     r"verific|tremor|rigidez|caracter[íi]sticas faciais"),
    ("Anamnese", r"pergunt|question|indag|anamnese|hist[óo]ri|antecedente|sintoma|irradia|uso de|h[áa]bito|explor|"
                 r"risco de"),
    ("Exames complementares", r"solicit|\bpedi|exame|laborat|dosagem|teste|sorolog|imagem|radiograf|ultrass|"
                              r"tomograf|resson|ecocardio|eletrocardio|\becg\b|bi[óo]psia|gasometria|lactato|"
                              r"marcador|n[íi]vel|perfil|hemoglobin|albumin|anticorpo|enzima|urina"),
    ("Conduta", r"inici|tratamento|trat[oa]u|encaminh|prescrev|contato|condut|administr|orient"),
    ("Raciocínio diagnóstico", r"consider|correlacion|valoriz|diagn[óo]st|diferencial|hip[óo]tese|reconhec"),
]
_ETAPAS = [(nome, re.compile(padrao, re.IGNORECASE)) for nome, padrao in ETAPAS]


def classificar_lacuna(texto: str) -> str:
    """Etapa da investigação em que a lacuna caiu.

    Feedbacks de antes de out/2026 listavam doenças ("Pericardite aguda") em vez de
    ações: diferencial não considerado é raciocínio diagnóstico.
    """
    if not re.match(r"\s*(n[ãa]o|faltou|deixou)\b", texto, re.IGNORECASE):
        return "Raciocínio diagnóstico"
    return next((nome for nome, padrao in _ETAPAS if padrao.search(texto)), "Outros")


def tempo_ativo(instantes: list[datetime]) -> float:
    """Segundos de estudo: soma dos intervalos entre mensagens, sem as pausas longas."""
    instantes = sorted(instantes)
    return sum(
        (b - a).total_seconds() for a, b in zip(instantes, instantes[1:]) if b - a <= PAUSA
    )


def derivar(c: dict) -> dict:
    """O caso encerrado com o que se mede nele: acerto, tempo ativo, perguntas, lacunas."""
    do_estudante = [t for p, t in c["mensagens"] if p == "user"]
    return {
        **c,
        "acertou": bool(c["feedback"].get("acertou")),
        "segundos": tempo_ativo([t for _, t in c["mensagens"]]),
        # A última mensagem do estudante é a entrega final, não uma pergunta.
        "perguntas": max(len(do_estudante) - 1, 0),
        "lacunas": [classificar_lacuna(l) for l in c["feedback"].get("hipoteses_nao_consideradas", [])],
        "inconsistencias": len(c["feedback"].get("inconsistencias", [])),
    }


def encerrados(casos: list[dict]) -> list[dict]:
    """Só os casos com feedback, em ordem cronológica, já derivados."""
    return [
        derivar(c) for c in sorted(casos, key=lambda c: c["criada_em"])
        if c["status"] == "encerrada" and c.get("feedback")
    ]


def _ordem_ciclo(ciclo: str) -> int:
    return CICLOS.index(ciclo) if ciclo in CICLOS else len(CICLOS)


def _taxa(acertos: int, casos: int) -> float | None:
    return acertos / casos if casos else None


def _grupos(casos: list[dict], chave) -> dict:
    """{chave: [casos, acertos, último]} — na ordem de primeira aparição."""
    grupos = {}
    for c in casos:
        g = grupos.setdefault(chave(c), [0, 0, None])
        g[0] += 1
        g[1] += c["acertou"]
        g[2] = max(filter(None, [g[2], c["criada_em"]]))
    return grupos


def resumir(casos: list[dict], importantes: list[dict], nomes: dict[str, str], agora: datetime) -> dict:
    """Painel do estudante a partir do histórico dele.

    `casos`: [{criada_em, ciclo, status, feedback, mensagens: [(papel, instante)],
    grande_area, especialidade, tema, tipo}] — os quatro últimos são da fonte sorteada
    (vazios em caso sem fonte). `importantes`: temas sorteáveis em ordem de peso
    [{id, nome}]. `nomes`: tema → nome. `agora`: referência para "últimas 4 semanas".
    """
    feitos = encerrados(casos)
    n = len(feitos)
    acertos = sum(c["acertou"] for c in feitos)
    recentes = [c for c in feitos if agora - c["criada_em"] <= RECENTE]
    antigos = [c for c in feitos if agora - c["criada_em"] > RECENTE]
    kpis = {
        "casos_concluidos": n,
        "casos_abertos": sum(c["status"] == "aberta" for c in casos),
        "taxa_acerto": _taxa(acertos, n),
        "taxa_acerto_recente": _taxa(sum(c["acertou"] for c in recentes), len(recentes)),
        "taxa_acerto_anterior": _taxa(sum(c["acertou"] for c in antigos), len(antigos)),
        "minutos_por_caso": statistics.median(c["segundos"] for c in feitos) / 60 if n else None,
        "perguntas_por_caso": statistics.mean(c["perguntas"] for c in feitos) if n else None,
        "lacunas_por_caso": statistics.mean(len(c["lacunas"]) for c in feitos) if n else None,
    }

    evolucao = []
    for i, c in enumerate(feitos):
        janela = feitos[max(0, i + 1 - JANELA_EVOLUCAO) : i + 1]
        evolucao.append({
            "ordem": i + 1, "data": c["criada_em"], "acertou": c["acertou"],
            "acerto_movel": sum(x["acertou"] for x in janela) / len(janela),
        })

    def segunda(d: datetime):
        return (d - timedelta(days=d.weekday())).date()

    semanas = _grupos(feitos, lambda c: segunda(c["criada_em"]))
    por_semana = [{"semana": s, "casos": g[0], "acertos": g[1]} for s, g in sorted(semanas.items())]

    def lista(grupos: dict, nome=str, id_=lambda k: None, detalhe=lambda k: None) -> list[dict]:
        linhas = [
            {"id": id_(k), "nome": nome(k), "detalhe": detalhe(k), "casos": g[0], "acertos": g[1], "ultimo": g[2]}
            for k, g in grupos.items()
        ]
        return sorted(linhas, key=lambda l: (-l["casos"], l["nome"]))

    com_fonte = [c for c in feitos if c.get("tema")]
    por_especialidade = lista(
        _grupos(com_fonte, lambda c: (c["grande_area"], c["especialidade"])),
        nome=lambda k: k[1], id_=lambda k: f"e:{k[0]}|{k[1]}", detalhe=lambda k: k[0],
    )
    por_tema = lista(
        _grupos(com_fonte, lambda c: (c["tema"], c["especialidade"])),
        nome=lambda k: OUTROS if k[0].startswith("outros:") else nomes.get(k[0], k[0]),
        id_=lambda k: f"t:{k[0]}", detalhe=lambda k: k[1],
    )
    # Ciclos na ordem do curso, não pela contagem.
    por_ciclo = sorted(lista(_grupos(feitos, lambda c: c["ciclo"])), key=lambda l: _ordem_ciclo(l["nome"]))
    por_apresentacao = lista(
        _grupos(com_fonte, lambda c: "Atípica (relato de caso)" if c["tipo"] == "Relato de caso" else "Típica (diretriz)")
    )
    contagem = Counter(l for c in feitos for l in c["lacunas"])
    lacunas = [
        {"etapa": etapa, "total": contagem[etapa], "por_caso": contagem[etapa] / n if n else 0}
        for etapa in [e for e, _ in ETAPAS] + ["Outros"]
        if contagem[etapa]
    ]

    return {
        "kpis": kpis,
        "evolucao": evolucao,
        "por_semana": por_semana,
        "por_especialidade": por_especialidade,
        "por_tema": por_tema,
        "por_ciclo": por_ciclo,
        "por_apresentacao": por_apresentacao,
        "lacunas": lacunas,
        "recomendacoes": recomendar(por_tema, por_especialidade, importantes, lacunas, casos),
    }


def recomendar(por_tema, por_especialidade, importantes, lacunas, casos) -> list[dict]:
    """O que estudar a seguir, por regra e com o motivo escrito (RN04: só o histórico
    deste estudante). Até 2 temas frágeis, até 2 temas importantes ainda não vistos e a
    etapa da investigação que mais falha. `no` é o nó da árvore para o "Treinar agora".
    """
    saida = []

    def frageis(linhas):
        return sorted(
            (l for l in linhas if l["casos"] >= MINIMO_FRAGIL and l["acertos"] / l["casos"] < LIMITE_FRAGIL),
            key=lambda l: (l["acertos"] / l["casos"], -l["casos"]),
        )

    vistos = set()
    for l in frageis(por_tema)[:2] or frageis(por_especialidade)[:2]:
        saida.append({
            "tipo": "fragil", "no": l["id"], "titulo": l["nome"],
            "motivo": f"{l['acertos']} de {l['casos']} diagnósticos corretos — vale treinar de novo.",
        })
        vistos.add(l["id"])

    praticados = {f"t:{c['tema']}" for c in casos if c.get("tema")}
    for t in [t for t in importantes if t["id"] not in praticados][:2]:
        saida.append({
            "tipo": "nao_praticado", "no": t["id"], "titulo": t["nome"],
            "motivo": "Tema frequente na prática e nas provas que você ainda não praticou.",
        })

    if lacunas and (pior := max(lacunas, key=lambda l: l["total"]))["total"] >= 3 and pior["etapa"] != "Outros":
        por_caso = f"{pior['por_caso']:.1f}".replace(".", ",")
        saida.append({
            "tipo": "etapa", "no": None, "titulo": pior["etapa"],
            "motivo": f"É onde mais faltou na investigação ({por_caso} lacuna(s) por caso). "
                      "Nos próximos casos, revise essa etapa antes de dar o diagnóstico.",
        })
    return saida


def _coluna(nome: str) -> str:
    """"Exame físico" → "exame_fisico": coluna sem acento, que R e planilhas leem sem susto."""
    import unicodedata

    return unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode().lower().replace(" ", "_")


async def exportar(destino: str) -> None:
    """Um caso encerrado por linha, de todos os estudantes, para a análise do TCC (RN07).

    O estudante vira um código sorteado a cada exportação: as linhas do mesmo estudante
    continuam agrupáveis, mas o código não volta ao id (nem entre duas exportações).
    Nada de texto livre — só contagens e categorias.
    """
    import csv
    import hashlib
    import secrets

    from core import db

    async with db.abrir_sessao() as s:
        feitos = encerrados(await db.historico_de_desempenho(s))
    segredo = secrets.token_hex(16)
    etapas = [e for e, _ in ETAPAS] + ["Outros"]
    with open(destino, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["estudante", "data", "ciclo", "grande_area", "especialidade", "tema", "apresentacao",
                    "acertou", "minutos_ativos", "perguntas", "inconsistencias",
                    *[f"lacunas_{_coluna(e)}" for e in etapas]])
        for c in feitos:
            w.writerow([
                hashlib.sha256(f"{segredo}:{c['usuario_id']}".encode()).hexdigest()[:10],
                c["criada_em"].date().isoformat(), c["ciclo"], c["grande_area"], c["especialidade"], c["tema"],
                "atípica" if c["tipo"] == "Relato de caso" else "típica",
                int(c["acertou"]), round(c["segundos"] / 60, 1), c["perguntas"], c["inconsistencias"],
                *[c["lacunas"].count(e) for e in etapas],
            ])
    print(f"{len(feitos)} casos encerrados exportados para {destino}.")


if __name__ == "__main__":
    import sys

    if sys.argv[1:2] == ["--exportar"]:
        import asyncio

        asyncio.run(exportar(sys.argv[2]))
        sys.exit()

    # Lacunas: a etapa pela palavra-chave; doença solta (feedback antigo) é diferencial.
    assert classificar_lacuna("Não perguntou sobre uso de substâncias ou álcool") == "Anamnese"
    assert classificar_lacuna("Não perguntou sobre exames anteriores") == "Anamnese", "a ordem importa"
    assert classificar_lacuna("Não avaliou hepatomegalia no exame físico") == "Exame físico"
    assert classificar_lacuna("Não realizou exame de fundo de olho (fundoscopia)") == "Exame físico"
    assert classificar_lacuna("Não solicitou eletrocardiograma (ECG) de emergência") == "Exames complementares"
    assert classificar_lacuna("Não investigou perfil lipídico") == "Exames complementares"
    assert classificar_lacuna("Não iniciou tratamento com hidroxocobalamina") == "Conduta"
    assert classificar_lacuna("Não considerou intoxicação por cianeto") == "Raciocínio diagnóstico"
    assert classificar_lacuna("Pericardite aguda") == "Raciocínio diagnóstico", "feedback antigo"
    assert classificar_lacuna("Não verificou rigidez articular, mãos em garra") == "Exame físico"
    assert classificar_lacuna("Não avaliou risco de suicídio") == "Anamnese"
    assert classificar_lacuna("Não fez algo indefinido") == "Outros"
    assert _coluna("Raciocínio diagnóstico") == "raciocinio_diagnostico"

    t0 = datetime(2026, 10, 1, 10, 0)
    m = lambda *minutos: [t0 + timedelta(minutes=x) for x in minutos]  # noqa: E731
    assert tempo_ativo(m(0, 2, 5)) == 300
    assert tempo_ativo(m(0, 2, 600, 603)) == 300, "a noite com a aba aberta não conta"
    assert tempo_ativo(m(0)) == 0 and tempo_ativo([]) == 0

    def caso(dia, acertou, tema="tb", esp="Infectologia", tipo="Manual MS", ciclo="clínico", lacunas=(), status="encerrada"):
        inicio = t0 + timedelta(days=dia)
        msgs = [("assistant", inicio), ("user", inicio + timedelta(minutes=2)),
                ("assistant", inicio + timedelta(minutes=3)), ("user", inicio + timedelta(minutes=6))]
        fb = {"acertou": acertou, "hipoteses_nao_consideradas": list(lacunas), "inconsistencias": []}
        return {"criada_em": inicio, "ciclo": ciclo, "status": status, "feedback": fb if status == "encerrada" else None,
                "mensagens": msgs, "grande_area": "Clínica Médica", "especialidade": esp, "tema": tema, "tipo": tipo}

    casos = [
        caso(0, False, lacunas=["Não perguntou sobre tosse", "Não perguntou sobre febre"]),
        caso(1, False, lacunas=["Não perguntou sobre perda de peso"]),
        caso(2, True, tema="has", esp="Cardiologia", tipo="PCDT"),
        caso(40, True, tema="outros:Clínica Médica:Cardiologia", esp="Cardiologia", tipo="Relato de caso"),
        caso(41, True, status="aberta"),
    ]
    importantes = [{"id": "t:has", "nome": "Hipertensão"}, {"id": "t:dm2", "nome": "Diabetes tipo 2"}]
    r = resumir(casos, importantes, {"tb": "Tuberculose", "has": "Hipertensão"}, agora=t0 + timedelta(days=42))

    k = r["kpis"]
    assert (k["casos_concluidos"], k["casos_abertos"], k["taxa_acerto"]) == (4, 1, 0.5)
    assert (k["taxa_acerto_recente"], k["taxa_acerto_anterior"]) == (1.0, 1 / 3), "últimas 4 semanas vs antes"
    assert k["minutos_por_caso"] == 6 and k["perguntas_por_caso"] == 1, "a entrega final não é pergunta"
    assert [round(e["acerto_movel"], 2) for e in r["evolucao"]] == [0, 0, 0.33, 0.5]
    assert [s["casos"] for s in r["por_semana"]] == [3, 1]
    assert [(t["nome"], t["casos"], t["acertos"]) for t in r["por_tema"]] == [
        ("Tuberculose", 2, 0), ("Hipertensão", 1, 1), (OUTROS, 1, 1)
    ]
    ciclos = resumir([caso(0, True, ciclo="internato"), caso(1, True), caso(2, True), caso(3, True, ciclo="básico")],
                     [], {}, agora=t0)["por_ciclo"]
    assert [c["nome"] for c in ciclos] == ["básico", "clínico", "internato"], "ordem do curso"
    assert r["por_especialidade"][0]["id"] == "e:Clínica Médica|Cardiologia"
    assert {a["nome"]: a["casos"] for a in r["por_apresentacao"]} == {"Típica (diretriz)": 3, "Atípica (relato de caso)": 1}
    assert r["lacunas"] == [{"etapa": "Anamnese", "total": 3, "por_caso": 0.75}]

    rec = r["recomendacoes"]
    assert [(x["tipo"], x["no"]) for x in rec] == [
        ("fragil", "t:tb"), ("nao_praticado", "t:dm2"), ("etapa", None)
    ], "TB 0/2 é frágil; HAS já praticada sai; anamnese é a etapa que mais falha"
    um_erro = resumir([caso(0, False)], importantes, {}, agora=t0)["recomendacoes"]
    assert all(x["tipo"] != "fragil" for x in um_erro), "1 erro isolado não faz tema frágil"
    vazio = resumir([], importantes, {}, agora=t0)
    assert vazio["kpis"]["taxa_acerto"] is None and vazio["evolucao"] == [] and len(vazio["recomendacoes"]) == 2
    print("OK: lacunas por etapa, tempo ativo sem pausas, KPIs, evolução, agrupamentos e recomendações.")
