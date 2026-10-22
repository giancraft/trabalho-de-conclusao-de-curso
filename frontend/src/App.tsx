import { useEffect, useState } from 'react'
import { Menu, Stethoscope } from 'lucide-react'
import Sidebar from './components/Sidebar'
import ChatWindow from './components/ChatWindow'
import Composer from './components/Composer'
import AuthPage from './components/AuthPage'
import * as api from './api'
import type { ConversaResumo, Feedback, Fonte, Mensagem, Opcoes, Usuario } from './types'

export default function App() {
  const [usuario, setUsuario] = useState<Usuario | null>(null)
  const [bootPronto, setBootPronto] = useState(false)

  const [opcoes, setOpcoes] = useState<Opcoes | null>(null)
  const [especialidade, setEspecialidade] = useState('Cardiologia')
  const [dificuldade, setDificuldade] = useState('intermediário')

  const [conversas, setConversas] = useState<ConversaResumo[]>([])
  const [casoId, setCasoId] = useState<string | null>(null)
  const [casoAberto, setCasoAberto] = useState(false) // status da conversa ativa
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
    api
      .buscarOpcoes()
      .then(setOpcoes)
      .catch(() => setErro('Backend indisponível. Inicie a API (uvicorn) e recarregue.'))
    atualizarConversas()
  }, [usuario])

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
  }

  async function novoCaso() {
    limparChat()
    setOcupado(true)
    setDigitando(true)
    try {
      const caso = await api.criarCaso(especialidade, dificuldade)
      setCasoId(caso.caso_id)
      setCasoAberto(true)
      setMensagens([{ role: 'assistant', content: caso.apresentacao }])
      atualizarConversas()
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'Falha ao criar o caso.')
    } finally {
      setDigitando(false)
      setOcupado(false)
    }
  }

  async function abrirConversa(id: string) {
    if (ocupado) return
    limparChat()
    try {
      const conversa = await api.carregarConversa(id)
      setCasoId(conversa.id)
      setCasoAberto(conversa.status === 'aberta')
      setMensagens(conversa.mensagens)
      setFeedback(conversa.feedback)
      setFontes(conversa.fontes)
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

  async function darDiagnostico(texto: string) {
    if (!casoId) return
    setOcupado(true)
    setErro(null)
    setMensagens((atual) => [
      ...atual,
      { role: 'user', content: `Diagnóstico final: ${texto}` },
    ])
    setDigitando(true)
    try {
      setFeedback(await api.enviarDiagnostico(casoId, texto))
      setCasoAberto(false)
      atualizarConversas()
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
        opcoes={opcoes}
        especialidade={especialidade}
        dificuldade={dificuldade}
        ocupado={ocupado}
        aberta={menuAberto}
        usuario={usuario}
        conversas={conversas}
        conversaAtivaId={casoId}
        onFechar={() => setMenuAberto(false)}
        onEspecialidade={setEspecialidade}
        onDificuldade={setDificuldade}
        onNovoCaso={novoCaso}
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
        <ChatWindow
          mensagens={mensagens}
          digitando={digitando}
          feedback={feedback}
          fontes={fontes}
          erro={erro}
          temCaso={mensagens.length > 0 || digitando}
          onNovoCaso={novoCaso}
        />
        {casoId && casoAberto && !feedback && (
          <Composer ocupado={ocupado} onMensagem={enviarMensagem} onDiagnostico={darDiagnostico} />
        )}
      </main>
    </div>
  )
}
