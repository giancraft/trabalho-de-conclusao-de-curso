// Blocos dos painéis: cartão de indicador, figura com tabela e tooltip.
import type { ReactNode } from 'react'

export function Cartao({ titulo, valor, detalhe }: { titulo: string; valor: string; detalhe?: ReactNode }) {
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4">
      <p className="text-xs font-medium text-zinc-500">{titulo}</p>
      <p className="mt-1 text-3xl font-semibold tabular-nums text-zinc-900">{valor}</p>
      {detalhe && <div className="mt-1 text-xs text-zinc-500">{detalhe}</div>}
    </div>
  )
}

/** Gráfico com título e a mesma informação em tabela (para quem não lê o gráfico). */
export function Figura({
  titulo,
  descricao,
  tabela,
  children,
}: {
  titulo: string
  descricao: string
  tabela: [string, string][]
  children: ReactNode
}) {
  return (
    <section className="rounded-xl border border-zinc-200 bg-white p-4" aria-label={titulo}>
      <h3 className="text-sm font-semibold text-zinc-900">{titulo}</h3>
      <p className="mb-3 text-xs text-zinc-500">{descricao}</p>
      {children}
      <details className="mt-2 text-xs text-zinc-500">
        <summary className="cursor-pointer select-none">Ver em tabela</summary>
        <table className="mt-2 w-full">
          <tbody>
            {tabela.map(([rotulo, valor]) => (
              <tr key={rotulo} className="border-t border-zinc-100">
                <td className="py-1 pr-2">{rotulo}</td>
                <td className="py-1 text-right tabular-nums text-zinc-700">{valor}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </section>
  )
}

export function Dica({ linhas }: { linhas: string[] }) {
  return (
    <div className="rounded-lg border border-zinc-200 bg-white px-3 py-2 text-xs shadow-sm">
      {linhas.map((l, i) => (
        <p key={i} className={i ? 'text-zinc-500' : 'font-medium text-zinc-800'}>
          {l}
        </p>
      ))}
    </div>
  )
}
