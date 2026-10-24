"""Integração com a IA Generativa — motor lógico do simulador de casos clínicos.

Três funções expostas:
- novo_caso():           abre o caso sobre a condição sorteada no corpus (RF04)
- responder_chat():      responde ao estudante como paciente e devolve os exames pedidos
- avaliar_diagnostico(): feedback formativo estruturado ao fechar o diagnóstico

O provedor é qualquer um compatível com a API da OpenAI (OpenRouter, Groq, DeepSeek,
DeepInfra, Ollama...), escolhido pelo .env. Toda chamada passa por `_estruturado`: o
schema sai dos modelos Pydantic abaixo e, onde o provedor aceita, é garantido por
constrained decoding (`json_schema` strict); onde não aceita, vai no prompt e o Pydantic
valida, com uma segunda tentativa.

Tudo é `async` (AsyncOpenAI): chamada de LLM é espera de rede, e um worker bloqueado
nela é um worker que não atende mais ninguém.
"""

import json
import logging
import os
import re
from collections.abc import AsyncIterator
from typing import TypeVar

from pydantic import BaseModel, ConfigDict, Field

# Qualquer provedor compatível com a API da OpenAI serve; trocar de modelo é só mudar o
# .env (ver .env.example). O padrão é o gpt-oss-120b pelo OpenRouter, servido pela Groq:
# na comparação de 24/10 (vs. DeepSeek V4 Flash, Qwen3-235B e GLM-5.3 Flash) foi o mais
# rápido e o que melhor seguiu o prompt.
MODELO = os.getenv("LLM_MODEL", "openai/gpt-oss-120b")
_BASE_URL = os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1")
# "estrito": o provedor garante o json_schema. "json": só json_object (ex.: API oficial do
# DeepSeek) — o schema vai no prompt e o Pydantic valida.
_MODO_JSON = os.getenv("LLM_JSON", "estrito")
_PROVEDORES = [p.strip() for p in os.getenv("LLM_PROVIDERS", "").split(",") if p.strip()]

# Turnos de conversa enviados ao modelo. O chat recorta para manter o custo por turno
# estável (e histórico inchado dispersa o modelo); a avaliação leva quase tudo, porque
# o que ela julga é o raciocínio ao longo de toda a investigação (RF07).
# O chat corta em blocos (cresce até 12, volta a 6) em vez de deslizar a cada mensagem:
# entre um corte e outro o começo do prompt é idêntico e o provedor o serve do cache
# (Groq: metade do preço e fora do limite de tokens). A ficha, que é a verdade do caso,
# está sempre no system — o corte só tira conversa antiga.
TURNOS_CHAT = 12
TURNOS_CHAT_APOS_CORTE = 6
TURNOS_AVALIACAO = 30

# Grandes áreas das DCN 2014, agrupadas: Clínica Médica, demais áreas do currículo e
# especialidades focais. Anestesiologia, Radiologia, Patologia e Medicina Legal ficam de
# fora — não cabem no fluxo único anamnese → exame físico → exames → diagnóstico.
ESPECIALIDADES = [
    # Clínica Médica
    "Cardiologia",
    "Pneumologia",
    "Endocrinologia",
    "Gastroenterologia",
    "Neurologia",
    "Nefrologia",
    "Infectologia",
    "Oncologia",
    "Hematologia",
    "Reumatologia",
    "Dermatologia",
    "Geriatria",
    # Grandes áreas do currículo
    "Pediatria",
    "Ginecologia e Obstetrícia",
    "Cirurgia Geral",
    "Psiquiatria",
    "Medicina de Emergência",
    "Medicina de Família e Comunidade",
    # Focais
    "Ortopedia e Traumatologia",
    "Urologia",
    "Oftalmologia",
    "Otorrinolaringologia",
]

DIFICULDADES = ["básico", "intermediário", "avançado"]

# Contexto educacional obrigatório: nunca orientação clínica real (RN06 do TCC).
_SYSTEM_BASE = (
    "Você faz parte de um simulador educacional de casos clínicos para estudantes de "
    "Medicina brasileiros. Todo conteúdo é SIMULAÇÃO EDUCACIONAL — nunca forneça "
    "orientação clínica real para pacientes reais. Escreva em português do Brasil."
)


M = TypeVar("M", bound=BaseModel)


class _Schema(BaseModel):
    """Base dos schemas trocados com o modelo.

    `extra="forbid"` emite `additionalProperties: false`, exigido pelo `json_schema`
    strict (junto com todos os campos obrigatórios).
    """

    model_config = ConfigDict(extra="forbid")


class Ficha(_Schema):
    """Tudo o que o estudante pode descobrir no caso, fixado na geração.

    Sem ela o tutor improvisa cada achado na hora e, com a janela de turnos, pode se
    contradizer; com ela, a mesma pergunta tem a mesma resposta a conversa toda.
    """

    anamnese: str = Field(
        description="fatos da história, em tópicos: HDA detalhada (início, evolução, "
        "características), antecedentes pessoais, medicações, alergias, história familiar, "
        "hábitos, contexto social e revisão de sistemas (com os negativos pertinentes)"
    )
    exame_fisico: str = Field(
        description="sinais vitais, antropometria quando pertinente e achados por sistema, "
        "incluindo os normais; só achados observáveis, sem interpretação"
    )
    exames: str = Field(
        description="resultados dos exames complementares pertinentes ao diagnóstico e ao "
        "diferencial, com valor, unidade e valor de referência (imagem: laudo descritivo). "
        "Só achados do paciente: nunca procedimentos ou cirurgias como resultado"
    )


class Gabarito(_Schema):
    diagnostico: str = Field(description="diagnóstico correto")
    justificativa: str = Field(
        description="raciocínio fisiopatológico e achados-chave que fecham o diagnóstico"
    )
    ficha: Ficha


