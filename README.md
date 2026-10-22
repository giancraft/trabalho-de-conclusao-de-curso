# Simulador Clínico — Casos com IA Generativa

Aplicação web em que estudantes de Medicina investigam casos clínicos **sem conhecer o
diagnóstico**. A IA Generativa (Groq) é o motor lógico: cria o caso oculto, responde à
anamnese como paciente/preceptor e avalia o diagnóstico final com feedback formativo.
Protótipo-base do TCC *"Sistema de apoio ao estudo médico baseado em inteligência artificial"*.

## Como funciona

1. O estudante **cria uma conta e faz login** (senha com hash bcrypt; sessão em cookie
   httpOnly revogável — o token nunca é acessível por JavaScript).
2. Escolhe **especialidade** (22 áreas da graduação) e **dificuldade**; o sistema sorteia
   uma condição do **corpus curado de PCDT do Ministério da Saúde** e a IA apresenta o
   paciente com os achados ancorados no protocolo sorteado (o gabarito fica **apenas no
   servidor** — impossível ver pelo navegador).
3. No chat, conduz a investigação: perguntas de anamnese, exame físico, exames. As
   respostas chegam em **streaming**, como nos chats de IA conhecidos.
4. Ao clicar em **"Dar diagnóstico"**, envia a hipótese final e recebe: acertos,
   inconsistências, hipóteses não consideradas e justificativa pedagógica (apoiadas no
   diagnóstico e na conduta do PCDT), além do gabarito e da **citação da
   fonte** — que só aparece depois do encerramento, porque o título do capítulo é o
   diagnóstico.
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
- `backend/rag/` — RAG sobre os PCDT do Ministério da Saúde (RF04/RF14): `prevalencia.py`
  tira do DATASUS os insumos da dificuldade, `catalogo.py` monta o `corpus.json`
  versionado, `ingestao.py` popula `fonte_referencia`/`trecho` (pgvector, HNSW),
  `busca.py` sorteia a condição e recupera os trechos, `embeddings.py` roda o
  `paraphrase-multilingual-MiniLM-L12-v2` sempre fora do event loop.
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

## Corpus do RAG

Duas camadas, com uma hierarquia que o prompt manda seguir — para critério diagnóstico e
conduta vale **PCDT (Ministério da Saúde) > diretriz de sociedade médica > revisão e
relato de caso**; a literatura entra para apresentação clínica e epidemiologia e, se
contradisser uma diretriz brasileira, a diretriz vence.

| Camada | Origem | Papel |
|---|---|---|
| PCDT | gov.br/saude (vigentes) | doença sorteável + conduta oficial |
| Relato de caso | Europe PMC / PubMed Central, autor brasileiro, 2016+ | doença sorteável (nível avançado) |
| Diretriz de sociedade | idem | apoio: diagnóstico e conduta |
| Revisão (fase B) | idem, 2019+ | apoio: quadro clínico e diferencial |

Cada caso usa a fonte sorteada e até duas de apoio, numeradas [1], [2]... O apoio é ligado
por **conceito exato**, nunca por semelhança de texto (`backend/rag/apoio.json`,
versionado, com o motivo de cada ligação): condição e apoio compartilham um descritor
MeSH de doença específico, ou o do apoio é o pai direto do da condição. O MeSH do PCDT sai
das CIDs dele, pelo título oficial em inglês da CID-10-CM. Sem ligação exata, sem apoio —
medido no corpus, a busca semântica ligava febre maculosa à doença de Chagas. O feedback cita esses números, e o caso encerrado
mostra a lista de **referências em ABNT** (NBR 6023:2018, sistema numérico da NBR
10520:2023) com tipo de fonte, licença e as seções consultadas, com link direto. O banco
guarda os ids exatos dos trechos usados em cada etapa (`caso_fonte`).

### PCDT

Portaria é ato oficial, sem proteção autoral (Lei 9.610/98, art. 8º, IV), e o portal só
publica a versão em vigor. `backend/rag/corpus.json` (versionado) tem uma linha por PCDT,
cada uma dizendo qual regra a decidiu (`regra`):

- **especialidade** — tabela CID-10 → área, pela primeira CID da seção 2 do PCDT;
- **dificuldade** — CID nas Condições Sensíveis à Atenção Primária (Portaria SAS/MS
  221/2008) → básico; senão, internações/ano no SIH/SUS acima da mediana do corpus →
  intermediário, abaixo → avançado;
- **atualidade** — PCDT com as mesmas CIDs de outro mais novo sai; portaria com mais de
  10 anos ganha `revisar: true`.

### Literatura (Europe PMC + PubMed Central)

Artigos com autor de afiliação brasileira, acesso aberto, texto completo e licença que
permite obra derivada (CC BY, BY-SA, BY-NC, BY-NC-SA, CC0 — as "ND" ficam de fora, porque
gerar um caso é derivação). Texto do Europe PMC; se faltar, do PubMed Central.
`backend/rag/literatura.json` (versionado) tem uma linha por artigo:

- **especialidade** — descritores MeSH principais → árvore MeSH da NLM → área
  (`mesh_arvore.csv`, versionado, mostra a árvore e a área de cada descritor); artigo
  ainda não indexado usa as palavras-chave do autor; paciente só pediátrico → Pediatria;
- **dificuldade** — relato de caso → avançado (é publicado por ser incomum).

`backend/rag/curadoria.json` é a revisão humana (RN05) das duas camadas, pela chave (slug
do PCDT ou PMCID), sempre com uma `nota`. Nenhuma etapa usa IA generativa.

```bash
# Uma vez, com rede:
cd backend && uv run --no-project --with datasus-dbc==0.1.3 python -m rag.prevalencia && cd ..   # DATASUS → CSVs (~6 min, no host)
docker compose exec backend python -m rag.catalogo      # PCDT: PDFs + corpus.json
docker compose exec backend python -m rag.literatura    # fase A: diretrizes e relatos (--revisoes: fase B)
docker compose exec backend python -m rag.apoio         # ligações condição → PCDT/diretriz (apoio.json)

# Popular o banco (idempotente; sem rede):
docker compose exec backend python -m rag.ingestao
```

PDFs e XMLs ficam em `backend/rag/corpus/`, fora do git e da imagem. Com o corpus vazio
o sistema continua funcionando: o caso é gerado sem ancoragem, como no protótipo.

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
docker compose exec backend python -m rag.busca  # sorteio, trechos por seção e kNN, em schema descartável
docker compose exec backend python -m rag.ingestao --check  # seções do PCDT e fatiamento
docker compose exec backend python -m rag.catalogo --check   # CID → área, portaria, CIDs, dificuldade
docker compose exec backend python -m rag.prevalencia --check  # faixas CID do TabWin
docker compose exec backend python -m rag.literatura --check   # MeSH → área, licença, linha do catálogo
docker compose exec backend python -m rag.citacao              # referências ABNT com saída exata
docker compose exec backend python -m rag.apoio --check        # ligação por descritor MeSH e cobertura
docker compose exec backend python -m rag.busca "dor torácica em aperto"  # consulta real no corpus
docker compose exec backend python -m rag.avaliacao  # acerto@5 em 12 quadros clínicos (ponto de corte do RAG)
npm --prefix frontend run build                  # type-check (tsc) + build
```

## Escopo do protótipo

Núcleo de simulação de casos + contas/persistência + ancoragem RAG em base curada.
Ficam para as próximas etapas: flashcards com repetição espaçada, painel adaptativo,
administração e recuperação de senha. Uso estritamente educacional — não fornece
orientação clínica real.
