// Primitive — THE utilisation bar (.progress + .progress-fill). One horizontal track
// whose fill colour follows the tone, so "how full is this" reads the same for a budget,
// a failure rate, or a share of total. `value` is 0..1 and is clamped: an over-cap ratio
// of 1.4 still draws a full bar (the number beside it carries the overshoot).
import type { HTMLAttributes } from 'react'

export type ProgressTone = 'ok' | 'warn' | 'danger' | 'accent' | 'neutral'

interface ProgressBarProps extends HTMLAttributes<HTMLDivElement> {
  value: number
  tone?: ProgressTone
  /** Accessible name; the bar is a real progressbar for screen readers. */
  label: string
}

export function ProgressBar({ value, tone = 'accent', label, className, ...rest }: ProgressBarProps) {
  const pct = Math.round(Math.min(1, Math.max(0, Number.isFinite(value) ? value : 0)) * 100)
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={pct}
      className={className ? `progress ${className}` : 'progress'}
      {...rest}
    >
      <span className={`progress-fill progress-${tone}`} style={{ width: `${pct}%` }} />
    </div>
  )
}
