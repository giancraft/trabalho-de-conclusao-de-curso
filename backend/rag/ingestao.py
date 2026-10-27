"""Ingestão do corpus → `fonte_referencia` + `trecho` (RF04).

    python -m rag.ingestao            # popula o banco (idempotente pela chave)
    python -m rag.ingestao --check    # self-check do seccionamento e do fatiamento, sem banco

Duas origens, um formato de trecho:
- PCDT e manual do MS: `rag/corpus/<chave>.pdf`, aprovado no `corpus.json` (especialidade e
  dificuldade); o manual é seccionado pelo corpo da fonte dos capítulos;
- artigo: `rag/corpus/pmc/<PMCID>.xml` (JATS), aprovado no `literatura.json` (com área).

Rodar de novo pula o que já está no banco e sincroniza especialidade, dificuldade, papel,
peso e lugar na árvore de temas (`rag/temas.py`) com os JSONs — é assim que uma correção da curadoria (RN05) chega ao sorteio.
"""

import asyncio
import collections
import json
import math
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

from sqlmodel import select, update

from rag import apoio, literatura, temas
from rag.catalogo import CORPUS_DIR, LICENCA, carregar
from rag.citacao import titulo_periodico

# O MiniLM trunca a entrada em 128 tokens; em português isso dá ~85 palavras. Trecho
# maior teria a cauda ignorada no embedding.
PALAVRAS = 80
# Fragmento menor que isto (um subtítulo solto, o rabo de um parágrafo partido) não vira
# trecho sozinho: sem contexto, ele fica perto de qualquer consulta genérica e sobe no
# ranking do kNN. Medido na primeira ingestão.
MINIMO = 20

# Título de seção: linha em caixa alta, com número ("3. DIAGNÓSTICO", ou o "3" sozinho
# na linha anterior) ou sem ele — a numeração automática do Word nem sempre sai no PDF.
# Sem número, só vale se for uma das seções-padrão do PCDT: tabela em caixa alta
# ("NR NR", "CICLOS DE ABVD") não pode abrir seção. Subseções ("3.1 Diagnóstico
# clínico") não casam e ficam dentro da seção-mãe.
_TITULO = re.compile(r"^(\d{1,2}\.?\s+)?([A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-ZÁÉÍÓÚÂÊÔÃÕÇ ,/\-–()]{3,})$")
_NUMERO = re.compile(r"^\d{1,2}\.?$")
_PADRAO = (
    "Introdução", "Diagnóstico", "Tratamento", "Monitor", "Critérios de", "Casos especiais",
    "Classificação estatística", "Regulação", "Termo de", "Referências", "Acompanhamento",
    "Metodologia", "Benefícios esperados", "Fármacos", "Abordagem terapêutica",
)
# Seções sem quadro clínico: administrativas e a lista de referências.
_IGNORADAS = (
    "Critérios de", "Classificação estatística", "Regulação", "Termo de", "Anexo", "Apêndice",
    "Metodologia", "Referências",
)
# Linha repetida em tantas páginas é cabeçalho ou rodapé ("Ministério da Saúde ...").
_REPETIDA = 5


def linhas_pdf(pdf) -> list[str]:
    """Linhas do PDF em ordem de leitura, sem cabeçalhos e rodapés repetidos."""
    import pymupdf

    with pymupdf.open(pdf) as doc:
        linhas = [" ".join(l.split()) for pag in doc for l in pag.get_text().splitlines()]
    frequencia = collections.Counter(linhas)
    return [l for l in linhas if l and frequencia[l] < _REPETIDA]


def _paragrafos(linhas: list[str]) -> list[str]:
    """Junta as linhas quebradas pelo layout do PDF até um fim de frase."""
    saida, atual = [], []
    for linha in linhas:
        atual.append(linha)
        if linha.endswith((".", ":", ";", "!", "?")):
            saida.append(" ".join(atual))
            atual = []
    if atual:
        saida.append(" ".join(atual))
    return saida


def _titulo(linha: str, anterior: str) -> str | None:
    m = _TITULO.match(linha)
    if not m:
        return None
    titulo = m.group(2).strip().capitalize()
    numerado = m.group(1) or _NUMERO.match(anterior)
    return titulo if numerado or titulo.startswith(_PADRAO) else None


