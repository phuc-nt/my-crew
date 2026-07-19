// Full-result drawer (v17 "Kết quả"): fetches one step's artifact and renders its
// markdown. Safety posture for LLM-produced text (second-order): react-markdown's
// defaults already refuse raw HTML and neutralize `javascript:` URLs; on top of that
// we refuse to render REMOTE <img> at all (red-team M4 — an image URL in a step result
// would ping an external host from the CEO's browser) — images render as plain links.
import { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { api } from '../../api/client'
import { Button } from '../../components/ui/button'
import { DICT } from '../../i18n/dictionary'
import { useLanguage } from '../../i18n/language-context'
import type { StepArtifactPayload } from '../../types'

interface ArtifactViewerProps {
  taskId: string
  seq: number
  stepId: string
  onClose: () => void
}

// Exported for tests: the components override that keeps remote images out. Uses DICT.vi
// directly (not t()) — this is a module-level constant outside any component, so it cannot
// read the language context; the "[image: …]" fallback text is a minor placeholder for a
// blocked remote image and stays vi-default like other non-component constants.
export const markdownComponents = {
  img: ({ src, alt }: { src?: unknown; alt?: string }) => (
    <a href={typeof src === 'string' ? src : undefined} target="_blank" rel="noreferrer noopener">
      [{DICT.vi['artifactViewer.imageAltFallback']}: {alt || (typeof src === 'string' ? src : '')}]
    </a>
  ),
}

export function ArtifactViewer({ taskId, seq, stepId, onClose }: ArtifactViewerProps) {
  const { t } = useLanguage()
  const [artifact, setArtifact] = useState<StepArtifactPayload | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    api.getStepArtifact(taskId, seq).then(setArtifact)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : t('artifactViewer.loadError')))
  }, [taskId, seq, t])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const copy = () => {
    if (!artifact) return
    navigator.clipboard?.writeText(artifact.result_text)
      .then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500) })
      .catch(() => undefined)
  }

  const download = () => {
    if (!artifact) return
    const blob = new Blob([artifact.result_text], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${taskId}-${stepId}.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="artifact-overlay" role="dialog" aria-modal="true">
      <div className="artifact-drawer">
        <div className="artifact-drawer-head">
          <h3>{artifact?.step_title ?? t('artifactViewer.fallbackTitle')}</h3>
          <div className="office-composer-actions">
            <Button variant="ghost" onClick={copy} disabled={!artifact}>
              {copied ? t('artifactViewer.copied') : t('artifactViewer.copy')}
            </Button>
            <Button variant="ghost" onClick={download} disabled={!artifact}>
              {t('artifactViewer.download')}
            </Button>
            <Button variant="ghost" onClick={onClose}>{t('common.close')}</Button>
          </div>
        </div>
        {artifact?.self_check_failed && (
          <p className="office-health-warn artifact-flag">
            {t('artifactViewer.selfCheckFailed')}
          </p>
        )}
        {error && <p className="error">{t('artifactViewer.errorPrefix', { message: error })}</p>}
        {!artifact && !error && <p className="office-room-status">{t('artifactViewer.loading')}</p>}
        {artifact && (
          <div className="artifact-markdown">
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
              {artifact.result_text}
            </ReactMarkdown>
          </div>
        )}
      </div>
    </div>
  )
}
