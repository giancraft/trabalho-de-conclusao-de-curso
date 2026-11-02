import { useEffect, useRef, type ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'
import termo from '../termo.md?raw'

interface Props {
  aberto: boolean
  onFechar: () => void
  // Ações no rodapé; sem elas, só "Fechar". `obrigatorio`: Esc não fecha (aceite pendente).
  acoes?: ReactNode
  obrigatorio?: boolean
}

/** Termo de uso e tratamento de dados (LGPD), num <dialog> nativo: foco preso, Esc e
 * fundo escurecido vêm do navegador. */
export default function Termo({ aberto, onFechar, acoes, obrigatorio = false }: Props) {
  const ref = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    const dialogo = ref.current
    if (aberto && !dialogo?.open) dialogo?.showModal()
    if (!aberto && dialogo?.open) dialogo.close()
  }, [aberto])

  return (
    <dialog
      ref={ref}
      // O Chrome deixa o Esc fechar mesmo com o `cancel` impedido (proteção contra
      // diálogos que prendem o usuário): no aceite obrigatório, reabre.
      onClose={() => (obrigatorio && aberto ? ref.current?.showModal() : onFechar())}
      onCancel={(e) => obrigatorio && e.preventDefault()}
      aria-label="Termo de uso e tratamento de dados"
      className="m-auto w-[min(40rem,calc(100%-2rem))] rounded-2xl p-0 shadow-xl backdrop:bg-black/40"
    >
      <div className="max-h-[70vh] overflow-y-auto px-6 py-5">
        <div className="prosa text-sm leading-relaxed text-zinc-700">
          <ReactMarkdown>{termo}</ReactMarkdown>
        </div>
      </div>
      <div className="flex justify-end gap-2 border-t border-zinc-200 px-6 py-3">
        {acoes ?? (
          <button
            onClick={onFechar}
            className="rounded-lg bg-teal-600 px-4 py-2 text-sm font-medium text-white hover:bg-teal-500"
          >
            Fechar
          </button>
        )}
      </div>
    </dialog>
  )
}
