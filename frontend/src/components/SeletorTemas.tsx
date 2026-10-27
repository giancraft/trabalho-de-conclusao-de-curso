import { useEffect, useMemo, useState } from 'react'
import { ChevronRight, Search } from 'lucide-react'
import type { NoTema } from '../types'

interface Props {
  arvore: NoTema[]
  ciclos: string[]
  ocupado: boolean
  onGerar: (selecao: string[], ciclo: string, quantidade: number) => void
}

// Seleção e preferências lembradas entre visitas, só neste navegador. Sem storage
// (aba anônima, bloqueio), a tela funciona igual, só não lembra.
const CHAVE = 'simulado:preferencias'

function lerPreferencias(): { marcados: string[]; ciclo?: string; quantidade?: number } {
  try {
    return JSON.parse(localStorage.getItem(CHAVE) ?? '') ?? { marcados: [] }
  } catch {
    return { marcados: [] }
  }
}

function folhas(no: NoTema): string[] {
  return no.filhos.length ? no.filhos.flatMap(folhas) : [no.id]
}

function normalizar(texto: string) {
  return texto.normalize('NFD').replace(/\p{Diacritic}/gu, '').toLowerCase()
}

/** Nós que casam com a busca, com os ancestrais; nó que casa leva a subárvore inteira. */
function filtrar(nos: NoTema[], termo: string): NoTema[] {
  return nos.flatMap((no) => {
    if (normalizar(no.nome).includes(termo)) return [no]
    const filhos = filtrar(no.filhos, termo)
    return filhos.length ? [{ ...no, filhos }] : []
  })
}

/** O que vai para a API: o nó mais alto inteiramente marcado ("a:Cirurgia" em vez das
 * 14 folhas dela) — o sorteio pesa a área toda, inclusive temas novos. */
function compactar(nos: NoTema[], marcados: Set<string>): string[] {
  return nos.flatMap((no) => {
    const fs = folhas(no)
    if (fs.every((f) => marcados.has(f))) return [no.id]
    return fs.some((f) => marcados.has(f)) ? compactar(no.filhos, marcados) : []
  })
}