def secoes(linhas: list[str]) -> list[tuple[str, list[str]]]:
    """(título da seção, parágrafos) de cada seção clínica de primeiro nível do PCDT.

    O preâmbulo da portaria (antes da primeira seção) fica de fora, como as
    administrativas. O sumário repete os títulos, então seções de mesmo título se fundem
    — e "Referências" não pode encerrar a leitura: no sumário ela vem antes do conteúdo
    (o PCDT de Hanseníase perdia tudo assim).
    """
    saida: dict[str, list[str]] = {}
    atual = None
    anterior = ""
    for linha in linhas:
        if titulo := _titulo(linha, anterior):
            atual = None if titulo.startswith(_IGNORADAS) else saida.setdefault(titulo, [])
        elif atual is not None and not _NUMERO.match(linha):
            atual.append(linha)
        anterior = linha
    return [(t, _paragrafos(ls)) for t, ls in saida.items() if ls]


# Capítulo de manual: começa com número ("1 Introdução", "2. Diagnóstico Diferencial").
_NUMERADO = re.compile(r"^\d{1,2}(\.\d+)*\.?(\s|$)")


def linhas_por_fonte(pdf, tamanho: float) -> list[tuple[str, bool]]:
    """(linha, é título) em ordem de leitura; título é a linha com fonte ≥ `tamanho` pt.

    Manual do MS não tem os títulos em caixa alta do PCDT: cada um tem a sua diagramação,
    e o que separa capítulo de texto é o corpo da fonte (curado por manual, `fonte_titulo`
    em `manuais.json`).
    """
    import pymupdf

    with pymupdf.open(pdf) as doc:
        linhas = [
            (" ".join("".join(s["text"] for s in l["spans"]).split()), max(s["size"] for s in l["spans"]) >= tamanho)
            for pag in doc for b in pag.get_text("dict")["blocks"] for l in b.get("lines", []) if l["spans"]
        ]
    frequencia = collections.Counter(t for t, _ in linhas)
    return [(t, e) for t, e in linhas if t and frequencia[t] < _REPETIDA]


def secoes_manual(linhas: list[tuple[str, bool]]) -> list[tuple[str, list[str]]]:
    """(capítulo, parágrafos) de um manual: só os capítulos numerados.

    Título sem número (capa, sumário, apresentação, referências, apêndices, "PARTE II")
    fecha o capítulo anterior e não abre outro: é assim que capa, ficha catalográfica e
    sumário ficam de fora sem lista de nomes. Linhas de título seguidas se juntam ("4
    Atendimento ao paciente com suspeita" + "de dengue"); uma linha numerada recomeça.
    """
    saida: dict[str, list[str]] = {}
    atual, titulo = None, []
    for texto, eh_titulo in linhas:
        if eh_titulo:
            titulo = [texto] if _NUMERADO.match(texto) or not titulo else titulo + [texto]
            continue
        if titulo:
            nome = " ".join(titulo)
            atual = None
            if _NUMERADO.match(nome) and (nome := _NUMERADO.sub("", nome).strip()):
                nome = nome.capitalize() if nome.isupper() else nome
                atual = saida.setdefault(nome, [])
            titulo = []
        if atual is not None and not _NUMERO.match(texto):
            atual.append(texto)
    return [(t, _paragrafos(ls)) for t, ls in saida.items() if ls]


# Seções de artigo sem conteúdo clínico.
_IGNORADAS_JATS = re.compile(
    r"acknowledg|agradec|funding|financ|conflict|conflito|author.{0,5}contrib|contribui|"
    r"data availab|disponibilidade|ethic|ética|supplement|abbreviation|abreviatura",
    re.IGNORECASE,
)


def _texto_xml(e: ET.Element) -> str:
    return " ".join("".join(e.itertext()).split())


def _paragrafos_xml(e: ET.Element):
    """Parágrafos em ordem, sem figuras/tabelas e sem repetir <p> aninhado."""
    for filho in e:
        if filho.tag == "p":
            yield _texto_xml(filho)
        elif filho.tag not in ("title", "fig", "table-wrap", "label", "caption"):
            yield from _paragrafos_xml(filho)


