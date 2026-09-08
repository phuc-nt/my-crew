import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { LanguageProvider } from '../../i18n/language-context'
import { extractCitations } from './citation-chips'
import { CitationChips } from './citation-chips.tsx'

describe('extractCitations', () => {
  it('reads http(s) URLs out of prose, one per host, first URL wins', () => {
    const text = [
      'Theo https://vnexpress.net/kinh-doanh/a-1.html, giá tăng.',
      'Xem thêm (https://www.cafef.vn/b) và https://vnexpress.net/c.',
      'Nguồn: <https://gso.gov.vn/d>; ftp://khong-tinh.vn/e',
    ].join('\n')
    expect(extractCitations(text)).toEqual([
      { url: 'https://vnexpress.net/kinh-doanh/a-1.html', host: 'vnexpress.net' },
      { url: 'https://www.cafef.vn/b', host: 'cafef.vn' },
      { url: 'https://gso.gov.vn/d', host: 'gso.gov.vn' },
    ])
  })

  it('returns nothing for text without links and caps the list', () => {
    expect(extractCitations('không có link nào ở đây')).toEqual([])
    const many = Array.from({ length: 12 }, (_, i) => `https://site-${i}.vn/x`).join(' ')
    expect(extractCitations(many)).toHaveLength(8)
    expect(extractCitations(many, 2).map((c) => c.host)).toEqual(['site-0.vn', 'site-1.vn'])
  })
})

describe('CitationChips', () => {
  it('renders one outbound chip per host and nothing when there are no links', () => {
    const { container, rerender } = render(
      <LanguageProvider>
        <CitationChips text="Nguồn: https://vnexpress.net/a và https://cafef.vn/b." />
      </LanguageProvider>,
    )
    const links = screen.getAllByRole('link')
    expect(links.map((a) => a.textContent)).toEqual(['vnexpress.net', 'cafef.vn'])
    expect(links[0].getAttribute('href')).toBe('https://vnexpress.net/a')
    expect(links[0].getAttribute('target')).toBe('_blank')
    expect(links[0].getAttribute('rel')).toBe('noopener noreferrer')

    rerender(
      <LanguageProvider>
        <CitationChips text="không có gì" />
      </LanguageProvider>,
    )
    expect(container.querySelector('[data-testid="citation-chips"]')).toBeNull()
  })
})
