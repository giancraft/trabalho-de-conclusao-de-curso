"""Avaliação da recuperação — o ponto de corte do RAG, com número (RNF05).

    python -m rag.avaliacao                          # modelo em uso, contra o banco
    python -m rag.avaliacao --modelo intfloat/multilingual-e5-small   # outro modelo, em memória

Cada consulta descreve um quadro clínico em português, sem nomear a doença, e diz qual
PCDT deveria voltar. A métrica é acerto@5 por fonte: algum dos 5 trechos mais próximos
é do PCDT esperado. É o número que a banca pode reproduzir.
"""

import asyncio
import sys

# (quadro clínico, prefixo da chave do PCDT esperado)
CONSULTAS = [
    ("dor torácica em aperto com irradiação para o braço esquerdo e sudorese", "linha-de-cuidado-do-infarto"),
    ("sibilância, dispneia e tosse noturna que pioram com exposição a poeira", "asma"),
    ("tremor de repouso, rigidez e lentidão dos movimentos em idoso", "doenca-de-parkinson"),
    ("manchas hipocrômicas na pele com perda de sensibilidade térmica e dolorosa", "hanseniase"),
    ("poliúria, polidipsia e perda de peso em adulto obeso com glicemia de jejum elevada", "diabete-melito-tipo-2"),
    ("crise convulsiva tônico-clônica generalizada com perda de consciência", "epilepsia"),
    ("dor e edema articular simétrico nas mãos com rigidez matinal prolongada", "artrite-reumatoide"),
    ("esquecimento progressivo de fatos recentes em idoso, com perda de autonomia", "doenca-de-alzheimer"),
    ("pressão arterial elevada em medidas repetidas em adulto assintomático", "hipertensao-arterial"),
    ("tosse produtiva crônica e dispneia progressiva em tabagista de longa data", "doenca-pulmonar-obstrutiva-cronica"),
    ("fadiga, palidez e unhas quebradiças em mulher com menstruação abundante", "anemia-deficiencia-de-ferro"),
    ("episódios de euforia, pouca necessidade de sono e gastos excessivos alternando com depressão", "transtorno-afetivo-bipolar"),
]
K = 5


def _acertos(ranking: list[list[str]]) -> int:
    """ranking[i] = chaves das fontes dos K trechos mais próximos da consulta i."""
    total = 0
    for (consulta, esperado), chaves in zip(CONSULTAS, ranking):
        ok = any(c.startswith(esperado) for c in chaves)
        total += ok
        print(f"  {'✓' if ok else '✗'} {consulta[:60]:60} → {chaves[0][:40]}")
    return total


async def no_banco() -> int:
    from core import db
    from rag.busca import buscar

    async with db.abrir_sessao() as s:
        return _acertos([[f.chave for _, f in await buscar(s, c, k=K)] for c, _ in CONSULTAS])


def em_memoria(modelo: str) -> int:
    """Refaz o fatiamento de todo o corpus e busca por força bruta com outro modelo."""
    import numpy as np
    from sentence_transformers import SentenceTransformer

    from rag.catalogo import CORPUS_DIR, carregar
    from rag.ingestao import fatiar, linhas_pdf, secoes

    e5 = "e5" in modelo  # a família E5 exige prefixo de papel no texto
    trechos, chaves = [], []
    for r in carregar():
        if r["especialidade"] and r["dificuldade"]:
            for _, pars in secoes(linhas_pdf(CORPUS_DIR / f"{r['chave']}.pdf")):
                for t in fatiar(pars):
                    trechos.append(("passage: " if e5 else "") + t)
                    chaves.append(r["chave"])
    m = SentenceTransformer(modelo, device="cpu")
    print(f"{len(trechos)} trechos com {modelo}", file=sys.stderr)
    vt = m.encode(trechos, batch_size=64, normalize_embeddings=True, show_progress_bar=True)
    vc = m.encode([("query: " if e5 else "") + c for c, _ in CONSULTAS], normalize_embeddings=True)
    return _acertos([[chaves[i] for i in np.argsort(-(vt @ q))[:K]] for q in vc])


if __name__ == "__main__":
    if "--modelo" in sys.argv:
        acertos = em_memoria(sys.argv[sys.argv.index("--modelo") + 1])
    else:
        acertos = asyncio.run(no_banco())
    print(f"acerto@{K}: {acertos}/{len(CONSULTAS)}")
