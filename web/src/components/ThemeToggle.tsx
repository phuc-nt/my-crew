// Theme switcher (v10 M24): a 3-way segmented control — light/dark/auto. Kept as buttons
// (not a <select>) so the current choice is always visible and one tap changes it.
// v53: labels go through the i18n dictionary (VN default, EN in language mode).
import { useLanguage } from '../i18n/language-context'
import type { UiKey } from '../i18n/dictionary'
import { useTheme } from '../theme-context'
import type { ThemePref } from '../theme-context'

const OPTIONS: { pref: ThemePref; labelKey: UiKey }[] = [
  { pref: 'light', labelKey: 'chrome.theme.light' },
  { pref: 'dark', labelKey: 'chrome.theme.dark' },
  { pref: 'auto', labelKey: 'chrome.theme.auto' },
]

export function ThemeToggle() {
  const { pref, setPref } = useTheme()
  const { t } = useLanguage()
  return (
    <div className="theme-toggle" role="group" aria-label="Theme">
      {OPTIONS.map((o) => (
        <button
          key={o.pref}
          type="button"
          className={o.pref === pref ? 'theme-toggle-btn active' : 'theme-toggle-btn'}
          aria-pressed={o.pref === pref}
          title={t(o.labelKey)}
          onClick={() => setPref(o.pref)}
        >
          {t(o.labelKey)}
        </button>
      ))}
    </div>
  )
}
