import { useEffect, useRef } from 'react'
import { Stethoscope } from 'lucide-react'
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
  onNovoCaso: () => void
}

export default function ChatWindow({
  mensagens,
  digitando,
  feedback,
  fontes,
  erro,
  temCaso,
  onNovoCaso,
}: Props) {
  const fimRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    fimRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [mensagens, digitando, feedback])

  if (!temCaso) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center px-6 text-center">
        <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-teal-600/10">
          <Stethoscope className="h-7 w-7 text-teal-600" />
        </div>
        <h2 className="mb-2 text-xl font-semibold text-zinc-900">
          Bem-vindo ao Simulador Clínico
        </h2>
        <p className="mb-6 max-w-md text-sm leading-relaxed text-zinc-500">
          Escolha uma especialidade e o seu ciclo do curso na barra lateral e inicie um novo
          caso. Você conduzirá a investigação — anamnese, exame físico, exames e conduta — sem
          conhecer o diagnóstico, e receberá feedback ao final, no nível do seu ciclo.
        </p>
        <button
          onClick={onNovoCaso}
          className="rounded-lg bg-teal-600 px-5 py-2.5 text-sm font-medium text-white
                     transition-colors hover:bg-teal-500"
        >
          Iniciar um caso
        </button>
      </div>
    )
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
            <div className="flex justify-center pb-2">
              <button
                onClick={onNovoCaso}
                className="rounded-lg bg-teal-600 px-5 py-2.5 text-sm font-medium text-white
                           transition-colors hover:bg-teal-500"
              >
                Iniciar novo caso
              </button>
            </div>
          </>
        )}
        <div ref={fimRef} />
      </div>
    </div>
  )
}
