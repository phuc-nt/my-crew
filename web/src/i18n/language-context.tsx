// v53 language mode — VN/EN for FE-static strings only (view-layer, never a
// permission; same shape as ui-mode-context). Default 'vi' so existing operators see
// zero change; persisted in localStorage['ui-lang']. `t()` falls back to vi when a
// runtime key is somehow missing — but the dictionary's `satisfies` constraint makes
// that a compile error first.
import { createContext, useCallback, useContext, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { DICT } from './dictionary'
import type { Language, UiKey } from './dictionary'

const STORAGE_KEY = 'ui-lang'

interface LanguageCtx {
  lang: Language
  setLang: (l: Language) => void
  t: (key: UiKey, params?: Record<string, string | number>) => string
}

const Ctx = createContext<LanguageCtx | null>(null)

function readStored(): Language {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    return v === 'en' ? 'en' : 'vi'
  } catch {
    return 'vi'
  }
}

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Language>(readStored)
  const setLang = useCallback((l: Language) => {
    setLangState(l)
    try { localStorage.setItem(STORAGE_KEY, l) } catch { /* nicety only */ }
  }, [])
  const t = useCallback(
    (key: UiKey, params?: Record<string, string | number>) => {
      let s: string = DICT[lang][key] ?? DICT.vi[key]
      if (params) {
        for (const [k, v] of Object.entries(params)) s = s.replaceAll(`{${k}}`, String(v))
      }
      return s
    },
    [lang],
  )
  const value = useMemo(() => ({ lang, setLang, t }), [lang, setLang, t])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useLanguage(): LanguageCtx {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useLanguage must be used within LanguageProvider')
  return ctx
}
