"""Fontes de apoio — qual PCDT ou diretriz acompanha cada condição sorteável (RF04).

    python -m rag.apoio          # gera apoio.json a partir de corpus.json e literatura.json
    python -m rag.apoio --check  # self-check das regras, sem rede

A ligação é por conceito, exata e registrada — nunca por semelhança de texto. Medido no
corpus: o kNN do título contra os trechos ligava febre maculosa à doença de Chagas e
Paget à linha de cuidado do infarto (distância menor que a de pares corretos); nenhum
limiar separava o certo do errado. Diretriz errada no prompt é pior que nenhuma.

Regra: condição e apoio se ligam quando compartilham um descritor MeSH de doença (árvores
C/F03, menos a C23 de sinais e sintomas), ou quando o do apoio é o pai direto do da
condição — "Epilepsy, Reflex" → diretriz de "Epilepsy". O descritor que liga precisa ser
específico (3+ níveis na árvore): "Skin Diseases" em comum não faz de uma diretriz de
dermatologia o apoio de qualquer lesão de pele. Medido na primeira versão, com 2 níveis
e sem esse piso: vasculite ligava à diretriz de cardiologia nuclear. Os descritores:
- artigo: os MeSH principais do Europe PMC (`literatura.json`);
- PCDT: as CIDs da seção 2 → título oficial em inglês da CID-10-CM (CMS, domínio
  público) → rótulos MeSH citados literalmente no título ("E22.0 Acromegaly and
  pituitary gigantism" → Acromegaly, Gigantism). Só vale se os rótulos cobrirem mais da
  metade das palavras do título ("Monocytic leukemia" → só "Leukemia" é metade: não): "Liver cell carcinoma" casaria só "Carcinoma" e ligaria
  o PCDT de hepatocarcinoma a todo carcinoma — melhor nenhum descritor.
Do lado do relato, só ligam os descritores da área em que ele foi classificado: um relato
de endometriose operada na pandemia tem "COVID-19" no MeSH, mas o apoio que interessa é
o PCDT de Endometriose, não a diretriz de COVID.

Sem ligação exata, sem apoio. A ordem segue a autoridade: PCDT antes de diretriz.
"""

import io
import json
import re
import sys
import zipfile

from rag import catalogo, literatura
from rag.catalogo import CORPUS_DIR, RAIZ, _ler

APOIO_JSON = RAIZ / "apoio.json"
CID10CM = "https://www.cms.gov/files/zip/2026-code-descriptions-tabular-order.zip"
NIVEIS = 1  # o apoio pode ser o pai direto do descritor da condição, não o avô
PROFUNDIDADE = 3  # níveis mínimos do descritor que liga: C14 e C14.907 são amplos demais
MAX_APOIO = 2
PRIORIDADE = {"PCDT": 0, "Manual MS": 0, "Diretriz": 1}
COBERTURA = 0.5  # fração mínima das palavras do título da CID explicada pelos rótulos MeSH
_VAZIAS = {"and", "or", "of", "with", "without", "in", "the", "a", "an", "to", "due", "other",
           "unspecified", "specified", "type", "not", "elsewhere", "classified", "by", "as", "on"}


def titulos_cid() -> dict[str, str]:
    """Código CID-10 sem ponto → título em inglês (arquivo de ordem da CID-10-CM)."""
    cache = CORPUS_DIR / "icd10cm_order.txt"
    if not cache.exists():
        pacote = zipfile.ZipFile(io.BytesIO(_ler(CID10CM)))
        nome = next(n for n in pacote.namelist() if n.startswith("icd10cm_order_") and "addenda" not in n)
        cache.write_bytes(pacote.read(nome))
    # "04567 E220    1 Acromegaly and pituitary gigantism    Acromegaly and ..."
    return {l[6:13].strip(): l[16:77].strip() for l in cache.read_text(errors="replace").splitlines() if len(l) > 16}


def doencas(nomes: list[str], arvores: dict[str, list[str]]) -> list[str]:
    """Só os descritores de doença: "Humans", "Brazil" ou "Inflammation" (C23, sinais e
    sintomas) em comum não ligam nada."""
    return [
        n for n in nomes
        if any(a.startswith(("C", "F03")) and not a.startswith("C23") for a in arvores.get(n, []))
    ]


def _palavras(texto: str) -> set[str]:
    return {p for p in re.findall(r"[a-z0-9'-]+", texto.lower()) if p not in _VAZIAS}


