import { useEffect, useRef, type ReactNode } from 'react'
import Message, { Digitando } from './Message'
import FeedbackCard from './FeedbackCard'
import type { Feedback, Fonte, Mensagem } from '../types'

interface Props {
  mensagens: Mensagem[]
  digitando: boolean
  feedback: Feedback | null
  fontes: Fonte[]
  erro: string | null
  temCaso: boolean
  inicio: ReactNode // sem caso ativo: o seletor de temas
  aposFeedback: ReactNode // próximo caso do simulado, ou o resumo
}

export default function ChatWindow({
  mensagens,
  digitando,
  feedback,
  fontes,
  erro,
  temCaso,
  inicio,
  aposFeedback,
}: Props) {
  const fimRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    fimRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [mensagens, digitando, feedback])

  if (!temCaso) {
    return <div className="flex-1 overflow-y-auto">{inicio}</div>
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-3xl space-y-6 px-4 py-6">
        {mensagens.map((m, i) => (
          <Message key={i} msg={m} />
        ))}
        {digitando && <Digitando />}
        {erro && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {erro}
          </div>
        )}
        {feedback && (
          <>
            <FeedbackCard fb={feedback} fontes={fontes} />
            {aposFeedback}
          </>
        )}
        <div ref={fimRef} />
      </div>
    </div>
  )
}
