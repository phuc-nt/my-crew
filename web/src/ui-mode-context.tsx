// UI density mode: low (default, CEO-first) vs high ("Chế độ nâng cao"). Persisted to
// localStorage['ui-mode']. Since the 5-hub shell, high mode no longer unlocks separate
// technical routes — every hub is always reachable — it reveals the technical detail
// inside a hub (office health strip, roster status column, artifact process tab).
// VIEW-LAYER only: auth + the Action Gateway are the real boundaries, never this flag.
import { createContext, useCallback, useContext, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

export type UiMode = 'low' | 'high'

interface UiModeCtx {
  mode: UiMode
  isHigh: boolean
  setMode: (m: UiMode) => void
}

const Ctx = createContext<UiModeCtx | null>(null)
const STORAGE_KEY = 'ui-mode'

function readMode(): UiMode {
  try {
    return localStorage.getItem(STORAGE_KEY) === 'high' ? 'high' : 'low'
  } catch {
    return 'low'
  }
}

export function UiModeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<UiMode>(readMode)

  const setMode = useCallback((m: UiMode) => {
    setModeState(m)
    try {
      localStorage.setItem(STORAGE_KEY, m)
    } catch {
      /* persistence is best-effort */
    }
  }, [])

  const value = useMemo(
    () => ({ mode, isHigh: mode === 'high', setMode }),
    [mode, setMode],
  )
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useUiMode(): UiModeCtx {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useUiMode must be used within UiModeProvider')
  return ctx
}