def mesh_do_titulo(titulo: str, indice: dict[str, str]) -> list[str]:
    """Rótulos MeSH do título da CID, se juntos cobrirem COBERTURA das palavras dele."""
    achados = literatura.doencas_no_texto(titulo, indice)
    conteudo = _palavras(titulo)
    cobertas = conteudo & set().union(*(_palavras(d) for d in achados)) if achados else set()
    return achados if conteudo and len(cobertas) / len(conteudo) > COBERTURA else []


def da_area(descritores: list[str], arvores: dict[str, list[str]]) -> list[str]:
    """Os descritores da área que a classificação escolheu (antes do ajuste de Pediatria,
    que muda a área sem mudar o assunto)."""
    area, _ = literatura.especialidade(descritores, arvores, set())
    return [d for d in descritores if literatura.area_do_descritor(arvores.get(d, [])) == area]


def mesh_do_pcdt(cids: list[str], titulos: dict[str, str], indice: dict[str, str]) -> list[str]:
    achados = []
    for cid in cids:
        codigo = cid.replace(".", "")
        for c in (codigo, codigo[:3]):  # o código e a categoria: "E220" e "E22"
            for d in mesh_do_titulo(titulos.get(c, ""), indice):
                if d not in achados:
                    achados.append(d)
    return achados


def relacao(condicao: list[str], apoio: list[str], arvores: dict[str, list[str]]) -> str | None:
    """Motivo da ligação ("Epilepsy, Reflex ⊂ Epilepsy"), ou None se não há."""
    def especifico(d: str) -> bool:
        return any(t.count(".") + 1 >= PROFUNDIDADE for t in arvores.get(d, []))

    for a in condicao:
        for b in apoio:
            if not especifico(b):
                continue
            if a == b:
                return a
            for ta in arvores.get(a, []):
                for tb in arvores.get(b, []):
                    extra = ta.count(".") - tb.count(".")
                    if tb.count(".") + 1 >= PROFUNDIDADE and 0 < extra <= NIVEIS and ta.startswith(tb + "."):
                        return f"{a} ⊂ {b}"
    return None


def ligar(condicoes: list[dict], apoios: list[dict], arvores: dict[str, list[str]]) -> dict:
    """{chave da condição: [{chave, tipo, titulo, motivo}]}, só para quem tem apoio."""
    ligacoes = {}
    for c in condicoes:
        achados = []
        for ap in apoios:
            if ap["chave"] != c["chave"] and (motivo := relacao(c["mesh"], ap["mesh"], arvores)):
                achados.append((PRIORIDADE[ap["tipo"]], -int(ap["ano"] or 0), ap, motivo))
        achados.sort(key=lambda x: x[:2])  # autoridade, depois o mais recente
        if achados:
            ligacoes[c["chave"]] = [
                {"chave": ap["chave"], "tipo": ap["tipo"], "titulo": ap["titulo"], "motivo": m}
                for _, _, ap, m in achados[:MAX_APOIO]
            ]
    return ligacoes


def gerar() -> None:
    arvores = literatura._arvores_mesh()
    indice = literatura.indice_doencas(arvores)
    titulos = titulos_cid()
    pcdt = [
        {"chave": r["chave"], "tipo": r["tipo"], "titulo": r["titulo"], "ano": (r["publicado_em"] or "0")[:4],
         "mesh": mesh_do_pcdt(r["cid10"], titulos, indice)}
        for r in catalogo.carregar() if r["especialidade"] and r["dificuldade"]
    ]
    artigos = [
        {**r, "mesh": da_area(doencas(r["mesh"], arvores), arvores)}
        for r in literatura.carregar() if r["especialidade"]
    ]
    condicoes = pcdt + [r for r in artigos if r["sorteavel"]]
    apoios = pcdt + [r for r in artigos if r["tipo"] == "Diretriz"]
    ligacoes = ligar(condicoes, apoios, arvores)
    APOIO_JSON.write_text(
        "{\n" + ",\n".join(f"{json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}" for k, v in sorted(ligacoes.items())) + "\n}\n"
    )
    com_mesh = sum(bool(p["mesh"]) for p in pcdt)
    print(f"PCDT com descritor MeSH via CID: {com_mesh}/{len(pcdt)}")
    print(f"{len(ligacoes)} de {len(condicoes)} condições com apoio "
          f"({sum(len(v) for v in ligacoes.values())} ligações).")


