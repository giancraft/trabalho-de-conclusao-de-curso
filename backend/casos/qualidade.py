"""Desempenho e qualidade da IA, medidos por regra (RNF02, RNF05) — o painel do admin.

    python -m casos.qualidade   # self-check, sem banco

Complementa o acerto@5 do RAG (`rag/avaliacao.py`, a recuperação) olhando a saída:
- citações: o feedback cita as fontes [n]? cada [n] aponta para uma fonte que de fato foi
  ao prompt da avaliação? os passos da conduta vêm referenciados?
- aderência ao sorteio (RN01): o diagnóstico do gabarito é a condição da fonte sorteada?
- formato: feedbacks antigos, de antes das lacunas virarem ações.

E o desempenho, sobre a telemetria (`chamada_ia`): latência p50/p95, tokens e custo por
etapa e por caso, erros e segundas tentativas.

Sem LLM: o mesmo banco dá sempre os mesmos números, e a banca pode refazer a conta.
"""

import re
import statistics
import unicodedata

_CITACAO = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
_ACAO = re.compile(r"\s*(n[ãa]o|faltou|deixou)\b", re.IGNORECASE)
# Palavras de título de protocolo que não dizem qual é a doença.
_GENERICAS = {
    "linha", "cuidado", "protocolo", "clinico", "diretrizes", "diretriz", "terapeuticas", "manejo",
    "tratamento", "doenca", "adulto", "adultos", "criancas", "adolescentes", "pediatria", "uso",
    "infeccao", "sindrome", "agudo", "aguda", "cronica", "cronico", "primaria", "tipo",
}


def _palavras(texto: str) -> set[str]:
    """Radicais (6 letras) das palavras que identificam a doença: "Diabete Melito" e
    "Diabetes mellitus" dão o mesmo conjunto."""
    limpo = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    return {p[:6] for p in re.findall(r"[a-z0-9]{4,}", limpo) if p not in _GENERICAS}


def aderente(diagnostico: str, titulo_fonte: str) -> bool:
    """O diagnóstico do gabarito nomeia a condição da fonte sorteada?"""
    return bool(_palavras(diagnostico) & _palavras(titulo_fonte))


def _citacoes(texto: str) -> list[int]:
    return [int(n) for grupo in _CITACAO.findall(texto) for n in grupo.split(",")]


def _textos(fb: dict) -> list[str]:
    return [*fb.get("acertos", []), *fb.get("inconsistencias", []), *fb.get("hipoteses_nao_consideradas", []),
            fb.get("justificativa_pedagogica", ""), *fb.get("conduta_referencia", []),
            *[a["comentario"] for a in fb.get("por_campo", [])]]


def _pct(parte: int, todo: int) -> float | None:
    return parte / todo if todo else None


def avaliar(casos: list[dict]) -> dict:
    """`casos`: [{feedback, gabarito, ciclo, tipo, titulo_fonte, fontes_feedback: set[int]}]
    dos casos encerrados. `tipo`/`titulo_fonte` vazios em caso sem fonte (anterior ao RAG)."""
    com_feedback = [c for c in casos if c.get("feedback")]
    citacoes = [(c, _citacoes(" ".join(_textos(c["feedback"])))) for c in com_feedback]
    todas = [(n, c["fontes_feedback"]) for c, ns in citacoes for n in ns]
    passos = [
        p for c in com_feedback if c["ciclo"] != "básico" for p in c["feedback"].get("conduta_referencia", [])
    ]
    # Relato de caso tem título de artigo (em inglês), não o nome da condição: fica fora.
    condicoes = [c for c in casos if c.get("tipo") in ("PCDT", "Manual MS")]
    nao_aderentes = [
        {"diagnostico": c["gabarito"].get("diagnostico", ""), "fonte": c["titulo_fonte"]}
        for c in condicoes if not aderente(c["gabarito"].get("diagnostico", ""), c["titulo_fonte"])
    ]
    return {
        "feedbacks": len(com_feedback),
        "feedbacks_com_citacao": _pct(sum(bool(ns) for _, ns in citacoes), len(com_feedback)),
        "citacoes_por_feedback": statistics.mean(len(ns) for _, ns in citacoes) if citacoes else None,
        "citacoes_validas": _pct(sum(n in fontes for n, fontes in todas), len(todas)),
        "conduta_com_citacao": _pct(sum(bool(_citacoes(p)) for p in passos), len(passos)),
        "casos_com_fonte": len(condicoes),
        "aderencia_ao_sorteio": _pct(len(condicoes) - len(nao_aderentes), len(condicoes)),
        "nao_aderentes": nao_aderentes[:10],
        "feedbacks_formato_antigo": sum(
            any(not _ACAO.match(l) for l in c["feedback"].get("hipoteses_nao_consideradas", []))
            for c in com_feedback
        ),
    }


