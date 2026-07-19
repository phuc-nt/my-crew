// v53 primitive — THE empty-state line (muted italic .ops-chat-empty, the most-used of
// the three drifted treatments). One component so the "nothing here" moment reads the
// same on every screen.
import type { ReactNode } from 'react'

export function EmptyState({ children }: { children: ReactNode }) {
  return <p className="ops-chat-empty">{children}</p>
}
