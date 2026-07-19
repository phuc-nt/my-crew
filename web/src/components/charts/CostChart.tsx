// Thin react-chartjs-2 wrapper: monthly cost series as a line, with the budget cap drawn
// as a flat reference line. Registers only the Chart.js pieces it uses (tree-shake).
import {
  CategoryScale,
  Chart as ChartJS,
  Legend,
  LinearScale,
  LineElement,
  PointElement,
  Tooltip,
} from 'chart.js'
import { Line } from 'react-chartjs-2'
import type { CostMonth } from '../../types'
import { useLanguage } from '../../i18n/language-context'
import { accentColor, chartChrome, dangerColor } from './chart-theme'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Legend)

export function CostChart({ series, cap }: { series: CostMonth[]; cap: number }) {
  const { t } = useLanguage()
  const labels = series.map((m) => m.month)
  const accent = accentColor()
  const chrome = chartChrome()
  const data = {
    labels,
    datasets: [
      {
        label: t('costChart.datasetCost'),
        data: series.map((m) => m.total_usd),
        borderColor: accent,
        backgroundColor: accent,
        tension: 0.2,
      },
      {
        label: t('costChart.datasetBudgetCap'),
        data: labels.map(() => cap),
        borderColor: dangerColor(),
        borderDash: [6, 4],
        pointRadius: 0,
      },
    ],
  }
  const options = {
    responsive: true,
    scales: {
      y: {
        beginAtZero: true,
        title: { display: true, text: 'USD', color: chrome.tick },
        ticks: { color: chrome.tick },
        grid: { color: chrome.grid },
      },
      x: { ticks: { color: chrome.tick }, grid: { color: chrome.grid } },
    },
    plugins: { legend: { labels: { color: chrome.legend } } },
  }
  return <Line data={data} options={options} aria-label={t('costChart.ariaLabel')} />
}
