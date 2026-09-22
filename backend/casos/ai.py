"""Integração com a IA Generativa (Groq) — motor lógico do simulador de casos clínicos.

Três funções expostas:
- novo_caso():           sorteia uma condição oculta na especialidade e abre o caso
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
from collections.abc import AsyncIterator

from pydantic import BaseModel, ConfigDict, Field

MODELO = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

# Turnos de conversa enviados ao modelo. O chat recorta para manter o custo por turno
# estável (e histórico inchado dispersa o modelo); a avaliação leva quase tudo, porque
# o que ela julga é o raciocínio ao longo de toda a investigação (RF07).
TURNOS_CHAT = 8
TURNOS_AVALIACAO = 30

ESPECIALIDADES = [
    "Cardiologia",
    "Pneumologia",
    "Endocrinologia",
    "Gastroenterologia",
    "Neurologia",
    "Nefrologia",
    "Infectologia",
    "Oncologia",
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


async def novo_caso(especialidade: str, dificuldade: str) -> CasoGerado:
    """Gera o caso: gabarito oculto (fica só no servidor) + mensagem de abertura.

    O formato sai do schema de `CasoGerado`, não de um JSON escrito no prompt — as
    descrições dos campos viajam junto e não há duas versões para manter em sincronia.
    """
    prompt = f"""Crie UM caso clínico educacional de {especialidade}, nível {dificuldade},
para o estudante diagnosticar SEM saber a resposta.

Escolha uma condição da especialidade adequada ao nível (varie: não use sempre as mais óbvias)."""
    resp = await _client().chat.completions.create(
        model=MODELO,
        messages=[
            {"role": "system", "content": _SYSTEM_BASE + " Responda no JSON do schema."},
            {"role": "user", "content": prompt},
        ],
        response_format=_formato(CasoGerado),
        temperature=0.9,  # variedade de condições entre casos
    )
    return CasoGerado.model_validate(_extrair_json(resp.choices[0].message.content))


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
    especialidade: str, gabarito: dict | Gabarito, historico: list[dict], diagnostico: str
) -> Feedback:
    """Feedback formativo (RN02: explicativo, nunca só classificatório)."""
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
Seja construtivo e explicativo; não atribua nota numérica."""
    resp = await _client().chat.completions.create(
        model=MODELO,
        messages=[
            {"role": "system", "content": _SYSTEM_BASE + " Responda no JSON do schema."},
            {"role": "user", "content": prompt},
        ],
        response_format=_formato(Feedback),
        temperature=0.4,
    )
    return Feedback.model_validate(_extrair_json(resp.choices[0].message.content))


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

    print("OK: parser, janela deslizante, schema strict e validação do gabarito.")