class CasoGerado(_Schema):
    titulo: str = Field(
        description="título curto (3 a 6 palavras) baseado na queixa/apresentação, SEM "
        "revelar nem sugerir o diagnóstico. Ex.: 'Dispneia progressiva aos esforços'"
    )
    gabarito: Gabarito
    # Cena e fala em campos separados, sem quebra de linha nem aspas: com tudo num campo
    # só o modelo escapava "\n" e aspas duas vezes e o JSON saía quebrado.
    cena: str = Field(
        description="uma frase curta, sem aspas: nome fictício, idade, local de atendimento "
        "(UBS, pronto-socorro, ambulatório) e com quem veio. Ex.: 'Lucas, 8 meses, chega à "
        "UBS com a mãe.'"
    )
    fala: str = Field(
        description="um parágrafo único, sem quebras de linha nem aspas: o que o paciente (ou "
        "o acompanhante, se criança ou incapaz) diz ao médico ao chegar, em primeira pessoa "
        "e linguagem leiga, chamando-o de 'doutor' (nunca de 'mãe'), em 5 a 8 frases curtas, "
        "cada uma com ponto final: o que "
        "sente ou notou, desde quando, como foi mudando, o que piora ou melhora, o que já "
        "tentou e o que o preocupa. Pode trazer um ou outro detalhe pessoal ou da rotina, "
        "mas deixa de fora o que só uma pergunta dirigida revelaria. PROIBIDO: termos "
        "técnicos, achados de exame físico, resultados de exames, nome ou pista explícita "
        "do diagnóstico e instruções ao estudante."
    )

    @property
    def apresentacao(self) -> str:
        """Mensagem de abertura do chat, montada aqui para o formato não depender do modelo."""
        fala = self.fala.strip().strip('"“”')
        return f'*{self.cena.strip()}*\n\n"{fala}"'


class Feedback(_Schema):
    acertou: bool
    diagnostico_correto: str = Field(description="nome do diagnóstico correto")
    acertos: list[str] = Field(
        description="o que o estudante fez ou concluiu corretamente, só o que está nas "
        "mensagens [ESTUDANTE]; o que o caso já entregou não conta como mérito"
    )
    inconsistencias: list[str] = Field(
        description="erros ou afirmações incorretas do estudante, cada um com a correção; "
        "lista vazia se não houver"
    )
    # O nome ficou de quando o campo listava diferenciais; mudar quebraria os feedbacks já
    # gravados. Hoje são lacunas da conduta — listar doenças tirava o foco do caso sorteado.
    hipoteses_nao_consideradas: list[str] = Field(
        description="lacunas na conduta do estudante: perguntas de anamnese, manobras de "
        "exame físico ou exames que faltaram para fechar o diagnóstico, e achados que ele "
        "não valorizou. Cada item é uma ação (ex.: 'Não perguntou sobre...'), nunca só o "
        "nome de uma doença. Lista vazia se a investigação cobriu o essencial"
    )
    justificativa_pedagogica: str = Field(
        description="explicação didática conectando os achados do caso à fisiopatologia "
        "do diagnóstico correto"
    )


class Achado(_Schema):
    manobra: str = Field(description="manobra, sinal ou sistema pedido. Ex.: 'Romberg'")
    achado: str = Field(
        description="resultado como se registra no prontuário: objetivo, com valores e "
        "lateralidade quando houver. Pode nomear o sinal ('Romberg positivo', 'Babinski "
        "bilateral'), mas sem conclusão ('indicando...', 'compatível com...', "
        "'sugestivo de...')"
    )


class Resultado(_Schema):
    exame: str = Field(
        description="nome do exame; em laboratório, um item por parâmetro "
        "(ex.: 'Hemograma — hemoglobina')"
    )
    resultado: str = Field(
        description="laboratório: valor e unidade. Imagem ou procedimento: o laudo completo, "
        "como sai do serviço (técnica, descrição dos achados e impressão)"
    )
    referencia: str = Field(
        description="faixa de referência do laboratório; '—' para laudos de imagem ou "
        "procedimento"
    )


class RespostaCaso(_Schema):
    """Resposta do caso a uma mensagem do estudante.

    Estruturada porque, em texto livre, o modelo respondia só à fala dirigida ao paciente
    e pulava as manobras e exames pedidos na mesma mensagem; aqui cada um tem um campo.
    """

    perguntas: list[str] = Field(
        description="cada pergunta ou tópico de história feito ao paciente nesta mensagem, "
        "inclusive dentro de discurso direto ('Eu diria: ...'); vazia se não houver"
    )
    quem_fala: str = Field(description="quem responde: 'Paciente', 'Mãe', o nome...")
    fala: str = Field(
        description="o que o paciente (ou acompanhante) diz, em primeira pessoa e linguagem "
        "leiga, sem aspas, respondendo a TODAS as perguntas, de forma natural, como ele "
        "falaria de verdade, sem limite de tamanho, mas sem ir além do perguntado. Sem "
        "perguntas: uma reação natural ao que o estudante disse ou decidiu. Só o que um "
        "leigo percebe, com palavras dele: nunca termo técnico nem achado de exame físico "
        "ou valor de exame. Vazia só se a mensagem tiver apenas exame físico ou exames"
    )
    exame_fisico: list[Achado] = Field(
        description="um item por manobra, sinal ou sistema que o estudante nomeou; vazia "
        "se não houver"
    )
    exames: list[Resultado] = Field(
        description="um item por exame complementar nomeado (laboratório: um por "
        "parâmetro, com o exame completo); vazia se não houver"
    )
    especificar: str = Field(
        description="só se a mensagem pedir exame físico ou exames de forma vaga, sem nomear "
        "nada: 'Quais sistemas você examina?' ou 'Quais exames você solicita?'. Senão, vazio"
    )


class Pedidos(_Schema):
    """O que o estudante pediu na mensagem, extraído antes de responder.

    Separado da resposta porque, com o histórico junto, o modelo imitava os turnos
    anteriores (só perguntas → só a fala do paciente) e devolvia `exames: []` mesmo com
    "solicito hemograma..." na mensagem. Lida sozinha, a mensagem não tem o que imitar.
    """

    perguntas: list[str] = Field(
        description="cada pergunta ou tópico de história dirigido ao paciente, inclusive em "
        "discurso direto ('Eu diria: ...')"
    )
    exame_fisico: list[str] = Field(
        description="cada manobra, sinal, medida ou sistema do exame físico nomeado"
    )
    exames: list[str] = Field(
        description="cada exame complementar nomeado pelo nome (laboratório, imagem, "
        "genético, procedimento diagnóstico), mesmo dentro de uma conduta"
    )
    vago: str = Field(
        description="'exame físico' ou 'exames' se o estudante pediu isso sem nomear "
        "nenhum item; senão vazio"
    )


