"""Catálogo da literatura brasileira — Europe PMC + PubMed Central (RF04, RN05).

    python -m rag.literatura                 # fase A: diretrizes e relatos de caso
    python -m rag.literatura --revisoes      # fase B: acrescenta as revisões
    python -m rag.literatura --check         # self-check das regras, sem rede

Recorte: artigos com autor de afiliação brasileira (`AFF:"Brazil"`), acesso aberto, texto
completo disponível e licença que permite obra derivada — gerar um caso a partir do texto
é derivação, então CC BY-ND e CC BY-NC-ND ficam de fora.

Papéis (`sorteavel`):
- relato de caso → condição sorteável, nível avançado (relato se publica por ser
  incomum: é a definição do gênero, não um palpite);
- diretriz e revisão → fonte de apoio: entram no contexto ao lado da condição sorteada,
  nunca sozinhas.

Especialidade sem IA generativa, por regra registrada em `regra`:
1. descritores MeSH marcados como tópico principal → árvore MeSH (NLM) → área
   (`_AREAS_MESH`), por maioria entre os descritores;
2. artigo ainda sem MeSH (recente demais para a indexação): palavras-chave do autor que
   casam exatamente com um descritor;
3. paciente só criança/adolescente (check tags de idade do MeSH) → Pediatria;
4. `curadoria.json` (revisão humana) sobrepõe tudo, pela chave PMCID.

O texto vem do Europe PMC (`fullTextXML`); se faltar, do PubMed Central (E-utilities
do NCBI). Os XMLs ficam em `rag/corpus/pmc/`, fora do git; `literatura.json` e
`mesh_arvore.csv` são versionados.
"""

import collections
import csv
import json
import re
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from rag.catalogo import ANOS_ATUAL, CORPUS_DIR, CURADORIA_JSON, RAIZ, _ler, salvar

LITERATURA_JSON = RAIZ / "literatura.json"
MESH_CSV = RAIZ / "mesh_arvore.csv"
PMC_DIR = CORPUS_DIR / "pmc"

EUROPE_PMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"
NCBI_EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id={}"
MESH_ARVORES = "https://nlmpubs.nlm.nih.gov/projects/mesh/2025/meshtrees/mtrees2025.bin"

_BASE = 'AFF:"Brazil" AND IN_EPMC:y AND OPEN_ACCESS:y'
# Ordem = prioridade quando um artigo cai em dois tipos (diretriz que também é revisão).
TIPOS = {
    "Diretriz": f'{_BASE} AND (PUB_TYPE:"Practice Guideline" OR PUB_TYPE:"Guideline")',
    "Relato de caso": f'{_BASE} AND PUB_TYPE:"Case Reports" AND PUB_YEAR:[2016 TO 2026]',
    "Revisão": f'{_BASE} AND PUB_TYPE:"Review" AND PUB_YEAR:[2019 TO 2026]',
}
SORTEAVEIS = {"Relato de caso"}

# Licenças que permitem derivação. A busca por LICENSE:"cc by" também casa "cc by-nd",
# então o filtro é aqui, pelo valor exato.
LICENCAS = {"cc by", "cc by-sa", "cc by-nc", "cc by-nc-sa", "cc0"}

