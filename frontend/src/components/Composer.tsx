import { useRef, useState } from 'react'
import { ClipboardCheck, SendHorizontal, X } from 'lucide-react'
import type { RespostaFinal } from '../types'

type Campo = keyof RespostaFinal

interface Props {
  ocupado: boolean
  ciclo: string
  onMensagem: (texto: string) => void
  onDiagnostico: (resposta: RespostaFinal, texto: string) => void
}

const ROTULOS: Record<Campo, string> = {
  diagnostico: 'Diagnóstico final',
  fisiologia: 'Fisiologia normal',
  fisiopatologia: 'Fisiopatologia',
  conduta: 'Conduta',
}

// Os campos de cada ciclo espelham ai.CAMPOS_POR_CICLO (o backend valida). As dicas só
// dizem o que o campo pede — nunca sugerem conteúdo.
const CAMPOS: Record<string, { campo: Campo; dica: string }[]> = {
  básico: [
    { campo: 'diagnostico', dica: 'Seu diagnóstico e o raciocínio que leva a ele.' },
    { campo: 'fisiologia', dica: 'Como o órgão ou sistema acometido funciona normalmente.' },
    { campo: 'fisiopatologia', dica: 'O que a doença altera nesse funcionamento e como isso explica os achados.' },
  ],
  clínico: [
    { campo: 'diagnostico', dica: 'Seu diagnóstico e o raciocínio que leva a ele.' },
    { campo: 'fisiopatologia', dica: 'O mecanismo da doença e como ele explica os achados.' },
    { campo: 'conduta', dica: 'Tratamento: medidas, fármacos ou classes de escolha e metas.' },
  ],
  internato: [
    { campo: 'diagnostico', dica: 'Seu diagnóstico e o raciocínio que leva a ele.' },
    { campo: 'fisiopatologia', dica: 'O mecanismo da doença e como ele explica os achados.' },
    { campo: 'conduta', dica: 'Conduta passo a passo: medidas, fármacos, doses, vias, volumes e monitorização.' },
  ],
}

const vazia: RespostaFinal = { diagnostico: '', fisiologia: '', fisiopatologia: '', conduta: '' }

export default function Composer({ ocupado, ciclo, onMensagem, onDiagnostico }: Props) {
  const [texto, setTexto] = useState('')
  const [modoDiagnostico, setModoDiagnostico] = useState(false)
  const [resposta, setResposta] = useState<RespostaFinal>(vazia)
  const areaRef = useRef<HTMLTextAreaElement>(null)
  const campos = CAMPOS[ciclo] ?? CAMPOS['clínico']
  const completa = campos.every(({ campo }) => resposta[campo]?.trim())

  function enviar() {
    const limpo = texto.trim()
    if (!limpo || ocupado) return
    onMensagem(limpo)
    setTexto('')
    if (areaRef.current) areaRef.current.style.height = 'auto'
  }

  function entregar() {
    if (!completa || ocupado) return
    // Mesmo texto rotulado que o backend grava no histórico (ai.texto_resposta).
    const rotulado = campos.map(({ campo }) => `${ROTULOS[campo]}: ${resposta[campo]?.trim()}`).join('\n\n')
    onDiagnostico(resposta, rotulado)
    setModoDiagnostico(false)
    setResposta(vazia)
  }

  if (modoDiagnostico) {
    return (
      <div className="mx-auto w-full max-w-3xl px-4 pb-4">
        <div className="rounded-2xl border border-teal-400 bg-white p-3 shadow-sm ring-2 ring-teal-100">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-sm font-medium text-teal-800">
              Resposta final · ciclo {ciclo}
            </span>
            <button
              onClick={() => setModoDiagnostico(false)}
              className="rounded p-0.5 text-teal-800 hover:bg-teal-50"
              aria-label="Voltar à investigação"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          <div className="space-y-3">
            {campos.map(({ campo, dica }) => (
              <div key={campo}>
                <label htmlFor={`campo-${campo}`} className="block text-xs font-semibold text-zinc-700">
                  {ROTULOS[campo]}
                </label>
                <p className="mb-1 text-xs text-zinc-500">{dica}</p>
                <textarea
                  id={`campo-${campo}`}
                  rows={campo === 'conduta' ? 5 : 3}
                  value={resposta[campo] ?? ''}
                  disabled={ocupado}
                  onChange={(e) => setResposta((r) => ({ ...r, [campo]: e.target.value }))}
                  className="w-full resize-y rounded-lg border border-zinc-300 px-3 py-2 text-sm text-zinc-800
                             outline-none focus:border-teal-400 disabled:opacity-50"
                />
              </div>
            ))}
          </div>
          <div className="mt-3 flex justify-end">
            <button
              onClick={entregar}
              disabled={ocupado || !completa}
              className="flex items-center gap-1.5 rounded-xl bg-teal-600 px-4 py-2 text-sm font-medium text-white
                         transition-colors hover:bg-teal-500 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <ClipboardCheck className="h-4 w-4" />
              Entregar e receber feedback
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="mx-auto w-full max-w-3xl px-4 pb-4">
      <div className="flex items-end gap-2 rounded-2xl border border-zinc-300 bg-white p-2 shadow-sm">
        <textarea
          ref={areaRef}
          rows={1}
          value={texto}
          disabled={ocupado}
          placeholder="Pergunte ao paciente, peça exames ou descreva sua conduta..."
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
        <button
          onClick={() => setModoDiagnostico(true)}
          disabled={ocupado}
          className="flex items-center gap-1.5 rounded-xl border border-teal-600 px-3 py-2 text-xs
                     font-medium text-teal-700 transition-colors hover:bg-teal-50 disabled:opacity-50"
          title="Encerrar a investigação e entregar a resposta final"
        >
          <ClipboardCheck className="h-4 w-4" />
          Dar diagnóstico
        </button>
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
