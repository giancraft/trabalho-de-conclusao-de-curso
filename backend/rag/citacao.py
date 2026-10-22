"""Referências no padrão ABNT — NBR 6023:2018 (lista) e NBR 10520:2023 (sistema numérico).

    python -m rag.citacao   # self-check com as saídas exatas

Uma função só monta a referência de qualquer fonte, para o feedback, a interface e o
texto do TCC dizerem a mesma coisa. Devolve também o trecho que a norma manda destacar
(título do periódico no artigo; título do documento no PCDT): a interface põe em negrito.
"""

from datetime import date

_MESES = "jan. fev. mar. abr. maio jun. jul. ago. set. out. nov. dez.".split()
# Palavras que ficam em minúscula no título do periódico (exceto na primeira posição).
_MINUSCULAS = {"a", "o", "e", "de", "da", "do", "das", "dos", "em", "para", "of", "the", "and", "in", "for", "on"}


def data_abnt(d: date) -> str:
    """date(2025, 11, 27) → "27 nov. 2025" (abreviatura de mês da NBR 6023)."""
    return f"{d.day} {_MESES[d.month - 1]} {d.year}"


def autores_abnt(autores: list[dict]) -> str:
    """Até três autores, todos; a partir de quatro, o primeiro seguido de "et al."."""

    def um(a: dict) -> str:
        return f"{a['sobrenome'].upper()}, {a['nome']}" if a.get("nome") else a["sobrenome"].upper()

    if len(autores) > 3:
        return f"{um(autores[0])} et al."
    return "; ".join(um(a) for a in autores)


def titulo_periodico(titulo: str) -> str:
    """O PubMed grafa "Arquivos brasileiros de oftalmologia"; a norma pede o título como
    o periódico o publica — "Arquivos Brasileiros de Oftalmologia"."""
    palavras = titulo.split()
    return " ".join(
        p if (i and p.lower() in _MINUSCULAS) or p[:1].isupper() else p[:1].upper() + p[1:]
        for i, p in enumerate(palavras)
    )


def citacao_abnt(fonte, acesso: date) -> tuple[str, str]:
    """(referência completa, trecho em destaque) de um PCDT ou de um artigo.

    `fonte` precisa de: tipo, titulo, orgao, identificador, publicado_em, url e, nos
    artigos, bibliografia (autores, revista, volume, numero, paginas, ano, doi).
    """
    final = f"Disponível em: {fonte.url}. Acesso em: {data_abnt(acesso)}."
    if fonte.tipo == "PCDT":
        destaque = f"Protocolo Clínico e Diretrizes Terapêuticas: {fonte.titulo}"
        data = f", de {data_abnt(fonte.publicado_em)}" if fonte.publicado_em else ""
        portaria = f" {fonte.identificador}{data}." if fonte.identificador else ""
        return f"BRASIL. {fonte.orgao}. {destaque}.{portaria} {final}", destaque

    b = fonte.bibliografia
    destaque = titulo_periodico(b["revista"])
    partes = [destaque]
    partes += [f"v. {b['volume']}"] if b.get("volume") else []
    partes += [f"n. {b['numero']}"] if b.get("numero") else []
    partes += [f"p. {b['paginas']}"] if b.get("paginas") else []
    partes += [b["ano"]]
    autores = autores_abnt(b["autores"])
    doi = f" DOI: {b['doi']}." if b.get("doi") else ""
    # "et al." já termina em ponto: não pode virar "et al.."
    inicio = f"{autores.removesuffix('.')}. " if autores else ""
    return f"{inicio}{fonte.titulo}. {', '.join(partes)}.{doi} {final}", destaque


def url_secao(url: str, secao_id: str | None) -> str:
    """Link direto para a seção no PMC (o id da <sec> vira âncora)."""
    return f"{url}#{secao_id}" if secao_id else url


