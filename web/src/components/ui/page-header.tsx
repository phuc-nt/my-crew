// v53 primitive — THE page header: h2 title left, actions right, one baseline
// (generalizes .office-header, the only structured header pre-v53; every other view
// was a naked <h2> with actions landing ad-hoc).
import type { ReactNode } from 'react'

interface PageHeaderProps {
  title: ReactNode
  actions?: ReactNode
}

export function PageHeader({ title, actions }: PageHeaderProps) {
  return (
    <header className="page-header">
      <h2>{title}</h2>
      {actions && <div className="page-header-actions">{actions}</div>}
    </header>
  )
}