def carregar() -> dict:
    return json.loads(APOIO_JSON.read_text()) if APOIO_JSON.exists() else {}


if __name__ == "__main__":
    if sys.argv[1:] != ["--check"]:
        gerar()
        sys.exit()

    arv = {
        "Epilepsy": ["C10.228.140.490"],
        "Epilepsy, Reflex": ["C10.228.140.490.400"],
        "Brain Diseases": ["C10.228.140"],
        "Nervous System Diseases": ["C10"],
        "Skin Diseases": ["C17.800"],
        "Inflammation": ["C23.550.470"],
        "Acromegaly": ["C05.116.099.343.110", "C19.700.355.179"],
        "Humans": ["B01.050"],
        "Syphilis": ["C01.150.252.400.840.500"],
        "Gigantism": ["C19.700.355.179.500"],
        "Carcinoma": ["C04.557.470.200"],
        "Colitis, Ulcerative": ["C06.405.205.731.500"],
    }
    assert relacao(["Epilepsy, Reflex"], ["Epilepsy"], arv) == "Epilepsy, Reflex ⊂ Epilepsy", "um nível acima"
    assert relacao(["Epilepsy"], ["Epilepsy"], arv) == "Epilepsy", "idêntico"
    assert relacao(["Epilepsy, Reflex"], ["Brain Diseases"], arv) is None, "avô não liga, só o pai"
    assert relacao(["Epilepsy"], ["Brain Diseases"], arv) == "Epilepsy ⊂ Brain Diseases", "pai de 3 níveis liga"
    assert relacao(["Epilepsy, Reflex"], ["Nervous System Diseases"], arv) is None, "genérico demais: não liga"
    assert relacao(["Skin Diseases"], ["Skin Diseases"], arv) is None, "nem idêntico, se amplo (2 níveis)"
    assert relacao(["Epilepsy"], ["Epilepsy, Reflex"], arv) is None, "apoio mais específico que a condição: não"
    assert relacao(["Syphilis"], ["Epilepsy"], arv) is None
    assert doencas(["Humans", "Epilepsy", "Brazil", "Inflammation"], arv) == ["Epilepsy"], "C23 fora"
    arv |= {"Endometriosis": ["C12.100.250.163"], "COVID-19": ["C01.925.705.500", "C08.730.730"]}
    assert da_area(["Endometriosis", "COVID-19"], arv) == ["Endometriosis"], "só a área do caso liga"

    titulos = {"E220": "Acromegaly and pituitary gigantism", "E22": "Hyperfunction of pituitary gland"}
    indice = literatura.indice_doencas(arv)
    assert mesh_do_pcdt(["E22.0"], titulos, indice) == ["Acromegaly", "Gigantism"]
    assert mesh_do_titulo("Liver cell carcinoma", indice) == [], "só 'carcinoma' de 3 palavras: não"
    assert mesh_do_titulo("Ulcerative colitis, unspecified", indice) == ["Colitis, Ulcerative"]
    arv["Leukemia"] = ["C04.557.337"]
    indice = literatura.indice_doencas(arv)
    assert mesh_do_titulo("Monocytic leukemia", indice) == [], "metade exata não basta"
    assert mesh_do_pcdt(["Z99"], titulos, indice) == []

    condicoes = [{"chave": "PMC1", "mesh": ["Epilepsy, Reflex"]}, {"chave": "PMC2", "mesh": ["Syphilis"]}]
    apoios = [
        {"chave": "PMC9", "tipo": "Diretriz", "titulo": "Diretriz de epilepsia", "ano": "2025", "mesh": ["Epilepsy"]},
        {"chave": "epilepsia", "tipo": "PCDT", "titulo": "Epilepsia", "ano": "2018", "mesh": ["Epilepsy"]},
    ]
    lig = ligar(condicoes, apoios, arv)
    assert list(lig) == ["PMC1"], "sífilis sem apoio exato fica sem apoio"
    assert [a["chave"] for a in lig["PMC1"]] == ["epilepsia", "PMC9"], "PCDT antes da diretriz"
    assert lig["PMC1"][0]["motivo"] == "Epilepsy, Reflex ⊂ Epilepsy"
    assert "epilepsia" not in ligar([{"chave": "epilepsia", "mesh": ["Epilepsy"]}], apoios[1:], arv), "não se apoia em si"
    print("OK: relação por descritor (idêntico ou pai direto, específico), MeSH do PCDT via CID com cobertura e ordem de autoridade.")