def secoes_jats(xml: str | bytes) -> list[tuple[str, str | None, list[str]]]:
    """(título, id da <sec>, parágrafos) do resumo e de cada seção de primeiro nível.

    Serve aos dois formatos do texto completo: o do Europe PMC (raiz <article>) e o do
    PubMed Central (<pmc-articleset><article>). O id da <sec> vira âncora na citação.
    """
    raiz = ET.fromstring(xml)
    artigo = raiz if raiz.tag == "article" else raiz.find(".//article")
    if artigo is None:
        return []
    saida = []
    resumo = artigo.find("front/article-meta/abstract")
    if resumo is not None and (pars := [p for p in _paragrafos_xml(resumo) if p]):
        saida.append(("Resumo", resumo.get("id"), pars))
    corpo = artigo.find("body")
    if corpo is None:
        return saida
    soltos = [_texto_xml(p) for p in corpo.findall("p")]  # carta/relato sem seções
    if any(soltos):
        saida.append(("Texto", None, [p for p in soltos if p]))
    for sec in corpo.findall("sec"):
        titulo = _texto_xml(sec.find("title")) if sec.find("title") is not None else "Texto"
        if not _IGNORADAS_JATS.search(titulo) and (pars := [p for p in _paragrafos_xml(sec) if p]):
            saida.append((titulo, sec.get("id"), pars))
    return saida


def fatiar(paragrafos: list[str], limite: int = PALAVRAS, minimo: int = MINIMO) -> list[str]:
    """Empacota parágrafos inteiros até `limite` palavras; só quebra os que não cabem.

    Respeitar a fronteira do parágrafo faz o papel da sobreposição (não corta uma ideia
    ao meio) sem duplicar texto quando trechos vizinhos vão juntos para o prompt.
    Fragmentos com menos de `minimo` palavras colam no vizinho, mesmo passando um pouco
    do limite.
    """
    fatias, atual = [], []
    for p in paragrafos:
        palavras = p.split()
        for i in range(0, len(palavras), limite):
            pedaco = palavras[i : i + limite]
            if len(atual) >= minimo and len(atual) + len(pedaco) > limite:
                fatias.append(" ".join(atual))
                atual = []
            atual += pedaco
    if atual:
        if fatias and len(atual) < minimo:
            fatias[-1] += " " + " ".join(atual)
        else:
            fatias.append(" ".join(atual))
    return fatias


# Temas comuns da prática e de prova de residência (curadoria humana, RN05).
RESIDENCIA = json.loads((Path(__file__).parent / "residencia.json").read_text())


def peso(r: dict) -> float:
    """Peso no sorteio (rag/busca.py): o que é comum na prática e em prova sai mais.

    Regra, sem LLM: a relevância de PCDT e manual do MS é 1 + log10(1 + internações/ano
    no SIH/SUS), +3 se for tema de residência, e o peso é essa relevância AO CUBO (HAS ≈
    794; PCDT raro = 1). Sem o cubo, o tema mais importante pesava só ~4x o mais raro, e
    os ~100 PCDT pouco cobrados somados levavam a maior parte dos sorteios: medido em 1.000
    sorteios de Clínica Médica, os 23 temas de residência saíam em 27% dos casos. O cubo
    mantém a ordem dos dois sinais e afasta os extremos (~60x).

    Relato de caso é publicado por ser atípico: 0,3, ou 1 quando a doença de base (MeSH)
    é um tema comum — TB, dengue, sepse... Relato e condição são sorteados em grupos
    separados (`busca.PROB_RELATO`), então as duas escalas nunca disputam entre si.
    """
    if r["tipo"] == "Relato de caso":
        comum = any(m.startswith(t) for m in r.get("mesh", []) for t in RESIDENCIA["mesh_relatos"])
        return 1.0 if comum else 0.3
    bonus = 3 if r["chave"] in RESIDENCIA["pcdt"] else 0
    return round((1 + math.log10(1 + (r.get("internacoes_ano") or 0)) + bonus) ** 3, 2)


