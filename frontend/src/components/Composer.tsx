import { useRef, useState } from 'react'
import { ClipboardCheck, SendHorizontal, X } from 'lucide-react'

interface Props {
  ocupado: boolean
  onMensagem: (texto: string) => void
  onDiagnostico: (texto: string) => void
}

export default function Composer({ ocupado, onMensagem, onDiagnostico }: Props) {
  const [texto, setTexto] = useState('')
  const [modoDiagnostico, setModoDiagnostico] = useState(false)
  const areaRef = useRef<HTMLTextAreaElement>(null)

  function enviar() {
    const limpo = texto.trim()
    if (!limpo || ocupado) return
    if (modoDiagnostico) {
      onDiagnostico(limpo)
      setModoDiagnostico(false)
    } else {
      onMensagem(limpo)
    }
    setTexto('')
    if (areaRef.current) areaRef.current.style.height = 'auto'
  }

  return (
    <div className="mx-auto w-full max-w-3xl px-4 pb-4">
      {modoDiagnostico && (
        <div className="mb-2 flex items-center justify-between rounded-lg bg-teal-50 px-3 py-2 text-sm text-teal-800">
          <span className="font-medium">
            Modo diagnóstico: descreva sua hipótese final e o raciocínio.
          </span>
          <button
            onClick={() => setModoDiagnostico(false)}
            className="rounded p-0.5 hover:bg-teal-100"
            aria-label="Cancelar diagnóstico"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      )}
      <div
        className={`flex items-end gap-2 rounded-2xl border bg-white p-2 shadow-sm ${
          modoDiagnostico ? 'border-teal-400 ring-2 ring-teal-100' : 'border-zinc-300'
        }`}
      >
        <textarea
          ref={areaRef}
          rows={1}
          value={texto}
          disabled={ocupado}
          placeholder={
            modoDiagnostico
              ? 'Meu diagnóstico é...'
              : 'Pergunte ao paciente, peça exames ou descreva sua conduta...'
          }
          className="max-h-40 flex-1 resize-none bg-transparent px-2 py-1.5 text-sm text-zinc-800
                     outline-none placeholder:text-zinc-400 disabled:opacity-50"
          onChange={(e) => {
            setTexto(e.target.value)
            e.target.style.height = 'auto'
            e.target.style.height = `${e.target.scrollHeight}px`
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              enviar()
            }
          }}
        />
        {!modoDiagnostico && (
          <button
            onClick={() => setModoDiagnostico(true)}
            disabled={ocupado}
            className="flex items-center gap-1.5 rounded-xl border border-teal-600 px-3 py-2 text-xs
                       font-medium text-teal-700 transition-colors hover:bg-teal-50 disabled:opacity-50"
            title="Encerrar a investigação e dar o diagnóstico final"
          >
            <ClipboardCheck className="h-4 w-4" />
            Dar diagnóstico
          </button>
        )}
        <button
          onClick={enviar}
          disabled={ocupado || !texto.trim()}
          className="rounded-xl bg-teal-600 p-2 text-white transition-colors hover:bg-teal-500
                     disabled:cursor-not-allowed disabled:opacity-40"
          aria-label="Enviar"
        >
          <SendHorizontal className="h-4 w-4" />
        </button>
      </div>
      <p className="mt-2 text-center text-xs text-zinc-400">
        Enter envia · Shift+Enter quebra linha · Conteúdo gerado por IA, apenas para estudo
      </p>
    </div>
  )
}