# Prefixo da árvore MeSH → área. Para cada descritor vale a primeira linha que casa com
# alguma das suas árvores: as específicas vêm antes. A ordem resolve os cruzamentos —
# linfoma está em C04 e em C15 (Hematologia); câncer renal, em C04 e em C12.950.419
# (rim); AIDS, em C01, C12.100.937 (IST) e C20. Descritor que não casa com nenhuma linha
# (estomatognáticas, sinais e sintomas) não define área.
_AREAS_MESH = [
    ("C15", "Hematologia"),
    ("C04", "Oncologia"),
    ("C10.228.140.300", "Neurologia"),  # cerebrovasculares (também em C14)
    ("C14", "Cardiologia"),
    ("C12.100.937", "Infectologia"),  # infecções sexualmente transmissíveis
    ("C12.950.419", "Nefrologia"),  # doenças renais
    ("C12.950", "Urologia"),  # urológicas: ITU, litíase, bexiga, uretra
    ("C12.200", "Urologia"),  # urogenitais masculinas
    ("C12.100.500", "Urologia"),  # genitais masculinas
    ("C12.050", "Ginecologia e Obstetrícia"),  # femininas e complicações da gravidez
    ("C12.100.250", "Ginecologia e Obstetrícia"),  # genitais femininas
    ("C12", "Urologia"),
    ("C09", "Otorrinolaringologia"),  # antes de C08: nariz e laringe estão nas duas
    ("C08", "Pneumologia"),
    ("C06", "Gastroenterologia"),
    ("C10", "Neurologia"),
    ("C11", "Oftalmologia"),
    ("C01", "Infectologia"),
    ("C05.550", "Reumatologia"),  # doenças articulares
    ("C05.799", "Reumatologia"),  # doenças reumáticas
    ("C05", "Ortopedia e Traumatologia"),
    ("C16", "Pediatria"),  # congênitas, hereditárias, neonatais
    ("C17.300", "Reumatologia"),  # doenças do tecido conjuntivo
    ("C17", "Dermatologia"),
    ("C18", "Endocrinologia"),
    ("C19", "Endocrinologia"),
    ("C20", "Reumatologia"),  # autoimunes, imunodeficiências, hipersensibilidade
    ("C21", "Medicina de Emergência"),  # agravos ambientais
    ("C25", "Medicina de Emergência"),  # intoxicações
    ("C26", "Ortopedia e Traumatologia"),  # traumas
    ("F03", "Psiquiatria"),
]
# Veterinária fica fora: um relato de glaucoma em cão não pode virar paciente humano.
_ANIMAL = re.compile(
    r"\b(dogs?|canine|cats?|feline|equine|horses?|mares?|bovine|cattle|cows?|calf|calves|"
    r"sheep|ovine|goats?|caprine|swine|pigs?|piglets?|birds?|avian|parrots?|rabbits?|"
    r"monkeys?|primates?|snakes?|tortoises?|turtles?|bitch|veterinary|wild animals?)\b",
    re.IGNORECASE,
)
_HUMANO = re.compile(
    r"\b(patients?|child|children|infant|newborn|neonate|girl|boy|wom[ae]n|m[ae]n|"
    r"elderly|pregnan\w*|adolescent|human|paciente|criança|mulher|homem|gestante)\b",
    re.IGNORECASE,
)


def veterinario(r: dict, arvores: dict[str, list[str]]) -> bool:
    """Estudo em animal, por MeSH (sem "Humans" e com "Animals" ou uma espécie da árvore
    B01, ou doença animal da C22), revista veterinária ou — sem MeSH — título que fala
    de animal e não de paciente humano."""
    nomes = {m["descriptorName"] for m in r.get("meshHeadingList", {}).get("meshHeading", [])}
    if nomes:
        def arvore(prefixo: str) -> bool:
            return any(a.startswith(prefixo) for n in nomes for a in arvores.get(n, []))

        if arvore("C22"):
            return True
        if "Humans" in nomes:
            return False
        if "Animals" in nomes or arvore("B01"):  # "Cats" sem o check tag "Animals"
            return True
        # MeSH sem humano nem espécie: decide pela revista e pelo título, como sem MeSH.
    revista = r.get("journalInfo", {}).get("journal", {}).get("title", "")
    titulo = r.get("title", "")
    # "adult" sozinho não prova humano ("an adult cat"): por isso fica fora de _HUMANO.
    return bool(re.search(r"veterin|animal|feline|canine|equine|JFMS", revista, re.I)) or (
        bool(_ANIMAL.search(titulo)) and not _HUMANO.search(titulo)
    )


_IDADE_PEDIATRICA = {"Infant, Newborn", "Infant", "Child, Preschool", "Child", "Adolescent"}
_IDADE_ADULTA = {"Adult", "Young Adult", "Middle Aged", "Aged", "Aged, 80 and over"}


# --- regras (puras, testadas no --check) ---