export default function SeletorTemas({ arvore, ciclos, ocupado, onGerar }: Props) {
  const inicial = useMemo(lerPreferencias, [])
  const existentes = useMemo(() => new Set(arvore.flatMap(folhas)), [arvore])
  const [marcados, setMarcados] = useState(
    () => new Set(inicial.marcados.filter((id) => existentes.has(id))),
  )
  const [abertos, setAbertos] = useState<Set<string>>(new Set())
  const [busca, setBusca] = useState('')
  const [ciclo, setCiclo] = useState(inicial.ciclo ?? 'clínico')
  const [quantidade, setQuantidade] = useState(inicial.quantidade ?? 5)

  const termo = normalizar(busca.trim())
  const visiveis = termo ? filtrar(arvore, termo) : arvore
  const selecao = compactar(arvore, marcados)

  function alternar(no: NoTema) {
    const fs = folhas(no)
    const todos = fs.every((f) => marcados.has(f))
    const novo = new Set(marcados)
    fs.forEach((f) => (todos ? novo.delete(f) : novo.add(f)))
    setMarcados(novo)
  }

  function expandir(id: string) {
    const novo = new Set(abertos)
    if (!novo.delete(id)) novo.add(id)
    setAbertos(novo)
  }

  // Salva a cada mudança: sair para um caso e voltar não perde o que estava marcado.
  useEffect(() => {
    try {
      localStorage.setItem(CHAVE, JSON.stringify({ marcados: [...marcados], ciclo, quantidade }))
    } catch {
      // sem storage: só não lembra na próxima visita
    }
  }, [marcados, ciclo, quantidade])

  function linha(no: NoTema, nivel: number) {
    const fs = folhas(no)
    const n = fs.filter((f) => marcados.has(f)).length
    const aberto = !!termo || abertos.has(no.id)
    return (
      <li key={no.id}>
        <div
          className="flex items-center gap-3 rounded-xl border border-zinc-200 bg-white px-3 py-2.5"
          style={{ marginLeft: nivel * 20 }}
        >
          <input
            type="checkbox"
            className="h-4 w-4 shrink-0 accent-teal-600"
            checked={n === fs.length}
            ref={(el) => {
              if (el) el.indeterminate = n > 0 && n < fs.length
            }}
            onChange={() => alternar(no)}
            aria-label={`Selecionar ${no.nome}`}
          />
          <button
            type="button"
            className="min-w-0 flex-1 text-left"
            onClick={() => (no.filhos.length ? expandir(no.id) : alternar(no))}
          >
            <span className="block truncate text-sm font-medium text-zinc-800">{no.nome}</span>
            <span className="block text-xs text-zinc-500">
              {no.respondidos} respondidos · {no.disponiveis} disponíveis
            </span>
          </button>
          {no.filhos.length > 0 && (
            <>
              <span className="hidden shrink-0 rounded-md bg-zinc-100 px-2 py-1 text-xs text-zinc-600 sm:block">
                {fs.length} {fs.length === 1 ? 'tema' : 'temas'}
              </span>
              <button
                type="button"
                onClick={() => expandir(no.id)}
                className="shrink-0 rounded-md p-1 text-teal-600 hover:bg-teal-50"
                aria-label={aberto ? `Recolher ${no.nome}` : `Expandir ${no.nome}`}
                aria-expanded={aberto}
              >
                <ChevronRight className={`h-5 w-5 transition-transform ${aberto ? 'rotate-90' : ''}`} />
              </button>
            </>
          )}
        </div>
        {aberto && no.filhos.length > 0 && (
          <ul className="mt-2 space-y-2">
            {no.filhos.map((f) => linha(f, nivel + 1))}
          </ul>
        )}
      </li>
    )
  }

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 px-4 py-6">
      <div>
        <h2 className="text-xl font-semibold text-zinc-900">Novo simulado</h2>
        <p className="mt-1 text-sm leading-relaxed text-zinc-500">
          Marque uma área inteira ou temas específicos. Os casos são sorteados entre eles, e os
          temas mais frequentes na prática e nas provas saem mais vezes. Em cada caso você conduz
          a investigação sem conhecer o diagnóstico e recebe feedback no nível do seu ciclo.
        </p>
      </div>

      <label className="flex items-center gap-2 rounded-full border border-zinc-300 bg-white px-4 py-2.5 focus-within:border-teal-500">
        <Search className="h-4 w-4 shrink-0 text-zinc-400" />
        <input
          type="search"
          value={busca}
          onChange={(e) => setBusca(e.target.value)}
          placeholder="Pesquise um tema. Ex.: Tuberculose"
          className="min-w-0 flex-1 bg-transparent text-sm text-zinc-800 outline-none placeholder:text-zinc-400"
        />
      </label>

      <ul className="space-y-2">
        {visiveis.map((no) => linha(no, 0))}
        {visiveis.length === 0 && (
          <li className="px-1 py-4 text-sm text-zinc-500">
            {arvore.length ? 'Nenhum tema com esse nome.' : 'Carregando temas…'}
          </li>
        )}
      </ul>

      <div className="sticky bottom-0 flex flex-wrap items-end gap-3 border-t border-zinc-200 bg-zinc-50 py-3">
        <label className="text-xs font-medium text-zinc-500">
          Ciclo
          <select
            value={ciclo}
            onChange={(e) => setCiclo(e.target.value)}
            className="mt-1 block rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-800"
          >
            {ciclos.map((c) => (
              <option key={c} value={c}>
                {c[0].toUpperCase() + c.slice(1)}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs font-medium text-zinc-500">
          Casos
          <select
            value={quantidade}
            onChange={(e) => setQuantidade(Number(e.target.value))}
            className="mt-1 block rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-800"
          >
            {Array.from({ length: 10 }, (_, i) => i + 1).map((n) => (
              <option key={n}>{n}</option>
            ))}
          </select>
        </label>
        <button
          onClick={() => onGerar(selecao, ciclo, quantidade)}
          disabled={ocupado || selecao.length === 0}
          className="min-w-48 flex-1 rounded-lg bg-teal-600 px-5 py-2.5 text-sm font-medium text-white
                     transition-colors hover:bg-teal-500 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {selecao.length === 0 ? 'Marque ao menos um tema' : 'Gerar simulado'}
        </button>
      </div>
    </div>
  )
}
