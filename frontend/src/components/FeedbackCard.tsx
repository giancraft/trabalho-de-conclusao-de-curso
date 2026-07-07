import {
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  CircleHelp,
  ClipboardCheck,
  XCircle,
} from 'lucide-react'
import type { Feedback } from '../types'
import type { LucideIcon } from 'lucide-react'

function Secao({
  icone: Icone,
  titulo,
  cor,
  itens,
}: {
  icone: LucideIcon
  titulo: string
  cor: string
  itens: string[] | string
}) {
  if (!itens || itens.length === 0) return null
  return (
    <div>
      <h4 className={`mb-1.5 flex items-center gap-1.5 text-sm font-semibold ${cor}`}>
        <Icone className="h-4 w-4" />
        {titulo}
      </h4>
      {typeof itens === 'string' ? (
        <p className="text-sm leading-relaxed text-zinc-700">{itens}</p>
      ) : (
        <ul className="space-y-1 pl-5 text-sm leading-relaxed text-zinc-700">
          {itens.map((item) => (
            <li key={item} className="list-disc">
              {item}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default function FeedbackCard({ fb }: { fb: Feedback }) {
  return (
    <div className="rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm">
      <div className="mb-4 flex items-center gap-2 border-b border-zinc-100 pb-3">
        <ClipboardCheck className="h-5 w-5 text-teal-600" />
        <h3 className="text-base font-semibold text-zinc-900">Feedback da investigação</h3>
      </div>

      <div
        className={`mb-4 rounded-lg px-4 py-3 text-sm font-medium ${
          fb.acertou ? 'bg-green-50 text-green-800' : 'bg-red-50 text-red-800'
        }`}
      >
        {fb.acertou ? 'Diagnóstico correto: ' : 'Diagnóstico correto era: '}
        {fb.diagnostico_correto}
      </div>

      <div className="space-y-4">
        <Secao icone={CheckCircle2} titulo="Acertos" cor="text-green-700" itens={fb.acertos} />
        <Secao
          icone={XCircle}
          titulo="Inconsistências"
          cor="text-red-700"
          itens={fb.inconsistencias}
        />
        <Secao
          icone={CircleHelp}
          titulo="Hipóteses não consideradas"
          cor="text-amber-700"
          itens={fb.hipoteses_nao_consideradas}
        />
        <Secao
          icone={BookOpen}
          titulo="Justificativa pedagógica"
          cor="text-blue-700"
          itens={fb.justificativa_pedagogica}
        />
      </div>

      <div className="mt-4 flex items-start gap-2 border-t border-zinc-100 pt-3">
        <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-zinc-400" />
        <p className="text-xs text-zinc-500">
          Conteúdo gerado por IA para fins educacionais; confira sempre a literatura de
          referência.
        </p>
      </div>
    </div>
  )
}
