// Padrões dos gráficos e formatadores compartilhados pelos painéis (estudante e admin).

// Uma série por gráfico, na cor do app (teal-600, validada contra a superfície branca);
// grade e eixos recessivos. Texto nunca usa a cor do dado.
export const COR = '#0d9488'
export const GRADE = '#e4e4e7' // zinc-200
export const EIXO = { fontSize: 12, fill: '#71717a' } // zinc-500

export const pct = (v: number | null | undefined) => (v == null ? '—' : `${Math.round(v * 100)}%`)
export const decimal = (v: number | null | undefined, casas = 1) =>
  v == null ? '—' : v.toLocaleString('pt-BR', { maximumFractionDigits: casas })
export const diaMes = (d: string) =>
  new Date(d).toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit', timeZone: 'UTC' })

export function haQuanto(iso: string | null) {
  if (!iso) return '—'
  const dias = Math.round((new Date(iso).getTime() - Date.now()) / 86_400_000)
  return new Intl.RelativeTimeFormat('pt-BR', { numeric: 'auto' }).format(dias, 'day')
}
