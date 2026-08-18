// One-line summaries for raw recorder events.
//
// Measured on a real step (task 847cefe9b088, seq 831): 13 events, and a single
// `llm_request` was 18,534 bytes because it carries the whole message chain including
// the system prompt. Printing events raw makes the transcript unreadable, so each kind
// collapses to a line that says what happened, with the raw JSON behind a toggle.
import type { StepTranscriptEvent } from '../../../types'

/** What the summary line shows for one event. */
export interface TranscriptLine {
  /** Event kind, verbatim from the recorder — used as the row's label. */
  kind: string
  /** Human-readable summary of the payload. Empty when there is nothing to add. */
  detail: string
  /** Cost in USD when the event reports one, else null. */
  costUsd: number | null
  /** Pretty-printed raw event, for the expandable detail. */
  raw: string
}

function num(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

function str(v: unknown): string {
  return typeof v === 'string' ? v : ''
}

/** First line of a possibly-long text, capped so one event stays one row. */
function firstLine(text: string, max = 120): string {
  const line = text.split('\n', 1)[0].trim()
  return line.length > max ? `${line.slice(0, max)}…` : line
}

export function summarize(event: StepTranscriptEvent): TranscriptLine {
  const e = event as StepTranscriptEvent & Record<string, unknown>
  const raw = JSON.stringify(event, null, 2)
  const costUsd = num(e.cost_usd)

  switch (event.t) {
    case 'meta':
      return { kind: event.t, detail: `${str(e.agent)} · ${str(e.step)}`, costUsd, raw }
    case 'llm_request': {
      // The chain is the model fallback order; the message COUNT stands in for the
      // prompt itself, which is far too large to inline.
      const chain = Array.isArray(e.chain) ? e.chain.join(' → ') : ''
      const count = Array.isArray(e.messages) ? e.messages.length : 0
      const detail = [str(e.role), chain, `${count} msg`].filter(Boolean).join(' · ')
      return { kind: event.t, detail, costUsd, raw }
    }
    case 'llm_response': {
      const tokens = `${num(e.prompt_tokens) ?? 0}→${num(e.completion_tokens) ?? 0} tok`
      const detail = [str(e.model), tokens, firstLine(str(e.content))].filter(Boolean).join(' · ')
      return { kind: event.t, detail, costUsd, raw }
    }
    case 'prefetch': {
      const queries = Array.isArray(e.queries) ? e.queries.length : 0
      return { kind: event.t, detail: `${queries} truy vấn · ${num(e.bytes) ?? 0} B`, costUsd, raw }
    }
    case 'tool_call':
      return { kind: event.t, detail: firstLine(str(e.tool) || str(e.name)), costUsd, raw }
    case 'tool_result':
      return { kind: event.t, detail: firstLine(str(e.result) || str(e.content)), costUsd, raw }
    case 'outcome':
      return {
        kind: event.t,
        detail: [str(e.status), str(e.pause_reason)].filter(Boolean).join(' · '),
        costUsd,
        raw,
      }
    default:
      // The recorder's kinds grow over time; an unknown one still gets a usable row
      // rather than being dropped from the log.
      return { kind: event.t, detail: '', costUsd, raw }
  }
}

/** Total spend across a step's events — the number a CEO actually asks about. */
export function totalCost(events: readonly StepTranscriptEvent[]): number {
  return events.reduce((sum, e) => sum + (num((e as Record<string, unknown>).cost_usd) ?? 0), 0)
}
