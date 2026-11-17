import {
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  CircleHelp,
  ClipboardCheck,
  GraduationCap,
  Library,
  ListOrdered,
  MinusCircle,
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
  vazio,
}: {
  icone: LucideIcon
  titulo: string
  cor: string
  itens: string[] | string
  /** Mensagem quando não há itens; sem ela, a seção some. */
  vazio?: string
}) {
  const semItens = !itens || itens.length === 0
  if (semItens && !vazio) return null
  return (
    <div>
      <h4 className={`mb-1.5 flex items-center gap-1.5 text-sm font-semibold ${cor}`}>
        <Icone className="h-4 w-4" />
        {titulo}
      </h4>
      {semItens ? (
        <p className="text-sm text-zinc-500">{vazio}</p>
      ) : typeof itens === 'string' ? (
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

const TOPICO: Record<string, string> = {
  diagnostico: 'Diagnóstico',
  fisiologia: 'Fisiologia normal',
  fisiopatologia: 'Fisiopatologia',
  conduta: 'Conduta',
}
// Situação sempre com ícone e texto, nunca só a cor.
const SITUACAO = {
  correto: { rotulo: 'Correto', icone: CheckCircle2, cor: 'text-green-700', fundo: 'border-green-200 bg-green-50/50' },
  parcial: { rotulo: 'Parcial', icone: MinusCircle, cor: 'text-amber-700', fundo: 'border-amber-200 bg-amber-50/50' },
  incorreto: { rotulo: 'Incorreto', icone: XCircle, cor: 'text-red-700', fundo: 'border-red-200 bg-red-50/50' },
}

/** Um bloco por campo da resposta final (diagnóstico, fisiopatologia, conduta...). */
function PorTopico({ itens }: { itens: Feedback['por_campo'] }) {
  if (!itens?.length) return null
  return (
    <div className="space-y-2">
      <h4 className="text-sm font-semibold text-zinc-900">Sua resposta, por tópico</h4>
      {itens.map((a) => {
        const s = SITUACAO[a.situacao]
        return (
          <div key={a.campo} className={`rounded-lg border px-3 py-2.5 ${s.fundo}`}>
            <p className="flex items-center justify-between gap-2 text-sm font-medium text-zinc-900">
              {TOPICO[a.campo] ?? a.campo}
              <span className={`inline-flex items-center gap-1 text-xs font-medium ${s.cor}`}>
                <s.icone className="h-3.5 w-3.5" aria-hidden />
                {s.rotulo}
              </span>
            </p>
            <p className="mt-1 text-sm leading-relaxed text-zinc-700">
              <ComCitacoes texto={a.comentario} />
            </p>
          </div>
        )
      })}
    </div>
  )
}

const corDoTipo: Record<string, string> = {
  PCDT: 'bg-teal-50 text-teal-800 ring-teal-200',
  'Manual MS': 'bg-emerald-50 text-emerald-800 ring-emerald-200',
  Diretriz: 'bg-blue-50 text-blue-800 ring-blue-200',
  Revisão: 'bg-zinc-50 text-zinc-700 ring-zinc-200',
  'Relato de caso': 'bg-amber-50 text-amber-800 ring-amber-200',
}
const nomeDoTipo: Record<string, string> = {
  PCDT: 'Diretriz oficial (MS)',
  'Manual MS': 'Manual oficial (MS)',
  Diretriz: 'Diretriz de sociedade',
  Revisão: 'Revisão',
  'Relato de caso': 'Relato de caso',
}

/** Texto com as URLs clicáveis; o ponto final da ABNT ("…/view. Acesso em") fica fora. */
function ComLinks({ texto }: { texto: string }) {
  return (
    <>
      {texto.split(/(https?:\/\/\S+?)(?=\.?(?:\s|$))/).map((parte, i) =>
        i % 2 ? (
          <a
            key={i}
            href={parte}
            target="_blank"
            rel="noreferrer"
            className="text-teal-700 underline hover:text-teal-600"
          >
            {parte}
          </a>
        ) : (
          parte
        ),
      )}
    </>
  )
}

/** Citação ABNT com o trecho que a NBR 6023 manda destacar em negrito. */
function Citacao({ citacao, destaque }: { citacao: string; destaque: string }) {
  const i = citacao.indexOf(destaque)
  if (!destaque || i < 0) return <ComLinks texto={citacao} />
  return (
    <>
      <ComLinks texto={citacao.slice(0, i)} />
      <strong>{destaque}</strong>
      <ComLinks texto={citacao.slice(i + destaque.length)} />
    </>
  )
}

/** Conduta de referência: passos numerados, com as citações [n] clicáveis. */
function CondutaReferencia({ passos }: { passos: string[] }) {
  if (passos.length === 0) return null
  return (
    <div>
      <h4 className="mb-1.5 flex items-center gap-1.5 text-sm font-semibold text-teal-700">
        <ListOrdered className="h-4 w-4" />
        Conduta de referência
      </h4>
      <ol className="list-decimal space-y-1 pl-5 text-sm leading-relaxed text-zinc-700">
        {passos.map((passo) => (
          <li key={passo}>
            <ComCitacoes texto={passo} />
          </li>
        ))}
      </ol>
    </div>
  )
}

/** Leitura indicada de fisiologia (ciclo básico): só a referência ABNT, título em negrito. */
function LeituraIndicada({ referencia }: { referencia: string }) {
  if (!referencia) return null
  return (
    <div className="rounded-lg bg-zinc-50 px-3 py-2.5">
      <h4 className="mb-1 flex items-center gap-1.5 text-sm font-semibold text-zinc-700">
        <GraduationCap className="h-4 w-4" />
        Para aprofundar a fisiologia
      </h4>
      <p className="text-sm leading-relaxed text-zinc-700">
        {referencia.split('**').map((parte, i) => (i % 2 ? <strong key={i}>{parte}</strong> : parte))}
      </p>
      <p className="mt-1 text-xs text-zinc-500">
        A explicação da fisiologia normal acima é do modelo, não das fontes citadas; use o livro
        para conferir e aprofundar.
      </p>
    </div>
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
  // Nome incompleto da doença certa: é acerto, com o nome completo como melhoria.
  const nomeIncompleto = fb.acertou && fb.por_campo?.find((a) => a.campo === 'diagnostico')?.situacao === 'parcial'
  const porTopico = (fb.por_campo?.length ?? 0) > 0
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
        {nomeIncompleto
          ? 'Diagnóstico correto. Nome completo: '
          : fb.acertou
            ? 'Diagnóstico correto: '
            : 'Diagnóstico correto era: '}
        {fb.diagnostico_correto}
      </div>

      <div className="space-y-4">
        <PorTopico itens={fb.por_campo} />
        <Secao
          icone={CheckCircle2}
          titulo={porTopico ? 'Acertos na investigação' : 'Acertos'}
          cor="text-green-700"
          itens={fb.acertos}
        />
        <Secao
          icone={XCircle}
          titulo={porTopico ? 'Inconsistências na investigação' : 'Inconsistências'}
          cor="text-red-700"
          itens={fb.inconsistencias}
          vazio="Nenhuma inconsistência."
        />
        <Secao
          icone={CircleHelp}
          titulo="O que faltou na investigação"
          cor="text-amber-700"
          itens={fb.hipoteses_nao_consideradas}
          vazio="Nada a apontar: sua investigação cobriu o essencial."
        />
        <Secao
          icone={BookOpen}
          titulo="Justificativa pedagógica"
          cor="text-blue-700"
          itens={fb.justificativa_pedagogica}
        />
        <CondutaReferencia passos={fb.conduta_referencia ?? []} />
        <LeituraIndicada referencia={fb.leitura_indicada ?? ''} />
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
