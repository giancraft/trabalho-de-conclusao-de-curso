"""Revisão espaçada por tema (RF09): o que errou volta logo; o que acertou, cada vez mais tarde.

    python -m casos.revisao   # self-check, sem banco

Cada tema que o estudante já praticou (o tema da fonte sorteada, `rag/temas.py`) é um
item de revisão. O agendamento é o SM-2 (Wozniak, 1990), o algoritmo por trás do Anki, com
a nota de cada caso tirada do feedback por regra:

    5 — acertou o diagnóstico e todos os tópicos da resposta corretos;
    4 — acertou o diagnóstico, com algum tópico parcial ou incorreto;
    2 — errou o diagnóstico.

Nota ≥ 3 espaça (1 dia, 3 dias, depois intervalo × facilidade); nota < 3 recomeça em
1 dia. Não há tabela: o estado é recalculado do histórico a cada leitura, então o mesmo
histórico dá sempre a mesma agenda — e o painel nunca fica defasado.

A revisão gera casos NOVOS do tema (não repete o caso antigo): o que se treina é o
raciocínio sobre a doença, não a memória de um enunciado.
"""

from datetime import date, timedelta

FACILIDADE_INICIAL = 2.5
FACILIDADE_MINIMA = 1.3
POR_SESSAO = 3  # temas numa revisão "normal" (um caso de cada)
MAX_SESSOES = 10


def nota(feedback: dict) -> int:
    if not feedback.get("acertou"):
        return 2
    return 5 if all(a["situacao"] == "correto" for a in feedback.get("por_campo", [])) else 4