def _percentil(valores: list[float], p: float) -> float:
    """Percentil por interpolação linear (p em 0–1)."""
    v = sorted(valores)
    i = (len(v) - 1) * p
    baixo = int(i)
    return v[baixo] + (v[min(baixo + 1, len(v) - 1)] - v[baixo]) * (i - baixo)


def desempenho(chamadas: list[dict]) -> dict:
    """`chamadas`: linhas de `chamada_ia` como dicts. Custo por caso soma todas as etapas do
    caso (geração, cada turno do chat, feedback); chamadas sem caso (falha na geração)
    entram no total, não no por caso."""
    n = len(chamadas)
    custo_total = sum(c["custo"] or 0 for c in chamadas)
    casos = {c["caso_id"] for c in chamadas if c["caso_id"]}
    por_etapa = []
    for etapa in ("caso", "pedidos", "chat", "feedback"):
        cs = [c for c in chamadas if c["etapa"] == etapa]
        if not cs:
            continue
        lat = [c["latencia_ms"] for c in cs if c["ok"]] or [0]
        entrada = sum(c["tokens_entrada"] for c in cs)
        por_etapa.append({
            "etapa": etapa,
            "chamadas": len(cs),
            "latencia_p50_ms": _percentil(lat, 0.5),
            "latencia_p95_ms": _percentil(lat, 0.95),
            "tokens_entrada_medio": entrada / len(cs),
            "tokens_saida_medio": sum(c["tokens_saida"] for c in cs) / len(cs),
            "cache": _pct(sum(c["tokens_cache"] for c in cs), entrada),
            "custo_medio": sum(c["custo"] or 0 for c in cs) / len(cs),
        })
    dias = {}
    for c in chamadas:
        d = dias.setdefault(c["criada_em"].date(), {"dia": c["criada_em"].date(), "chamadas": 0, "custo": 0.0})
        d["chamadas"] += 1
        d["custo"] += c["custo"] or 0
    return {
        "chamadas": n,
        "taxa_erro": _pct(sum(not c["ok"] for c in chamadas), n),
        "segunda_tentativa": _pct(sum(c["tentativas"] > 1 for c in chamadas), n),
        "custo_total": custo_total,
        "casos": len(casos),
        "custo_por_caso": sum(c["custo"] or 0 for c in chamadas if c["caso_id"]) / len(casos) if casos else None,
        "por_etapa": por_etapa,
        "por_dia": [dias[d] for d in sorted(dias)],
    }


