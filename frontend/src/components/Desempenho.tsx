import { useEffect, useState } from 'react'
import { ArrowDownRight, ArrowRight, ArrowUpRight } from 'lucide-react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  LabelList,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import * as api from '../api'
import type { Desempenho as Dados, Grupo } from '../types'
import { COR, EIXO, GRADE, decimal, diaMes, haQuanto, pct } from '../graficos'
import { Cartao, Dica, Figura } from './Painel'

interface Props {
  ocupado: boolean
  onTreinar: (no: string) => void
  onRevisao: () => void
}

const MINIMO = 3 // casos para o painel dizer alguma coisa

/** Barras horizontais de acerto (0–100%), com "n" ao lado: 1 de 1 não é 7 de 7. */
function BarrasDeAcerto({ grupos }: { grupos: Grupo[] }) {
  const dados = grupos.map((g) => ({
    ...g,
    taxa: g.acertos / g.casos,
    rotulo: `${pct(g.acertos / g.casos)} · ${g.acertos}/${g.casos}`,
  }))
  return (
    <ResponsiveContainer width="100%" height={Math.max(dados.length * 34, 80)}>
      <BarChart data={dados} layout="vertical" margin={{ left: 0, right: 84, top: 0, bottom: 0 }}>
        <CartesianGrid horizontal={false} stroke={GRADE} />
        <XAxis type="number" domain={[0, 1]} tickFormatter={pct} tick={EIXO} axisLine={false} tickLine={false} />
        <YAxis type="category" dataKey="nome" width={150} tick={EIXO} axisLine={false} tickLine={false} />
        <Tooltip
          cursor={{ fill: '#f4f4f5' }}
          content={({ active, payload }) =>
            active && payload?.[0] ? (
              <Dica
                linhas={[
                  payload[0].payload.nome,
                  `${payload[0].payload.acertos} de ${payload[0].payload.casos} corretos (${pct(payload[0].payload.taxa)})`,
                ]}
              />
            ) : null
          }
        />
        {/* minPointSize: 0% ainda mostra um traço e o rótulo, em vez de sumir. */}
        <Bar dataKey="taxa" fill={COR} radius={[0, 4, 4, 0]} maxBarSize={20} minPointSize={2} isAnimationActive={false}>
          <LabelList dataKey="rotulo" position="right" style={{ fontSize: 12, fill: '#3f3f46' }} />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

export default function Desempenho({ ocupado, onTreinar, onRevisao }: Props) {
  const [dados, setDados] = useState<Dados | null>(null)
  const [erro, setErro] = useState<string | null>(null)

  useEffect(() => {
    api
      .buscarDesempenho()
      .then(setDados)
      .catch((e) => setErro(e instanceof Error ? e.message : 'Falha ao carregar o desempenho.'))
  }, [])

  if (erro) return <p className="m-6 text-sm text-red-700">{erro}</p>
  if (!dados) return <p className="m-6 text-sm text-zinc-500">Carregando…</p>

  const k = dados.kpis
  const poucos = k.casos_concluidos < MINIMO
  const delta =
    k.taxa_acerto_recente != null && k.taxa_acerto_anterior != null
      ? Math.round((k.taxa_acerto_recente - k.taxa_acerto_anterior) * 100)
      : null
  const lacunas = [...dados.lacunas].sort((a, b) => b.por_caso - a.por_caso)

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-5xl space-y-5 px-4 py-6">
        <div>
          <h2 className="text-xl font-semibold text-zinc-900">Meu desempenho</h2>
          <p className="mt-1 text-sm text-zinc-500">
            Calculado a partir dos seus casos encerrados: diagnóstico, tempo de investigação e o
            que faltou em cada um, segundo o feedback.
          </p>
        </div>

        {poucos && (
          <p className="rounded-lg border border-zinc-200 bg-white px-4 py-3 text-sm text-zinc-600">
            Conclua pelo menos {MINIMO} casos para ver suas métricas
            {k.casos_concluidos > 0 && ` (até agora: ${k.casos_concluidos})`}.
          </p>
        )}

        {!poucos && (
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Cartao
              titulo="Casos concluídos"
              valor={String(k.casos_concluidos)}
              detalhe={k.casos_abertos ? `${k.casos_abertos} em andamento` : undefined}
            />
            <Cartao
              titulo="Diagnósticos corretos"
              valor={pct(k.taxa_acerto)}
              detalhe={
                delta != null && (
                  <span className="inline-flex items-center gap-1">
                    {delta >= 0 ? (
                      <ArrowUpRight className="h-3.5 w-3.5 text-teal-600" aria-hidden />
                    ) : (
                      <ArrowDownRight className="h-3.5 w-3.5 text-amber-600" aria-hidden />
                    )}
                    {delta >= 0 ? '+' : ''}
                    {delta} p.p. nas últimas 4 semanas
                  </span>
                )
              }
            />
            <Cartao
              titulo="Tempo por caso"
              valor={k.minutos_por_caso == null ? '—' : `${Math.round(k.minutos_por_caso)} min`}
              detalhe="mediana do tempo ativo"
            />
            <Cartao
              titulo="Perguntas por caso"
              valor={decimal(k.perguntas_por_caso)}
              detalhe={`${decimal(k.lacunas_por_caso)} lacuna(s) por caso`}
            />
          </div>
        )}

        <button
          onClick={onRevisao}
          className="flex w-full items-center justify-between gap-3 rounded-xl border border-teal-200 bg-teal-50/60 px-4 py-3 text-left hover:bg-teal-50"
        >
          <span>
            <span className="block text-sm font-semibold text-zinc-900">O que estudar a seguir</span>
            <span className="block text-xs text-zinc-600">
              Temas para revisar hoje e recomendações, com base no seu histórico.
            </span>
          </span>
          <span className="inline-flex shrink-0 items-center gap-1 text-sm font-medium text-teal-700">
            Ver revisões <ArrowRight className="h-4 w-4" aria-hidden />
          </span>
        </button>

        {!poucos && (
          <div className="grid gap-4 lg:grid-cols-2">
            <Figura
              titulo="Evolução do acerto"
              descricao="Acerto dos seus últimos 5 casos, caso a caso"
              tabela={dados.evolucao.map((e) => [
                `Caso ${e.ordem} (${diaMes(e.data)})`,
                `${pct(e.acerto_movel)} · ${e.acertou ? 'acertou' : 'errou'}`,
              ])}
            >
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={dados.evolucao} margin={{ left: -12, right: 12, top: 8, bottom: 0 }}>
                  <CartesianGrid vertical={false} stroke={GRADE} />
                  <XAxis dataKey="ordem" tick={EIXO} axisLine={false} tickLine={false} />
                  <YAxis domain={[0, 1]} ticks={[0, 0.5, 1]} tickFormatter={pct} tick={EIXO} axisLine={false} tickLine={false} />
                  <Tooltip
                    content={({ active, payload }) =>
                      active && payload?.[0] ? (
                        <Dica
                          linhas={[
                            `Caso ${payload[0].payload.ordem} · ${diaMes(payload[0].payload.data)}`,
                            `${payload[0].payload.acertou ? 'Acertou' : 'Errou'} · média móvel ${pct(payload[0].payload.acerto_movel)}`,
                          ]}
                        />
                      ) : null
                    }
                  />
                  <Line
                    type="monotone"
                    dataKey="acerto_movel"
                    stroke={COR}
                    strokeWidth={2}
                    dot={{ r: 4, fill: COR, stroke: '#fff', strokeWidth: 2 }}
                    activeDot={{ r: 6, stroke: '#fff', strokeWidth: 2 }}
                    isAnimationActive={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </Figura>

            <Figura
              titulo="Casos por semana"
              descricao="Quantos casos você concluiu em cada semana"
              tabela={dados.por_semana.map((s) => [`Semana de ${diaMes(s.semana)}`, `${s.casos} (${s.acertos} corretos)`])}
            >
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={dados.por_semana} margin={{ left: -24, right: 12, top: 8, bottom: 0 }}>
                  <CartesianGrid vertical={false} stroke={GRADE} />
                  <XAxis dataKey="semana" tickFormatter={diaMes} tick={EIXO} axisLine={false} tickLine={false} />
                  <YAxis allowDecimals={false} tick={EIXO} axisLine={false} tickLine={false} />
                  <Tooltip
                    cursor={{ fill: '#f4f4f5' }}
                    content={({ active, payload }) =>
                      active && payload?.[0] ? (
                        <Dica
                          linhas={[
                            `Semana de ${diaMes(payload[0].payload.semana)}`,
                            `${payload[0].payload.casos} casos · ${payload[0].payload.acertos} corretos`,
                          ]}
                        />
                      ) : null
                    }
                  />
                  <Bar dataKey="casos" fill={COR} radius={[4, 4, 0, 0]} maxBarSize={24} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </Figura>

            <Figura
              titulo="Acerto por especialidade"
              descricao="Diagnósticos corretos em cada especialidade"
              tabela={dados.por_especialidade.map((g) => [g.nome, `${g.acertos}/${g.casos} (${pct(g.acertos / g.casos)})`])}
            >
              <BarrasDeAcerto grupos={dados.por_especialidade} />
            </Figura>

            <Figura
              titulo="Onde faltou na investigação"
              descricao="Lacunas apontadas pelo feedback, em média por caso"
              tabela={lacunas.map((l) => [l.etapa, `${decimal(l.por_caso, 2)} por caso (${l.total} no total)`])}
            >
              <ResponsiveContainer width="100%" height={Math.max(lacunas.length * 34, 80)}>
                <BarChart data={lacunas} layout="vertical" margin={{ left: 0, right: 48, top: 0, bottom: 0 }}>
                  <CartesianGrid horizontal={false} stroke={GRADE} />
                  <XAxis type="number" tick={EIXO} axisLine={false} tickLine={false} allowDecimals />
                  <YAxis type="category" dataKey="etapa" width={150} tick={EIXO} axisLine={false} tickLine={false} />
                  <Tooltip
                    cursor={{ fill: '#f4f4f5' }}
                    content={({ active, payload }) =>
                      active && payload?.[0] ? (
                        <Dica
                          linhas={[
                            payload[0].payload.etapa,
                            `${decimal(payload[0].payload.por_caso, 2)} por caso · ${payload[0].payload.total} no total`,
                          ]}
                        />
                      ) : null
                    }
                  />
                  <Bar dataKey="por_caso" fill={COR} radius={[0, 4, 4, 0]} maxBarSize={20} isAnimationActive={false}>
                    <LabelList
                      dataKey="por_caso"
                      position="right"
                      formatter={(v) => decimal(Number(v))}
                      style={{ fontSize: 12, fill: '#3f3f46' }}
                    />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </Figura>

            {dados.por_topico.length > 0 && (
              <Figura
                titulo="Acerto por tópico da resposta"
                descricao="Tópicos avaliados como corretos (parcial não conta)"
                tabela={dados.por_topico.map((g) => [g.nome, `${g.acertos}/${g.casos}`])}
              >
                <BarrasDeAcerto grupos={dados.por_topico} />
              </Figura>
            )}

            <Figura
              titulo="Por ciclo"
              descricao="Diagnósticos corretos no nível de cobrança de cada ciclo"
              tabela={dados.por_ciclo.map((g) => [g.nome, `${g.acertos}/${g.casos}`])}
            >
              <BarrasDeAcerto grupos={dados.por_ciclo} />
            </Figura>

            <Figura
              titulo="Apresentação típica e atípica"
              descricao="Casos de diretriz contra casos baseados em relato publicado"
              tabela={dados.por_apresentacao.map((g) => [g.nome, `${g.acertos}/${g.casos}`])}
            >
              <BarrasDeAcerto grupos={dados.por_apresentacao} />
            </Figura>
          </div>
        )}

        {dados.por_tema.length > 0 && (
          <section className="rounded-xl border border-zinc-200 bg-white p-4" aria-label="Temas praticados">
            <h3 className="mb-3 text-sm font-semibold text-zinc-900">Temas praticados</h3>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[560px] text-sm">
                <thead className="text-left text-xs text-zinc-500">
                  <tr>
                    <th className="pb-2 font-medium">Tema</th>
                    <th className="pb-2 font-medium">Especialidade</th>
                    <th className="pb-2 text-right font-medium">Casos</th>
                    <th className="pb-2 text-right font-medium">Acerto</th>
                    <th className="pb-2 text-right font-medium">Último</th>
                    <th className="pb-2" />
                  </tr>
                </thead>
                <tbody>
                  {dados.por_tema.map((t) => (
                    <tr key={t.id} className="border-t border-zinc-100">
                      <td className="py-2 pr-2 text-zinc-800">{t.nome}</td>
                      <td className="py-2 pr-2 text-zinc-500">{t.detalhe}</td>
                      <td className="py-2 text-right tabular-nums text-zinc-700">{t.casos}</td>
                      <td className="py-2 text-right tabular-nums text-zinc-700">
                        {t.acertos}/{t.casos}
                      </td>
                      <td className="py-2 text-right text-zinc-500">{haQuanto(t.ultimo)}</td>
                      <td className="py-2 pl-2 text-right">
                        {t.id && (
                          <button
                            onClick={() => onTreinar(t.id!)}
                            disabled={ocupado}
                            className="text-xs font-medium text-teal-700 hover:underline disabled:opacity-50"
                          >
                            Treinar
                          </button>
                        )}
                      </td>
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