_SYSTEM_PEDIDOS = (
    "Você lê a mensagem de um estudante de Medicina num caso clínico simulado e lista o "
    "que ele pediu, sem responder nada. Regras:\n"
    "- Toda ação nomeada conta como pedida agora, em qualquer tempo ou forma verbal: "
    "\"solicito\", \"solicitaria\", \"vou examinar\", \"pediria\", \"deve-se avaliar\", "
    "\"minhas ações seriam\", \"considerar\", \"discutir\", \"conforme avaliação\". Percorra "
    "a mensagem inteira, inclusive listas numeradas.\n"
    "- Exame nomeado dentro de uma conduta conta: \"encaminharia ao oftalmologista para "
    "fundo de olho e OCT\" → exames: fundo de olho, OCT.\n"
    "- \"Investigar\" um sintoma ou tópico concreto (\"investigar deglutição, ganho de "
    "peso\") vai para perguntas. Investigar uma doença, síndrome ou hipóteses "
    "(\"investigar epilepsia farmacorresistente\", \"condição genética\") não entra.\n"
    "- Categoria genérica sem nome de exame (\"exames metabólicos direcionados\", "
    "\"outros exames\") não entra em exames.\n"
    "- Encaminhamento, tratamento, orientação, raciocínio e hipóteses não entram em "
    "nenhuma lista.\n"
    "- Liste cada exame com o nome dado pelo estudante, um por item; não acrescente nada."
)


async def _extrair_pedidos(mensagem: str) -> Pedidos:
    return await _estruturado(
        Pedidos,
        [{"role": "system", "content": _SYSTEM_PEDIDOS}, {"role": "user", "content": mensagem}],
        temperatura=0,
        # Listar o que foi pedido é tarefa mecânica: raciocínio baixo, mesma lista (teste
        # de equivalência de 24/10 nas mensagens reais do caso de TEA e do de EM).
        raciocinio="low",
    )


def _checklist(p: Pedidos) -> str:
    """Bloco anexado à mensagem: o que a resposta tem que cobrir, item a item."""
    secoes = [
        ("Perguntas ao paciente (responda todas na `fala`)", p.perguntas),
        ("Exame físico (um item de `exame_fisico` para cada)", p.exame_fisico),
        ("Exames complementares (resultado de cada um em `exames`)", p.exames),
    ]
    linhas = [f"{titulo}:\n" + "\n".join(f"- {i}" for i in itens) for titulo, itens in secoes if itens]
    if p.vago and not (p.exame_fisico or p.exames):
        linhas.append(f"Pedido vago de {p.vago}, sem nada nomeado: preencha `especificar`.")
    if not linhas:
        return ""
    return "\n\nITENS A RESPONDER (todos, sem exceção):\n" + "\n".join(linhas)


def _formato(modelo: type[BaseModel]) -> dict:
    """`response_format` com schema garantido por constrained decoding."""
    return {
        "type": "json_schema",
        "json_schema": {
            "name": modelo.__name__.lower(),
            "schema": modelo.model_json_schema(),
            "strict": True,
        },
    }


def _openrouter() -> bool:
    return "openrouter.ai" in _BASE_URL


def _extra() -> dict:
    """Preferências de roteamento do OpenRouter; vazio em qualquer outro provedor.

    `require_parameters` só deixa o pedido cair em provedores que respeitam o schema, e
    `data_collection: deny` exclui os que treinam com o que recebem (LGPD).
    """
    if not _openrouter():
        return {}
    provider: dict = {"require_parameters": True, "data_collection": "deny"}
    if _PROVEDORES:
        provider["order"] = _PROVEDORES
    return {"provider": provider}


def _parametros(modelo: type[BaseModel], mensagens: list[dict], raciocinio: str | None = None) -> dict:
    """Argumentos de `create()` conforme o provedor aceite ou não schema estrito.

    No modo "json" (ex.: API oficial do DeepSeek, que só tem `json_object`) o schema vai
    no system prompt e quem garante o formato é a validação do Pydantic em `_estruturado`.
    """
    if _MODO_JSON == "json":
        sistema, *resto = mensagens
        schema = json.dumps(modelo.model_json_schema(), ensure_ascii=False)
        instrucao = (
            "\n\nResponda só com um objeto JSON válido que siga exatamente este JSON "
            f"Schema (todos os campos, nenhum a mais):\n{schema}"
        )
        mensagens = [{**sistema, "content": sistema["content"] + instrucao}, *resto]
        formato = {"type": "json_object"}
    else:
        formato = _formato(modelo)
    params = {"model": MODELO, "messages": mensagens, "response_format": formato}
    extra = _extra()
    # Esforço de raciocínio: tokens de raciocínio são cobrados como saída (4x a entrada).
    # O OpenRouter usa o objeto `reasoning`; Groq e OpenAI, `reasoning_effort`.
    if raciocinio and _openrouter():
        extra = {**extra, "reasoning": {"effort": raciocinio, "exclude": True}}
    elif raciocinio:
        params["reasoning_effort"] = raciocinio
    if extra:
        params["extra_body"] = extra
    return params


# Logger do uvicorn: sai formatado no stdout do container (`docker compose logs backend`).
log = logging.getLogger("uvicorn.error")


def _registrar_uso(nome: str, resp) -> None:
    """Uma linha de log por chamada: tokens, cache e custo — o gasto real, medido."""
    u = getattr(resp, "usage", None)
    if not u:
        return
    cache = getattr(getattr(u, "prompt_tokens_details", None), "cached_tokens", None) or 0
    log.info(
        "LLM %s %s: entrada=%s (cache=%s) saída=%s custo=%s",
        MODELO, nome, u.prompt_tokens, cache, u.completion_tokens, getattr(u, "cost", None),
    )


