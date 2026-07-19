// Code-split entry point for the unified office screen (v15). react-three-fiber/drei/
// three are heavy and only needed here, so the whole view (canvas included) is pulled
// in via React.lazy — Vite emits a separate chunk that never loads for anyone who
// doesn't visit /office.
//
// v32 hardening: a chunk that FAILS to load (offline asset, WebGL-less environment
// where module eval dies, stale deploy hash) previously left the CEO on
// "Đang tải văn phòng…" forever. Two guards now bound that: an error boundary catches
// a rejected import, and a 12s watchdog converts a silent hang into the same friendly
// escape hatch (reload + the table-based timeline link).
import { Component, Suspense, lazy, useEffect, useState, type ReactNode } from 'react'
import { Link } from 'react-router'
import { Button } from '../components/ui/button'
import { useLanguage } from '../i18n/language-context'

const OfficeUnified = lazy(() => import('../views/office-unified/office-unified'))

function OfficeLoadEscape() {
  const { t } = useLanguage()
  return (
    <div style={{ padding: '2rem' }}>
      <p className="error">{t('officeLazy.loadFailedTitle')}</p>
      <p>
        <Button variant="ghost" onClick={() => window.location.reload()}>
          {t('officeLazy.reload')}
        </Button>{' '}
        {t('officeLazy.loadFailedHint')}{' '}
        <Link to="/office/timeline">{t('officeLazy.tableViewLink')}</Link>.
      </p>
    </div>
  )
}

class OfficeErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() {
    return { failed: true }
  }
  render() {
    return this.state.failed ? <OfficeLoadEscape /> : this.props.children
  }
}

function LoadingWithWatchdog() {
  const { t } = useLanguage()
  const [stuck, setStuck] = useState(false)
  useEffect(() => {
    const timer = setTimeout(() => setStuck(true), 12_000)
    return () => clearTimeout(timer)
  }, [])
  return stuck ? <OfficeLoadEscape /> : <p style={{ padding: '2rem' }}>{t('officeLazy.loadingTitle')}</p>
}

export function OfficeUnifiedLazy() {
  return (
    <OfficeErrorBoundary>
      <Suspense fallback={<LoadingWithWatchdog />}>
        <OfficeUnified />
      </Suspense>
    </OfficeErrorBoundary>
  )
}
