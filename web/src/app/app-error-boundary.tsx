// The last net under a hub: a render crash inside one route must not blank the whole
// shell (header, nav, bell), and the CEO must be able to recover without knowing what
// React is. Class component because that is the only way to catch a render error.
//
// Reset happens two ways: "Thử lại" re-renders the same route (a transient crash — a
// half-arrived payload — usually clears), and the shell keys this boundary by pathname
// so simply navigating to another hub leaves the crash behind.
import { Component, type ErrorInfo, type ReactNode } from 'react'
import { Button } from '../components/ui/button'
import { useLanguage } from '../i18n/language-context'

interface Labels {
  title: string
  hint: string
  retry: string
  reload: string
}

interface BoundaryProps {
  children: ReactNode
  labels: Labels
  onReload?: () => void
}

interface BoundaryState {
  error: Error | null
}

export class AppErrorBoundary extends Component<BoundaryProps, BoundaryState> {
  state: BoundaryState = { error: null }

  static getDerivedStateFromError(error: Error): BoundaryState {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // The console is the only trace we keep; the backend never sees a client crash.
    console.error('[app-error-boundary]', error, info.componentStack)
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children
    const { labels, onReload } = this.props
    return (
      <section className="app-error-boundary" role="alert" data-testid="app-error-boundary">
        <h2>{labels.title}</h2>
        <p>{labels.hint}</p>
        <pre className="app-error-boundary-detail">{error.message || String(error)}</pre>
        <div className="app-error-boundary-actions">
          <Button variant="primary" onClick={() => this.setState({ error: null })}>
            {labels.retry}
          </Button>
          <Button onClick={onReload ?? (() => window.location.reload())}>{labels.reload}</Button>
        </div>
      </section>
    )
  }
}

/** Hook-friendly wrapper: reads the labels once and hands them to the class. */
export function RouteErrorBoundary({ children }: { children: ReactNode }) {
  const { t } = useLanguage()
  return (
    <AppErrorBoundary
      labels={{
        title: t('errorBoundary.title'),
        hint: t('errorBoundary.hint'),
        retry: t('errorBoundary.retry'),
        reload: t('errorBoundary.reload'),
      }}
    >
      {children}
    </AppErrorBoundary>
  )
}
