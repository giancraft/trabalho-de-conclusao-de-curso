import type {
  AvaliacaoRAG,
  CasoAberto,
  ConfigIA,
  ConfiguracaoLeitura,
  ConversaCompleta,
  ConversaResumo,
  Desempenho,
  DesempenhoIA,
  Feedback,
  Opcoes,
  QualidadeIA,
  RespostaFinal,
  Simulado,
  Usuario,
} from './types'

async function checar(res: Response): Promise<Response> {
  if (!res.ok) {
    const corpo = await res.json().catch(() => null)
    // 422 de validação do FastAPI traz uma lista de erros; os nossos, uma frase.
    const detalhe = Array.isArray(corpo?.detail)
      ? corpo.detail.map((d: { msg: string }) => d.msg.replace(/^Value error, /, '')).join('; ')
      : corpo?.detail
    throw new Error(detalhe ?? `Erro ${res.status} na API`)
  }
  return res
}

const json = { 'Content-Type': 'application/json' }

/** Árvore de temas (com o progresso do estudante em cada nó) e os ciclos. */
export async function buscarOpcoes(): Promise<Opcoes> {
  return (await checar(await fetch('/api/temas'))).json()
}

// --- autenticação (cookie httpOnly gerenciado pelo navegador) ---

export async function registrar(
  nome: string,
  email: string,
  senha: string,
  aceite: boolean,
): Promise<Usuario> {
  const res = await fetch('/api/auth/registro', {
    method: 'POST',
    headers: json,
    body: JSON.stringify({ nome, email, senha, aceite }),
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

// --- conta do usuário (LGPD) ---

export async function editarConta(nome: string, email: string): Promise<Usuario> {
  const res = await fetch('/api/auth/eu', { method: 'PATCH', headers: json, body: JSON.stringify({ nome, email }) })
  return (await checar(res)).json()
}

export async function consentir(): Promise<Usuario> {
  return (await checar(await fetch('/api/auth/consentimento', { method: 'POST' }))).json()
}

/** Todos os dados do usuário, como texto JSON (o componente oferece para baixar). */
export async function meusDados(): Promise<string> {
  return (await checar(await fetch('/api/auth/meus-dados'))).text()
}

export async function excluirConta(senha: string): Promise<void> {
  await checar(await fetch('/api/auth/conta', { method: 'DELETE', headers: json, body: JSON.stringify({ senha }) }))
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

/** Painel do estudante: KPIs, evolução, recortes e recomendações (calculados no servidor). */
export async function buscarDesempenho(): Promise<Desempenho> {
  return (await checar(await fetch('/api/desempenho'))).json()
}

// --- área do administrador (o backend responde 403 para estudante) ---

export async function desempenhoIA(dias: number): Promise<DesempenhoIA> {
  return (await checar(await fetch(`/api/admin/ia/desempenho?dias=${dias}`))).json()
}

export async function qualidadeIA(): Promise<QualidadeIA> {
  return (await checar(await fetch('/api/admin/ia/qualidade'))).json()
}

export async function avaliarRAG(): Promise<AvaliacaoRAG> {
  return (await checar(await fetch('/api/admin/ia/avaliacao-rag', { method: 'POST' }))).json()
}

export async function lerConfigIA(): Promise<ConfiguracaoLeitura> {
  return (await checar(await fetch('/api/admin/ia/configuracao'))).json()
}

export async function salvarConfigIA(config: ConfigIA): Promise<ConfiguracaoLeitura> {
  const res = await fetch('/api/admin/ia/configuracao', { method: 'PUT', headers: json, body: JSON.stringify(config) })
  return (await checar(res)).json()
}

export async function restaurarConfigIA(id: number): Promise<ConfiguracaoLeitura> {
  return (await checar(await fetch(`/api/admin/ia/configuracao/${id}/restaurar`, { method: 'POST' }))).json()
}
