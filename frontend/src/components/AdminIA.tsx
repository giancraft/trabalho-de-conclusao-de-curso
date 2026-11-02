import { useEffect, useState } from 'react'
import { Play } from 'lucide-react'
import { Bar, BarChart, CartesianGrid, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import * as api from '../api'
import type { AvaliacaoRAG, DesempenhoIA, QualidadeIA } from '../types'
import { COR, EIXO, GRADE, decimal, diaMes, pct } from '../graficos'
import { Cartao, Dica, Figura } from './Painel'

const ETAPAS: Record<string, string> = {
  caso: 'Geração do caso',
  pedidos: 'Leitura dos pedidos',
  chat: 'Respostas do chat',
  feedback: 'Feedback',
}
const PERIODOS = [7, 30, 90]

const dolar = (v: number | null | undefined, casas = 4) =>
  v == null
    ? '—'
    : v.toLocaleString('pt-BR', { style: 'currency', currency: 'USD', maximumFractionDigits: casas })
const segundos = (ms: number) => `${decimal(ms / 1000)} s`

/** Desempenho e qualidade da IA — só para o administrador (o backend responde 403 aos demais). */
export default function AdminIA() {
  const [dias, setDias] = useState(30)
  const [uso, setUso] = useState<DesempenhoIA | null>(null)
  const [qualidade, setQualidade] = useState<QualidadeIA | null>(null)
  const [rag, setRag] = useState<AvaliacaoRAG | null>(null)
  const [avaliando, setAvaliando] = useState(false)
  const [erro, setErro] = useState<string | null>(null)

  useEffect(() => {
    api.desempenhoIA(dias).then(setUso).catch((e) => setErro(e.message))
  }, [dias])
  useEffect(() => {
    api.qualidadeIA().then(setQualidade).catch((e) => setErro(e.message))
  }, [])

  function avaliarRAG() {
    setAvaliando(true)
    api
      .avaliarRAG()
      .then(setRag)
      .catch((e) => setErro(e.message))
      .finally(() => setAvaliando(false))
  }

  const etapas = (uso?.por_etapa ?? []).map((e) => ({
    ...e,
    nome: ETAPAS[e.etapa],
    tokens: e.tokens_entrada_medio + e.tokens_saida_medio,
    rotuloLatencia: `p50 ${segundos(e.latencia_p50_ms)} · p95 ${segundos(e.latencia_p95_ms)}`,
    rotuloP95: segundos(e.latencia_p95_ms),
  }))

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-5xl space-y-5 px-4 py-6">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-xl font-semibold text-zinc-900">Desempenho da IA</h2>
            <p className="mt-1 text-sm text-zinc-500">
              Cada chamada ao modelo de linguagem é registrada com tempo, tokens e custo; a qualidade é
              medida por regra sobre os casos encerrados.
            </p>
          </div>
          <label className="text-xs font-medium text-zinc-500">
            Período
            <select
              value={dias}
              onChange={(e) => setDias(Number(e.target.value))}
              className="mt-1 block rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-800"
            >
              {PERIODOS.map((p) => (
                <option key={p} value={p}>
                  Últimos {p} dias
                </option>
              ))}
            </select>
          </label>
        </div>

        {erro && <p className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">{erro}</p>}

        {uso && (
          <>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <Cartao
                titulo="Chamadas ao modelo"
                valor={String(uso.chamadas)}
                detalhe={`${uso.casos} ${uso.casos === 1 ? 'caso' : 'casos'}`}
              />
              <Cartao titulo="Custo por caso" valor={dolar(uso.custo_por_caso)} detalhe={`total no período ${dolar(uso.custo_total)}`} />
              <Cartao
                titulo="Falhas"
                valor={pct(uso.taxa_erro)}
                detalhe="chamadas que terminaram em erro"
              />
              <Cartao
                titulo="Segunda tentativa"
                valor={pct(uso.segunda_tentativa)}
                detalhe="resposta fora do formato na 1ª"
              />
            </div>

            {uso.chamadas === 0 ? (
              <p className="rounded-lg border border-zinc-200 bg-white px-4 py-3 text-sm text-zinc-600">
                Nenhuma chamada registrada no período.
              </p>
            ) : (
              <div className="grid gap-4 lg:grid-cols-2">
                <Figura
                  titulo="Tempo de resposta por etapa"
                  descricao="Barra: p95 (95% das chamadas responderam em até este tempo); p50 no detalhe"
                  tabela={etapas.map((e) => [e.nome, `${e.rotuloLatencia} · ${e.chamadas} chamadas`])}
                >
                  <ResponsiveContainer width="100%" height={Math.max(etapas.length * 40, 80)}>
                    <BarChart data={etapas} layout="vertical" margin={{ left: 0, right: 56, top: 0, bottom: 0 }}>
                      <CartesianGrid horizontal={false} stroke={GRADE} />
                      <XAxis type="number" tickFormatter={(v) => `${v / 1000}s`} tick={EIXO} axisLine={false} tickLine={false} />
                      <YAxis type="category" dataKey="nome" width={130} tick={EIXO} axisLine={false} tickLine={false} />
                      <Tooltip
                        cursor={{ fill: '#f4f4f5' }}
                        content={({ active, payload }) =>
                          active && payload?.[0] ? (
                            <Dica linhas={[payload[0].payload.nome, payload[0].payload.rotuloLatencia, `${payload[0].payload.chamadas} chamadas`]} />
                          ) : null
                        }
                      />
                      <Bar dataKey="latencia_p95_ms" fill={COR} radius={[0, 4, 4, 0]} maxBarSize={20} isAnimationActive={false}>
                        <LabelList dataKey="rotuloP95" position="right" style={{ fontSize: 12, fill: '#3f3f46' }} />
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </Figura>

                <Figura
                  titulo="Tokens por chamada"
                  descricao="Média de entrada + saída; o cache é a parte da entrada que o provedor cobra menos"
                  tabela={etapas.map((e) => [
                    e.nome,
                    `${Math.round(e.tokens_entrada_medio)} entrada · ${Math.round(e.tokens_saida_medio)} saída · cache ${pct(e.cache)}`,
                  ])}
                >
                  <ResponsiveContainer width="100%" height={Math.max(etapas.length * 40, 80)}>
                    <BarChart data={etapas} layout="vertical" margin={{ left: 0, right: 64, top: 0, bottom: 0 }}>
                      <CartesianGrid horizontal={false} stroke={GRADE} />
                      <XAxis type="number" tick={EIXO} axisLine={false} tickLine={false} />
                      <YAxis type="category" dataKey="nome" width={130} tick={EIXO} axisLine={false} tickLine={false} />
                      <Tooltip
                        cursor={{ fill: '#f4f4f5' }}
                        content={({ active, payload }) =>
                          active && payload?.[0] ? (
                            <Dica
                              linhas={[
                                payload[0].payload.nome,
                                `${Math.round(payload[0].payload.tokens_entrada_medio)} entrada · ${Math.round(payload[0].payload.tokens_saida_medio)} saída`,
                                `cache ${pct(payload[0].payload.cache)} · ${dolar(payload[0].payload.custo_medio)} por chamada`,
                              ]}
                            />
                          ) : null
                        }
                      />
                      <Bar dataKey="tokens" fill={COR} radius={[0, 4, 4, 0]} maxBarSize={20} isAnimationActive={false}>
                        <LabelList dataKey="tokens" position="right" formatter={(v) => decimal(Number(v), 0)} style={{ fontSize: 12, fill: '#3f3f46' }} />
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </Figura>

                <Figura
                  titulo="Custo por dia"
                  descricao="Soma do custo informado pelo provedor (USD)"
                  tabela={uso.por_dia.map((d) => [diaMes(d.dia), `${dolar(d.custo)} · ${d.chamadas} chamadas`])}
                >
                  <ResponsiveContainer width="100%" height={200}>
                    <BarChart data={uso.por_dia} margin={{ left: 0, right: 12, top: 8, bottom: 0 }}>
                      <CartesianGrid vertical={false} stroke={GRADE} />
                      <XAxis dataKey="dia" tickFormatter={diaMes} tick={EIXO} axisLine={false} tickLine={false} />
                      <YAxis tickFormatter={(v) => dolar(v, 3)} width={70} tick={EIXO} axisLine={false} tickLine={false} />
                      <Tooltip
                        cursor={{ fill: '#f4f4f5' }}
                        content={({ active, payload }) =>
                          active && payload?.[0] ? (
                            <Dica linhas={[diaMes(payload[0].payload.dia), `${dolar(payload[0].payload.custo)} · ${payload[0].payload.chamadas} chamadas`]} />
                          ) : null
                        }
                      />
                      <Bar dataKey="custo" fill={COR} radius={[4, 4, 0, 0]} maxBarSize={24} isAnimationActive={false} />
                    </BarChart>
                  </ResponsiveContainer>
                </Figura>
              </div>
            )}
          </>
        )}

        <section aria-label="Qualidade da saída" className="space-y-3">
          <h3 className="text-sm font-semibold text-zinc-900">Qualidade da saída</h3>
          {qualidade && (
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <Cartao
                titulo="Feedbacks com citação"
                valor={pct(qualidade.feedbacks_com_citacao)}
                detalhe={`${decimal(qualidade.citacoes_por_feedback)} citações por feedback · ${qualidade.feedbacks} feedbacks`}
              />
              <Cartao
                titulo="Citações válidas"
                valor={pct(qualidade.citacoes_validas)}
                detalhe="apontam para uma fonte que foi ao prompt"
              />
              <Cartao
                titulo="Conduta referenciada"
                valor={pct(qualidade.conduta_com_citacao)}
                detalhe="passos da conduta com citação [n]"
              />
              <Cartao
                titulo="Aderência ao sorteio"
                valor={pct(qualidade.aderencia_ao_sorteio)}
                detalhe={`gabarito = condição sorteada · ${qualidade.casos_com_fonte} casos`}
              />
            </div>
          )}
          {qualidade && qualidade.feedbacks_formato_antigo > 0 && (
            <p className="text-xs text-zinc-500">
              {qualidade.feedbacks_formato_antigo} feedback(s) no formato antigo (lacunas como nomes de doença).
            </p>
          )}
          {qualidade && qualidade.nao_aderentes.length > 0 && (
            <details className="rounded-xl border border-zinc-200 bg-white p-4 text-sm">
              <summary className="cursor-pointer font-medium text-zinc-800">
                Casos em que o gabarito não nomeia a condição sorteada
              </summary>
              <ul className="mt-2 space-y-1 text-zinc-600">
                {qualidade.nao_aderentes.map((n, i) => (
                  <li key={i}>
                    {n.diagnostico} <span className="text-zinc-400">← {n.fonte}</span>
                  </li>
                ))}
              </ul>
            </details>
          )}

          <div className="flex flex-wrap items-center gap-3 rounded-xl border border-zinc-200 bg-white p-4">
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-zinc-900">Recuperação do RAG (acerto@5)</p>
              <p className="text-xs text-zinc-500">
                Quadros clínicos de teste: a fonte certa está entre os 5 trechos mais próximos?
              </p>
            </div>
            {rag && (
              <p className="text-2xl font-semibold tabular-nums text-zinc-900">
                {rag.acertos}/{rag.consultas}
              </p>
            )}
            <button
              onClick={avaliarRAG}
              disabled={avaliando}
              className="inline-flex items-center gap-1.5 rounded-lg bg-teal-600 px-3 py-2 text-sm font-medium text-white hover:bg-teal-500 disabled:opacity-50"
            >
              <Play className="h-4 w-4" aria-hidden />
              {avaliando ? 'Avaliando…' : 'Rodar avaliação'}
            </button>
          </div>
        </section>
      </div>
    </div>
  )
}
