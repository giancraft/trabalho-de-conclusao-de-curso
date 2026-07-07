import { useState } from 'react'
import { Stethoscope } from 'lucide-react'
import * as api from '../api'
import type { Usuario } from '../types'

const campo =
  'w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-800 ' +
  'outline-none transition-colors focus:border-teal-500 focus:ring-2 focus:ring-teal-100'
const rotulo = 'mb-1 block text-sm font-medium text-zinc-700'

export default function AuthPage({ onEntrar }: { onEntrar: (u: Usuario) => void }) {
  const [modo, setModo] = useState<'login' | 'registro'>('login')
  const [nome, setNome] = useState('')
  const [email, setEmail] = useState('')
  const [senha, setSenha] = useState('')
  const [erro, setErro] = useState<string | null>(null)
  const [ocupado, setOcupado] = useState(false)

  async function enviar(e: React.FormEvent) {
    e.preventDefault()
    setErro(null)
    setOcupado(true)
    try {
      const usuario =
        modo === 'login'
          ? await api.login(email, senha)
          : await api.registrar(nome, email, senha)
      onEntrar(usuario)
    } catch (err) {
      setErro(err instanceof Error ? err.message : 'Falha na autenticação.')
    } finally {
      setOcupado(false)
    }
  }

  return (
    <div className="flex h-full items-center justify-center bg-zinc-50 px-4 font-sans">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex flex-col items-center">
          <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-teal-600">
            <Stethoscope className="h-6 w-6 text-white" />
          </div>
          <h1 className="text-xl font-semibold text-zinc-900">Simulador Clínico</h1>
          <p className="text-sm text-zinc-500">Casos clínicos com IA generativa</p>
        </div>

        <form onSubmit={enviar} className="rounded-2xl border border-zinc-200 bg-white p-6 shadow-sm">
          <h2 className="mb-4 text-base font-semibold text-zinc-900">
            {modo === 'login' ? 'Entrar na sua conta' : 'Criar conta'}
          </h2>

          <div className="space-y-3">
            {modo === 'registro' && (
              <div>
                <label htmlFor="nome" className={rotulo}>
                  Nome
                </label>
                <input
                  id="nome"
                  className={campo}
                  value={nome}
                  onChange={(e) => setNome(e.target.value)}
                  required
                />
              </div>
            )}
            <div>
              <label htmlFor="email" className={rotulo}>
                Email
              </label>
              <input
                id="email"
                type="email"
                className={campo}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>
            <div>
              <label htmlFor="senha" className={rotulo}>
                Senha
              </label>
              <input
                id="senha"
                type="password"
                className={campo}
                value={senha}
                onChange={(e) => setSenha(e.target.value)}
                minLength={modo === 'registro' ? 8 : undefined}
                required
              />
              {modo === 'registro' && (
                <p className="mt-1 text-xs text-zinc-400">Mínimo de 8 caracteres.</p>
              )}
            </div>
          </div>

          {erro && (
            <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{erro}</p>
          )}

          <button
            type="submit"
            disabled={ocupado}
            className="mt-4 w-full rounded-lg bg-teal-600 px-3 py-2.5 text-sm font-medium text-white
                       transition-colors hover:bg-teal-500 disabled:opacity-50"
          >
            {ocupado ? 'Aguarde...' : modo === 'login' ? 'Entrar' : 'Criar conta'}
          </button>

          <p className="mt-4 text-center text-sm text-zinc-500">
            {modo === 'login' ? 'Não tem conta?' : 'Já tem conta?'}{' '}
            <button
              type="button"
              onClick={() => {
                setModo(modo === 'login' ? 'registro' : 'login')
                setErro(null)
              }}
              className="font-medium text-teal-700 hover:underline"
            >
              {modo === 'login' ? 'Criar conta' : 'Entrar'}
            </button>
          </p>
        </form>

        <p className="mt-4 text-center text-xs text-zinc-400">
          Simulação educacional — não fornece orientação clínica real.
        </p>
      </div>
    </div>
  )
}
