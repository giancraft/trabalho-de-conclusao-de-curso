import { useState } from 'react'
import { Download, FileText, Trash2 } from 'lucide-react'
import * as api from '../api'
import type { Usuario } from '../types'
import Termo from './Termo'

interface Props {
  usuario: Usuario
  onAtualizado: (u: Usuario) => void
  onExcluida: () => void
}

const campo =
  'w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-800 ' +
  'outline-none focus:border-teal-500 focus:ring-2 focus:ring-teal-100'
const rotulo = 'mb-1 block text-sm font-medium text-zinc-700'
const secao = 'rounded-xl border border-zinc-200 bg-white p-5'

/** Minha conta: editar nome e email, baixar os dados e excluir a conta (RF02, LGPD). */
export default function Conta({ usuario, onAtualizado, onExcluida }: Props) {
  const [nome, setNome] = useState(usuario.nome)
  const [email, setEmail] = useState(usuario.email)
  const [senha, setSenha] = useState('')
  const [aviso, setAviso] = useState<{ tipo: 'ok' | 'erro'; texto: string } | null>(null)
  const [ocupado, setOcupado] = useState(false)
  const [termoAberto, setTermoAberto] = useState(false)

  async function executar(acao: () => Promise<void>) {
    setOcupado(true)
    setAviso(null)
    try {
      await acao()
    } catch (e) {
      setAviso({ tipo: 'erro', texto: e instanceof Error ? e.message : 'Algo deu errado.' })
    } finally {
      setOcupado(false)
    }
  }

  const salvar = (e: React.FormEvent) => {
    e.preventDefault()
    executar(async () => {
      onAtualizado(await api.editarConta(nome, email))
      setAviso({ tipo: 'ok', texto: 'Dados atualizados.' })
    })
  }

  const baixar = () =>
    executar(async () => {
      const blob = new Blob([await api.meusDados()], { type: 'application/json' })
      const link = document.createElement('a')
      link.href = URL.createObjectURL(blob)
      link.download = 'meus-dados-simulador.json'
      link.click()
      URL.revokeObjectURL(link.href)
    })

  const excluir = (e: React.FormEvent) => {
    e.preventDefault()
    if (!confirm('Excluir a conta apaga todos os seus casos e não pode ser desfeito. Continuar?')) return
    executar(async () => {
      await api.excluirConta(senha)
      onExcluida()
    })
  }

  const alterado = nome.trim() !== usuario.nome || email.trim().toLowerCase() !== usuario.email

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-2xl space-y-5 px-4 py-6">
        <div>
          <h2 className="text-xl font-semibold text-zinc-900">Minha conta</h2>
          <p className="mt-1 text-sm text-zinc-500">
            Seus dados de acesso e o que o sistema guarda sobre você.
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

        <form onSubmit={salvar} className={`${secao} space-y-3`}>
          <h3 className="text-sm font-semibold text-zinc-900">Perfil</h3>
          <div>
            <label htmlFor="conta-nome" className={rotulo}>
              Nome
            </label>
            <input id="conta-nome" className={campo} value={nome} onChange={(e) => setNome(e.target.value)} required />
          </div>
          <div>
            <label htmlFor="conta-email" className={rotulo}>
              Email
            </label>
            <input
              id="conta-email"
              type="email"
              className={campo}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>
          <button
            type="submit"
            disabled={ocupado || !alterado}
            className="rounded-lg bg-teal-600 px-4 py-2 text-sm font-medium text-white hover:bg-teal-500 disabled:opacity-50"
          >
            Salvar alterações
          </button>
        </form>

        <section className={`${secao} space-y-3`}>
          <h3 className="text-sm font-semibold text-zinc-900">Seus dados</h3>
          <p className="text-sm text-zinc-500">
            Baixe tudo o que o sistema guarda sobre você: conta, casos, mensagens e feedbacks.
          </p>
          <div className="flex flex-wrap gap-2">
            <button
              onClick={baixar}
              disabled={ocupado}
              className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-300 px-3 py-2 text-sm text-zinc-700 hover:bg-zinc-50 disabled:opacity-50"
            >
              <Download className="h-4 w-4" aria-hidden />
              Baixar meus dados
            </button>
            <button
              onClick={() => setTermoAberto(true)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-300 px-3 py-2 text-sm text-zinc-700 hover:bg-zinc-50"
            >
              <FileText className="h-4 w-4" aria-hidden />
              Termo de uso
            </button>
          </div>
        </section>

        <form onSubmit={excluir} className={`${secao} space-y-3 border-red-200`}>
          <h3 className="text-sm font-semibold text-red-700">Excluir conta</h3>
          <p className="text-sm text-zinc-500">
            Apaga a conta, todos os casos, mensagens e registros de uso. Não pode ser desfeito.
          </p>
          <div>
            <label htmlFor="conta-senha" className={rotulo}>
              Confirme com sua senha
            </label>
            <input
              id="conta-senha"
              type="password"
              className={campo}
              value={senha}
              onChange={(e) => setSenha(e.target.value)}
              autoComplete="current-password"
              required
            />
          </div>
          <button
            type="submit"
            disabled={ocupado || !senha}
            className="inline-flex items-center gap-1.5 rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-500 disabled:opacity-50"
          >
            <Trash2 className="h-4 w-4" aria-hidden />
            Excluir minha conta
          </button>
        </form>
      </div>
      <Termo aberto={termoAberto} onFechar={() => setTermoAberto(false)} />
    </div>
  )
}
