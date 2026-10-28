// Seleção e preferências lembradas entre visitas, só neste navegador. Sem storage
// (aba anônima, bloqueio), a tela funciona igual, só não lembra.
export const CHAVE = 'simulado:preferencias'

export function lerPreferencias(): { marcados: string[]; ciclo?: string; quantidade?: number } {
  try {
    return JSON.parse(localStorage.getItem(CHAVE) ?? '') ?? { marcados: [] }
  } catch {
    return { marcados: [] }
  }
}
