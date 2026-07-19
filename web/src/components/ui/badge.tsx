// v53 primitive — THE badge: always pill-shaped (.badge), tone via role-split tokens.
// Replaces the drifted 10px-radius variants (badge-on/off/trust-*, health-chip).
import type { HTMLAttributes } from 'react'

export type BadgeTone = 'ok' | 'warn' | 'danger' | 'accent' | 'neutral'

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: BadgeTone
}

export function Badge({ tone = 'neutral', className, ...rest }: BadgeProps) {
  const cls = `badge badge-${tone}${className ? ` ${className}` : ''}`
  return <span className={cls} {...rest} />
}