async def _estruturado(
    modelo: type[M], mensagens: list[dict], temperatura: float, raciocinio: str | None = None
) -> M:
    """Chamada ao LLM que devolve `modelo` validado — o único ponto que fala com a API.

    Uma segunda tentativa, sem loop, quando a resposta não valida: JSON quebrado, campo
    faltando ou conteúdo vazio (a doc do DeepSeek avisa que o modo JSON às vezes devolve
    vazio). O erro vai junto, para o modelo saber o que corrigir.
    """
    params = _parametros(modelo, mensagens, raciocinio)
    cliente = _client()
    erro = ""
    for _ in range(2):
        msgs = params["messages"]
        if erro:
            msgs = [*msgs, {"role": "user", "content": f"Sua resposta anterior era inválida ({erro}). Responda de novo, só com o JSON correto."}]
        resp = await cliente.chat.completions.create(**{**params, "messages": msgs}, temperature=temperatura)
        _registrar_uso(modelo.__name__, resp)
        if not resp.choices:  # 200 só com `error` (doc de erros do OpenRouter): tenta de novo
            erro = f"provedor sem resposta: {getattr(resp, 'error', None)}"
            continue
        try:
            # ValidationError e JSONDecodeError são ValueError
            return modelo.model_validate(_extrair_json(resp.choices[0].message.content or ""))
        except ValueError as e:
            erro = str(e)[:300]
    raise ValueError(f"Resposta inválida do modelo após 2 tentativas: {erro}")


