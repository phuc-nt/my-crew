// v96: the "nothing here yet" moment on each hub, turned into a first step. Instead of
// a muted line, the empty board / overview / roster says what fills it and offers three
// example briefs; picking one seeds the chat composer with it, so the first task is one
// click from any hub.
import { useNavigate } from 'react-router'
import { Button } from '../../components/ui/button'
import type { UiKey } from '../../i18n/dictionary'
import { useLanguage } from '../../i18n/language-context'

export type WelcomeHub = 'chat' | 'work' | 'team'

export const EXAMPLE_BRIEF_KEYS: readonly UiKey[] = [
  'welcome.brief.report',
  'welcome.brief.posts',
  'welcome.brief.plan',
]

const TITLE_KEY: Record<WelcomeHub, UiKey> = {
  chat: 'welcome.chat.title',
  work: 'welcome.work.title',
  team: 'welcome.team.title',
}
const BODY_KEY: Record<WelcomeHub, UiKey> = {
  chat: 'welcome.chat.body',
  work: 'welcome.work.body',
  team: 'welcome.team.body',
}

interface PageWelcomeProps {
  hub: WelcomeHub
  /** On the chat hub the composer is on screen: seed it in place instead of navigating. */
  onPick?: (brief: string) => void
}

export function PageWelcome({ hub, onPick }: PageWelcomeProps) {
  const { t } = useLanguage()
  const navigate = useNavigate()

  const pick = (brief: string) => {
    if (onPick) onPick(brief)
    else navigate('/chat', { state: { assignSeed: brief } })
  }

  return (
    <section className="page-welcome" data-testid="page-welcome" data-hub={hub}>
      <h3 className="page-welcome-title">{t(TITLE_KEY[hub])}</h3>
      <p className="page-welcome-body">{t(BODY_KEY[hub])}</p>
      <ul className="page-welcome-briefs" aria-label={t('welcome.examples')}>
        {EXAMPLE_BRIEF_KEYS.map((key) => (
          <li key={key}>
            <Button variant="chip" className="page-welcome-brief" onClick={() => pick(t(key))}>
              {t(key)}
            </Button>
          </li>
        ))}
      </ul>
      {hub === 'team' ? (
        <Button variant="ghost" onClick={() => navigate('/team?hire=1')}>
          {t('welcome.team.hire')}
        </Button>
      ) : null}
    </section>
  )
}
