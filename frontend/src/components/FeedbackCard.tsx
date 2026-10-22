import {
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  CircleHelp,
  ClipboardCheck,
  Library,
  XCircle,
} from 'lucide-react'
import type { Feedback, Fonte } from '../types'
import type { LucideIcon } from 'lucide-react'

/** Texto do feedback com cada [n] virando link para a referência de mesmo número. */
function ComCitacoes({ texto }: { texto: string }) {
  const partes = texto.split(/(\[\d+(?:,\s*\d+)*\])/)
  return (
    <>
      {partes.map((parte, i) => {
        const numeros = parte.match(/^\[([\d,\s]+)\]$/)?.[1].split(',').map((n) => n.trim())
        if (!numeros) return parte
        return (
          <sup key={i} className="ml-0.5 font-medium">
            [
            {numeros.map((n, j) => (
              <span key={n}>
                {j > 0 && ', '}
                <a href={`#ref-${n}`} className="text-teal-700 hover:underline">
                  {n}
                </a>
              </span>
            ))}
            ]
          </sup>
        )
      })}
    </>
  )
}

function Secao({
  icone: Icone,
  titulo,
  cor,
  itens,
}: {
  icone: LucideIcon
  titulo: string
  cor: string
  itens: string[] | string
}) {
  if (!itens || itens.length === 0) return null
  return (
    <div>
      <h4 className={`mb-1.5 flex items-center gap-1.5 text-sm font-semibold ${cor}`}>
        <Icone className="h-4 w-4" />
        {titulo}
      </h4>
      {typeof itens === 'string' ? (
        <p className="text-sm leading-relaxed text-zinc-700">
          <ComCitacoes texto={itens} />
        </p>
      ) : (
        <ul className="space-y-1 pl-5 text-sm leading-relaxed text-zinc-700">
          {itens.map((item) => (
            <li key={item} className="list-disc">
              <ComCitacoes texto={item} />
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

const corDoTipo: Record<string, string> = {
  PCDT: 'bg-teal-50 text-teal-800 ring-teal-200',
  Diretriz: 'bg-blue-50 text-blue-800 ring-blue-200',
  Revisão: 'bg-zinc-50 text-zinc-700 ring-zinc-200',
  'Relato de caso': 'bg-amber-50 text-amber-800 ring-amber-200',
}
const nomeDoTipo: Record<string, string> = {
  PCDT: 'Diretriz oficial (MS)',
  Diretriz: 'Diretriz de sociedade',
  Revisão: 'Revisão',
  'Relato de caso': 'Relato de caso',
}

/** Citação ABNT com o trecho que a NBR 6023 manda destacar em negrito. */
function Citacao({ citacao, destaque }: { citacao: string; destaque: string }) {
  const i = citacao.indexOf(destaque)
  if (!destaque || i < 0) return <>{citacao}</>
  return (
    <>
      {citacao.slice(0, i)}
      <strong>{destaque}</strong>
      {citacao.slice(i + destaque.length)}
    </>
  )
}

/** Referências do caso (RF14), numeradas como as citações [n] do feedback. */
function Referencias({ fontes }: { fontes: Fonte[] }) {
  if (fontes.length === 0) return null
  return (
    <div>
      <h4 className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-zinc-700">
        <Library className="h-4 w-4" />
        Referências
      </h4>
      <ol className="space-y-3 text-sm leading-relaxed text-zinc-700">
        {fontes.map((f) => (
          <li key={f.numero} id={`ref-${f.numero}`} className="flex gap-2 scroll-mt-4">
            <span className="shrink-0 font-medium text-zinc-500">[{f.numero}]</span>
            <div className="min-w-0 space-y-1">
              <span
                className={`inline-block rounded px-1.5 py-0.5 text-xs font-medium ring-1 ${
                  corDoTipo[f.tipo] ?? corDoTipo['Revisão']
                }`}
              >
                {nomeDoTipo[f.tipo] ?? f.tipo}
              </span>
              <p className="break-words">
                <Citacao citacao={f.citacao} destaque={f.destaque} />
              </p>
              {f.secoes.length > 0 && (
                <p className="text-xs text-zinc-500">
                  Seções consultadas:{' '}
                  {f.secoes.map((sec, j) => (
                    <span key={`${sec.titulo}-${j}`}>
                      {j > 0 && ' · '}
                      <a
                        href={sec.url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-teal-700 underline hover:text-teal-600"
                      >
                        {sec.titulo}
                      </a>
                    </span>
                  ))}
                </p>
              )}
              <p className="text-xs text-zinc-400">Licença: {f.licenca}</p>
            </div>
          </li>
        ))}
      </ol>
    </div>
  )
}

export default function FeedbackCard({ fb, fontes }: { fb: Feedback; fontes: Fonte[] }) {
  return (
    <div className="rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm">
      <div className="mb-4 flex items-center gap-2 border-b border-zinc-100 pb-3">
        <ClipboardCheck className="h-5 w-5 text-teal-600" />
        <h3 className="text-base font-semibold text-zinc-900">Feedback da investigação</h3>
      </div>

      <div
        className={`mb-4 rounded-lg px-4 py-3 text-sm font-medium ${
          fb.acertou ? 'bg-green-50 text-green-800' : 'bg-red-50 text-red-800'
        }`}
      >
        {fb.acertou ? 'Diagnóstico correto: ' : 'Diagnóstico correto era: '}
        {fb.diagnostico_correto}
      </div>

      <div className="space-y-4">
        <Secao icone={CheckCircle2} titulo="Acertos" cor="text-green-700" itens={fb.acertos} />
        <Secao
          icone={XCircle}
          titulo="Inconsistências"
          cor="text-red-700"
          itens={fb.inconsistencias}
        />
        <Secao
          icone={CircleHelp}
          titulo="Hipóteses não consideradas"
          cor="text-amber-700"
          itens={fb.hipoteses_nao_consideradas}
        />
        <Secao
          icone={BookOpen}
          titulo="Justificativa pedagógica"
          cor="text-blue-700"
          itens={fb.justificativa_pedagogica}
        />
        <Referencias fontes={fontes} />
      </div>

      <div className="mt-4 flex items-start gap-2 border-t border-zinc-100 pt-3">
        <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-zinc-400" />
        <p className="text-xs text-zinc-500">
          Conteúdo gerado por IA para fins educacionais; confira sempre a literatura de
          referência.
        </p>
      </div>
    </div>
  )
}