def area_do_descritor(arvores: list[str]) -> str | None:
    for prefixo, area in _AREAS_MESH:
        if any(a == prefixo or a.startswith(prefixo + ".") for a in arvores):
            return area
    return None


def especialidade(principais: list[str], arvores: dict[str, list[str]], idades: set[str]) -> tuple[str | None, str]:
    """(área, regra) a partir dos descritores principais, na ordem em que vieram.

    Sinal e sintoma (árvore C23) não votam se houver doença: num relato de hanseníase
    lepromatosa, "Hoarseness" puxava a área para Otorrino. Só decidem quando são tudo
    o que o artigo tem.
    """
    def sintoma(d: str) -> bool:
        return any(a.startswith("C23") for a in arvores.get(d, []))

    doencas = [d for d in principais if not sintoma(d)]
    votantes = doencas if any(area_do_descritor(arvores.get(d, [])) for d in doencas) else principais
    areas = [a for a in (area_do_descritor(arvores.get(d, [])) for d in votantes) if a]
    if not areas:
        # Sem doença, mas o assunto é a operação (colecistectomia, lesão iatrogênica de via
        # biliar): é caso de cirurgia.
        cirurgicos = [d for d in principais if any(a.startswith("E04") for a in arvores.get(d, []))]
        if cirurgicos:
            return "Cirurgia Geral", f"MeSH de procedimento cirúrgico (E04: {', '.join(cirurgicos[:2])}) → Cirurgia Geral"
        return None, "sem descritor MeSH de doença"
    contagem = collections.Counter(areas)
    area = max(areas, key=lambda a: (contagem[a], -areas.index(a)))  # empate: o primeiro
    regra = f"MeSH → área ({', '.join(principais[:3])})"
    if idades & _IDADE_PEDIATRICA and not idades & _IDADE_ADULTA and area != "Pediatria":
        return "Pediatria", f"{regra}; paciente só pediátrico (MeSH de idade) → Pediatria"
    return area, regra


def licenca_ok(licenca: str | None) -> bool:
    return (licenca or "").lower() in LICENCAS


def indice_doencas(arvores: dict[str, list[str]]) -> dict[str, str]:
    """Rótulo em minúsculas → descritor, só para doenças (árvores C e F03).

    Também na ordem natural: o MeSH grafa "Colitis, Ulcerative", o texto diz "ulcerative
    colitis". Sem a inversão, só o "colitis" genérico casaria.
    """
    indice = {}
    for rotulo, numeros in arvores.items():
        if any(n.startswith(("C", "F03")) for n in numeros):
            indice[rotulo.lower()] = rotulo
            if rotulo.count(", ") == 1:
                cabeca, modificador = rotulo.lower().split(", ")
                indice.setdefault(f"{modificador} {cabeca}", rotulo)
    return indice


def doencas_no_texto(texto: str, indice: dict[str, str]) -> list[str]:
    """Descritores de doença citados literalmente no texto (expressões de até 5 palavras).

    As mais longas primeiro, e palavra já usada não entra de novo: em "diabetic
    retinopathy" vale a retinopatia, não um "diabetes" que puxaria a votação da área.
    """
    palavras = re.findall(r"[\w'-]+", texto.lower())
    usadas: set[int] = set()
    achados = []
    for n in range(5, 0, -1):
        for i in range(len(palavras) - n + 1):
            faixa = set(range(i, i + n))
            if not faixa & usadas and (d := indice.get(" ".join(palavras[i : i + n]))):
                usadas |= faixa
                if d not in achados:
                    achados.append(d)
    return achados


