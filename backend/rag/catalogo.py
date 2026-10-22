"""Catálogo do corpus brasileiro — PCDT do Ministério da Saúde (RF04, RN05).

    python -m rag.catalogo          # baixa os PDFs que faltam e regera o corpus.json
    python -m rag.catalogo --check  # self-check das regras, sem rede

Fonte: os Protocolos Clínicos e Diretrizes Terapêuticas vigentes, listados de A a Z em
gov.br/saude. São portarias — atos oficiais, sem proteção autoral (Lei 9.610/98, art.
8º, IV) — e o próprio portal só publica a versão em vigor.

Nada aqui usa IA generativa. Cada linha do `corpus.json` diz qual regra a decidiu:
- especialidade: tabela CID-10 → área (`_AREAS`), pela primeira CID do PCDT (a principal);
- dificuldade: CID na lista de Condições Sensíveis à Atenção Primária (Portaria SAS/MS
  221/2008) → básico; senão, internações/ano no SIH/SUS acima da mediana do corpus →
  intermediário, abaixo → avançado (dados em `prevalencia_sih.csv`, `rag.prevalencia`);
- `curadoria.json` (revisão humana, RN05) sobrepõe qualquer regra.

PCDT sem CID (diretrizes de assistência, linhas de cuidado) ficam sem especialidade e
fora da ingestão até a curadoria decidir. Portaria com mais de 10 anos ou sem data
legível ganha `revisar: true`.
"""

import collections
import http.client
import json
import re
import statistics
import string
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from rag.prevalencia import carregar_icsap, carregar_prevalencia, dentro

RAIZ = Path(__file__).resolve().parent
CORPUS_JSON = RAIZ / "corpus.json"
CURADORIA_JSON = RAIZ / "curadoria.json"
CORPUS_DIR = RAIZ / "corpus"

LISTA = "https://www.gov.br/saude/pt-br/assuntos/pcdt/{letra}"
ORGAO = "Ministério da Saúde"
LICENCA = "Ato oficial — sem proteção autoral (Lei 9.610/98, art. 8º, IV)"
ANOS_ATUAL = 10

# Faixas de categoria CID-10 → área. A primeira que casa vence: as específicas vêm antes
# das do capítulo inteiro. None = fora do simulador (ex.: cavidade oral).
_AREAS = [
    ("I26", "I28", "Pneumologia"),  # TEP, hipertensão pulmonar
    ("I60", "I69", "Neurologia"),  # doenças cerebrovasculares
    ("I70", "I79", "Cirurgia Geral"),  # aorta e artérias (vascular)
    ("I83", "I89", "Cirurgia Geral"),  # varizes, hemorroidas
    ("I00", "I99", "Cardiologia"),
    ("A00", "B99", "Infectologia"),
    ("C81", "C96", "Hematologia"),  # linfomas, leucemias, mieloma
    ("D45", "D47", "Hematologia"),  # mieloproliferativas
    ("C00", "D48", "Oncologia"),
    ("D86", "D86", "Pneumologia"),  # sarcoidose
    ("D80", "D89", "Reumatologia"),  # imunodeficiências e doenças imunes
    ("D50", "D89", "Hematologia"),
    ("E84", "E84", "Pneumologia"),  # fibrose cística
    ("E78", "E78", "Endocrinologia"),  # dislipidemias
    ("E83", "E83", "Gastroenterologia"),  # Wilson, hemocromatose
    ("E86", "E87", "Nefrologia"),  # volume e eletrólitos
    ("E70", "E90", "Pediatria"),  # erros inatos do metabolismo
    ("E00", "E90", "Endocrinologia"),
    ("F00", "F03", "Geriatria"),  # demências
    ("F00", "F99", "Psiquiatria"),
    ("G30", "G30", "Geriatria"),  # Alzheimer
    ("G00", "G99", "Neurologia"),
    ("H00", "H59", "Oftalmologia"),
    ("H60", "H95", "Otorrinolaringologia"),
    ("J00", "J06", "Otorrinolaringologia"),  # vias aéreas superiores
    ("J30", "J39", "Otorrinolaringologia"),
    ("J00", "J99", "Pneumologia"),
    ("K00", "K14", None),  # cavidade oral: odontologia
    ("K35", "K46", "Cirurgia Geral"),  # apendicite, hérnias
    ("K56", "K56", "Cirurgia Geral"),  # obstrução intestinal
    ("K80", "K81", "Cirurgia Geral"),  # colelitíase, colecistite
    ("K00", "K93", "Gastroenterologia"),
    ("L00", "L99", "Dermatologia"),
    ("M20", "M25", "Ortopedia e Traumatologia"),
    ("M40", "M54", "Ortopedia e Traumatologia"),  # dorsopatias
    ("M84", "M94", "Ortopedia e Traumatologia"),
    ("M00", "M99", "Reumatologia"),
    ("N20", "N23", "Urologia"),  # litíase
    ("N30", "N51", "Urologia"),  # bexiga, uretra, próstata, genital masculino
    ("N00", "N29", "Nefrologia"),
    ("N60", "N98", "Ginecologia e Obstetrícia"),
    ("O00", "O99", "Ginecologia e Obstetrícia"),
    ("P00", "Q99", "Pediatria"),  # perinatais e congênitas
    ("S06", "S06", "Medicina de Emergência"),  # TCE
    ("S00", "T14", "Ortopedia e Traumatologia"),
    ("T15", "T98", "Medicina de Emergência"),  # queimaduras, intoxicações, envenenamentos
    ("V01", "Y98", "Medicina de Emergência"),
    ("U00", "U99", "Infectologia"),
    ("Z21", "Z21", "Infectologia"),
    ("Z30", "Z39", "Ginecologia e Obstetrícia"),
]

