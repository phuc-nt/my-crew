// Code-split boundary for the Chart.js charts. chart.js + react-chartjs-2 weigh ~500 kB
// of the entry bundle but only two screens (Cost, Guardrail) ever draw a chart, so they
// load on demand instead of on every page.
//
// A failed chunk degrades to a one-line notice rather than an error screen: losing the
// chart must not cost the reader the numbers rendered around it.
import { Component, Suspense, lazy, type ReactNode } from 'react'
import { useLanguage } from '../../i18n/language-context'

const CostChartImpl = lazy(() =>
  import('./CostChart').then((m) => ({ default: m.CostChart })),
)
const VerdictChartImpl = lazy(() =>
  import('./VerdictChart').then((m) => ({ default: m.VerdictChart })),
)

function ChartFallback({ message }: { message: string }) {
  return <p style={{ padding: '1rem 0' }}>{message}</p>
}

class ChartErrorBoundary extends Component<
  { children: ReactNode; message: string },
  { failed: boolean }
> {
  state = { failed: false }
  static getDerivedStateFromError() {
    return { failed: true }
  }
  render() {
    return this.state.failed ? (
      <ChartFallback message={this.props.message} />
    ) : (
      this.props.children
    )
  }
}

function ChartBoundary({ children }: { children: ReactNode }) {
  const { t } = useLanguage()
  return (
    <ChartErrorBoundary message={t('charts.loadFailed')}>
      <Suspense fallback={<ChartFallback message={t('charts.loading')} />}>{children}</Suspense>
    </ChartErrorBoundary>
  )
}

export function LazyCostChart(props: React.ComponentProps<typeof CostChartImpl>) {
  return (
    <ChartBoundary>
      <CostChartImpl {...props} />
    </ChartBoundary>
  )
}

export function LazyVerdictChart(props: React.ComponentProps<typeof VerdictChartImpl>) {
  return (
    <ChartBoundary>
      <VerdictChartImpl {...props} />
    </ChartBoundary>
  )
}