def _documentos() -> list[tuple[dict, dict, callable]]:
    """(linha do catálogo, campos da FonteReferencia, leitor de seções) de cada documento.

    O leitor devolve [(título da seção, id da seção, parágrafos)] — o mesmo formato para
    PCDT e artigo, então o resto da ingestão não sabe de onde veio o texto.
    """
    docs = []
    for r in carregar():
        if r["especialidade"] and r["dificuldade"]:
            campos = dict(
                orgao=r["orgao"], identificador=r["identificador"], licenca=r.get("licenca", LICENCA),
                cid10=r["cid10"], bibliografia=r.get("bibliografia"), sorteavel=True,
            )
            pdf = CORPUS_DIR / f"{r['chave']}.pdf"
            if r["tipo"] == "Manual MS":
                ler = lambda pdf=pdf, r=r: [
                    (t, ps) for t, ps in secoes_manual(linhas_por_fonte(pdf, r["fonte_titulo"]))
                    if t.startswith(tuple(r.get("capitulos") or [""]))
                ]
            else:
                ler = lambda pdf=pdf: secoes(linhas_pdf(pdf))
            docs.append((r, campos, lambda ler=ler: [(t, None, ps) for t, ps in ler()]))
    for r in literatura.carregar():
        if r["especialidade"]:  # apoio sem área não tem como ser achado pela área
            campos = dict(
                orgao=titulo_periodico(r["revista"]),
                identificador="; ".join(f"{k.upper()} {r[k]}" for k in ("pmid", "pmcid") if r[k]),
                licenca=r["licenca"],
                cid10=[],
                bibliografia={k: r[k] for k in ("autores", "revista", "volume", "numero", "paginas", "ano", "doi", "pmid", "pmcid")},
                sorteavel=r["sorteavel"],
            )
            xml = literatura.PMC_DIR / f"{r['chave']}.xml"
            docs.append((r, campos, lambda xml=xml: secoes_jats(xml.read_bytes()) if xml.exists() else []))
    return docs


async def ingerir() -> None:
    from core import db
    from models import FonteReferencia, Trecho
    from rag.embeddings import embedar

    docs = _documentos()
    async with db.abrir_sessao() as s:
        existentes = set((await s.execute(select(FonteReferencia.chave))).scalars())

        # Curadoria: reclassificação nos JSONs vale também para o que já foi ingerido. O
        # que perdeu a especialidade fica com "" e nunca mais é sorteado (apagar quebraria
        # o RF14 dos casos que o usaram).
        catalogo = {r["chave"]: r for r in carregar() + literatura.carregar()}
        arvore = temas.classificar(list(catalogo.values()), apoio.carregar(), temas.arvores_mesh())
        for chave in existentes & catalogo.keys():
            r = catalogo[chave]
            area, tema = arvore.get(chave, ("", ""))
            await s.execute(
                update(FonteReferencia)
                .where(FonteReferencia.chave == chave)
                .values(
                    especialidade=r["especialidade"] or "",
                    dificuldade=r["dificuldade"] or "",
                    sorteavel=r.get("sorteavel", True) and bool(r["especialidade"]),
                    peso=peso(r),
                    grande_area=area,
                    tema=tema,
                )
            )
        await s.commit()

        pendentes = [d for d in docs if d[0]["chave"] not in existentes]
        print(f"{len(existentes)} já no banco; {len(pendentes)} a ingerir.", file=sys.stderr)
        inicio, total = time.monotonic(), 0
        for n, (r, campos, ler_secoes) in enumerate(pendentes, 1):
            fatias = [(sec, sec_id, t) for sec, sec_id, pars in ler_secoes() for t in fatiar(pars)]
            if not fatias:
                print(f"  sem seções reconhecíveis: {r['chave']}", file=sys.stderr)
                continue
            vetores = await embedar([t for _, _, t in fatias])
            fonte = FonteReferencia(
                chave=r["chave"],
                titulo=r["titulo"],
                tipo=r["tipo"],
                publicado_em=date.fromisoformat(r["publicado_em"]) if r["publicado_em"] else None,
                url=r["url"],
                especialidade=r["especialidade"],
                dificuldade=r["dificuldade"] or "",
                peso=peso(r),
                grande_area=arvore.get(r["chave"], ("", ""))[0],
                tema=arvore.get(r["chave"], ("", ""))[1],
                **campos,
            )
            s.add(fonte)
            await s.flush()  # gera o id para os trechos
            s.add_all(
                Trecho(fonte_id=fonte.id, ordem=i, secao=sec, secao_id=sec_id, texto=t, embedding=v)
                for i, ((sec, sec_id, t), v) in enumerate(zip(fatias, vetores))
            )
            await s.commit()  # por documento: interromper não deixa fonte sem trechos
            total += len(fatias)
            if n % 100 == 0:
                ritmo = total / (time.monotonic() - inicio)
                print(f"  {n} / {len(pendentes)} documentos, {total} trechos ({ritmo:.0f}/s)", file=sys.stderr)
    print(f"Ingestão completa: +{total} trechos.")