_MESES = {m: i for i, m in enumerate(
    "JANEIRO FEVEREIRO MARÇO ABRIL MAIO JUNHO JULHO AGOSTO SETEMBRO OUTUBRO NOVEMBRO DEZEMBRO".split(), 1
)}
_PORTARIA = re.compile(
    r"(PORTARIA[A-Z/ ]*?N[º°O.]*\s*[\d.]+)\s*,?\s*DE\s+(\d{1,2})[º°O]?\s+DE\s+([A-ZÇ]+)\s+DE\s+(\d{4})"
)
_CID = re.compile(r"\b([A-TV-Z]\d{2})(?:\.?(\d{1,2}))?\b")  # "J45.0" e "M070"
_SECAO_CID = re.compile(r"CLASSIFICA[ÇC][ÃA]O\s+ESTAT[ÍI]STICA\s+INTERNACIONAL", re.IGNORECASE)
_MENCAO_CID = re.compile(r"CID[\s-]*10\s*[:(]?\s*((?:[A-TV-Z]\d{2}(?:\.?\d{1,2})?[\s,;e/-]*)+)", re.IGNORECASE)


# --- regras (puras, testadas no --check) ---


def area_da_cid(cid: str) -> str | None:
    c = cid[:3].upper()
    return next((area for ini, fim, area in _AREAS if ini <= c <= fim), None)


def especialidade(cids: list[str]) -> str | None:
    """Área da primeira CID que tem área.

    O PCDT lista a condição principal primeiro. Maioria não serve: o de Hipertensão
    Arterial traz I10, I15 e depois várias O10.x (hipertensão na gestação), e virava
    Ginecologia e Obstetrícia.
    """
    return next((a for a in map(area_da_cid, cids) if a), None)


def portaria(texto: str) -> tuple[str, date] | None:
    """('Portaria Conjunta SAES/SECTICS nº 23', date(2025, 10, 22)) do cabeçalho."""
    m = _PORTARIA.search(" ".join(texto.upper().split()))
    if not m or m.group(3) not in _MESES:
        return None
    nome = re.sub(r"\s+N[º°O.]*\s*(?=\d)", " nº ", m.group(1)).capitalize()
    nome = re.sub(r"\b([a-z]+/[a-z/]+)\b", lambda x: x.group(1).upper(), nome)  # siglas
    return nome, date(int(m.group(4)), _MESES[m.group(3)], int(m.group(2)))


def _codigos(texto: str) -> list[str]:
    return [f"{cat}.{sub}" if sub else cat for cat, sub in _CID.findall(texto)]


def cids_do_pcdt(texto: str) -> list[str]:
    """CIDs do PCDT, em ordem e sem repetição.

    Vêm da seção 2 ("Classificação Estatística Internacional de Doenças..."). O título
    aparece também no sumário, então vale a primeira ocorrência que traz códigos. Sem a
    seção, cai para menções no texto ("... (CID-10: E11)").
    """
    for m in _SECAO_CID.finditer(texto):
        resto = texto[m.end():]
        fim = re.search(r"\n\s*3\.?\s+[A-ZÁÉÍÓÚÇ]", resto)
        secao = resto[: fim.start() if fim else 3000].split("CID-10)", 1)[-1]
        if cids := _codigos(secao):
            return list(dict.fromkeys(cids))
    return list(dict.fromkeys(c for m in _MENCAO_CID.finditer(texto) for c in _codigos(m.group(1))))


def dificuldade(cids: list[str], icsap, internacoes: int, mediana: float) -> tuple[str, str]:
    if any(dentro(c, icsap) for c in cids):
        return "básico", "CID em Condições Sensíveis à Atenção Primária (Portaria SAS/MS 221/2008)"
    if internacoes >= mediana:
        return "intermediário", f"{internacoes} internações/ano no SIH/SUS (≥ mediana {mediana:.0f})"
    return "avançado", f"{internacoes} internações/ano no SIH/SUS (< mediana {mediana:.0f})"