def agendar(tentativas: list[tuple[date, int]]) -> dict:
    """SM-2 sobre as tentativas de um tema [(dia, nota)], em ordem cronológica."""
    facilidade, intervalo, seguidas = FACILIDADE_INICIAL, 0, 0
    for _, q in tentativas:
        if q < 3:
            seguidas, intervalo = 0, 1
        else:
            seguidas += 1
            intervalo = 1 if seguidas == 1 else 3 if seguidas == 2 else round(intervalo * facilidade)
        facilidade = max(FACILIDADE_MINIMA, facilidade + 0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
    ultimo = tentativas[-1][0]
    return {"proxima": ultimo + timedelta(days=intervalo), "intervalo_dias": intervalo, "facilidade": facilidade}


def agenda(casos: list[dict], temas: dict[str, dict], hoje: date) -> list[dict]:
    """Um item por tema praticado. `casos`: histórico ({criada_em, status, feedback,
    tema}); `temas`: tema → {nome, especialidade, peso}. O balde "Outros relatos" fica
    fora: é um conjunto de doenças atípicas, não um tema a revisar."""
    por_tema: dict[str, list[tuple[date, int, bool]]] = {}
    for c in sorted(casos, key=lambda c: c["criada_em"]):
        if c["status"] == "encerrada" and c.get("feedback") and c.get("tema") and not c["tema"].startswith("outros:"):
            por_tema.setdefault(c["tema"], []).append(
                (c["criada_em"].date(), nota(c["feedback"]), bool(c["feedback"].get("acertou")))
            )
    itens = []
    for tema, ts in por_tema.items():
        info = temas.get(tema, {})
        estado = agendar([(d, q) for d, q, _ in ts])
        itens.append({
            "no": f"t:{tema}",
            "nome": info.get("nome", tema),
            "especialidade": info.get("especialidade", ""),
            "peso": info.get("peso", 1.0),
            "proxima": estado["proxima"],
            "intervalo_dias": estado["intervalo_dias"],
            "atraso_dias": (hoje - estado["proxima"]).days,
            "ultimo_acertou": ts[-1][2],
            "tentativas": len(ts),
            "acertos": sum(a for _, _, a in ts),
        })
    return itens


def montar(itens: list[dict]) -> dict:
    """Vencidos em ordem de prioridade (errou por último > mais atrasado > tema mais
    relevante) e as sessões prontas: normal = 3 temas, express = 1 tema."""
    vencidos = sorted(
        (i for i in itens if i["atraso_dias"] >= 0),
        key=lambda i: (i["ultimo_acertou"], -i["atraso_dias"], -i["peso"]),
    )
    proximas = sorted((i for i in itens if i["atraso_dias"] < 0), key=lambda i: (i["proxima"], -i["peso"]))
    return {
        "vencidos": vencidos,
        "sessoes_normais": [vencidos[k : k + POR_SESSAO] for k in range(0, len(vencidos), POR_SESSAO)][:MAX_SESSOES],
        "sessoes_express": [[i] for i in vencidos[:MAX_SESSOES]],
        "proximas": proximas[:20],
    }


if __name__ == "__main__":
    from datetime import datetime

    assert nota({"acertou": False}) == 2
    assert nota({"acertou": True, "por_campo": [{"situacao": "correto"}, {"situacao": "parcial"}]}) == 4
    assert nota({"acertou": True, "por_campo": [{"situacao": "correto"}]}) == 5
    assert nota({"acertou": True}) == 5, "feedback antigo, sem tópicos"

    d0 = date(2026, 11, 1)

    def dias(*notas):
        return [(d0 + timedelta(days=i), q) for i, q in enumerate(notas)]

    assert [agendar(dias(*[5] * n))["intervalo_dias"] for n in (1, 2, 3, 4)] == [1, 3, 8, 22], "espaça"
    assert agendar(dias(5, 5, 2))["intervalo_dias"] == 1, "errou: volta amanhã"
    assert agendar(dias(5, 5, 2))["facilidade"] < agendar(dias(5, 5, 5))["facilidade"], "erro baixa a facilidade"
    assert agendar(dias(2, 2, 2, 2, 2, 2))["facilidade"] == FACILIDADE_MINIMA
    assert agendar(dias(4, 4, 4))["intervalo_dias"] == round(3 * 2.5), "nota 4 mantém a facilidade"
    assert agendar(dias(5))["proxima"] == d0 + timedelta(days=1)

    hoje = date(2026, 11, 10)

    def caso(dia, tema, acertou, por_campo=()):
        return {"criada_em": datetime(2026, 11, dia, 9), "status": "encerrada", "tema": tema,
                "feedback": {"acertou": acertou, "por_campo": [{"situacao": s} for s in por_campo]}}

    casos = [
        caso(1, "tb", True), caso(8, "tb", False),               # errou no dia 8: venceu dia 9
        caso(2, "has", True), caso(5, "has", True),              # 1 → 3 dias: venceu dia 8
        caso(10, "asma", True),                                  # feito hoje: vence amanhã
        caso(8, "dengue", True), caso(9, "dengue", True, ["parcial"]),  # 3 dias: vence 12
        caso(7, "dm", True),                                     # venceu dia 8, peso maior que HAS
        caso(9, "outros:Clínica Médica:Cardiologia", False),     # balde: fora
        {**caso(9, "ic", False), "status": "aberta", "feedback": None},
    ]
    temas = {"tb": {"nome": "Tuberculose", "peso": 8}, "has": {"nome": "Hipertensão", "peso": 9},
             "dm": {"nome": "Diabetes", "peso": 10}, "asma": {"nome": "Asma", "peso": 7}}
    itens = agenda(casos, temas, hoje)
    assert {i["no"] for i in itens} == {"t:tb", "t:has", "t:asma", "t:dengue", "t:dm"}, "balde e caso aberto fora"
    r = montar(itens)
    assert [i["no"] for i in r["vencidos"]] == ["t:tb", "t:dm", "t:has"], (
        "errou primeiro; depois mais atrasado e, no empate (dia 8), o de maior peso"
    )
    assert [i["no"] for i in r["proximas"]] == ["t:asma", "t:dengue"]
    assert [[i["no"] for i in s] for s in r["sessoes_normais"]] == [["t:tb", "t:dm", "t:has"]]
    assert len(r["sessoes_express"]) == 3 and r["sessoes_express"][0][0]["no"] == "t:tb"
    tb = next(i for i in itens if i["no"] == "t:tb")
    assert (tb["tentativas"], tb["acertos"], tb["ultimo_acertou"], tb["nome"]) == (2, 1, False, "Tuberculose")
    assert montar(agenda([], {}, hoje)) == {"vencidos": [], "sessoes_normais": [], "sessoes_express": [], "proximas": []}
    print("OK: nota pelo feedback, SM-2 (espaça, erro volta amanhã), prioridade dos vencidos e sessões.")