def _janela(historico: list[dict], turnos: int, apos_corte: int | None = None) -> list[dict]:
    """Primeira mensagem + no máximo os últimos `turnos`.

    A primeira é preservada por ser a apresentação do caso — o enunciado, não um turno
    qualquer. Sem esse corte o custo por turno cresce sem limite numa conversa longa.

    Com `apos_corte`, o corte é em blocos: ao passar de `turnos`, o início pula para que
    sobrem `apos_corte` + 1 e fica parado até o próximo estouro. Assim o prefixo do prompt
    se repete entre chamadas e cai no cache do provedor. Sem ele, desliza a cada mensagem.
    """
    primeira, resto = historico[:1], historico[1:]
    if len(resto) <= turnos:
        return historico
    if apos_corte is None:
        return primeira + resto[-turnos:]
    bloco = turnos - apos_corte
    inicio = ((len(resto) - turnos - 1) // bloco + 1) * bloco
    return primeira + resto[inicio:]


def _gabarito(bruto: dict | Gabarito) -> Gabarito:
    """Normaliza o gabarito vindo do banco.

    Validar aqui, e não em cada uso, é o que impede um gabarito malformado de virar
    silenciosamente um diagnóstico oculto vazio no prompt do tutor.
    """
    if isinstance(bruto, Gabarito):
        return bruto
    # Casos gerados antes da ficha seguem jogáveis: o tutor improvisa, como antes.
    vazia = {"anamnese": "", "exame_fisico": "", "exames": ""}
    return Gabarito.model_validate({"ficha": vazia, **bruto})


def _client():
    from openai import AsyncOpenAI  # import preguiçoso: self-checks rodam sem a dependência

    chave = os.getenv("LLM_API_KEY")
    if not chave:
        raise RuntimeError(
            "LLM_API_KEY não definida. Copie .env.example para .env e preencha a chave."
        )
    # Cabeçalho opcional do quickstart do OpenRouter: identifica o app no painel Activity
    # (sem ele aparece "Unknown"). O HTTP-Referer entra quando houver URL pública.
    # Sem acento: cabeçalho HTTP só aceita ASCII.
    cabecalhos = {"X-OpenRouter-Title": "Simulador de Casos Clinicos (TCC)"} if _openrouter() else {}
    return AsyncOpenAI(base_url=_BASE_URL, api_key=chave, default_headers=cabecalhos)


def _extrair_json(texto: str) -> dict:
    """Parseia JSON tolerando texto/markdown ao redor do objeto."""
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        ini, fim = texto.find("{"), texto.rfind("}")
        if ini == -1 or fim <= ini:
            raise ValueError(f"Resposta sem JSON reconhecível: {texto[:200]!r}")
        return json.loads(texto[ini : fim + 1])


def _referencia(contexto: str, citar: bool = False) -> str:
    """Bloco de material de referência para o prompt (vazio se não houver RAG).

    As fontes chegam numeradas ([1], [2]...) e com o tipo. A hierarquia é o que mantém o
    caso brasileiro mesmo quando a literatura vem de fora: critério e conduta seguem o
    SUS; artigo só entra para quadro clínico e epidemiologia.
    """
    if not contexto:
        return ""
    citacao = (
        "Cite a fonte de cada afirmação clínica com o número entre colchetes logo depois "
        "dela, ex.: [1] ou [1, 2]. Use só os números do material."
        if citar
        else "Não cite fontes, números nem títulos no texto do caso."
    )
    return (
        "\n\nMATERIAL DE REFERÊNCIA — fontes numeradas, cada uma com o tipo. Para "
        "critérios diagnósticos e conduta, siga nesta ordem: PCDT (Ministério da Saúde) > "
        "Diretriz (sociedade médica) > Revisão e Relato de caso. A literatura serve só "
        "para apresentação clínica e epidemiologia; se contradisser uma diretriz "
        "brasileira, a diretriz vence. Parte do material está em inglês: escreva em "
        "português, com a terminologia e as condutas do SUS. Não copie o texto. "
        f"{citacao}\n"
        f'"""\n{contexto}\n"""'
    )


# "[1]", "[1, 2]" — com o espaço antes, para a remoção não deixar "texto ." para trás.
_CITACAO = re.compile(r"\s*\[(\d+(?:\s*,\s*\d+)*)\]")
_FONTE_NUMERADA = re.compile(r"^\[(\d+)\] ", re.MULTILINE)


def filtrar_citacoes(texto: str, validos: set[int]) -> str:
    """Mantém só as citações [n] de fontes que estão no material; o resto sai.

    O modelo pode inventar um [4] com três fontes: citação para fonte inexistente é
    pior que nenhuma, porque parece rastreável e não é.
    """

    def troca(m: re.Match) -> str:
        ns = dict.fromkeys(n for n in map(int, m.group(1).split(",")) if n in validos)
        return f" [{', '.join(map(str, ns))}]" if ns else ""

    return _CITACAO.sub(troca, texto)


async def novo_caso(
    especialidade: str, dificuldade: str, condicao: str = "", contexto: str = ""
) -> CasoGerado:
    """Gera o caso: gabarito oculto (fica só no servidor) + mensagem de abertura.

    Com `condicao`, a condição vem do sorteio no corpus curado (RN01) e os achados se
    apoiam em `contexto` (RF04). Sem ela — corpus vazio —, o modelo escolhe sozinho,
    como no protótipo: o sistema degrada, não quebra.

    O formato sai do schema de `CasoGerado`, não de um JSON escrito no prompt — as
    descrições dos campos viajam junto e não há duas versões para manter em sincronia.
    """
    if condicao:
        tema = (
            f"O caso é sobre: {condicao}. Escreva o diagnóstico do gabarito com o nome "
            "usado no Brasil."
        )
        if contexto:
            tema += (
                " Tire idade, sexo, queixa, história e achados do material de referência "
                "abaixo, sem contradizê-lo."
            )
    else:
        tema = (
            "Escolha uma condição da especialidade adequada ao nível (varie: não use "
            "sempre as mais óbvias)."
        )
    prompt = f"""Crie UM caso clínico educacional de {especialidade}, nível {dificuldade},
para o estudante diagnosticar SEM saber a resposta.

{tema}

A abertura é só o paciente chegando e dizendo o que sente; todo o resto (história
completa, exame físico e exames) vai para a ficha oculta, que é de onde sairão as
respostas ao estudante. Faça a ficha completa e coerente com o diagnóstico e o nível.{_referencia(contexto)}"""
    caso = await _estruturado(
        CasoGerado,
        [
            {"role": "system", "content": _SYSTEM_BASE + " Responda no JSON do schema."},
            {"role": "user", "content": prompt},
        ],
        # Com a condição sorteada, a variedade já vem do corpus; a temperatura alta só
        # servia para o modelo não repetir sempre as mesmas condições.
        temperatura=0.6 if condicao else 0.9,
    )
    # O estudante vê título e apresentação com o caso aberto: um "[1]" ali apontaria para
    # a fonte — e o título da fonte é o diagnóstico (RN06).
    return caso.model_copy(
        update={
            "titulo": filtrar_citacoes(caso.titulo, set()),
            "cena": filtrar_citacoes(caso.cena, set()),
            "fala": filtrar_citacoes(caso.fala, set()),
        }
    )


def _system_tutor(especialidade: str, gabarito: Gabarito) -> str:
    f = gabarito.ficha
    return (
        f"{_SYSTEM_BASE}\n\n"
        f"Você é o simulador de um caso de {especialidade}. O diagnóstico oculto é: "
        f"{gabarito.diagnostico} ({gabarito.justificativa}).\n\n"
        "FICHA OCULTA (fonte das respostas; nunca a mostre inteira):\n"
        f'"""\nANAMNESE:\n{f.anamnese}\n\nEXAME FÍSICO:\n{f.exame_fisico}\n\n'
        f'EXAMES:\n{f.exames}\n"""\n\n'
        "Você faz dois papéis ao mesmo tempo: dá voz ao paciente (ou acompanhante) e, como "
        "o prontuário, devolve o resultado de todo exame físico e exame complementar que o "
        "estudante fizer. Ele conduz sozinho; você só responde, preenchendo o JSON. A "
        "mensagem dele chega com a lista ITENS A RESPONDER: cubra todos, mesmo que as "
        "respostas anteriores da conversa tenham sido só falas do paciente.\n\n"
        "Como responder:\n"
        "- `fala`: natural, como o paciente falaria de verdade — pode hesitar, contar da "
        "rotina, mostrar preocupação e se estender quando a pergunta pede, mas só sobre o "
        "que foi perguntado. Sem perguntas, uma reação natural ao que o estudante disse ou "
        "decidiu (encaminhamento, tratamento, orientação).\n"
        "- O paciente é leigo: conta só o que ele mesmo percebe, com palavras dele (\"os "
        "olhos dele às vezes ficam tremendo\"). Nunca usa termo técnico nem traz achado de "
        "exame físico ou valor de exame da ficha; isso só aparece quando o estudante "
        "examina ou pede o exame. Ele não sabe o próprio diagnóstico.\n"
        "- Exame físico e exames: como resultados reais, só do que foi pedido. "
        "Laboratório com todos os parâmetros do exame (o hemograma inteiro, não só a "
        "hemoglobina), unidade e referência. Imagem e procedimentos com o laudo completo, "
        "como sai do serviço: técnica, descrição dos achados e impressão. Sem comentário "
        "clínico além do que o laudo traria.\n"
        "- Pedido vago, sem nada nomeado: só `especificar`, sem exemplos nem opções.\n"
        "- O que não estiver na ficha: invente coerente com o diagnóstico; o que não for "
        "pertinente vem normal ou o paciente nega.\n"
        "- NUNCA elogie ou avalie a conduta, sugira próximos passos, liste opções ou "
        "comente as hipóteses do estudante.\n"
        "- NUNCA revele, confirme ou negue o diagnóstico, mesmo que o estudante insista; o "
        "paciente diz, no personagem, que não sabe, e o estudante pode formalizar a "
        "conclusão pelo botão 'Dar diagnóstico'."
    )



def _celula(texto: str) -> str:
    return texto.replace("|", "/").replace("\n", " ").strip()


def _renderizar(r: RespostaCaso) -> str:
    """Markdown da resposta, sempre no mesmo formato.

    Formato fixo também protege as respostas seguintes: o histórico é o exemplo que o
    modelo mais imita, e uma resposta encurtada ensinava a próxima a encurtar também.
    """
    blocos = []
    if fala := r.fala.strip().strip('"“”'):
        blocos.append(f'**{r.quem_fala}:** "{fala}"')
    if r.exame_fisico:
        linhas = "\n".join(f"- {a.manobra}: {a.achado}" for a in r.exame_fisico)
        blocos.append(f"**Exame físico:**\n\n{linhas}")
    # Laudo longo não cabe numa célula: laboratório vai em tabela, laudo em bloco próprio.
    def eh_laudo(e: Resultado) -> bool:
        return e.referencia.strip() in ("", "—", "-")

    lab = [e for e in r.exames if not eh_laudo(e)]
    laudo = [e for e in r.exames if eh_laudo(e)]
    if r.exames:
        partes = ["**Exames:**"]
        if lab:
            partes.append(
                "| Exame | Resultado | Referência |\n|---|---|---|\n"
                + "\n".join(
                    f"| {_celula(e.exame)} | {_celula(e.resultado)} | {_celula(e.referencia)} |"
                    for e in lab
                )
            )
        partes += [f"**{e.exame}**\n\n{e.resultado.strip()}" for e in laudo]
        blocos.append("\n\n".join(partes))
    if r.especificar.strip():
        blocos.append(f"*{r.especificar.strip()}*")
    # Rede de segurança: com o schema, não deveria sobrar resposta vazia.
    return "\n\n".join(blocos) or f"*{r.quem_fala or 'O paciente'} aguarda.*"


async def responder_chat(
    especialidade: str, gabarito: dict | Gabarito, historico: list[dict], mensagem: str
) -> AsyncIterator[str]:
    """Responde ao estudante: extrai o que ele pediu, depois responde item a item.

    Continua um gerador para o router e o frontend, que consomem stream, não mudarem; mas
    vem num pedaço só: o JSON estruturado só vira texto depois de completo.
    """
    pedidos = await _extrair_pedidos(mensagem)
    mensagens = [
        {"role": "system", "content": _system_tutor(especialidade, _gabarito(gabarito))},
        *_janela(historico, TURNOS_CHAT, TURNOS_CHAT_APOS_CORTE),
        {"role": "user", "content": mensagem + _checklist(pedidos)},
    ]

    async def gerar(msgs: list[dict]) -> RespostaCaso:
        # baixa: aqui importa seguir as regras, não variar o texto
        return await _estruturado(RespostaCaso, msgs, temperatura=0.4)

    r = await gerar(mensagens)
    # Uma segunda chance, sem loop: se ainda assim veio vazio o que foi pedido, avisa o quê.
    faltou = [
        nome
        for nome, pedido, devolvido in (
            ("exame físico", pedidos.exame_fisico, r.exame_fisico),
            ("exames", pedidos.exames, r.exames),
        )
        if pedido and not devolvido
    ]
    if faltou:
        aviso = f"\n\nSua resposta anterior deixou vazio: {', '.join(faltou)}. Preencha."
        r = await gerar([*mensagens[:-1], {"role": "user", "content": mensagens[-1]["content"] + aviso}])
    yield _renderizar(r)


async def avaliar_diagnostico(
    especialidade: str,
    gabarito: dict | Gabarito,
    historico: list[dict],
    diagnostico: str,
    contexto: str = "",
) -> Feedback:
    """Feedback formativo (RN02: explicativo, nunca só classificatório).

    `contexto` traz o diagnóstico diferencial e a conduta da fonte do caso (RF04): é o
    que dá respaldo às hipóteses não consideradas e à justificativa pedagógica.
    """
    # Rótulos explícitos: com [assistant]/[user] o modelo creditava ao estudante achados
    # que o próprio caso tinha entregado.
    rotulo = {"user": "ESTUDANTE", "assistant": "CASO"}
    conversa = "\n".join(
        f"[{rotulo.get(m['role'], m['role'])}] {m['content']}"
        for m in _janela(historico, TURNOS_AVALIACAO)
    )
    prompt = f"""O estudante encerrou a investigação e deu seu diagnóstico final.

DIAGNÓSTICO CORRETO (gabarito): {_gabarito(gabarito).model_dump_json()}

CONVERSA DA INVESTIGAÇÃO:
\"\"\"
{conversa}
\"\"\"

DIAGNÓSTICO DO ESTUDANTE:
\"\"\"
{diagnostico}
\"\"\"

Avalie o raciocínio ao longo da investigação e o diagnóstico final. Julgue só o que o
estudante escreveu nas mensagens [ESTUDANTE]: o que o [CASO] informou não é mérito dele,
e o que ele não descreveu não foi feito. A ficha do gabarito mostra o que havia para
descobrir. Seja construtivo e explicativo; não atribua nota numérica.{_referencia(contexto, citar=True)}"""
    fb = await _estruturado(
        Feedback,
        [
            {"role": "system", "content": _SYSTEM_BASE + " Responda no JSON do schema."},
            {"role": "user", "content": prompt},
        ],
        temperatura=0.4,
    )
    validos = set(map(int, _FONTE_NUMERADA.findall(contexto)))
    return fb.model_copy(
        update={
            "acertos": [filtrar_citacoes(t, validos) for t in fb.acertos],
            "inconsistencias": [filtrar_citacoes(t, validos) for t in fb.inconsistencias],
            "hipoteses_nao_consideradas": [filtrar_citacoes(t, validos) for t in fb.hipoteses_nao_consideradas],
            "justificativa_pedagogica": filtrar_citacoes(fb.justificativa_pedagogica, validos),
        }
    )


if __name__ == "__main__":
    # Self-checks determinísticos, sem rede e sem a dependência `openai`.
    from pydantic import ValidationError

    # 1. Parser tolera ruído ao redor do objeto (rede de segurança do modo strict).
    assert _extrair_json('{"a": 1}') == {"a": 1}
    assert _extrair_json('Aqui está:\n```json\n{"a": 2}\n``` fim')["a"] == 2
    try:
        _extrair_json("sem json aqui")
        raise AssertionError("deveria ter falhado")
    except ValueError:
        pass

    # 2. Janela: preserva a apresentação do caso e corta o meio da conversa.
    curto = [{"role": "assistant", "content": "apresentação"}]
    assert _janela(curto, 8) == curto, "histórico curto passa inteiro"
    longo = [{"role": "assistant", "content": "apresentação"}] + [
        {"role": "user", "content": str(i)} for i in range(20)
    ]
    recortado = _janela(longo, 8)
    assert len(recortado) == 9, "apresentação + 8 turnos"
    assert recortado[0] == longo[0], "apresentação preservada"
    assert recortado[-1] == longo[-1], "último turno preservado"
    assert recortado[1]["content"] == "12", "corta o meio, não o fim"

    # 2b. Janela em blocos (chat): estável entre cortes, para o prefixo cair no cache.
    def conversa_de(n):
        return [{"role": "assistant", "content": "apresentação"}] + [
            {"role": "user", "content": str(i)} for i in range(n)
        ]
    assert _janela(conversa_de(12), 12, 6) == conversa_de(12), "até o máximo passa inteira"
    j13 = _janela(conversa_de(13), 12, 6)
    assert j13[0]["content"] == "apresentação" and len(j13) == 1 + 7, "ao estourar, volta perto do mínimo"
    for n in range(13, 19):  # entre dois cortes o início não se move
        j = _janela(conversa_de(n), 12, 6)
        assert j[1]["content"] == "6" and j == conversa_de(n)[:1] + conversa_de(n)[7:], n
    assert _janela(conversa_de(19), 12, 6)[1]["content"] == "12", "próximo bloco"
    assert all(6 <= len(_janela(conversa_de(n), 12, 6)) - 1 <= 12 for n in range(13, 60))

    # 3. Schema atende às exigências do json_schema strict.
    esquema = _formato(CasoGerado)["json_schema"]
    assert esquema["strict"] is True
    assert esquema["schema"]["additionalProperties"] is False
    assert set(esquema["schema"]["required"]) == {"titulo", "gabarito", "cena", "fala"}
    assert esquema["schema"]["$defs"]["Gabarito"]["additionalProperties"] is False, (
        "o modelo aninhado também precisa proibir campos extras"
    )

    # 4. Gabarito malformado falha alto, em vez de virar diagnóstico oculto vazio.
    assert _gabarito({"diagnostico": "IC", "justificativa": "..."}).diagnostico == "IC"
    for ruim in ({"diagnostico": "IC"}, {}, {"diagnostico": "IC", "justificativa": None}):
        try:
            _gabarito(ruim)
            raise AssertionError(f"gabarito inválido deveria falhar: {ruim}")
        except ValidationError:
            pass

    # 4b. Ficha: exigida na geração, opcional na leitura (casos antigos) e no prompt do tutor.
    defs = esquema["schema"]["$defs"]
    assert "ficha" in defs["Gabarito"]["required"] and defs["Ficha"]["additionalProperties"] is False
    assert set(defs["Ficha"]["required"]) == {"anamnese", "exame_fisico", "exames"}
    assert _gabarito({"diagnostico": "IC", "justificativa": "..."}).ficha.exames == "", "caso antigo"
    com_ficha = _gabarito({"diagnostico": "IC", "justificativa": "...", "ficha": {
        "anamnese": "dispneia há 2 meses", "exame_fisico": "B3", "exames": "BNP 900 pg/mL"}})
    tutor = _system_tutor("Cardiologia", com_ficha)
    assert "BNP 900 pg/mL" in tutor and "socrátic" not in tutor
    assert "Respostas curtas" not in tutor and "aguarda" not in tutor

    # 4c. Resposta do caso: schema strict e markdown montado aqui, sempre no mesmo formato.
    resp = _formato(RespostaCaso)["json_schema"]["schema"]
    assert resp["additionalProperties"] is False
    assert all(d["additionalProperties"] is False for d in resp["$defs"].values())
    vazia = dict(perguntas=[], quem_fala="Mãe", fala="", exame_fisico=[], exames=[], especificar="")
    so_fala = _renderizar(RespostaCaso(**{**vazia, "fala": '"Faz três dias, doutor."'}))
    assert so_fala == '**Mãe:** "Faz três dias, doutor."', "aspas do modelo não duplicam"
    completa = _renderizar(RespostaCaso(**{
        **vazia,
        "exame_fisico": [Achado(manobra="Romberg", achado="positivo")],
        "exames": [
            Resultado(exame="Hemograma — Hb", resultado="12 g/dL", referencia="12|16 g/dL"),
            Resultado(exame="RM de encéfalo", resultado="Lesões periventriculares.", referencia="—"),
        ],
    }))
    assert "- Romberg: positivo" in completa
    assert "| Hemograma — Hb | 12 g/dL | 12/16 g/dL |" in completa, "| na célula quebraria a tabela"
    assert "**RM de encéfalo**\n\nLesões periventriculares." in completa, "laudo fora da tabela"
    assert "**Mãe:**" not in completa, "fala vazia não vira bloco"
    assert _renderizar(RespostaCaso(**vazia)) == "*Mãe aguarda.*"
    assert _renderizar(RespostaCaso(**{**vazia, "especificar": "Quais exames você solicita?"})) == (
        "*Quais exames você solicita?*"
    )

    # 4d. Pedidos extraídos antes da resposta e o checklist que vai junto da mensagem.
    ped = _formato(Pedidos)["json_schema"]["schema"]
    assert ped["additionalProperties"] is False
    assert set(ped["required"]) == {"perguntas", "exame_fisico", "exames", "vago"}
    nada = dict(perguntas=[], exame_fisico=[], exames=[], vago="")
    assert _checklist(Pedidos(**nada)) == "", "sem pedidos, a mensagem segue intacta"
    lista = _checklist(Pedidos(**{**nada, "perguntas": ["casos na família?"], "exames": ["TSH", "exoma"]}))
    assert lista.startswith("\n\nITENS A RESPONDER") and "- TSH\n- exoma" in lista
    assert "casos na família?" in lista and "Exame físico" not in lista
    assert "especificar" in _checklist(Pedidos(**{**nada, "vago": "exames"}))
    assert "especificar" not in _checklist(Pedidos(**{**nada, "vago": "exames", "exames": ["TSH"]}))

    # 5. Caso sem as chaves do gabarito não passa (antes passava e quebrava em silêncio).
    try:
        CasoGerado.model_validate(
            {"titulo": "t", "gabarito": {"diagnostico": "IC"}, "cena": "c", "fala": "f"}
        )
        raise AssertionError("caso com gabarito incompleto deveria falhar")
    except ValidationError:
        pass

    # 6. Bloco de referência só aparece com RAG — sem corpus, o prompt é o do protótipo.
    assert _referencia("") == ""
    assert "## Diagnóstico" in _referencia("## Diagnóstico\n\nECG") and "Ministério da Saúde" in _referencia("x")
    assert "Cite a fonte" in _referencia("x", citar=True) and "Não cite" in _referencia("x")

    # 7. Citações: só as de fontes que existem no material; o resto some sem deixar
    #    espaço sobrando. O número das fontes sai do próprio contexto.
    assert filtrar_citacoes("Troponina elevada [1].", {1}) == "Troponina elevada [1]."
    assert filtrar_citacoes("ECG [1, 4] e eco [3].", {1, 2}) == "ECG [1] e eco."
    assert filtrar_citacoes("Sem citação [2] .", set()) == "Sem citação ."
    assert filtrar_citacoes("Duplicada [2,2].", {2}) == "Duplicada [2]."
    assert filtrar_citacoes("Ano 2024 e lista [a].", {1}) == "Ano 2024 e lista [a].", "só números entre colchetes"
    ctx = "[1] PCDT — Asma (MS, 2026)\n\n## Diagnóstico\n\ntexto [9]\n\n[2] Diretriz — X (Y, 2025)"
    assert set(map(int, _FONTE_NUMERADA.findall(ctx))) == {1, 2}, "[9] no meio do texto não é fonte"

    # 8. Camada do provedor: modo do JSON, roteamento do OpenRouter e segunda tentativa.
    import asyncio
    from types import SimpleNamespace

    msgs = [{"role": "system", "content": "sis"}, {"role": "user", "content": "oi"}]
    _MODO_JSON = "estrito"
    p = _parametros(Pedidos, msgs)
    assert p["response_format"]["json_schema"]["strict"] is True and p["messages"] == msgs
    _MODO_JSON = "json"
    p = _parametros(Pedidos, msgs)
    assert p["response_format"] == {"type": "json_object"}
    assert '"perguntas"' in p["messages"][0]["content"] and msgs[0]["content"] == "sis", (
        "schema vai no system prompt sem alterar a lista original"
    )
    _MODO_JSON = "estrito"

    _BASE_URL, _PROVEDORES = "https://openrouter.ai/api/v1", ["deepinfra", "parasail"]
    prov = _extra()["provider"]
    assert prov["order"] == ["deepinfra", "parasail"] and prov["require_parameters"] is True
    assert prov["data_collection"] == "deny"
    _PROVEDORES = []
    assert "order" not in _extra()["provider"]
    _BASE_URL = "https://api.groq.com/openai/v1"
    assert _extra() == {} and "extra_body" not in _parametros(Pedidos, msgs), (
        "fora do OpenRouter não manda campo que o provedor não conhece"
    )

    def cliente_falso(respostas: list[str]):
        chamadas = []

        async def create(**kw):
            chamadas.append(kw["messages"])
            texto = respostas.pop(0)
            if texto is None:  # 200 sem `choices`
                return SimpleNamespace(choices=None)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=texto))])

        return chamadas, SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    ok = '{"perguntas": [], "exame_fisico": [], "exames": ["TSH"], "vago": ""}'
    chamadas, falso = cliente_falso(["", ok])
    cliente_real = _client
    _client = lambda: falso  # noqa: E731
    assert asyncio.run(_estruturado(Pedidos, msgs, 0)).exames == ["TSH"], "vazio → 2ª tentativa"
    assert len(chamadas) == 2 and "inválida" in chamadas[1][-1]["content"], "o erro vai junto"
    chamadas, falso = cliente_falso(['{"perguntas": []}', "nada"])
    try:
        asyncio.run(_estruturado(Pedidos, msgs, 0))
        raise AssertionError("duas respostas inválidas deveriam falhar")
    except ValueError:
        pass
    assert len(chamadas) == 2, "sem loop: no máximo duas chamadas"

    # 200 sem `choices` (provedor aqueceu/escalou) também ganha a segunda tentativa.
    chamadas, falso = cliente_falso([None, ok])
    assert asyncio.run(_estruturado(Pedidos, msgs, 0)).exames == ["TSH"] and len(chamadas) == 2

    # Esforço de raciocínio: objeto `reasoning` no OpenRouter, `reasoning_effort` fora dele.
    _BASE_URL = "https://openrouter.ai/api/v1"
    p = _parametros(Pedidos, msgs, "low")
    assert p["extra_body"]["reasoning"] == {"effort": "low", "exclude": True} and "reasoning_effort" not in p
    assert "reasoning" not in _parametros(Pedidos, msgs)["extra_body"], "sem o parâmetro, padrão do modelo"
    _BASE_URL = "https://api.groq.com/openai/v1"
    p = _parametros(Pedidos, msgs, "low")
    assert p["reasoning_effort"] == "low" and "extra_body" not in p
    assert "reasoning_effort" not in _parametros(Pedidos, msgs)

    # Cabeçalho de identificação só vai para o OpenRouter (cliente real, sem rede).
    os.environ.setdefault("LLM_API_KEY", "chave-de-teste")
    _BASE_URL = "https://openrouter.ai/api/v1"
    assert cliente_real().default_headers.get("X-OpenRouter-Title", "é").isascii(), "header só ASCII"
    _BASE_URL = "https://api.groq.com/openai/v1"
    assert "X-OpenRouter-Title" not in cliente_real().default_headers

    print("OK: parser, janela deslizante, schema strict, gabarito, bloco de referência, citações e provedor.")