def linha(r: dict, tipo: str, arvores: dict[str, list[str]], indice: dict[str, str]) -> dict:
    """Registro do Europe PMC (resultType=core) → linha do `literatura.json`."""
    mesh = r.get("meshHeadingList", {}).get("meshHeading", [])
    principais = [m["descriptorName"] for m in mesh if m.get("majorTopic_YN") == "Y"]
    principais = principais or [m["descriptorName"] for m in mesh]
    idades = {m["descriptorName"] for m in mesh} & (_IDADE_PEDIATRICA | _IDADE_ADULTA)
    origem = "MeSH"
    if not mesh:
        # Recente demais para a indexação: palavras-chave do autor e o título, casados
        # com os rótulos de doença do MeSH — literal, sem semântica, auditável.
        chaves = [indice[k.lower()] for k in r.get("keywordList", {}).get("keyword", []) if k.lower() in indice]
        principais = list(dict.fromkeys(chaves + doencas_no_texto(r["title"], indice)))
        origem = "palavras-chave/título"
    area, regra = especialidade(principais, arvores, idades)
    if origem != "MeSH":
        regra = regra.replace("MeSH →", "palavras-chave/título → rótulo MeSH →")
    if veterinario(r, arvores):
        area, regra = None, "estudo em animal (veterinária): fora do simulador"

    ji = r.get("journalInfo", {})
    publicado = r.get("firstPublicationDate") or f"{r.get('pubYear')}-01-01"
    sorteavel = tipo in SORTEAVEIS and area is not None
    return {
        "chave": r["pmcid"],
        "tipo": tipo,
        "titulo": " ".join(r["title"].split()).rstrip("."),
        "autores": [
            {"sobrenome": a.get("lastName") or a.get("collectiveName", ""), "nome": a.get("firstName", "")}
            for a in r.get("authorList", {}).get("author", [])
        ],
        "revista": ji.get("journal", {}).get("title", ""),
        "volume": ji.get("volume", ""),
        "numero": ji.get("issue", ""),
        "paginas": r.get("pageInfo", ""),
        "ano": str(r.get("pubYear", "")),
        "publicado_em": publicado,
        "doi": r.get("doi", ""),
        "pmid": r.get("pmid", ""),
        "pmcid": r["pmcid"],
        "url": f"https://pmc.ncbi.nlm.nih.gov/articles/{r['pmcid']}/",
        "licenca": r["license"].upper(),
        "mesh": principais,
        "especialidade": area,
        "dificuldade": "avançado" if sorteavel else None,
        "sorteavel": sorteavel,
        "regra": regra + ("; relato de caso → avançado" if sorteavel else ""),
        "revisar": tipo == "Diretriz" and (date.today() - date.fromisoformat(publicado)).days > 365 * ANOS_ATUAL,
    }


# --- coleta ---


def _arvores_mesh() -> dict[str, list[str]]:
    """Descritor → números de árvore, do arquivo oficial da NLM (cache local)."""
    cache = CORPUS_DIR / "mtrees.bin"
    if not cache.exists():
        CORPUS_DIR.mkdir(exist_ok=True)
        cache.write_bytes(_ler(MESH_ARVORES))
    arvores = collections.defaultdict(list)
    for l in cache.read_text(encoding="utf-8", errors="replace").splitlines():
        if ";" in l:
            rotulo, numero = l.strip().rsplit(";", 1)
            arvores[rotulo].append(numero)
    return arvores


def _buscar(consulta: str) -> list[dict]:
    resultados, cursor = [], "*"
    while True:
        params = urllib.parse.urlencode(
            {"query": consulta, "format": "json", "resultType": "core", "pageSize": 500, "cursorMark": cursor}
        )
        pagina = json.loads(_ler(f"{EUROPE_PMC}/search?{params}"))
        resultados += pagina["resultList"]["result"]
        print(f"    {len(resultados)} / {pagina['hitCount']}", file=sys.stderr)
        proximo = pagina.get("nextCursorMark")
        if not proximo or proximo == cursor or not pagina["resultList"]["result"]:
            return resultados
        cursor = proximo


def _baixar_xml(pmcid: str) -> bool:
    """Texto completo: Europe PMC; se não houver, PubMed Central. Gravação atômica."""
    destino = PMC_DIR / f"{pmcid}.xml"
    if destino.exists():
        return True
    for url in (f"{EUROPE_PMC}/{pmcid}/fullTextXML", NCBI_EFETCH.format(pmcid)):
        try:
            xml = _ler(url)
        except OSError:  # 404 do Europe PMC: tenta o PMC
            continue
        if b"<body" in xml:  # só metadados não serve
            parcial = destino.with_suffix(".parcial")
            parcial.write_bytes(xml)
            parcial.rename(destino)
            return True
        if "ncbi" in url:
            time.sleep(0.4)  # E-utilities sem chave: até 3 requisições/s
    return False


