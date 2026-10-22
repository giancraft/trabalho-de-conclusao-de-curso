"""Integração com a IA Generativa (Groq) — motor lógico do simulador de casos clínicos.

Três funções expostas:
- novo_caso():           abre o caso sobre a condição sorteada no corpus (RF04)
- responder_chat():      responde ao estudante como paciente/tutor, em streaming
- avaliar_diagnostico(): feedback formativo estruturado ao fechar o diagnóstico

As duas chamadas estruturadas usam o modo `strict` da Groq: o schema sai dos modelos
Pydantic abaixo e é garantido por constrained decoding, então não há um JSON escrito
no prompt para manter em sincronia. `_extrair_json` fica como rede de segurança.

As três são `async` (AsyncGroq): chamada de LLM é espera de rede, e um worker bloqueado
nela é um worker que não atende mais ninguém.
"""

import json
import os
import re
from collections.abc import AsyncIterator

from pydantic import BaseModel, ConfigDict, Field

MODELO = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

# Turnos de conversa enviados ao modelo. O chat recorta para manter o custo por turno
# estável (e histórico inchado dispersa o modelo); a avaliação leva quase tudo, porque
# o que ela julga é o raciocínio ao longo de toda a investigação (RF07).
TURNOS_CHAT = 8
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


class _Schema(BaseModel):
    """Base dos schemas trocados com o modelo.

    `extra="forbid"` emite `additionalProperties: false`, exigido pelo modo `strict`
    da Groq (junto com todos os campos obrigatórios).
    """

    model_config = ConfigDict(extra="forbid")


class Gabarito(_Schema):
    diagnostico: str = Field(description="diagnóstico correto")
    justificativa: str = Field(
        description="raciocínio fisiopatológico e achados-chave que fecham o diagnóstico"
    )


class CasoGerado(_Schema):
    titulo: str = Field(
        description="título curto (3 a 6 palavras) baseado na queixa/apresentação, SEM "
        "revelar nem sugerir o diagnóstico. Ex.: 'Dispneia progressiva aos esforços'"
    )
    gabarito: Gabarito
    apresentacao: str = Field(
        description="Texto de abertura em markdown apresentando o paciente: identificação "
        "(idade, sexo, contexto), queixa principal e breve história inicial contada de forma "
        "natural, como um preceptor apresentando o caso. NÃO revele nem sugira o diagnóstico. "
        "Termine convidando o estudante a conduzir a investigação (anamnese, exame físico, exames)."
    )


class Feedback(_Schema):
    acertou: bool
    diagnostico_correto: str = Field(description="nome do diagnóstico correto")
    acertos: list[str] = Field(
        description="o que o estudante fez/identificou corretamente na investigação e conclusão"
    )
    inconsistencias: list[str] = Field(
        description="erros ou afirmações incorretas, cada um com a correção"
    )
    hipoteses_nao_consideradas: list[str] = Field(
        description="diferenciais ou achados relevantes que faltaram"
    )
    justificativa_pedagogica: str = Field(
        description="explicação didática conectando os achados do caso à fisiopatologia "
        "do diagnóstico correto"
    )


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


def _janela(historico: list[dict], turnos: int) -> list[dict]:
    """Primeira mensagem + os últimos `turnos`.

    A primeira é preservada por ser a apresentação do caso — o enunciado, não um turno
    qualquer. Sem esse corte o custo por turno cresce sem limite numa conversa longa.
    """
    if len(historico) <= turnos + 1:
        return historico
    return historico[:1] + historico[-turnos:]


def _gabarito(bruto: dict | Gabarito) -> Gabarito:
    """Normaliza o gabarito vindo do banco.

    Validar aqui, e não em cada uso, é o que impede um gabarito malformado de virar
    silenciosamente um diagnóstico oculto vazio no prompt do tutor.
    """
    return bruto if isinstance(bruto, Gabarito) else Gabarito.model_validate(bruto)


def _client():
    from groq import AsyncGroq  # import preguiçoso: self-checks rodam sem a dependência

    chave = os.getenv("GROQ_API_KEY")
    if not chave:
        raise RuntimeError(
            "GROQ_API_KEY não definida. Copie .env.example para .env e preencha a chave."
        )
    return AsyncGroq(api_key=chave)


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

