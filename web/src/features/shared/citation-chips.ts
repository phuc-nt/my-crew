// v95: the sources behind a piece of text. There is no separate "sources" payload — an
// agent's deliverable is markdown that names its URLs inline — so the chips are read
// straight out of the text. One chip per host (the first URL seen wins): a report that
// cites five pages of one site is one source to the CEO, not five.
export interface Citation {
  url: string
  host: string
}

/** http(s) URLs only; stops at whitespace, quotes and closing brackets. */
const URL_RE = /https?:\/\/[^\s<>"'`)\]}]+/g

/** Trailing punctuation belongs to the sentence, not the link. */
const TRAILING_PUNCT_RE = /[.,;:!?]+$/

export const MAX_CITATIONS = 8

export function extractCitations(text: string, max = MAX_CITATIONS): Citation[] {
  const seen = new Set<string>()
  const out: Citation[] = []
  for (const match of text.matchAll(URL_RE)) {
    const url = match[0].replace(TRAILING_PUNCT_RE, '')
    let host: string
    try {
      host = new URL(url).hostname.replace(/^www\./, '')
    } catch {
      continue
    }
    if (!host || seen.has(host)) continue
    seen.add(host)
    out.push({ url, host })
    if (out.length >= max) break
  }
  return out
}
