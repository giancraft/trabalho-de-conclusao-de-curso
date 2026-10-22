FROM python:3.13-slim AS base
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/opt/hf
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && useradd --create-home app
# O modelo de embedding (o mesmo de rag/embeddings.py) é baixado no build: sem isto o
# container depende de rede no boot e o primeiro request trava no download.
RUN python -c "from sentence_transformers import SentenceTransformer as S; \
S('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')"
ENV HF_HUB_OFFLINE=1


FROM base AS dev
# /app/backend é onde vivem main.py e alembic.ini: com o cwd aqui, tanto o uvicorn
# quanto `docker compose exec backend alembic upgrade head` rodam sem flag de caminho.
WORKDIR /app/backend
USER app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]


FROM node:22-slim AS frontend
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build


FROM base AS prod
COPY --chown=app:app backend/ ./backend/
# main.py monta este diretório com StaticFiles — é o que faz um processo só servir
# API e frontend na mesma origem.
COPY --from=frontend --chown=app:app /fe/dist ./frontend/dist
WORKDIR /app/backend
USER app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
