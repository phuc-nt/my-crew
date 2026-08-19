// "Quá trình" tab of the ArtifactViewer (v82) — the step attempt's process transcript
// (v80 recorder): which tools were called, which sources were actually opened, LLM
// usage. High ui-mode only (the parent renders the tab bar only when isHigh).
//
// Rendering is deliberately one compact line per event — the transcript is evidence
// for "did the agent really open a source", not a chat replay. Event bodies were
// secret-scrubbed and head-capped at write time; we still only show short summaries
// (args_head/content_head), never full LLM prompts, to keep the drawer readable.
import { useEffect, useState } from 'react'
import { api, ApiError } from '../../api/client'
import { useLanguage } from '../../i18n/language-context'
import type { StepTranscriptEvent, StepTranscriptPayload } from '../../types'

const HEAD_CHARS = 160

function head(value: unknown, limit = HEAD_CHARS): string {
  const s = typeof value === 'string' ? value : value == null ? '' : String(value)
  return s.length > limit ? `${s.slice(0, limit)}…` : s
}

// Pure summary line per event kind — exported for unit tests (jsdom needs no drawer
// to check that a tool_call renders its name and an llm_response its token counts).
export function describeTranscriptEvent(e: StepTranscriptEvent): string {
  switch (e.t) {
    case 'meta':
      return `@${head(e.agent, 40)} · attempt ${head(e.attempt, 40)}`
    case 'tool_call':
      return `${head(e.name, 60)}(${head(e.args_head)})`
    case 'tool_result':
      return `${head(e.name, 60)} → ${head(e.content_head)}`
    case 'prefetch': {
      const queries = Array.isArray(e.queries) ? e.queries.map((q) => head(q, 60)).join(', ') : ''
      return `web ×${Array.isArray(e.queries) ? e.queries.length : 0}: ${queries}`
    }
    case 'llm_request': {
      const n = Array.isArray(e.messages) ? e.messages.length : 0
      return `${head(e.role, 30)} · ${n} messages`
    }
    case 'llm_response':
      return `${head(e.model, 60)} · ${Number(e.prompt_tokens) || 0}+${Number(e.completion_tokens) || 0} tok`
    case 'outcome':
      return head(e.status ?? e.result ?? '', 120)
    default:
      return ''
  }
}

export function TranscriptTab({ taskId, seq }: { taskId: string; seq: number }) {
  const { t } = useLanguage()
  const [data, setData] = useState<StepTranscriptPayload | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [missing, setMissing] = useState(false)

  useEffect(() => {
    api.getStepTranscript(taskId, seq).then(setData)
      .catch((e: unknown) => {
        // 404 = the step simply has no transcript (recorder off / pre-v80) — an empty
        // state, not an error banner.
        if (e instanceof ApiError && e.status === 404) setMissing(true)
        else setError(e instanceof Error ? e.message : t('transcriptTab.loadError'))
      })
  }, [taskId, seq, t])

  if (error) return <p className="error">{t('transcriptTab.errorPrefix', { message: error })}</p>
  if (missing) return <p className="office-room-status">{t('transcriptTab.empty')}</p>
  if (!data) return <p className="office-room-status">{t('transcriptTab.loading')}</p>

  return (
    <div className="transcript-tab">
      {data.attempts > 1 && (
        <p className="muted">{t('transcriptTab.attempts', { n: data.attempts })}</p>
      )}
      <ul className="transcript-events">
        {data.events.map((e, i) => (
          <li key={i} className="transcript-event">
            <code className={`transcript-kind transcript-kind-${e.t}`}>{e.t}</code>{' '}
            <span className="transcript-desc">{describeTranscriptEvent(e)}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
