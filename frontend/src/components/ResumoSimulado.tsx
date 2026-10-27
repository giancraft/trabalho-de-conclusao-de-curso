import { CheckCircle2, XCircle } from 'lucide-react'
import type { Simulado } from '../types'

interface Props {
  simulado: Simulado
  onAbrir: (casoId: string) => void
}

/** Fim do simulado: acertos e o diagnóstico de cada caso, com link para revisar. */
export default function ResumoSimulado({ simulado, onAbrir }: Props) {
  const acertos = simulado.casos.filter((c) => c.acertou).length
  return (
    <section className="rounded-xl border border-zinc-200 bg-white p-5">
      <h3 className="text-base font-semibold text-zinc-900">Simulado concluído</h3>
      <p className="mt-1 text-sm text-zinc-500">
        {acertos} de {simulado.total} diagnósticos corretos · ciclo {simulado.ciclo}
      </p>
      <ol className="mt-4 divide-y divide-zinc-100">
        {simulado.casos.map((c) => (
          <li key={c.caso_id}>
            <button
              onClick={() => onAbrir(c.caso_id)}
              className="flex w-full items-center gap-3 py-2.5 text-left hover:bg-zinc-50"
            >
              {c.acertou ? (
                <CheckCircle2 className="h-4 w-4 shrink-0 text-teal-600" aria-label="Acertou" />
              ) : (
                <XCircle className="h-4 w-4 shrink-0 text-red-500" aria-label="Errou" />
              )}
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm text-zinc-800">
                  {c.ordem}. {c.titulo}
                </span>
                {c.diagnostico_correto && (
                  <span className="block truncate text-xs text-zinc-500">{c.diagnostico_correto}</span>
                )}
              </span>
            </button>
          </li>
        ))}
      </ol>
    </section>
  )
}
