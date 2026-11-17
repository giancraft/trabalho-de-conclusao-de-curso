import { useEffect, useState } from 'react'
import { AlertTriangle, ArrowRight, CalendarClock, ClipboardList, Play, RotateCcw, Sparkles } from 'lucide-react'
import * as api from '../api'
import type { ItemRevisao, Recomendacao, Revisao as Dados } from '../types'

interface Props {
  ocupado: boolean
  onRevisar: (nos: string[]) => void // simulado com um caso de cada tema
  onTreinar: (no: string) => void
}

const ICONE = { fragil: AlertTriangle, nao_praticado: Sparkles, etapa: ClipboardList }
const ROTULO = { fragil: 'Ponto fraco', nao_praticado: 'Ainda não praticado', etapa: 'Investigação' }

function quando(item: ItemRevisao) {
  const dias = -item.atraso_dias
  return new Intl.RelativeTimeFormat('pt-BR', { numeric: 'auto' }).format(dias, 'day')
}

/** Tema numa sessão: errado por último ganha o ícone de alerta (nunca só a cor). */
function Chip({ item }: { item: ItemRevisao }) {
  return (
    <span
      className={`inline-flex max-w-[16rem] items-center gap-1 truncate rounded-full border px-2.5 py-1 text-xs ${
        item.ultimo_acertou ? 'border-zinc-200 bg-white text-zinc-700' : 'border-amber-200 bg-amber-50 text-amber-900'
      }`}
      title={`${item.nome} · ${item.especialidade} · ${item.acertos}/${item.tentativas} corretos`}
    >
      {!item.ultimo_acertou && <AlertTriangle className="h-3 w-3 shrink-0" aria-label="Errou da última vez" />}
      <span className="truncate">{item.nome}</span>
    </span>
  )
}

function Recomendacoes({ itens, ocupado, onTreinar }: { itens: Recomendacao[]; ocupado: boolean; onTreinar: (no: string) => void }) {
  if (!itens.length) return null
  return (
    <section aria-label="O que estudar a seguir" className="space-y-2">
      <h3 className="text-sm font-semibold text-zinc-900">O que estudar a seguir</h3>
      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
        {itens.map((r) => {
          const Icone = ICONE[r.tipo]
          return (
            <div key={`${r.tipo}-${r.titulo}`} className="flex flex-col rounded-xl border border-zinc-200 bg-white p-4">
              <p className="flex items-center gap-1.5 text-xs font-medium text-zinc-500">
                <Icone className={`h-3.5 w-3.5 ${r.tipo === 'fragil' ? 'text-amber-600' : 'text-teal-600'}`} aria-hidden />
                {ROTULO[r.tipo]}
              </p>
              <p className="mt-1 text-sm font-semibold text-zinc-900">{r.titulo}</p>
              <p className="mt-1 flex-1 text-xs leading-relaxed text-zinc-500">{r.motivo}</p>
              {r.no && (
                <button
                  onClick={() => onTreinar(r.no!)}
                  disabled={ocupado}
                  className="mt-3 inline-flex items-center justify-center gap-1.5 rounded-lg bg-teal-600 px-3 py-2 text-xs font-medium text-white hover:bg-teal-500 disabled:opacity-50"
                >
                  <Play className="h-3.5 w-3.5" aria-hidden />
                  Treinar agora
                </button>
              )}
            </div>
          )
        })}
      </div>
    </section>
  )
}

