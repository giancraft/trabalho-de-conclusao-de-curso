/**
 * Tipos da API — apelidos sobre o schema gerado a partir do OpenAPI do backend.
 *
 * Nada aqui é escrito à mão: `types.generated.ts` sai de `npm run gen:types` e os nomes
 * abaixo existem só para o resto do frontend continuar importando `Feedback` em vez de
 * `components['schemas']['Feedback']`.
 *
 * Mudou a API? Rode `npm run gen:types` (com o backend no ar) — o type-check aponta o
 * que quebrou, em vez de a divergência aparecer em runtime.
 */
import type { components } from './types.generated'

type Schemas = components['schemas']

export type Opcoes = Schemas['Opcoes']
export type Usuario = Schemas['UsuarioPublico']
export type CasoAberto = Schemas['CasoAberto']
export type ConversaResumo = Schemas['CasoResumo']
export type ConversaCompleta = Schemas['CasoLeitura']
export type Feedback = Schemas['Feedback']
export type Mensagem = Schemas['MensagemLeitura']
export type Fonte = Schemas['FonteLeitura']