{tema}{_referencia(contexto)}"""
    resp = await _client().chat.completions.create(
        model=MODELO,
        messages=[
            {"role": "system", "content": _SYSTEM_BASE + " Responda no JSON do schema."},
            {"role": "user", "content": prompt},
        ],
        response_format=_formato(CasoGerado),
        # Com a condição sorteada, a variedade já vem do corpus; a temperatura alta só
        # servia para o modelo não repetir sempre as mesmas condições.
        temperature=0.6 if condicao else 0.9,
    )
    caso = CasoGerado.model_validate(_extrair_json(resp.choices[0].message.content))
    # O estudante vê título e apresentação com o caso aberto: um "[1]" ali apontaria para
    # a fonte — e o título da fonte é o diagnóstico (RN06).
    return caso.model_copy(
        update={
            "titulo": filtrar_citacoes(caso.titulo, set()),
            "apresentacao": filtrar_citacoes(caso.apresentacao, set()),
        }
    )


def _system_tutor(especialidade: str, gabarito: Gabarito) -> str:
    return (
        f"{_SYSTEM_BASE}\n\n"
        f"Você conduz um caso simulado de {especialidade}. O diagnóstico oculto do caso é: "
        f"{gabarito.diagnostico} ({gabarito.justificativa}).\n\n"
        "Regras da simulação:\n"
        "- Atue como paciente (respondendo à anamnese em primeira pessoa) e como preceptor "
        "(fornecendo achados de exame físico e resultados de exames quando solicitados).\n"
        "- Todos os achados devem ser clinicamente coerentes com o diagnóstico oculto.\n"
        "- NUNCA revele, confirme ou negue o diagnóstico, mesmo que o estudante pergunte "
        "diretamente ou insista; nesse caso, oriente-o a formalizar sua conclusão pelo botão "
        "'Dar diagnóstico'.\n"
        "- Não liste hipóteses diagnósticas prontas; estimule o raciocínio com perguntas "
        "socráticas curtas quando apropriado.\n"
        "- Respostas concisas, em markdown simples."
    )


async def responder_chat(
    especialidade: str, gabarito: dict | Gabarito, historico: list[dict], mensagem: str
) -> AsyncIterator[str]:
    """Responde ao estudante em streaming (chunks de texto)."""
    stream = await _client().chat.completions.create(
        model=MODELO,
        messages=[
            {"role": "system", "content": _system_tutor(especialidade, _gabarito(gabarito))},
            *_janela(historico, TURNOS_CHAT),
            {"role": "user", "content": mensagem},
        ],
        temperature=0.6,
        stream=True,
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


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
    conversa = "\n".join(
        f"[{m['role']}] {m['content']}" for m in _janela(historico, TURNOS_AVALIACAO)
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

Avalie o raciocínio ao longo da investigação e o diagnóstico final.
Seja construtivo e explicativo; não atribua nota numérica.{_referencia(contexto, citar=True)}"""
    resp = await _client().chat.completions.create(
        model=MODELO,
        messages=[
            {"role": "system", "content": _SYSTEM_BASE + " Responda no JSON do schema."},
            {"role": "user", "content": prompt},
        ],
        response_format=_formato(Feedback),
        temperature=0.4,
    )
    fb = Feedback.model_validate(_extrair_json(resp.choices[0].message.content))
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
    # Self-checks determinísticos, sem rede e sem a dependência `groq`.
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

    # 3. Schema atende às exigências do modo strict da Groq.
    esquema = _formato(CasoGerado)["json_schema"]
    assert esquema["strict"] is True
    assert esquema["schema"]["additionalProperties"] is False
    assert set(esquema["schema"]["required"]) == {"titulo", "gabarito", "apresentacao"}
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

    # 5. Caso sem as chaves do gabarito não passa (antes passava e quebrava em silêncio).
    try:
        CasoGerado.model_validate(
            {"titulo": "t", "gabarito": {"diagnostico": "IC"}, "apresentacao": "a"}
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

    print("OK: parser, janela deslizante, schema strict, gabarito, bloco de referência e citações.")
