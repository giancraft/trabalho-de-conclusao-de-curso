# Simulador Clínico — Casos com IA Generativa

Aplicação web em que estudantes de Medicina investigam casos clínicos **sem conhecer o
diagnóstico**. A IA Generativa (Groq) é o motor lógico: cria o caso oculto, responde à
anamnese como paciente/preceptor e avalia o diagnóstico final com feedback formativo.
Protótipo-base do TCC *"Sistema de apoio ao estudo médico baseado em inteligência artificial"*.

## Como funciona

1. O estudante **cria uma conta e faz login** (senha com hash bcrypt; sessão em cookie
   httpOnly revogável — o token nunca é acessível por JavaScript).
2. Escolhe **especialidade** (Cardiologia, Oncologia...) e **dificuldade**; a IA sorteia
   uma condição oculta e apresenta o paciente (o gabarito fica **apenas no servidor** —
   impossível ver pelo navegador).
3. No chat, conduz a investigação: perguntas de anamnese, exame físico, exames. As
   respostas chegam em **streaming**, como nos chats de IA conhecidos.
4. Ao clicar em **"Dar diagnóstico"**, envia a hipótese final e recebe: acertos,
   inconsistências, hipóteses não consideradas e justificativa pedagógica, além do gabarito.
5. **Todas as conversas persistem** (PostgreSQL) e aparecem no menu lateral: casos abertos
   podem ser retomados de onde pararam; encerrados abrem em leitura com o feedback.

## Arquitetura

| Camada | Stack | Papel |
|---|---|---|
| `frontend/` | React + TypeScript + Vite + Tailwind CSS | Interface de chat (sidebar, mensagens, composer, feedback) |
| `backend/`  | FastAPI + Groq (`gpt-oss-120b`) + PostgreSQL/pgvector | Rotas da API, autenticação, persistência, prompts e streaming |

O backend é organizado por domínio, tudo `async` de ponta a ponta:

- `backend/main.py` — monta os routers e, em produção, serve o frontend construído.
- `backend/models.py` — entidades (SQLModel) e schemas de leitura da API.
- `backend/casos/ai.py` — integração com a IA: `novo_caso()`, `responder_chat()` (streaming),
  `avaliar_diagnostico()`. As chamadas estruturadas usam o modo `strict` da Groq, com o
  schema derivado dos modelos Pydantic — não há JSON escrito no prompt.
- `backend/casos/router.py` — rotas de casos (`/api/casos...`) e histórico (`/api/conversas...`).
- `backend/auth/router.py` — registro/login/logout com bcrypt e cookie de sessão httpOnly.
- `backend/core/db.py` — persistência em PostgreSQL (SQLModel + asyncpg).
- `backend/migrations/` — migrações Alembic; a inicial habilita a extensão `vector`.
- `frontend/src/api.ts` — cliente da API; os tipos saem do OpenAPI (ver abaixo).

As tabelas usam os nomes da modelagem conceitual do TCC: `caso_clinico` é o que a API
chama de "conversa", e `resposta` é o que ela chama de "mensagem".

## Rodando com Docker

```bash
cp .env.example .env    # preencha GROQ_API_KEY (https://console.groq.com/keys)
docker compose up       # http://localhost:5173 (frontend) e :8000 (API)
```

```bash
docker compose exec backend alembic upgrade head    # primeira vez, e a cada migração nova
```

Um `compose.yaml` só, com dois profiles. `COMPOSE_PROFILES=dev` (no `.env`) é o do dia a
dia: código por bind mount com `--reload` e o Vite como serviço. O `.env` fica só no
host — o compose injeta as variáveis, e o segredo nunca entra na imagem.

Produção — um processo serve API e frontend na mesma origem, sem CORS, com o cookie de
sessão marcado `Secure`:

```bash
COMPOSE_PROFILES=prod docker compose up --build -d
```

A aplicação inteira responde em http://localhost:8000.

### Sem Docker

Precisa de um PostgreSQL acessível; ajuste `DATABASE_URL` no `.env` se não for o padrão.

```bash
python -m venv .venv
source .venv/bin/activate            # fish: source .venv/bin/activate.fish
pip install -r backend/requirements.txt
cp .env.example .env
cd backend && alembic upgrade head && uvicorn main:app --reload

cd frontend && npm install && npm run dev   # outro terminal
```

## Tipos do frontend

`frontend/src/types.generated.ts` é gerado do OpenAPI e **não deve ser editado à mão**;
`types.ts` só dá nomes curtos ao que veio de lá. Mudou a API, com o backend no ar:

```bash
npm --prefix frontend run gen:types
```

## Testes rápidos

```bash
# `-m` e não o caminho do arquivo: os módulos importam uns aos outros por pacote.
docker compose exec backend python -m casos.ai   # parser, janela, schema strict (sem rede)
docker compose exec backend python -m core.db    # CRUD contra o Postgres, em schema descartável
npm --prefix frontend run build                  # type-check (tsc) + build
```

## Escopo do protótipo

Núcleo de simulação de casos + contas/persistência. Ficam para o TCC: flashcards com
repetição espaçada, painel adaptativo, ancoragem RAG em base curada (a extensão `vector`
já está habilitada) e recuperação de senha. Uso estritamente educacional — não fornece
orientação clínica real.
