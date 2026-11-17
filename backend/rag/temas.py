"""Árvore de temas para montar o simulado: grande área → especialidade → tema.

    python -m rag.temas   # self-check das regras, sem banco

Como no catálogo, nada aqui usa IA generativa:
- grande área: a da especialidade (`ai.GRANDE_AREA`);
- tema: cada PCDT ou manual do MS é um tema (o título é a condição). Relato de caso entra
  no tema da primeira condição a que o `apoio.json` o liga por MeSH, se for da mesma
  especialidade; senão, no balde "Outros relatos" da especialidade.

A classificação é gravada em `fonte_referencia` pela ingestão (`grande_area`, `tema`),
e a seleção do estudante vira um filtro SQL (`resolver`) para o sorteio.
"""

from casos.ai import ESPECIALIDADES, GRANDE_AREA, GRANDES_AREAS

OUTROS = "Outros relatos (apresentações atípicas)"
CONDICOES = ("PCDT", "Manual MS")
def grande_area(r: dict) -> str:
    return GRANDE_AREA.get(r["especialidade"], "")


def classificar(docs: list[dict], ligacoes: dict) -> dict[str, tuple[str, str]]:
    """{chave: (grande área, tema)} dos documentos com especialidade.

    Duas passadas: primeiro as condições do catálogo, que são os temas; depois os
    relatos, que herdam o tema da condição ligada — um relato de TB fica junto do
    manual de TB.
    """
    docs = [r for r in docs if r["especialidade"]]
    saida, temas = {}, {}
    for r in docs:
        if r["tipo"] in CONDICOES:
            saida[r["chave"]] = (grande_area(r), r["chave"])
            temas[r["chave"]] = (*saida[r["chave"]], r["especialidade"])
    for r in docs:
        if r["chave"] in saida:
            continue
        ligado = next(
            (temas[l["chave"]] for l in ligacoes.get(r["chave"], [])
             if l["chave"] in temas and temas[l["chave"]][2] == r["especialidade"]),
            None,
        )
        if ligado:
            saida[r["chave"]] = ligado[:2]
        else:
            area = grande_area(r)
            saida[r["chave"]] = (area, f"outros:{area}:{r['especialidade']}")
    return saida


def resolver(selecao: list[str]):
    """Nós marcados → filtro SQL sobre `FonteReferencia` (OR entre eles).

    Ids: "a:<área>", "e:<área>|<especialidade>" e "t:<tema>".
    """
    from sqlalchemy import false, or_

    from models import FonteReferencia as F

    condicoes = []
    for no in selecao:
        tipo, _, valor = no.partition(":")
        if tipo == "a":
            condicoes.append(F.grande_area == valor)
        elif tipo == "e":
            area, _, esp = valor.partition("|")
            condicoes.append((F.grande_area == area) & (F.especialidade == esp))
        elif tipo == "t":
            condicoes.append(F.tema == valor)
    return or_(*condicoes) if condicoes else false()


def arvore(
    disponiveis: dict[tuple[str, str, str], int],
    respondidos: dict[tuple[str, str, str], int],
    nomes: dict[str, str],
) -> list[dict]:
    """Nós aninhados {id, nome, disponiveis, respondidos, filhos} a partir das contagens
    por (área, especialidade, tema). Áreas e especialidades na ordem do currículo; temas
    em ordem alfabética, "Outros relatos" por último. Nó sem caso disponível não aparece.
    """

    def no(id_, nome, chaves, filhos=()):
        return {
            "id": id_, "nome": nome, "filhos": list(filhos),
            "disponiveis": sum(disponiveis[k] for k in chaves),
            "respondidos": sum(respondidos.get(k, 0) for k in chaves),
        }

    def nome_tema(t: str) -> str:
        return OUTROS if t.startswith("outros:") else nomes.get(t, t)

    saida = []
    for a in GRANDES_AREAS:
        especialidades = []
        for e in ESPECIALIDADES:
            chaves = [k for k in disponiveis if k[:2] == (a, e)]
            if not chaves:
                continue
            ordem = sorted(chaves, key=lambda k: (k[2].startswith("outros:"), nome_tema(k[2]).casefold()))
            temas = [no(f"t:{k[2]}", nome_tema(k[2]), [k]) for k in ordem]
            especialidades.append(no(f"e:{a}|{e}", e, chaves, temas))
        if especialidades:
            saida.append(no(f"a:{a}", a, [k for k in disponiveis if k[0] == a], especialidades))
    return saida


if __name__ == "__main__":
    go = "Ginecologia e Obstetrícia"
    assert grande_area({"especialidade": go}) == go, "uma área só, como nas provas"
    assert grande_area({"especialidade": "Cardiologia"}) == "Clínica Médica"
    assert grande_area({"especialidade": "Urologia"}) == "Cirurgia"

    docs = [
        {"chave": "tb", "tipo": "Manual MS", "especialidade": "Infectologia", "cid10": ["A15"]},
        {"chave": "pe", "tipo": "PCDT", "especialidade": go, "cid10": ["O14"]},
        {"chave": "PMC1", "tipo": "Relato de caso", "especialidade": "Infectologia", "mesh": []},
        {"chave": "PMC2", "tipo": "Relato de caso", "especialidade": "Infectologia", "mesh": []},
        {"chave": "PMC3", "tipo": "Relato de caso", "especialidade": "Pneumologia", "mesh": []},
        {"chave": "PMC4", "tipo": "Relato de caso", "especialidade": go, "mesh": []},
        {"chave": "x", "tipo": "PCDT", "especialidade": None},
    ]
    ligacoes = {
        "PMC1": [{"chave": "PMC9"}, {"chave": "tb"}],  # a 1ª ligação é diretriz: vale a condição
        "PMC3": [{"chave": "tb"}],  # TB pulmonar em relato de pneumo: outra especialidade
        "PMC4": [{"chave": "pe"}],
    }
    c = classificar(docs, ligacoes)
    assert c["tb"] == ("Clínica Médica", "tb") and c["pe"] == (go, "pe")
    assert c["PMC1"] == ("Clínica Médica", "tb"), "relato ligado herda o tema"
    assert c["PMC2"] == ("Clínica Médica", "outros:Clínica Médica:Infectologia"), "sem ligação: outros"
    assert c["PMC3"] == ("Clínica Médica", "outros:Clínica Médica:Pneumologia"), "tema de outra área não serve"
    assert c["PMC4"] == (go, "pe")
    assert "x" not in c, "sem especialidade fica fora da árvore"

    disp = {
        ("Clínica Médica", "Infectologia", "tb"): 3,
        ("Clínica Médica", "Infectologia", "outros:Clínica Médica:Infectologia"): 5,
        ("Clínica Médica", "Cardiologia", "has"): 1,
        (go, go, "pe"): 2,
    }
    a = arvore(disp, {("Clínica Médica", "Infectologia", "tb"): 2}, {"tb": "Tuberculose", "has": "Hipertensão"})
    assert [n["id"] for n in a] == ["a:Clínica Médica", f"a:{go}"], "ordem do currículo, sem área vazia"
    cm = a[0]
    assert (cm["disponiveis"], cm["respondidos"]) == (9, 2)
    assert [e["nome"] for e in cm["filhos"]] == ["Cardiologia", "Infectologia"]
    infecto = cm["filhos"][1]
    assert infecto["id"] == "e:Clínica Médica|Infectologia"
    assert [(t["nome"], t["disponiveis"]) for t in infecto["filhos"]] == [("Tuberculose", 3), (OUTROS, 5)]
    assert arvore({}, {}, {}) == []
    print("OK: grande área, tema por ligação, balde de outros e árvore.")
