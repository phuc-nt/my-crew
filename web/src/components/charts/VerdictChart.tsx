// Thin react-chartjs-2 wrapper: guardrail verdict breakdown as a doughnut. Colors map the
// safety meaning (allow=green, deny=red, pending=amber, …). Registers only used pieces.
import { ArcElement, Chart as ChartJS, Legend, Tooltip } from 'chart.js'
import { Doughnut } from 'react-chartjs-2'
import { useLanguage } from '../../i18n/language-context'
import { chartChrome, neutralColor, verdictColors } from './chart-theme'

ChartJS.register(ArcElement, Tooltip, Legend)

export function VerdictChart({ counts }: { counts: Record<string, number> }) {
  const { t } = useLanguage()
  const labels = Object.keys(counts)
  const colors = verdictColors()
  const fallback = neutralColor()
  const data = {
    labels,
    datasets: [
      {
        data: labels.map((k) => counts[k]),
        backgroundColor: labels.map((k) => colors[k] ?? fallback),
      },
    ],
  }
  const options = { plugins: { legend: { labels: { color: chartChrome().legend } } } }
  return <Doughnut data={data} options={options} aria-label={t('verdictChart.ariaLabel')} />
}