def gerar(tipos: list[str]) -> None:
    arvores = _arvores_mesh()
    indice = indice_doencas(arvores)
    curadoria = json.loads(CURADORIA_JSON.read_text()) if CURADORIA_JSON.exists() else {}
    vistos, corpus = set(), []
    for tipo in tipos:
        print(f"  {tipo}:", file=sys.stderr)
        for r in _buscar(TIPOS[tipo]):
            if r.get("pmcid") and r["pmcid"] not in vistos and licenca_ok(r.get("license")):
                vistos.add(r["pmcid"])
                corpus.append(linha(r, tipo, arvores, indice))

    PMC_DIR.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        com_texto = dict(zip((r["chave"] for r in corpus), pool.map(_baixar_xml, (r["chave"] for r in corpus))))
    for r in corpus:
        if not com_texto[r["chave"]]:
            r["sorteavel"], r["especialidade"], r["regra"] = False, None, r["regra"] + "; sem texto completo"
        if ajuste := curadoria.get(r["chave"]):
            r.update({k: v for k, v in ajuste.items() if k in ("especialidade", "dificuldade", "revisar", "sorteavel")})
            if ajuste.get("descartar"):
                r["especialidade"], r["sorteavel"] = None, False
            r["regra"] += f"; curadoria: {ajuste.get('nota', 'ajuste manual')}"

    # Cache versionado só com os descritores usados: a banca confere a árvore de cada um.
    usados = sorted({d for r in corpus for d in r["mesh"]})
    with MESH_CSV.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["descritor", "arvores", "area"])
        w.writerows((d, "|".join(arvores[d]), area_do_descritor(arvores[d]) or "") for d in usados)

    corpus.sort(key=lambda r: (r["tipo"], r["titulo"].casefold()))
    salvar(corpus, LITERATURA_JSON)
    _relatorio(corpus)


def carregar() -> list[dict]:
    return json.loads(LITERATURA_JSON.read_text()) if LITERATURA_JSON.exists() else []


def _relatorio(corpus: list[dict]) -> None:
    from casos.ai import ESPECIALIDADES

    por_tipo = collections.Counter(r["tipo"] for r in corpus)
    print(f"{len(corpus)} artigos: " + ", ".join(f"{n} {t}" for t, n in por_tipo.items()))
    sorteaveis = [r for r in corpus if r["sorteavel"]]
    apoio = collections.Counter(r["especialidade"] for r in corpus if not r["sorteavel"] and r["especialidade"])
    area = collections.Counter(r["especialidade"] for r in sorteaveis)
    print(f"{len(sorteaveis)} sorteáveis; {sum(not r['especialidade'] for r in corpus)} sem área.\n")
    print(f"{'':32}{'sorteáv.':>9}{'apoio':>7}")
    for e in ESPECIALIDADES:
        print(f"{e:32}{area[e]:>9}{apoio[e]:>7}")