# --- coleta ---


def _ler(url: str) -> bytes:
    """GET com retentativa: o gov.br corta downloads grandes e estoura timeouts."""
    for tentativa in range(4):
        try:
            with urllib.request.urlopen(url, timeout=120) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code == 404 or tentativa == 3:  # não existe: repetir não muda nada
                raise
        except (OSError, http.client.HTTPException):  # IncompleteRead, timeout, reset
            if tentativa == 3:
                raise
            time.sleep(5 * (tentativa + 1))


def listar() -> list[dict]:
    """PCDT vigentes das páginas A–Z: [{titulo, url, chave}]."""
    itens = []
    for letra in string.ascii_lowercase:
        html = _ler(LISTA.format(letra=letra)).decode("utf-8")
        padrao = rf'href="(https://www\.gov\.br/saude/pt-br/assuntos/pcdt/{letra}/([^"/]+)/view)" title="File">([^<]+)'
        for url, arquivo, titulo in re.findall(padrao, html):
            chave = re.sub(r"(\.|%2c)pdf$", "", arquivo, flags=re.IGNORECASE)
            itens.append({"chave": chave, "titulo": " ".join(titulo.split()), "url": url})
    return itens


def _baixar_pdf(item: dict) -> None:
    destino = CORPUS_DIR / f"{item['chave']}.pdf"
    if not destino.exists():
        # Grava e só então renomeia: um PDF parcial nunca passa por baixado.
        parcial = destino.with_suffix(".parcial")
        parcial.write_bytes(_ler(item["url"].removesuffix("/view") + "/@@download/file"))
        parcial.rename(destino)


def _texto(pdf: Path) -> str:
    import pymupdf

    with pymupdf.open(pdf) as doc:
        return "\n".join(pag.get_text() for pag in doc)


def carregar() -> list[dict]:
    return json.loads(CORPUS_JSON.read_text()) if CORPUS_JSON.exists() else []


def salvar(corpus: list[dict], destino: Path = CORPUS_JSON) -> None:
    # Uma linha por documento: o diff do git mostra exatamente o que a curadoria mudou.
    linhas = ",\n".join(json.dumps(r, ensure_ascii=False) for r in corpus)
    destino.write_text(f"[\n{linhas}\n]\n")


def gerar() -> None:
    itens = listar()
    CORPUS_DIR.mkdir(exist_ok=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(_baixar_pdf, itens))

    icsap, prevalencia = carregar_icsap(), carregar_prevalencia()
    curadoria = json.loads(CURADORIA_JSON.read_text()) if CURADORIA_JSON.exists() else {}
    hoje = date.today()

    corpus = []
    for item in itens:
        texto = _texto(CORPUS_DIR / f"{item['chave']}.pdf")
        ajuste = curadoria.get(item["chave"], {})
        # CID da curadoria vence a extraída: é assim que um PCDT sem a seção 2 entra.
        cids = ajuste.get("cid10") or cids_do_pcdt(texto)
        port = portaria(texto)
        regra = "CID da curadoria → área" if ajuste.get("cid10") else "CID-10 → área"
        corpus.append(
            {
                **item,
                "tipo": "PCDT",
                "orgao": ORGAO,
                "identificador": port[0] if port else "",
                "publicado_em": port[1].isoformat() if port else None,
                "cid10": cids,
                "internacoes_ano": sum(prevalencia.get(c, 0) for c in {c[:3] for c in cids}),
                "especialidade": especialidade(cids),
                "dificuldade": None,
                "regra": regra if cids else "sem CID: aguarda curadoria",
                "revisar": not port or (hoje - port[1]).days > 365 * ANOS_ATUAL,
            }
        )

    # Atualidade: dois documentos com exatamente as mesmas CIDs cobrem a mesma condição —
    # fica o mais recente, e o outro sai do sorteio dizendo por quê.
    por_cids = collections.defaultdict(list)
    for r in corpus:
        if r["cid10"]:
            por_cids[frozenset(r["cid10"])].append(r)
    for grupo in por_cids.values():
        grupo.sort(key=lambda r: r["publicado_em"] or "", reverse=True)
        for velho in grupo[1:]:
            velho["especialidade"] = None
            velho["regra"] += f"; superado por {grupo[0]['chave']} (mais recente)"

    # Mediana só entre os que não são ICSAP: é a régua entre intermediário e avançado.
    com_cid = [r for r in corpus if r["cid10"]]
    nao_icsap = [r["internacoes_ano"] for r in com_cid if not any(dentro(c, icsap) for c in r["cid10"])]
    mediana = statistics.median(nao_icsap) if nao_icsap else 0
    for r in com_cid:
        r["dificuldade"], regra = dificuldade(r["cid10"], icsap, r["internacoes_ano"], mediana)
        r["regra"] += f"; {regra}"

    for r in corpus:
        if ajuste := curadoria.get(r["chave"]):
            r.update({k: v for k, v in ajuste.items() if k in ("especialidade", "dificuldade", "revisar")})
            if ajuste.get("descartar"):
                r["especialidade"] = None
            r["regra"] += f"; curadoria: {ajuste.get('nota', 'ajuste manual')}"

    corpus.sort(key=lambda r: r["titulo"].casefold())
    salvar(corpus)
    _relatorio(corpus)


