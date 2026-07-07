"""Integração com a IA Generativa (Groq) — motor lógico do simulador de casos clínicos.

Três funções expostas:
- novo_caso():           sorteia uma condição oculta na especialidade e abre o caso (JSON mode)
- responder_chat():      responde ao estudante como paciente/tutor, em streaming
- avaliar_diagnostico(): feedback formativo estruturado ao fechar o diagnóstico (JSON mode)
"""

import json
import os
from collections.abc import Iterator

MODELO = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

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


def _client():
    from groq import Groq  # import preguiçoso: self-checks rodam sem a dependência

    chave = os.getenv("GROQ_API_KEY")
    if not chave:
        raise RuntimeError(
            "GROQ_API_KEY não definida. Copie .env.example para .env e preencha a chave."
        )
    return Groq(api_key=chave)


def _extrair_json(texto: str) -> dict:
    """Parseia JSON tolerando texto/markdown ao redor do objeto."""
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        ini, fim = texto.find("{"), texto.rfind("}")
        if ini == -1 or fim <= ini:
            raise ValueError(f"Resposta sem JSON reconhecível: {texto[:200]!r}")
        return json.loads(texto[ini : fim + 1])


def novo_caso(especialidade: str, dificuldade: str) -> dict:
    """Gera o caso: gabarito oculto (fica só no servidor) + mensagem de abertura."""
    prompt = f"""Crie UM caso clínico educacional de {especialidade}, nível {dificuldade},
para o estudante diagnosticar SEM saber a resposta.

Escolha uma condição da especialidade adequada ao nível (varie: não use sempre as mais óbvias).

Responda apenas com JSON, com exatamente estas chaves:
{{
  "titulo": "título curto (3 a 6 palavras) baseado na queixa/apresentação, SEM revelar nem sugerir o diagnóstico. Ex.: 'Dispneia progressiva aos esforços'",
  "gabarito": {{
    "diagnostico": "diagnóstico correto",
    "justificativa": "raciocínio fisiopatológico e achados-chave que fecham o diagnóstico"
  }},
  "apresentacao": "Texto de abertura em markdown apresentando o paciente: identificação (idade, sexo, contexto), queixa principal e breve história inicial contada de forma natural, como um preceptor apresentando o caso. NÃO revele nem sugira o diagnóstico. Termine convidando o estudante a conduzir a investigação (anamnese, exame físico, exames)."
}}"""
    resp = _client().chat.completions.create(
        model=MODELO,
        messages=[
            {"role": "system", "content": _SYSTEM_BASE + " Responda apenas com JSON válido."},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.9,  # variedade de condições entre casos
    )
    caso = _extrair_json(resp.choices[0].message.content)
    if any(chave not in caso for chave in ("titulo", "gabarito", "apresentacao")):
        raise ValueError(f"Caso gerado sem as chaves esperadas: {list(caso)}")
    return caso


def _system_tutor(especialidade: str, gabarito: dict) -> str:
    return (
        f"{_SYSTEM_BASE}\n\n"
        f"Você conduz um caso simulado de {especialidade}. O diagnóstico oculto do caso é: "
        f"{gabarito.get('diagnostico', '?')} ({gabarito.get('justificativa', '')}).\n\n"
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


def responder_chat(
    especialidade: str, gabarito: dict, historico: list[dict], mensagem: str
) -> Iterator[str]:
    """Responde ao estudante em streaming (chunks de texto)."""
    stream = _client().chat.completions.create(
        model=MODELO,
        messages=[
            {"role": "system", "content": _system_tutor(especialidade, gabarito)},
            *historico,
            {"role": "user", "content": mensagem},
        ],
        temperature=0.6,
        stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


def avaliar_diagnostico(
    especialidade: str, gabarito: dict, historico: list[dict], diagnostico: str
) -> dict:
    """Feedback formativo (RN02: explicativo, nunca só classificatório)."""
    conversa = "\n".join(f"[{m['role']}] {m['content']}" for m in historico)
    prompt = f"""O estudante encerrou a investigação e deu seu diagnóstico final.

DIAGNÓSTICO CORRETO (gabarito): {json.dumps(gabarito, ensure_ascii=False)}

CONVERSA DA INVESTIGAÇÃO:
\"\"\"
{conversa}
\"\"\"

DIAGNÓSTICO DO ESTUDANTE:
\"\"\"
{diagnostico}
\"\"\"

Avalie o raciocínio ao longo da investigação e o diagnóstico final. Responda apenas com JSON:
{{
  "acertou": true/false,
  "diagnostico_correto": "nome do diagnóstico correto",
  "acertos": ["o que o estudante fez/identificou corretamente na investigação e conclusão"],
  "inconsistencias": ["erros ou afirmações incorretas, cada um com a correção"],
  "hipoteses_nao_consideradas": ["diferenciais ou achados relevantes que faltaram"],
  "justificativa_pedagogica": "explicação didática conectando os achados do caso à fisiopatologia do diagnóstico correto"
}}
Seja construtivo e explicativo; não atribua nota numérica."""
    resp = _client().chat.completions.create(
        model=MODELO,
        messages=[
            {"role": "system", "content": _SYSTEM_BASE + " Responda apenas com JSON válido."},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.4,
    )
    return _extrair_json(resp.choices[0].message.content)


if __name__ == "__main__":
    # Self-check do parser (sem rede): deve extrair o objeto mesmo com ruído ao redor.
    assert _extrair_json('{"a": 1}') == {"a": 1}
    assert _extrair_json('Aqui está:\n```json\n{"a": 2}\n``` fim')["a"] == 2
    try:
        _extrair_json("sem json aqui")
        raise AssertionError("deveria ter falhado")
    except ValueError:
        pass
    print("OK: _extrair_json tolera ruído ao redor do objeto.")