if __name__ == "__main__":
    if sys.argv[1:] == ["--check"]:
        arv = {
            "Lymphoma": ["C04.557.386", "C15.604.515.435"],
            "Kidney Neoplasms": ["C04.588.945.947.535", "C12.950.419.780"],
            "Stroke": ["C10.228.140.300.775", "C14.907.253.855"],
            "Pneumonia": ["C08.381.677", "C01.748"],
            "Pregnancy Complications": ["C12.050.703"],
            "Kidney Diseases": ["C12.950.419"],
            "Arthritis, Rheumatoid": ["C05.550.114.154", "C17.300.775.099", "C20.111.199"],
            "Fractures, Bone": ["C26.404"],
            "Acquired Immunodeficiency Syndrome": ["C01.221.812.640.400.040", "C12.100.937.640.400.040", "C20.673.480.040"],
            "Azoospermia": ["C12.100.500.430.380", "C12.200.294.430.380"],
            "Urinary Tract Infections": ["C01.915", "C12.050.351.968.892", "C12.950.892"],
            "Endometriosis": ["C12.100.250.163"],
            "Cholecystectomy": ["E04.210.120"],
            "Kounis Syndrome": ["C14.280.647.500", "C20.543.206"],
            "Syndrome": ["C23.550.288"],
            "Humans": ["B01.050.150.900.649.313.988.400.112.400.400"],
        }
        assert area_do_descritor(arv["Lymphoma"]) == "Hematologia", "C15 vence C04"
        assert area_do_descritor(arv["Kidney Neoplasms"]) == "Oncologia", "C04 vence o rim"
        assert area_do_descritor(arv["Stroke"]) == "Neurologia", "AVC é neuro"
        assert area_do_descritor(arv["Pneumonia"]) == "Pneumologia", "órgão antes de infecção"
        assert area_do_descritor(arv["Pregnancy Complications"]) == "Ginecologia e Obstetrícia"
        assert area_do_descritor(arv["Kidney Diseases"]) == "Nefrologia"
        assert area_do_descritor(arv["Arthritis, Rheumatoid"]) == "Reumatologia"
        assert area_do_descritor(arv["Humans"]) is None
        assert area_do_descritor(arv["Acquired Immunodeficiency Syndrome"]) == "Infectologia", "IST, não urologia"
        assert area_do_descritor(arv["Azoospermia"]) == "Urologia"
        assert area_do_descritor(arv["Urinary Tract Infections"]) == "Urologia"
        assert area_do_descritor(arv["Endometriosis"]) == "Ginecologia e Obstetrícia"
        assert area_do_descritor(arv["Syndrome"]) is None, "sinais e sintomas não decidem"
        assert area_do_descritor(["C05.5501"]) == "Ortopedia e Traumatologia", (
            "C05.5501 não é filho de C05.550 (articulares): o prefixo casa nó inteiro"
        )

        assert especialidade(["Pneumonia", "Stroke", "Pneumonia"], arv, set())[0] == "Pneumologia", "maioria"
        assert especialidade(["Stroke", "Pneumonia"], arv, set())[0] == "Neurologia", "empate: o primeiro"
        assert especialidade(["Humans"], arv, set()) == (None, "sem descritor MeSH de doença")
        assert especialidade(["Humans", "Cholecystectomy"], arv, set())[0] == "Cirurgia Geral", "procedimento"
        arv |= {"Leprosy, Lepromatous": ["C01.150.252.410.040.552.475"],
                "Hoarseness": ["C09.400.535.380", "C23.888.592.979.380"],
                "Hematuria": ["C12.950.385", "C23.888.942.343"]}
        assert especialidade(["Leprosy, Lepromatous", "Hoarseness", "Hoarseness"], arv, set())[0] == "Infectologia", (
            "sintoma não vota quando há doença"
        )
        assert especialidade(["Hematuria"], arv, set())[0] == "Urologia", "só sintoma: ele decide"

        arv["Colitis, Ulcerative"] = ["C06.405.205.731.500"]
        indice = indice_doencas(arv)
        assert "humans" not in indice and indice["kounis syndrome"] == "Kounis Syndrome"
        assert doencas_no_texto("Severe ulcerative colitis in pregnancy", indice) == ["Colitis, Ulcerative"], "invertido"
        assert doencas_no_texto("Kounis syndrome after a wasp sting: a case report", indice) == [
            "Kounis Syndrome"
        ], "só a expressão mais longa: o 'syndrome' dentro dela não conta de novo"
        assert especialidade(["Fractures, Bone"], arv, {"Child"})[0] == "Pediatria", "só criança"
        assert especialidade(["Fractures, Bone"], arv, {"Child", "Adult"})[0] == "Ortopedia e Traumatologia"

        assert licenca_ok("cc by") and licenca_ok("CC BY-NC") and not licenca_ok("cc by-nc-nd")
        assert not licenca_ok(None)

        r = {
            "pmcid": "PMC1", "title": "Pneumonia in a child.", "pubYear": 2021, "license": "cc by",
            "firstPublicationDate": "2021-11-29", "doi": "10.1/x", "pmid": "9",
            "authorList": {"author": [{"lastName": "Silva", "firstName": "Ana"}]},
            "journalInfo": {"volume": "85", "issue": "6", "journal": {"title": "Arquivos de Teste"}},
            "pageInfo": "1-5",
            "meshHeadingList": {"meshHeading": [
                {"descriptorName": "Pneumonia", "majorTopic_YN": "Y"},
                {"descriptorName": "Child", "majorTopic_YN": "N"},
            ]},
        }
        l = linha(r, "Relato de caso", arv, indice)
        assert (l["especialidade"], l["dificuldade"], l["sorteavel"]) == ("Pediatria", "avançado", True)
        assert l["titulo"] == "Pneumonia in a child" and l["autores"] == [{"sobrenome": "Silva", "nome": "Ana"}]
        assert l["url"] == "https://pmc.ncbi.nlm.nih.gov/articles/PMC1/"
        sem_mesh = {**r, "meshHeadingList": {}, "keywordList": {"keyword": ["stroke", "Case Report"]}}
        assert linha(sem_mesh, "Relato de caso", arv, indice)["especialidade"] == "Neurologia", "palavra-chave"
        pelo_titulo = {**r, "meshHeadingList": {}, "title": "Kounis syndrome after a wasp sting"}
        assert linha(pelo_titulo, "Relato de caso", arv, indice)["especialidade"] == "Cardiologia", "título"
        assert not linha(r, "Diretriz", arv, indice)["sorteavel"], "diretriz é apoio, não condição"

        # Veterinária fora, por MeSH, por árvore C22, por revista ou pelo título.
        arv["Dog Diseases"] = ["C22.268"]
        cao = {**r, "meshHeadingList": {"meshHeading": [
            {"descriptorName": "Glaucoma", "majorTopic_YN": "Y"}, {"descriptorName": "Animals", "majorTopic_YN": "N"}]}}
        assert veterinario(cao, arv), "Animals sem Humans"
        assert not veterinario({**cao, "meshHeadingList": {"meshHeading": [
            {"descriptorName": "Animals"}, {"descriptorName": "Humans"}]}}, arv), "zoonose em humano fica"
        assert veterinario({**r, "meshHeadingList": {"meshHeading": [{"descriptorName": "Dog Diseases"}]}}, arv)
        arv["Cats"] = ["B01.050.150.900.649.313.750.250.216.200"]
        assert veterinario({**r, "meshHeadingList": {"meshHeading": [{"descriptorName": "Kernicterus"},
                                                                     {"descriptorName": "Cats"}]}}, arv), "espécie sem Animals"
        assert veterinario({**r, "meshHeadingList": {}, "title": "Ocular melanoma in a dog"}, arv)
        assert not veterinario({**r, "meshHeadingList": {}, "title": "Dog bite injury in a child"}, arv)
        assert veterinario({**r, "meshHeadingList": {}, "title": "Kernicterus in an adult cat"}, arv), "adult ≠ humano"
        assert veterinario({**r, "meshHeadingList": {"meshHeading": [{"descriptorName": "COVID-19"}]},
                            "title": "Lethal SARS-CoV-2 variant infection in a cat"}, arv), "MeSH sem humano nem espécie"
        assert veterinario({**r, "meshHeadingList": {}, "title": "Otitis", "journalInfo": {"journal": {"title": "Open Veterinary Journal"}}}, arv)
        l = linha({**r, "meshHeadingList": {}, "title": "Pneumonia in a horse"}, "Relato de caso", arv, indice)
        assert (l["especialidade"], l["sorteavel"]) == (None, False)
        print("OK: MeSH → área, maioria/empate, idade pediátrica, licença e linha do catálogo.")
    else:
        gerar(list(TIPOS) if "--revisoes" in sys.argv else ["Diretriz", "Relato de caso"])
