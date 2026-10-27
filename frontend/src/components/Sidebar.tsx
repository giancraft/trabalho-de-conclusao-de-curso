import { Check, LogOut, Plus, ShieldAlert, Stethoscope, Trash2 } from 'lucide-react'
import type { ConversaResumo, Usuario } from '../types'

interface Props {
  ocupado: boolean
  aberta: boolean
  usuario: Usuario
  conversas: ConversaResumo[]
  conversaAtivaId: string | null
  onFechar: () => void
  onNovoSimulado: () => void
  onAbrirConversa: (id: string) => void
  onApagarConversa: (id: string) => void
  onLogout: () => void
}

const rotulo = 'mb-1.5 block text-xs font-medium uppercase tracking-wide text-zinc-400'

export default function Sidebar({
  ocupado,
  aberta,
  usuario,
  conversas,
  conversaAtivaId,
  onFechar,
  onNovoSimulado,
  onAbrirConversa,
  onApagarConversa,
  onLogout,
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
        <div className="mb-6 flex items-center gap-2.5 px-1">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-teal-600">
            <Stethoscope className="h-5 w-5 text-white" />
          </div>
          <div>
            <h1 className="text-sm font-semibold text-zinc-100">Simulador Clínico</h1>
            <p className="text-xs text-zinc-400">Casos com IA generativa</p>
          </div>
        </div>

        <button
          onClick={onNovoSimulado}
          disabled={ocupado}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-teal-600 px-3 py-2.5
                     text-sm font-medium text-white transition-colors hover:bg-teal-500
                     disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Plus className="h-4 w-4" />
          Novo simulado
        </button>

        <div className="mt-5 flex min-h-0 flex-1 flex-col">
          <p className={rotulo}>Conversas</p>
          <div className="-mx-1 flex-1 space-y-0.5 overflow-y-auto px-1">
            {conversas.length === 0 && (
              <p className="px-1 py-2 text-xs text-zinc-500">
                Seus casos aparecerão aqui.
              </p>
            )}
            {conversas.map((c) => (
              <div
                key={c.id}
                className={`group flex items-center gap-2 rounded-lg px-2 py-2 ${
                  c.id === conversaAtivaId ? 'bg-zinc-800' : 'hover:bg-zinc-800/60'
                }`}
              >
                <button
                  onClick={() => onAbrirConversa(c.id)}
                  className="flex min-w-0 flex-1 items-center gap-2 text-left"
                  title={c.titulo}
                >
                  {c.status === 'encerrada' ? (
                    <Check className="h-3.5 w-3.5 shrink-0 text-zinc-500" />
                  ) : (
                    <span className="h-2 w-2 shrink-0 rounded-full bg-teal-500" />
                  )}
                  <span className="min-w-0">
                    <span className="block truncate text-sm text-zinc-200">{c.titulo}</span>
                    <span className="block truncate text-xs text-zinc-500">
                      {c.especialidade}
                      {c.total && c.total > 1 ? ` · ${c.ordem}/${c.total}` : ''}
                    </span>
                  </span>
                </button>
                <button
                  onClick={() => onApagarConversa(c.id)}
                  className="hidden shrink-0 rounded p-1 text-zinc-500 hover:bg-zinc-700
                             hover:text-red-400 group-hover:block"
                  aria-label={`Apagar conversa ${c.titulo}`}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
          </div>
        </div>

        <div className="mt-3 space-y-3 border-t border-zinc-800 pt-3">
          <div className="flex items-center justify-between px-1">
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-zinc-200">{usuario.nome}</p>
              <p className="truncate text-xs text-zinc-500">{usuario.email}</p>
            </div>
            <button
              onClick={onLogout}
              className="shrink-0 rounded-lg p-2 text-zinc-400 transition-colors hover:bg-zinc-800 hover:text-zinc-200"
              title="Sair"
              aria-label="Sair"
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
          <div className="flex items-start gap-2 rounded-lg border border-zinc-800 bg-zinc-800/50 p-3">
            <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
            <p className="text-xs leading-relaxed text-zinc-400">
              Simulação educacional. Não substitui orientação clínica real nem supervisão
              docente.
            </p>
          </div>
        </div>
      </aside>
    </>
  )
}
