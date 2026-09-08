// The chip row for `citation-chips.ts`: one outbound link per host, under the text it
// was read from. Renders nothing when the text names no URL.
import { useMemo } from 'react'
import { useLanguage } from '../../i18n/language-context'
import { extractCitations } from './citation-chips'

export function CitationChips({ text, className = '' }: { text: string; className?: string }) {
  const { t } = useLanguage()
  const items = useMemo(() => extractCitations(text), [text])
  if (items.length === 0) return null
  return (
    <ul
      className={`citation-chips ${className}`.trim()}
      aria-label={t('citations.label')}
      data-testid="citation-chips"
    >
      {items.map((c) => (
        <li key={c.host}>
          <a
            className="citation-chip"
            href={c.url}
            target="_blank"
            rel="noopener noreferrer"
            title={c.url}
          >
            {c.host}
          </a>
        </li>
      ))}
    </ul>
  )
}
