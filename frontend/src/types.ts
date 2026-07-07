export interface Opcoes {
  especialidades: string[]
  dificuldades: string[]
}

export interface Usuario {
  nome: string
  email: string
}

export interface CasoAberto {
  caso_id: string
  titulo: string
  apresentacao: string
}

export interface ConversaResumo {
  id: string
  titulo: string
  especialidade: string
  status: 'aberta' | 'encerrada'
  criada_em: string
}

export interface ConversaCompleta {
  id: string
  titulo: string
  especialidade: string
  status: 'aberta' | 'encerrada'
  mensagens: Mensagem[]
  feedback: Feedback | null
}

export interface Feedback {
  acertou: boolean
  diagnostico_correto: string
  acertos: string[]
  inconsistencias: string[]
  hipoteses_nao_consideradas: string[]
  justificativa_pedagogica: string
}

export interface Mensagem {
  role: 'user' | 'assistant'
  content: string
}
