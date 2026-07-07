export interface Opcoes {
  especialidades: string[]
  dificuldades: string[]
}

export interface CasoAberto {
  caso_id: string
  apresentacao: string
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
