// Decides whether the 3D scene should render its 2D fallback (agent-status-table) instead of
// the Canvas: `prefers-reduced-motion: reduce` OR a mobile-looking UA. Kept as a tiny standalone
// hook so the trigger logic is unit-testable without mounting react-three-fiber (which needs a
// WebGL context jsdom doesn't provide).
import { useEffect, useState } from 'react'

const MOBILE_UA_RE = /Android|iPhone|iPad|iPod|Mobile/i

export function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || !window.matchMedia) return false
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

export function isMobileUserAgent(): boolean {
  if (typeof navigator === 'undefined') return false
  return MOBILE_UA_RE.test(navigator.userAgent)
}

export function shouldUseFallback(): boolean {
  return prefersReducedMotion() || isMobileUserAgent()
}

// Re-evaluates if the OS motion preference changes live (mirrors theme-context's live-follow
// pattern) — a CEO who flips "reduce motion" on mid-session sees the scene drop to the table
// without a page reload.
export function use3dFallback(): boolean {
  const [fallback, setFallback] = useState(shouldUseFallback)

  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    const onChange = () => setFallback(shouldUseFallback())
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])

  return fallback
}
