"""Embeddings do RAG (sentence-transformers, na CPU).

Modelo multilíngue: a consulta nasce em português e o corpus é inglês. `encode()` é
CPU pura e síncrona — chamado direto numa rota, trava o event loop e todos os outros
usuários junto. Por isso a única porta de entrada é `embedar()`, que roda em thread.
"""

import asyncio

MODELO = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DIMENSAO = 384

_modelo = None


def _carregar():
    """Singleton preguiçoso: importar este módulo não custa os ~500 MB do torch."""
    global _modelo
    if _modelo is None:
        from sentence_transformers import SentenceTransformer

        # A imagem Docker baixa o modelo no build e liga HF_HUB_OFFLINE: em runtime
        # nada vai à rede.
        _modelo = SentenceTransformer(MODELO, device="cpu")
    return _modelo


def _embedar(textos: list[str]) -> list[list[float]]:
    # Normalizado: com norma 1, a distância de cosseno do pgvector vira produto escalar.
    return _carregar().encode(textos, batch_size=64, normalize_embeddings=True).tolist()


async def embedar(textos: list[str]) -> list[list[float]]:
    return await asyncio.to_thread(_embedar, textos)