if __name__ == "__main__":
    from types import SimpleNamespace

    acesso = date(2026, 10, 7)
    assert data_abnt(date(2025, 5, 3)) == "3 maio 2025", "maio não abrevia"
    assert titulo_periodico("Arquivos brasileiros de oftalmologia") == "Arquivos Brasileiros de Oftalmologia"
    assert titulo_periodico("Jornal Brasileiro de Pneumologia") == "Jornal Brasileiro de Pneumologia"

    def artigo(n_autores: int, **extra):
        nomes = [("Bandoli", "Lorranne"), ("Moura", "Frederico"), ("Silva", "Ana"), ("Souza", "Rui"), ("Lima", "Eva")]
        return SimpleNamespace(
            tipo="Relato de caso",
            titulo="Autoimmune optic neuropathy as the differential diagnosis of neuromyelitis optica spectrum disorders",
            url="https://pmc.ncbi.nlm.nih.gov/articles/PMC11826678/",
            bibliografia={
                "autores": [{"sobrenome": s, "nome": n} for s, n in nomes[:n_autores]],
                "revista": "Arquivos brasileiros de oftalmologia",
                "volume": "85", "numero": "6", "paginas": "620-624", "ano": "2021",
                "doi": "10.5935/0004-2749.20220064", **extra,
            },
        )

    ref, destaque = citacao_abnt(artigo(2), acesso)
    assert ref == (
        "BANDOLI, Lorranne; MOURA, Frederico. Autoimmune optic neuropathy as the differential "
        "diagnosis of neuromyelitis optica spectrum disorders. Arquivos Brasileiros de "
        "Oftalmologia, v. 85, n. 6, p. 620-624, 2021. DOI: 10.5935/0004-2749.20220064. "
        "Disponível em: https://pmc.ncbi.nlm.nih.gov/articles/PMC11826678/. Acesso em: 7 out. 2026."
    ), ref
    assert destaque == "Arquivos Brasileiros de Oftalmologia" and destaque in ref

    ref, _ = citacao_abnt(artigo(5), acesso)
    assert ref.startswith("BANDOLI, Lorranne et al. Autoimmune"), "4+ autores: primeiro + et al."
    ref, _ = citacao_abnt(artigo(3), acesso)
    assert ref.startswith("BANDOLI, Lorranne; MOURA, Frederico; SILVA, Ana. "), "3 autores: todos"
    ref, _ = citacao_abnt(artigo(1, numero="", paginas="", doi=""), acesso)
    assert ", v. 85, 2021. Disponível em:" in ref, "campos vazios somem sem deixar vírgula sobrando"

    pcdt = SimpleNamespace(
        tipo="PCDT", titulo="Doença Pulmonar Obstrutiva Crônica", orgao="Ministério da Saúde",
        identificador="Portaria conjunta SAES/SCTIE nº 29", publicado_em=date(2025, 11, 27),
        url="https://www.gov.br/saude/pt-br/assuntos/pcdt/d/doenca-pulmonar-obstrutiva-cronica/view",
    )
    ref, destaque = citacao_abnt(pcdt, acesso)
    assert ref == (
        "BRASIL. Ministério da Saúde. Protocolo Clínico e Diretrizes Terapêuticas: Doença "
        "Pulmonar Obstrutiva Crônica. Portaria conjunta SAES/SCTIE nº 29, de 27 nov. 2025. "
        "Disponível em: https://www.gov.br/saude/pt-br/assuntos/pcdt/d/doenca-pulmonar-obstrutiva-cronica/view. "
        "Acesso em: 7 out. 2026."
    ), ref
    assert destaque == "Protocolo Clínico e Diretrizes Terapêuticas: Doença Pulmonar Obstrutiva Crônica"
    sem_portaria = SimpleNamespace(**{**vars(pcdt), "identificador": "", "publicado_em": None})
    assert "Crônica. Disponível em:" in citacao_abnt(sem_portaria, acesso)[0]

    assert url_secao("https://x/PMC1/", "sec3") == "https://x/PMC1/#sec3"
    assert url_secao("https://x/", None) == "https://x/"
    print("OK: referências ABNT de artigo (1, 2, 3 e 5 autores) e de PCDT, datas e âncoras.")
