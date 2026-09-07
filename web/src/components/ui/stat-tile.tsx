// Primitive — THE stat tile: one big number with a small label, optional trailing badge
// and a footer slot (a progress bar, a hint). Dashboards read as a row of these before
// any table, so the headline numbers land first.
import type { ReactNode } from 'react'

interface StatTileProps {
  label: string
  value: ReactNode
  badge?: ReactNode
  footer?: ReactNode
  className?: string
}

export function StatTile({ label, value, badge, footer, className }: StatTileProps) {
  return (
    <div className={className ? `stat-tile ${className}` : 'stat-tile'}>
      <div className="stat-tile-head">
        <span className="stat-tile-label">{label}</span>
        {badge}
      </div>
      <div className="stat-tile-value">{value}</div>
      {footer && <div className="stat-tile-footer">{footer}</div>}
    </div>
  )
}
