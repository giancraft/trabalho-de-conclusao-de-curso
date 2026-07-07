import { Plus, ShieldAlert, Stethoscope } from 'lucide-react'
import type { Opcoes } from '../types'

interface Props {
  opcoes: Opcoes | null
  especialidade: string
  dificuldade: string
  ocupado: boolean
  aberta: boolean
  onFechar: () => void
  onEspecialidade: (v: string) => void
  onDificuldade: (v: string) => void
  onNovoCaso: () => void
}

const rotulo = 'mb-1.5 block text-xs font-medium uppercase tracking-wide text-zinc-400'
const campo =
  'w-full rounded-lg border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-100 ' +
  'outline-none focus:border-zinc-500'

export default function Sidebar({
  opcoes,
  especialidade,
  dificuldade,
  ocupado,
  aberta,
  onFechar,
  onEspecialidade,
  onDificuldade,
  onNovoCaso,
}: Props) {
  return (
    <>
      {aberta && (
        <div
          className="fixed inset-0 z-10 bg-black/40 md:hidden"
          onClick={onFechar}
          aria-hidden
        />
      )}
      <aside
        className={`flex w-72 shrink-0 flex-col border-r border-zinc-800 bg-zinc-900 p-4
                    max-md:fixed max-md:inset-y-0 max-md:left-0 max-md:z-20 ${
                      aberta ? '' : 'max-md:hidden'
                    }`}
      >
      <div className="mb-8 flex items-center gap-2.5 px-1">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-teal-600">
          <Stethoscope className="h-5 w-5 text-white" />
        </div>
        <div>
          <h1 className="text-sm font-semibold text-zinc-100">Simulador Clínico</h1>
          <p className="text-xs text-zinc-400">Casos com IA generativa</p>
        </div>
      </div>

      <div className="space-y-4">
        <div>
          <label htmlFor="especialidade" className={rotulo}>
            Especialidade
          </label>
          <select
            id="especialidade"
            className={campo}
            value={especialidade}
            onChange={(e) => onEspecialidade(e.target.value)}
          >
            {(opcoes?.especialidades ?? []).map((e) => (
              <option key={e}>{e}</option>
            ))}
          </select>
        </div>

        <div>
          <label htmlFor="dificuldade" className={rotulo}>
            Dificuldade
          </label>
          <select
            id="dificuldade"
            className={campo}
            value={dificuldade}
            onChange={(e) => onDificuldade(e.target.value)}
          >
            {(opcoes?.dificuldades ?? []).map((d) => (
              <option key={d}>{d}</option>
            ))}
          </select>
        </div>

        <button
          onClick={onNovoCaso}
          disabled={ocupado || !opcoes}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-teal-600 px-3 py-2.5
                     text-sm font-medium text-white transition-colors hover:bg-teal-500
                     disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Plus className="h-4 w-4" />
          Novo caso
        </button>
      </div>

      <div className="mt-auto flex items-start gap-2 rounded-lg border border-zinc-800 bg-zinc-800/50 p-3">
        <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
        <p className="text-xs leading-relaxed text-zinc-400">
          Simulação educacional. Não substitui orientação clínica real nem supervisão docente.
        </p>
      </div>
      </aside>
    </>
  )
}
