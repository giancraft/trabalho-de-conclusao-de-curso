import type {
  CasoAberto,
  ConversaCompleta,
  ConversaResumo,
  Feedback,
  Opcoes,
  RespostaFinal,
  Simulado,
  Usuario,
} from './types'

async function checar(res: Response): Promise<Response> {
  if (!res.ok) {
    const corpo = await res.json().catch(() => null)
    throw new Error(corpo?.detail ?? `Erro ${res.status} na API`)
  }
  return res
}

const json = { 'Content-Type': 'application/json' }

/** Árvore de temas (com o progresso do estudante em cada nó) e os ciclos. */
export async function buscarOpcoes(): Promise<Opcoes> {
  return (await checar(await fetch('/api/temas'))).json()
}

// --- autenticação (cookie httpOnly gerenciado pelo navegador) ---

export async function registrar(nome: string, email: string, senha: string): Promise<Usuario> {
  const res = await fetch('/api/auth/registro', {
    method: 'POST',
    headers: json,
    body: JSON.stringify({ nome, email, senha }),
  })
  return (await checar(res)).json()
}

export async function login(email: string, senha: string): Promise<Usuario> {
  const res = await fetch('/api/auth/login', {
    method: 'POST',
    headers: json,
    body: JSON.stringify({ email, senha }),
  })
  return (await checar(res)).json()
}

export async function logout(): Promise<void> {
  await checar(await fetch('/api/auth/logout', { method: 'POST' }))
}

/** Usuário da sessão atual, ou null se não autenticado. */
export async function eu(): Promise<Usuario | null> {
  const res = await fetch('/api/auth/eu')
  if (res.status === 401) return null
  return (await checar(res)).json()
}

// --- histórico de conversas ---

export async function listarConversas(): Promise<ConversaResumo[]> {
  const res = await checar(await fetch('/api/conversas'))
  return (await res.json()).conversas
}

export async function carregarConversa(id: string): Promise<ConversaCompleta> {
  return (await checar(await fetch(`/api/conversas/${id}`))).json()
}

export async function apagarConversa(id: string): Promise<void> {
  await checar(await fetch(`/api/conversas/${id}`, { method: 'DELETE' }))
}

// --- simulados: N casos sorteados dos temas marcados, gerados um a um ---

export async function criarSimulado(
  selecao: string[],
  ciclo: string,
  quantidade: number,
): Promise<CasoAberto> {
  const res = await fetch('/api/simulados', {
    method: 'POST',
    headers: json,
    body: JSON.stringify({ selecao, ciclo, quantidade }),
  })
  return (await checar(res)).json()
}

export async function proximoCaso(simuladoId: string): Promise<CasoAberto> {
  return (await checar(await fetch(`/api/simulados/${simuladoId}/proximo`, { method: 'POST' }))).json()
}

export async function lerSimulado(simuladoId: string): Promise<Simulado> {
  return (await checar(await fetch(`/api/simulados/${simuladoId}`))).json()
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
  resposta: RespostaFinal,
): Promise<Feedback> {
  const res = await fetch(`/api/casos/${casoId}/diagnostico`, {
    method: 'POST',
    headers: json,
    body: JSON.stringify(resposta),
  })
  return (await checar(res)).json()
}
