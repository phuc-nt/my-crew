// v53 primitive — THE card surface (.card: --space-3 padding, --radius, shadow-sm).
// Extra chrome (grid placement, fixed positioning) rides in via className; padding/
// border/radius always come from .card so every panel shares one rhythm.
import type { HTMLAttributes } from 'react'

export function Card({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div className={className ? `card ${className}` : 'card'} {...rest} />
}
