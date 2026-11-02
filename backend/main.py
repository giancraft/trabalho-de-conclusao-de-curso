"""API do simulador de casos clínicos (FastAPI) — monta os routers.

Conversas persistem em PostgreSQL e pertencem a um usuário autenticado (cookie httpOnly).
O gabarito de cada caso fica apenas no servidor até o estudante fechar o diagnóstico —
o frontend nunca o recebe antes disso.

Em produção este mesmo processo serve o frontend construído: um artefato, uma origem,
sem CORS. Em desenvolvimento o Vite serve o frontend e fala com a API pelo proxy.
"""

from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # antes de importar casos.ai e core.config, que leem o ambiente no import

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from auth.router import router as auth_router
from casos import ai
from casos.router import router as casos_router
from casos.router_admin import router as admin_router
from core import config, db

_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # O schema é criado pelo Alembic (`alembic upgrade head`), não aqui.
    # A configuração da IA em vigor é a última versão salva pelo administrador.
    async with db.abrir_sessao() as s:
        versao = await db.configuracao_atual(s)
    ai.aplicar_config(versao.dados if versao else None, versao.id if versao else None)
    yield
    await db.engine.dispose()


app = FastAPI(title="Simulador de Casos Clínicos", lifespan=lifespan)

if not config.PRODUCAO:
    # Só existe em dev, onde o Vite roda em outra porta. Em produção é a mesma origem.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],  # dev server do Vite
        allow_credentials=True,  # cookie de sessão
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(auth_router)
app.include_router(casos_router)
app.include_router(admin_router)

# Depois dos routers de propósito: um mount em "/" atende tudo o que não casou antes.
# O diretório só existe na imagem de produção (stage `prod` do Dockerfile); em dev quem
# serve o frontend é o Vite. Sem react-router no projeto, `html=True` basta.
if _DIST.is_dir():
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="frontend")
