import type { CasoAberto, Feedback, Opcoes } from './types'

async function checar(res: Response): Promise<Response> {
  if (!res.ok) {
    const corpo = await res.json().catch(() => null)
    throw new Error(corpo?.detail ?? `Erro ${res.status} na API`)
  }
  return res
}

const json = { 'Content-Type': 'application/json' }

export async function buscarOpcoes(): Promise<Opcoes> {
  return (await checar(await fetch('/api/especialidades'))).json()
}

export async function criarCaso(
  especialidade: string,
  dificuldade: string,
): Promise<CasoAberto> {
  const res = await fetch('/api/casos', {
    method: 'POST',
    headers: json,
    body: JSON.stringify({ especialidade, dificuldade }),
  })
  return (await checar(res)).json()
}

/** Envia uma mensagem e consome a resposta em streaming, chunk a chunk. */
export async function enviarMensagem(
  casoId: string,
  mensagem: string,
  onChunk: (texto: string) => void,
): Promise<void> {
  const res = await fetch(`/api/casos/${casoId}/mensagens`, {
    method: 'POST',
    headers: json,
    body: JSON.stringify({ mensagem }),
  })
  await checar(res)
  const reader = res.body!.getReader()
  const decoder = new TextDecoder()
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    onChunk(decoder.decode(value, { stream: true }))
  }
}

export async function enviarDiagnostico(
  casoId: string,
  diagnostico: string,
): Promise<Feedback> {
  const res = await fetch(`/api/casos/${casoId}/diagnostico`, {
    method: 'POST',
    headers: json,
    body: JSON.stringify({ diagnostico }),
  })
  return (await checar(res)).json()
}