if __name__ == "__main__":
    if sys.argv[1:] != ["--check"]:
        asyncio.run(ingerir())
        sys.exit()

    # Self-check determinístico: seccionamento e fatiamento, sem PDF, banco nem modelo.
    linhas = [
        "PORTARIA CONJUNTA Nº 1, DE 2 DE JANEIRO DE 2026.",
        "Art. 1º Fica aprovado o Protocolo.",  # preâmbulo: fora
        "1. INTRODUÇÃO",
        "A asma é uma doença",
        "inflamatória crônica.",  # linha quebrada pelo layout: junta
        "2. CLASSIFICAÇÃO ESTATÍSTICA INTERNACIONAL DE DOENÇAS",
        "J45.0 Asma predominantemente alérgica",
        "3. DIAGNÓSTICO",
        "3.1 Diagnóstico clínico",  # subseção: fica dentro da seção-mãe
        "Sibilância recorrente.",
        "4. CRITÉRIOS DE INCLUSÃO",
        "Idade acima de 6 anos.",
        "6. TRATAMENTO",
        "Corticoide inalatório.",
        "9. REFERÊNCIAS",
        "1. GINA. Global strategy.",
        "10. ANEXO",
    ]
    s = secoes(linhas)
    assert [t for t, _ in s] == ["Introdução", "Diagnóstico", "Tratamento"], (
        "preâmbulo, CID, critérios e o que vem depois das referências ficam fora"
    )
    assert s[0][1] == ["A asma é uma doença inflamatória crônica."], "linhas do PDF viram parágrafo"
    assert s[1][1] == ["3.1 Diagnóstico clínico Sibilância recorrente."]
    assert secoes([]) == [] and secoes(["texto solto"]) == []
    # Formatos alternativos: sem número (numeração automática do Word) e número numa
    # linha à parte. Tabela em caixa alta não abre seção.
    s = secoes(["INTRODUÇÃO", "Texto.", "NR NR", "Mais texto.", "3", "DIAGNÓSTICO", "Critério."])
    assert s == [("Introdução", ["Texto.", "NR NR Mais texto."]), ("Diagnóstico", ["Critério."])]
    # Sumário no início: títulos sem texto, "Referências" inclusive. Não pode encerrar
    # nada nem duplicar seções.
    sumario = ["SUMÁRIO", "1", "INTRODUÇÃO", "15", "3.1 Diagnóstico clínico", "9. REFERÊNCIAS", "40"]
    s = secoes(sumario + ["1. INTRODUÇÃO", "Texto.", "3. DIAGNÓSTICO", "Critério.", "9. REFERÊNCIAS", "Ref."])
    assert s == [("Introdução", ["3.1 Diagnóstico clínico Texto."]), ("Diagnóstico", ["Critério."])]

    # JATS: resumo + seções de primeiro nível com id; figuras, tabelas e agradecimentos fora.
    jats = """<article><front><article-meta><abstract><p>Resumo do caso.</p></abstract>
      </article-meta></front><body>
      <sec id="sec1"><title>Introduction</title><p>Intro.</p></sec>
      <sec id="sec2"><title>Case report</title><p>A 34-year-old <italic>woman</italic>.</p>
        <fig><caption><p>legenda</p></caption></fig>
        <sec id="sec2.1"><title>Exams</title><p>CRP 12.</p></sec></sec>
      <sec id="sec5"><title>Acknowledgments</title><p>Obrigado.</p></sec>
      </body><back><ref-list><ref>ref</ref></ref-list></back></article>"""
    assert secoes_jats(jats) == [
        ("Resumo", None, ["Resumo do caso."]),
        ("Introduction", "sec1", ["Intro."]),
        ("Case report", "sec2", ["A 34-year-old woman.", "CRP 12."]),
    ], secoes_jats(jats)
    pmc = "<pmc-articleset>" + jats + "</pmc-articleset>"
    assert secoes_jats(pmc) == secoes_jats(jats), "formato do PubMed Central também"
    assert secoes_jats("<article><body><p>Carta sem seções.</p></body></article>") == [
        ("Texto", None, ["Carta sem seções."])
    ]

    assert fatiar(["a b", "c d"], limite=5, minimo=0) == ["a b c d"], "parágrafos curtos se juntam"
    assert fatiar(["a b c", "d e f"], limite=4, minimo=0) == ["a b c", "d e f"], "não parte parágrafo que cabe"
    longo = " ".join(map(str, range(10)))
    assert fatiar([longo], limite=4, minimo=0) == ["0 1 2 3", "4 5 6 7", "8 9"], "parágrafo longo é quebrado"
    assert all(len(f.split()) <= 4 for f in fatiar([longo, "x y", longo], limite=4, minimo=0))
    assert fatiar([]) == []
    # Fragmentos curtos não ficam sozinhos: título solto cola no parágrafo seguinte, e o
    # rabo de um parágrafo partido cola no pedaço anterior.
    assert fatiar(["Imaging", "a b c d"], limite=4, minimo=2) == ["Imaging a b c d"]
    assert fatiar([longo], limite=4, minimo=3) == ["0 1 2 3", "4 5 6 7 8 9"]
    assert fatiar(["x"], minimo=5) == ["x"], "capítulo minúsculo ainda gera um trecho"

    # Peso do sorteio: relevância pela regra, sem LLM.
    has = {"tipo": "PCDT", "chave": "hipertensao-arterial-sistemica", "internacoes_ano": 181771}
    raro = {"tipo": "PCDT", "chave": "x", "internacoes_ano": 0}
    assert 790 < peso(has) < 800 and peso(raro) == 1.0, (peso(has), peso(raro))
    comum = {"tipo": "PCDT", "chave": "x", "internacoes_ano": 4000}  # ~mediana do SIH no corpus
    assert peso(has) / peso(comum) > 6, "tema de residência frequente bem acima do PCDT comum"
    assert peso({"tipo": "Relato de caso", "mesh": ["Tuberculosis, Pulmonary"]}) == 1.0, "tema comum"
    assert peso({"tipo": "Relato de caso", "mesh": ["Kounis Syndrome"]}) == 0.3
    assert all(c in {r["chave"] for r in carregar()} for c in RESIDENCIA["pcdt"]), "chave de PCDT inexistente"

    # Manual: capítulo é a linha em fonte grande e numerada. Capa, ficha e sumário (títulos
    # sem número) ficam fora; título em duas linhas se junta; parte + capítulo seguidos
    # valem pelo capítulo.
    manual = [
        ("DENGUE", True), ("Ficha catalográfica.", False),
        ("Sumário", True), ("1 Introdução | 9", False),
        ("1", True), ("Introdução", True), ("A dengue é", False), ("endêmica.", False), ("9", False),
        ("4 Atendimento ao paciente com suspeita", True), ("de dengue", True), ("Anamnese.", False),
        ("PARTE II", True), ("DIAGNÓSTICO", True), ("1. DIAGNÓSTICO CLÍNICO", True), ("Tosse.", False),
        ("Referências", True), ("BRASIL. Ministério.", False),
    ]
    assert secoes_manual(manual) == [
        ("Introdução", ["A dengue é endêmica."]),
        ("Atendimento ao paciente com suspeita de dengue", ["Anamnese."]),
        ("Diagnóstico clínico", ["Tosse."]),
    ], secoes_manual(manual)
    assert peso({"tipo": "Manual MS", "chave": "x", "internacoes_ano": 0}) == 1.0
    print("OK: seções do PCDT, do manual e do JATS, fatiamento por parágrafo e peso do sorteio.")