def _relatorio(corpus: list[dict]) -> None:
    from casos.ai import DIFICULDADES, ESPECIALIDADES

    aprovados = [r for r in corpus if r["especialidade"] and r["dificuldade"]]
    print(f"{len(corpus)} PCDT; {len(aprovados)} com especialidade e dificuldade; "
          f"{sum(r['revisar'] for r in corpus)} marcados para revisão.")
    idades = [(date.today() - date.fromisoformat(r["publicado_em"])).days / 365
              for r in corpus if r["publicado_em"]]
    if idades:
        print(f"Idade das portarias: mediana {statistics.median(idades):.1f} anos, máxima {max(idades):.1f}.")
    baldes = collections.Counter((r["especialidade"], r["dificuldade"]) for r in aprovados)
    print(f"\n{'':32}" + "".join(f"{d[:5]:>7}" for d in DIFICULDADES))
    for e in ESPECIALIDADES:
        print(f"{e:32}" + "".join(f"{baldes[(e, d)]:>7}" for d in DIFICULDADES))


if __name__ == "__main__":
    if sys.argv[1:] != ["--check"]:
        gerar()
        sys.exit()

    assert area_da_cid("I21.0") == "Cardiologia"
    assert area_da_cid("I63") == "Neurologia", "AVC é neuro, não cardio"
    assert area_da_cid("C91.0") == "Hematologia" and area_da_cid("C50") == "Oncologia"
    assert area_da_cid("J45.0") == "Pneumologia" and area_da_cid("J03") == "Otorrinolaringologia"
    assert area_da_cid("K02") is None, "cavidade oral fica fora"
    assert area_da_cid("R10") is None, "sintoma não define área"
    assert especialidade(["I10", "O10.0", "O10.1", "O10.2"]) == "Cardiologia", "vale a primeira, não a maioria"
    assert especialidade(["R52", "M05.0"]) == "Reumatologia", "pula CID sem área"
    assert especialidade(["R52"]) is None and especialidade([]) is None

    assert portaria("PORTARIA CONJUNTA SAES/SECTICS Nº 23, DE 22 DE OUTUBRO DE 2025.") == (
        "Portaria conjunta SAES/SECTICS nº 23", date(2025, 10, 22)
    )
    assert portaria("PORTARIA SAS/MS Nº 1.321, DE 1º DE\nDEZEMBRO DE 2014")[1] == date(2014, 12, 1)
    assert portaria("sem cabeçalho") is None

    texto = """1. INTRODUÇÃO
A asma (CID-10 J45) é comum.
2. CLASSIFICAÇÃO ESTATÍSTICA INTERNACIONAL DE DOENÇAS E PROBLEMAS RELACIONADOS À
SAÚDE (CID-10)
- J45.0 - Asma predominante alérgica
- J45.1 - Asma não alérgica
3. DIAGNÓSTICO
Diferencial com J44 (DPOC)."""
    assert cids_do_pcdt(texto) == ["J45.0", "J45.1"], "só a seção 2, sem a CID do título"
    assert cids_do_pcdt("sem seção") == []
    sumario = "SUMÁRIO\n2. CLASSIFICAÇÃO ESTATÍSTICA INTERNACIONAL DE DOENÇAS 4\n3. DIAGNÓSTICO 5\n"
    assert cids_do_pcdt(sumario + texto) == ["J45.0", "J45.1"], "o sumário não engana"
    assert cids_do_pcdt("2 CLASSIFICAÇÃO ESTATÍSTICA INTERNACIONAL (CID-10)\n- M070 Artropatia\n- M072\n3\nDIAGNÓSTICO") == [
        "M07.0", "M07.2"
    ], "código sem ponto"
    assert cids_do_pcdt("O diabete melito tipo 2 (CID-10: E11) é comum.") == ["E11"], "menção no texto"

    icsap = [("J450", "J469")]
    assert dificuldade(["J45.0"], icsap, 10, 5)[0] == "básico"
    assert dificuldade(["M05.0"], icsap, 10, 5)[0] == "intermediário"
    assert dificuldade(["E22.0"], icsap, 1, 5)[0] == "avançado"
    print("OK: CID → área, portaria, seção de CIDs e dificuldade.")