/** Revisão espaçada por tema (RF09): cada sessão gera casos novos dos temas vencidos. */
export default function Revisao({ ocupado, onRevisar, onTreinar }: Props) {
  const [dados, setDados] = useState<Dados | null>(null)
  const [modo, setModo] = useState<'normal' | 'express'>('normal')
  const [erro, setErro] = useState<string | null>(null)

  useEffect(() => {
    api
      .buscarRevisao()
      .then(setDados)
      .catch((e) => setErro(e instanceof Error ? e.message : 'Falha ao carregar a revisão.'))
  }, [])

  if (erro) return <p className="m-6 text-sm text-red-700">{erro}</p>
  if (!dados) return <p className="m-6 text-sm text-zinc-500">Carregando…</p>

  const sessoes = modo === 'normal' ? dados.sessoes_normais : dados.sessoes_express
  const primeira = dados.sessoes_normais[0]
  const praticou = dados.vencidos.length + dados.proximas.length > 0

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-5xl space-y-5 px-4 py-6">
        <div>
          <h2 className="text-xl font-semibold text-zinc-900">Revisão</h2>
          <p className="mt-1 text-sm text-zinc-500">
            Os temas que você já estudou voltam no momento certo: o que errou volta no dia seguinte; o que
            acertou, cada vez mais espaçado (repetição espaçada). Cada revisão gera casos novos do tema.
          </p>
        </div>

        <section className="flex flex-wrap items-center gap-4 rounded-xl border border-zinc-200 bg-white p-5" aria-label="Revisão de hoje">
          <RotateCcw className="h-8 w-8 shrink-0 text-teal-600" aria-hidden />
          <div className="min-w-[12rem] flex-1">
            <p className="text-sm font-semibold text-zinc-900">Revisão de hoje</p>
            <p className="text-sm text-zinc-500">
              {dados.vencidos.length
                ? `${dados.vencidos.length} ${dados.vencidos.length === 1 ? 'tema para revisar' : 'temas para revisar'}`
                : praticou
                  ? `Nada para hoje. Próxima: ${dados.proximas[0].nome}, ${quando(dados.proximas[0])}.`
                  : 'A revisão começa depois dos seus primeiros casos encerrados.'}
            </p>
          </div>
          {primeira && (
            <button
              onClick={() => onRevisar(primeira.map((i) => i.no))}
              disabled={ocupado}
              className="inline-flex items-center gap-1.5 rounded-lg bg-teal-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-teal-500 disabled:opacity-50"
            >
              <Play className="h-4 w-4" aria-hidden />
              Iniciar revisão normal
            </button>
          )}
        </section>

        {dados.vencidos.length > 0 && (
          <section className="rounded-xl border border-zinc-200 bg-white p-5" aria-label="Mais revisões para você">
            <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
              <div>
                <h3 className="text-sm font-semibold text-zinc-900">Mais revisões para você</h3>
                <p className="text-xs text-zinc-500">
                  {modo === 'normal' ? 'Normal: 3 temas, um caso de cada.' : 'Express: 1 tema, um caso.'} Os que você
                  errou vêm primeiro.
                </p>
              </div>
              <div role="tablist" className="inline-flex rounded-lg bg-zinc-100 p-1 text-sm">
                {(['normal', 'express'] as const).map((m) => (
                  <button
                    key={m}
                    role="tab"
                    aria-selected={modo === m}
                    onClick={() => setModo(m)}
                    className={`rounded-md px-3 py-1 ${modo === m ? 'bg-white font-medium text-zinc-900 shadow-sm' : 'text-zinc-500'}`}
                  >
                    {m === 'normal' ? 'Normal' : 'Express'}
                  </button>
                ))}
              </div>
            </div>
            <ol className="space-y-2">
              {sessoes.map((sessao, i) => (
                <li key={sessao.map((t) => t.no).join()} className="flex items-center gap-3 rounded-lg border border-zinc-100 px-3 py-2">
                  <span className="w-5 shrink-0 text-sm font-medium tabular-nums text-zinc-500">{i + 1}</span>
                  <div className="flex min-w-0 flex-1 flex-wrap gap-1.5">
                    {sessao.map((t) => (
                      <Chip key={t.no} item={t} />
                    ))}
                  </div>
                  <button
                    onClick={() => onRevisar(sessao.map((t) => t.no))}
                    disabled={ocupado}
                    className="shrink-0 rounded-md p-1.5 text-teal-700 hover:bg-teal-50 disabled:opacity-50"
                    aria-label={`Iniciar revisão ${i + 1}: ${sessao.map((t) => t.nome).join(', ')}`}
                  >
                    <ArrowRight className="h-5 w-5" />
                  </button>
                </li>
              ))}
            </ol>
          </section>
        )}

        <Recomendacoes itens={dados.recomendacoes} ocupado={ocupado} onTreinar={onTreinar} />

        {dados.proximas.length > 0 && (
          <section className="rounded-xl border border-zinc-200 bg-white p-5" aria-label="Próximas revisões">
            <h3 className="mb-3 flex items-center gap-1.5 text-sm font-semibold text-zinc-900">
              <CalendarClock className="h-4 w-4" aria-hidden />
              Próximas revisões
            </h3>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[480px] text-sm">
                <thead className="text-left text-xs text-zinc-500">
                  <tr>
                    <th className="pb-2 font-medium">Tema</th>
                    <th className="pb-2 font-medium">Especialidade</th>
                    <th className="pb-2 text-right font-medium">Acertos</th>
                    <th className="pb-2 text-right font-medium">Revisão</th>
                  </tr>
                </thead>
                <tbody>
                  {dados.proximas.map((t) => (
                    <tr key={t.no} className="border-t border-zinc-100">
                      <td className="py-2 pr-2 text-zinc-800">{t.nome}</td>
                      <td className="py-2 pr-2 text-zinc-500">{t.especialidade}</td>
                      <td className="py-2 text-right tabular-nums text-zinc-700">
                        {t.acertos}/{t.tentativas}
                      </td>
                      <td className="py-2 text-right text-zinc-500">{quando(t)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}
      </div>
    </div>
  )
}
