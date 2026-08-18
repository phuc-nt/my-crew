// Room titles are the CEO's raw brief verbatim — measured on real data: 108 of 115 rooms
// exceed 60 chars, median 120. The list pane is 280px wide, so a title is truncated by
// CSS to ~1 line no matter what; cutting it here instead lets us cut at a WORD boundary
// and keep the informative head of the sentence.
const MAX_TITLE = 52

export function shortTitle(title: string, max = MAX_TITLE): string {
  const clean = title.trim().replace(/\s+/g, ' ')
  if (clean.length <= max) return clean
  const cut = clean.slice(0, max)
  const lastSpace = cut.lastIndexOf(' ')
  // Only respect the word boundary when it isn't hacking off most of the line.
  return `${(lastSpace > max * 0.6 ? cut.slice(0, lastSpace) : cut).trimEnd()}…`
}