if __name__ == "__main__":
    from datetime import datetime

    assert _percentil([100, 200, 300, 400, 500], 0.5) == 300
    assert _percentil([100, 200], 0.95) == 195 and _percentil([7], 0.95) == 7
    dia = datetime(2026, 10, 28, 10)

    def chamada(etapa, caso, ms, custo=0.001, ok=True, tentativas=1):
        return {"etapa": etapa, "caso_id": caso, "latencia_ms": ms, "tokens_entrada": 1000, "tokens_cache": 500,
                "tokens_saida": 200, "custo": custo, "ok": ok, "tentativas": tentativas, "criada_em": dia}

    d = desempenho([chamada("caso", "a", 4000), chamada("chat", "a", 1000), chamada("chat", "a", 3000, tentativas=2),
                    chamada("feedback", "a", 6000), chamada("caso", None, 9000, custo=None, ok=False)])
    assert (d["chamadas"], d["casos"], d["taxa_erro"], d["segunda_tentativa"]) == (5, 1, 0.2, 0.2)
    assert abs(d["custo_por_caso"] - 0.004) < 1e-9 and abs(d["custo_total"] - 0.004) < 1e-9
    caso = d["por_etapa"][0]
    assert caso["etapa"] == "caso" and caso["latencia_p50_ms"] == 4000, "falha não entra na latência"
    assert [e["etapa"] for e in d["por_etapa"]] == ["caso", "chat", "feedback"] and d["por_etapa"][1]["cache"] == 0.5
    assert d["por_dia"] == [{"dia": dia.date(), "chamadas": 5, "custo": 0.004}] or abs(d["por_dia"][0]["custo"] - 0.004) < 1e-9
    assert desempenho([])["custo_por_caso"] is None

    assert aderente("Diabetes mellitus tipo 2", "Diabete Melito Tipo 2"), "grafias diferentes"
    assert aderente("Infarto agudo do miocárdio com supra de ST",
                    "Linha de Cuidado do Infarto Agudo do Miocárdio e o Protocolo de Síndromes Coronarianas")
    assert aderente("Tuberculose pulmonar", "Tuberculose")
    assert not aderente("Pneumonia comunitária", "Tuberculose")
    assert not aderente("Síndrome aguda", "Doença crônica do adulto"), "palavras genéricas não contam"
    assert _citacoes("Febre [1] e tosse [1, 2]. Ano 2024.") == [1, 1, 2]

    fb = {"acertos": ["Pediu ECG [1]"], "inconsistencias": [], "justificativa_pedagogica": "A IC [2] [3]",
          "hipoteses_nao_consideradas": ["Não perguntou sobre dispneia"], "conduta_referencia": ["IECA [1]", "Diurético"]}
    antigo = {**fb, "hipoteses_nao_consideradas": ["Pericardite"], "conduta_referencia": []}
    casos = [
        {"feedback": fb, "gabarito": {"diagnostico": "Insuficiência cardíaca"}, "ciclo": "clínico",
         "tipo": "PCDT", "titulo_fonte": "Insuficiência Cardíaca com Fração de Ejeção Reduzida", "fontes_feedback": {1, 2}},
        {"feedback": antigo, "gabarito": {"diagnostico": "Pneumonia"}, "ciclo": "básico",
         "tipo": "PCDT", "titulo_fonte": "Asma", "fontes_feedback": {1, 2}},
        {"feedback": {**fb, "acertos": [], "justificativa_pedagogica": "", "conduta_referencia": []},
         "gabarito": {"diagnostico": "x"}, "ciclo": "básico", "tipo": "Relato de caso", "titulo_fonte": "A case", "fontes_feedback": set()},
    ]
    r = avaliar(casos)
    assert r["feedbacks"] == 3 and r["feedbacks_com_citacao"] == 2 / 3
    assert r["citacoes_validas"] == 5 / 7, "[3] não estava no prompt da avaliação"
    assert r["conduta_com_citacao"] == 0.5, "só ciclo clínico/internato: 'IECA [1]' sim, 'Diurético' não"
    assert (r["casos_com_fonte"], r["aderencia_ao_sorteio"]) == (2, 0.5), "relato fica fora"
    assert r["nao_aderentes"] == [{"diagnostico": "Pneumonia", "fonte": "Asma"}]
    assert r["feedbacks_formato_antigo"] == 1
    assert avaliar([])["feedbacks_com_citacao"] is None
    print("OK: citações, aderência ao sorteio, formato antigo, percentis e desempenho por etapa/caso/dia.")
