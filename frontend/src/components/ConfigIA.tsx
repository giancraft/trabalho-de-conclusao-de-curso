import { useEffect, useState } from 'react'
import { History, RotateCcw, Save } from 'lucide-react'
import * as api from '../api'
import type { ConfigIA as Config, ConfiguracaoLeitura } from '../types'

type NomeEtapa = 'caso' | 'pedidos' | 'chat' | 'feedback'

const ETAPAS: [NomeEtapa, string, string][] = [
  ['caso', 'Geração do caso', 'Cria o paciente e a ficha oculta a partir da fonte sorteada'],
  ['pedidos', 'Leitura dos pedidos', 'Lista o que o estudante pediu (exame físico, exames, conduta)'],
  ['chat', 'Respostas do chat', 'Responde como paciente e devolve os resultados'],
  ['feedback', 'Feedback', 'Avalia a investigação e a resposta final'],
]
const RACIOCINIO = { padrao: 'Padrão do modelo', low: 'Baixo', medium: 'Médio', high: 'Alto' }

const campo =
  'w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-800 ' +
  'outline-none focus:border-teal-500 focus:ring-2 focus:ring-teal-100'
const rotulo = 'mb-1 block text-xs font-medium text-zinc-500'
const secao = 'rounded-xl border border-zinc-200 bg-white p-5'

/** "caso.temperatura: 0.6 → 0.7" para cada campo que mudou entre duas versões. */
function mudancas(antes: Config, depois: Config): string[] {
  const plano = (c: Config): Record<string, string> =>
    Object.fromEntries(
      Object.entries(c).flatMap(([k, v]) =>
        v && typeof v === 'object' && !Array.isArray(v)
          ? Object.entries(v).map(([k2, v2]) => [`${k}.${k2}`, String(v2)])
          : [[k, Array.isArray(v) ? v.join(', ') || '—' : String(v)]],
      ),
    )
  const a = plano(antes)
  const d = plano(depois)
  return Object.keys(d)
    .filter((k) => a[k] !== d[k])
    .map((k) => `${k}: ${a[k]} → ${d[k]}`)
}

/** Parâmetros técnicos da IA (RF12) — só administrador. Salvar cria uma versão nova; as
 * chamadas seguintes registram qual versão estava em vigor. */
