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
5. **Todas as conversas persistem** (SQLite) e aparecem no menu lateral: casos abertos
   podem ser retomados de onde pararam; encerrados abrem em leitura com o feedback.

## Arquitetura

| Camada | Stack | Papel |
|---|---|---|
| `frontend/` | React + TypeScript + Vite + Tailwind CSS | Interface de chat (sidebar, mensagens, composer, feedback) |
| `backend/`  | FastAPI + Groq (`llama-3.3-70b-versatile`) + SQLite | Rotas da API, autenticação, persistência, prompts e streaming |

- `backend/ai.py` — integração com a IA: `novo_caso()` (JSON mode), `responder_chat()`
  (streaming), `avaliar_diagnostico()` (JSON mode).
- `backend/db.py` — persistência em SQLite (stdlib): usuários, sessões, conversas, mensagens.
- `backend/auth.py` — registro/login/logout com bcrypt e cookie de sessão httpOnly.
- `backend/main.py` — rotas de casos (`/api/casos...`) e histórico (`/api/conversas...`).
- `frontend/src/api.ts` — cliente tipado da API, incluindo leitura do stream.

O banco (`backend/dados.db`) é criado automaticamente na primeira execução.

## Rodando (dois processos)

```bash
# 1. Backend
python -m venv .venv
source .venv/bin/activate            # fish: source .venv/bin/activate.fish
pip install -r backend/requirements.txt
cp .env.example .env                  # preencha GROQ_API_KEY (https://console.groq.com/keys)
uvicorn main:app --app-dir backend --reload

# 2. Frontend (outro terminal)
cd frontend
npm install
npm run dev                           # http://localhost:5173 (proxy /api -> :8000)
```

## Testes rápidos

```bash
python backend/ai.py      # self-check do parser JSON (sem rede)
python backend/db.py      # self-check do CRUD em banco na memória (sem rede)
cd frontend && npm run build   # type-check (tsc) + build
```

## Escopo do protótipo

Núcleo de simulação de casos + contas/persistência. Ficam para o TCC: flashcards com
repetição espaçada, painel adaptativo, ancoragem RAG em base curada, recuperação de senha
e Postgres. Uso estritamente educacional — não fornece orientação clínica real.
