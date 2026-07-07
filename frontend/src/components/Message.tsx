import ReactMarkdown from 'react-markdown'
import { Stethoscope } from 'lucide-react'
import type { Mensagem } from '../types'

export default function Message({ msg }: { msg: Mensagem }) {
  if (msg.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] rounded-2xl rounded-br-md bg-teal-600 px-4 py-2.5 text-sm text-white">
          <p className="whitespace-pre-wrap">{msg.content}</p>
        </div>
      </div>
    )
  }
  return (
    <div className="flex gap-3">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-zinc-200">
        <Stethoscope className="h-4 w-4 text-zinc-600" />
      </div>
      <div className="prosa min-w-0 pt-1 text-sm leading-relaxed text-zinc-800">
        <ReactMarkdown>{msg.content}</ReactMarkdown>
      </div>
    </div>
  )
}

export function Digitando() {
  return (
    <div className="flex gap-3">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-zinc-200">
        <Stethoscope className="h-4 w-4 text-zinc-600" />
      </div>
      <div className="flex items-center gap-1 pt-3">
        {[0, 150, 300].map((atraso) => (
          <span
            key={atraso}
            className="h-1.5 w-1.5 animate-bounce rounded-full bg-zinc-400"
            style={{ animationDelay: `${atraso}ms` }}
          />
        ))}
      </div>
    </div>
  )
}