export default function ConfigIA() {
  const [leitura, setLeitura] = useState<ConfiguracaoLeitura | null>(null)
  const [form, setForm] = useState<Config | null>(null)
  const [provedores, setProvedores] = useState('')
  const [aviso, setAviso] = useState<{ tipo: 'ok' | 'erro'; texto: string } | null>(null)
  const [ocupado, setOcupado] = useState(false)

  function carregar(l: ConfiguracaoLeitura) {
    setLeitura(l)
    setForm(l.atual)
    setProvedores(l.atual.provedores.join(', '))
  }

  useEffect(() => {
    api.lerConfigIA().then(carregar).catch((e) => setAviso({ tipo: 'erro', texto: e.message }))
  }, [])

  async function executar(acao: () => Promise<ConfiguracaoLeitura>, sucesso: string) {
    setOcupado(true)
    setAviso(null)
    try {
      carregar(await acao())
      setAviso({ tipo: 'ok', texto: sucesso })
    } catch (e) {
      setAviso({ tipo: 'erro', texto: e instanceof Error ? e.message : 'Falha ao salvar.' })
    } finally {
      setOcupado(false)
    }
  }

  if (!form || !leitura) {
    return <p className="m-6 text-sm text-zinc-500">{aviso?.texto ?? 'Carregando…'}</p>
  }

  const editado: Config = {
    ...form,
    provedores: provedores.split(',').map((p) => p.trim()).filter(Boolean),
  }
  const pendentes = mudancas(leitura.atual, editado)
  const etapa = (nome: NomeEtapa, mudanca: Partial<Config[NomeEtapa]>) =>
    setForm({ ...form, [nome]: { ...form[nome], ...mudanca } })

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-3xl space-y-5 px-4 py-6">
        <div>
          <h2 className="text-xl font-semibold text-zinc-900">Configuração da IA</h2>
          <p className="mt-1 text-sm text-zinc-500">
            Em vigor: {leitura.versao_id ? `versão #${leitura.versao_id}` : 'padrão do sistema'}. Salvar cria uma
            versão nova, que vale a partir da próxima chamada. A chave da API e o endereço do provedor ficam no
            servidor (.env).
          </p>
        </div>

        {aviso && (
          <p
            role="status"
            className={`rounded-lg px-4 py-3 text-sm ${
              aviso.tipo === 'ok' ? 'bg-teal-50 text-teal-800' : 'bg-red-50 text-red-700'
            }`}
          >
            {aviso.texto}
          </p>
        )}

        <section className={`${secao} grid gap-3 sm:grid-cols-2`}>
          <div className="sm:col-span-2">
            <h3 className="text-sm font-semibold text-zinc-900">Modelo</h3>
          </div>
          <div>
            <label htmlFor="cfg-modelo" className={rotulo}>
              Modelo (id no provedor)
            </label>
            <input
              id="cfg-modelo"
              className={campo}
              value={form.modelo}
              onChange={(e) => setForm({ ...form, modelo: e.target.value })}
            />
          </div>
          <div>
            <label htmlFor="cfg-provedores" className={rotulo}>
              Provedores, em ordem (OpenRouter)
            </label>
            <input
              id="cfg-provedores"
              className={campo}
              value={provedores}
              placeholder="vazio: o OpenRouter escolhe"
              onChange={(e) => setProvedores(e.target.value)}
            />
          </div>
        </section>

        <section className={`${secao} space-y-3`}>
          <h3 className="text-sm font-semibold text-zinc-900">Etapas</h3>
          {ETAPAS.map(([nome, titulo, descricao]) => (
            <div key={nome} className="grid items-end gap-3 border-t border-zinc-100 pt-3 sm:grid-cols-[1fr_8rem_10rem]">
              <div>
                <p className="text-sm font-medium text-zinc-800">{titulo}</p>
                <p className="text-xs text-zinc-500">{descricao}</p>
              </div>
              <div>
                <label htmlFor={`cfg-${nome}-temp`} className={rotulo}>
                  Temperatura
                </label>
                <input
                  id={`cfg-${nome}-temp`}
                  type="number"
                  min={0}
                  max={1.5}
                  step={0.1}
                  className={campo}
                  value={form[nome].temperatura}
                  onChange={(e) => etapa(nome, { temperatura: Number(e.target.value) })}
                />
              </div>
              <div>
                <label htmlFor={`cfg-${nome}-rac`} className={rotulo}>
                  Raciocínio
                </label>
                <select
                  id={`cfg-${nome}-rac`}
                  className={campo}
                  value={form[nome].raciocinio}
                  onChange={(e) => etapa(nome, { raciocinio: e.target.value as Config[NomeEtapa]['raciocinio'] })}
                >
                  {Object.entries(RACIOCINIO).map(([valor, texto]) => (
                    <option key={valor} value={valor}>
                      {texto}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          ))}
        </section>

        <section className={`${secao} space-y-3`}>
          <div>
            <h3 className="text-sm font-semibold text-zinc-900">Janela da conversa</h3>
            <p className="text-xs text-zinc-500">
              Turnos enviados ao modelo. O chat cresce até o limite e volta ao corte: entre um corte e outro o
              começo do prompt se repete e o provedor o serve do cache, mais barato.
            </p>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            {(
              [
                ['turnos_chat', 'Chat: limite'],
                ['turnos_chat_apos_corte', 'Chat: após o corte'],
                ['turnos_avaliacao', 'Feedback'],
              ] as const
            ).map(([chave, texto]) => (
              <div key={chave}>
                <label htmlFor={`cfg-${chave}`} className={rotulo}>
                  {texto}
                </label>
                <input
                  id={`cfg-${chave}`}
                  type="number"
                  min={1}
                  max={100}
                  className={campo}
                  value={form[chave]}
                  onChange={(e) => setForm({ ...form, [chave]: Number(e.target.value) })}
                />
              </div>
            ))}
          </div>
        </section>

        <div className="sticky bottom-0 flex flex-wrap items-center gap-2 border-t border-zinc-200 bg-zinc-50 py-3">
          <button
            onClick={() => executar(() => api.salvarConfigIA(editado), 'Nova versão salva e em vigor.')}
            disabled={ocupado || pendentes.length === 0}
            className="inline-flex items-center gap-1.5 rounded-lg bg-teal-600 px-4 py-2 text-sm font-medium text-white hover:bg-teal-500 disabled:opacity-50"
          >
            <Save className="h-4 w-4" aria-hidden />
            Salvar {pendentes.length > 0 && `(${pendentes.length} alteraç${pendentes.length > 1 ? 'ões' : 'ão'})`}
          </button>
          <button
            onClick={() => {
              setForm(leitura.padrao)
              setProvedores(leitura.padrao.provedores.join(', '))
            }}
            disabled={ocupado}
            className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-300 bg-white px-4 py-2 text-sm text-zinc-700 hover:bg-zinc-50"
          >
            <RotateCcw className="h-4 w-4" aria-hidden />
            Preencher com o padrão
          </button>
          {pendentes.length > 0 && (
            <button onClick={() => carregar(leitura)} className="text-sm text-zinc-500 hover:underline">
              Descartar
            </button>
          )}
        </div>

        <section className={secao} aria-label="Histórico de versões">
          <h3 className="mb-3 flex items-center gap-1.5 text-sm font-semibold text-zinc-900">
            <History className="h-4 w-4" aria-hidden />
            Histórico
          </h3>
          {leitura.historico.length === 0 ? (
            <p className="text-sm text-zinc-500">Nenhuma versão salva: vale o padrão do sistema.</p>
          ) : (
            <ol className="divide-y divide-zinc-100">
              {leitura.historico.map((v, i) => {
                const anterior = leitura.historico[i + 1]?.dados ?? leitura.padrao
                const diferencas = mudancas(anterior, v.dados)
                return (
                  <li key={v.id} className="flex flex-wrap items-start gap-3 py-2.5">
                    <div className="min-w-0 flex-1">
                      <p className="text-sm text-zinc-800">
                        Versão #{v.id}
                        {v.id === leitura.versao_id && (
                          <span className="ml-2 rounded bg-teal-50 px-1.5 py-0.5 text-xs text-teal-800">em vigor</span>
                        )}
                      </p>
                      <p className="text-xs text-zinc-500">
                        {new Date(v.criado_em).toLocaleString('pt-BR')} · {v.autor ?? 'conta excluída'}
                      </p>
                      <p className="mt-1 text-xs text-zinc-600">
                        {diferencas.length ? diferencas.join(' · ') : 'sem mudança em relação à anterior'}
                      </p>
                    </div>
                    {v.id !== leitura.versao_id && (
                      <button
                        onClick={() => executar(() => api.restaurarConfigIA(v.id), `Versão #${v.id} restaurada.`)}
                        disabled={ocupado}
                        className="text-xs font-medium text-teal-700 hover:underline disabled:opacity-50"
                      >
                        Restaurar
                      </button>
                    )}
                  </li>
                )
              })}
            </ol>
          )}
        </section>
      </div>
    </div>
  )
}
