import { useEffect, useState } from 'react'
import { Menu, Stethoscope } from 'lucide-react'
import Sidebar from './components/Sidebar'
import ChatWindow from './components/ChatWindow'
import Composer from './components/Composer'
import AuthPage from './components/AuthPage'
import SeletorTemas from './components/SeletorTemas'
import { lerPreferencias } from './preferencias'
import Desempenho from './components/Desempenho'
import Conta from './components/Conta'
import AdminIA from './components/AdminIA'
import ConfigIA from './components/ConfigIA'
import Termo from './components/Termo'
import type { Tela } from './components/Sidebar'
import ResumoSimulado from './components/ResumoSimulado'
import * as api from './api'
import type {
  CasoAberto,
  ConversaResumo,
  Feedback,
  Fonte,
  Mensagem,
  Opcoes,
  RespostaFinal,
  Simulado,
  Usuario,
} from './types'

/** Onde o caso ativo está no simulado. */
interface Progresso {
  id: string
  ordem: number
  total: number
}

export default function App() {
  const [usuario, setUsuario] = useState<Usuario | null>(null)
  const [bootPronto, setBootPronto] = useState(false)

  const [opcoes, setOpcoes] = useState<Opcoes | null>(null)
  const [progresso, setProgresso] = useState<Progresso | null>(null)
  const [resumo, setResumo] = useState<Simulado | null>(null) // no fim do simulado
  const [tela, setTela] = useState<Tela>('caso')

  const [conversas, setConversas] = useState<ConversaResumo[]>([])
  const [casoId, setCasoId] = useState<string | null>(null)
  const [casoAberto, setCasoAberto] = useState(false) // status da conversa ativa
  const [casoCiclo, setCasoCiclo] = useState('clínico') // ciclo do caso ativo: campos da entrega
  const [mensagens, setMensagens] = useState<Mensagem[]>([])
  const [feedback, setFeedback] = useState<Feedback | null>(null)
  const [fontes, setFontes] = useState<Fonte[]>([])
  const [ocupado, setOcupado] = useState(false)
  const [digitando, setDigitando] = useState(false)
  const [erro, setErro] = useState<string | null>(null)
  const [menuAberto, setMenuAberto] = useState(false)

  useEffect(() => {
    api
      .eu()
      .then(setUsuario)
      .catch(() => setUsuario(null))
      .finally(() => setBootPronto(true))
  }, [])

  useEffect(() => {
    if (!usuario) return
    atualizarOpcoes()
    atualizarConversas()
  }, [usuario])

  function atualizarOpcoes() {
    api
      .buscarOpcoes()
      .then(setOpcoes)
      .catch(() => setErro('Backend indisponível. Inicie a API (uvicorn) e recarregue.'))
  }

  function atualizarConversas() {
    api.listarConversas().then(setConversas).catch(() => {})
  }

  function limparChat() {
    setCasoId(null)
    setCasoAberto(false)
    setMensagens([])
    setFeedback(null)
    setFontes([])
    setErro(null)
    setMenuAberto(false)
    setProgresso(null)
    setResumo(null)
    setTela('caso')
  }

  function irPara(destino: Tela) {
    setMenuAberto(false)
    setTela(destino)
  }

  /** "Treinar agora" do painel: um simulado curto só daquele tema, no ciclo de sempre. */
  function treinar(no: string) {
    limparChat()
    iniciarCaso(() => api.criarSimulado([no], lerPreferencias().ciclo ?? 'clínico', 3))
  }

  /** Abre o caso que a API acabou de gerar. A tela atual (seletor ou feedback do caso
   * anterior) só sai quando ele chega: se a geração falhar, o erro aparece onde se está. */
  async function iniciarCaso(pedido: () => Promise<CasoAberto>) {
    setOcupado(true)
    setErro(null)
    setDigitando(true)
    try {
      const caso = await pedido()
      setCasoId(caso.caso_id)
      setCasoCiclo(caso.ciclo)
      setCasoAberto(true)
      setFeedback(null)
      setFontes([])
      setResumo(null)
      setProgresso({ id: caso.simulado_id, ordem: caso.ordem, total: caso.total })
      setMensagens([{ role: 'assistant', content: caso.apresentacao }])
      atualizarConversas()
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'Falha ao criar o caso.')
    } finally {
      setDigitando(false)
      setOcupado(false)
    }
  }

  function gerarSimulado(selecao: string[], ciclo: string, quantidade: number) {
    iniciarCaso(() => api.criarSimulado(selecao, ciclo, quantidade))
  }

  function proximoCaso() {
    if (progresso) iniciarCaso(() => api.proximoCaso(progresso.id))
  }

  /** Último caso do simulado encerrado: carrega o resumo. */
  function talvezResumo(p: Progresso | null) {
    if (p && p.ordem >= p.total) api.lerSimulado(p.id).then(setResumo).catch(() => {})
  }

  async function abrirConversa(id: string) {
    if (ocupado) return
    limparChat()
    try {
      const conversa = await api.carregarConversa(id)
      setCasoId(conversa.id)
      setCasoCiclo(conversa.ciclo)
      setCasoAberto(conversa.status === 'aberta')
      setMensagens(conversa.mensagens)
      setFeedback(conversa.feedback)
      setFontes(conversa.fontes)
      const p = conversa.simulado_id
        ? { id: conversa.simulado_id, ordem: conversa.ordem ?? 1, total: conversa.total ?? 1 }
        : null
      setProgresso(p)
      if (conversa.status === 'encerrada') talvezResumo(p)
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'Falha ao abrir a conversa.')
    }
  }

  async function apagarConversa(id: string) {
    if (!confirm('Apagar esta conversa?')) return
    try {
      await api.apagarConversa(id)
      if (id === casoId) limparChat()
      atualizarConversas()
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'Falha ao apagar a conversa.')
    }
  }

  async function sair() {
    await api.logout().catch(() => {})
    limparChat()
    setConversas([])
    setUsuario(null)
  }

  async function enviarMensagem(texto: string) {
    if (!casoId) return
    setOcupado(true)
    setErro(null)
    setMensagens((atual) => [...atual, { role: 'user', content: texto }])
    setDigitando(true)
    let comecou = false
    try {
      await api.enviarMensagem(casoId, texto, (chunk) => {
        if (!comecou) {
          comecou = true
          setDigitando(false)
          setMensagens((atual) => [...atual, { role: 'assistant', content: chunk }])
        } else {
          setMensagens((atual) => {
            const copia = [...atual]
            const ultima = copia[copia.length - 1]
            copia[copia.length - 1] = { ...ultima, content: ultima.content + chunk }
            return copia
          })
        }
      })
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'Falha ao enviar a mensagem.')
    } finally {
      setDigitando(false)
      setOcupado(false)
    }
  }

  async function darDiagnostico(resposta: RespostaFinal, texto: string) {
    if (!casoId) return
    setOcupado(true)
    setErro(null)
    setMensagens((atual) => [...atual, { role: 'user', content: texto }])
    setDigitando(true)
    try {
      setFeedback(await api.enviarDiagnostico(casoId, resposta))
      setCasoAberto(false)
      atualizarConversas()
      atualizarOpcoes() // "respondidos" da árvore
      talvezResumo(progresso)
      // As fontes só saem da API com o caso encerrado (o título do capítulo é o
      // diagnóstico) — agora que encerrou, busca.
      api
        .carregarConversa(casoId)
        .then((c) => setFontes(c.fontes))
        .catch(() => {})
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'Falha ao avaliar o diagnóstico.')
    } finally {
      setDigitando(false)
      setOcupado(false)
    }
  }

  if (!bootPronto) return null
  if (!usuario) return <AuthPage onEntrar={setUsuario} />

  return (
    <div className="flex h-full bg-zinc-50 font-sans">
      <Sidebar
        ocupado={ocupado}
        aberta={menuAberto}
        usuario={usuario}
        conversas={conversas}
        conversaAtivaId={casoId}
        onFechar={() => setMenuAberto(false)}
        onNovoSimulado={limparChat}
        tela={tela}
        onTela={irPara}
        onAbrirConversa={abrirConversa}
        onApagarConversa={apagarConversa}
        onLogout={sair}
      />
      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-2 border-b border-zinc-200 bg-white px-3 py-2.5 md:hidden">
          <button
            onClick={() => setMenuAberto(true)}
            className="rounded-lg p-1.5 text-zinc-600 hover:bg-zinc-100"
            aria-label="Abrir menu"
          >
            <Menu className="h-5 w-5" />
          </button>
          <Stethoscope className="h-4 w-4 text-teal-600" />
          <span className="text-sm font-semibold text-zinc-800">Simulador Clínico</span>
        </header>
        {tela === 'desempenho' ? (
          <Desempenho ocupado={ocupado} onTreinar={treinar} />
        ) : tela === 'conta' ? (
          <Conta
            usuario={usuario}
            onAtualizado={(u) => {
              setUsuario(u)
              atualizarConversas()
            }}
            onExcluida={() => {
              limparChat()
              setConversas([])
              setUsuario(null)
            }}
          />
        ) : tela === 'admin-ia' ? (
          <AdminIA />
        ) : tela === 'config-ia' ? (
          <ConfigIA />
        ) : (
        <>
        {casoId && progresso && progresso.total > 1 && (
          <div className="border-b border-zinc-200 bg-white px-4 py-2 text-center text-xs text-zinc-500">
            Simulado · caso {progresso.ordem} de {progresso.total}
          </div>
        )}
        <ChatWindow
          mensagens={mensagens}
          digitando={digitando}
          feedback={feedback}
          fontes={fontes}
          erro={erro}
          temCaso={mensagens.length > 0 || digitando}
          inicio={
            <>
              {erro && (
                <div className="mx-auto mt-6 max-w-3xl px-4">
                  <p className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                    {erro}
                  </p>
                </div>
              )}
              <SeletorTemas
                arvore={opcoes?.arvore ?? []}
                ciclos={opcoes?.ciclos ?? []}
                ocupado={ocupado}
                onGerar={gerarSimulado}
              />
            </>
          }
          aposFeedback={
            <div className="space-y-4 pb-2">
              {progresso && progresso.ordem < progresso.total ? (
                <div className="flex justify-center">
                  <button
                    onClick={proximoCaso}
                    disabled={ocupado}
                    className="rounded-lg bg-teal-600 px-5 py-2.5 text-sm font-medium text-white
                               transition-colors hover:bg-teal-500 disabled:opacity-50"
                  >
                    Próximo caso ({progresso.ordem + 1}/{progresso.total})
                  </button>
                </div>
              ) : (
                <>
                  {resumo && resumo.total > 1 && <ResumoSimulado simulado={resumo} onAbrir={abrirConversa} />}
                  <div className="flex justify-center">
                    <button
                      onClick={limparChat}
                      className="rounded-lg bg-teal-600 px-5 py-2.5 text-sm font-medium text-white
                                 transition-colors hover:bg-teal-500"
                    >
                      Novo simulado
                    </button>
                  </div>
                </>
              )}
            </div>
          }
        />
        {casoId && casoAberto && !feedback && (
          <Composer
            ocupado={ocupado}
            ciclo={casoCiclo}
            onMensagem={enviarMensagem}
            onDiagnostico={darDiagnostico}
          />
        )}
        </>
        )}
      </main>
      {/* Conta anterior ao termo: aceitar para continuar (LGPD). */}
      <Termo
        aberto={!usuario.consentiu}
        obrigatorio
        onFechar={() => {}}
        acoes={
          <>
            <button onClick={sair} className="rounded-lg px-4 py-2 text-sm text-zinc-600 hover:bg-zinc-100">
              Sair
            </button>
            <button
              onClick={() => api.consentir().then(setUsuario).catch(() => {})}
              className="rounded-lg bg-teal-600 px-4 py-2 text-sm font-medium text-white hover:bg-teal-500"
            >
              Li e aceito
            </button>
          </>
        }
      />
    </div>
  )
}
