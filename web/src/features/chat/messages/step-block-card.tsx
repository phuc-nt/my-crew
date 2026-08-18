// A collapsed run of `step_status` events for one task. Shows the LATEST step (the
// useful one while work is running) plus how many folded behind it. No expand affordance:
// the folded rows carry no detail the block omits — a step's actual RESULT arrives as its
// own `handoff` event, and those never fold into a block.
import { useLanguage } from '../../../i18n/language-context'
import type { ThreadItem } from '../chat-state'

export function StepBlockCard({ item }: { item: ThreadItem }) {
  const { t } = useLanguage()
  return (
    <li className="chat-row chat-row-steps">
      <div className="chat-bubble chat-step-block">
        <p className="chat-step-title">{item.body.task_title ?? ''}</p>
        <p className="chat-step-current">
          {t('chat.stepBlockCurrent', { step: item.stepTitle ?? '' })}
        </p>
        <p className="chat-step-count">{t('chat.stepBlockCount', { n: item.stepCount ?? 1 })}</p>
      </div>
    </li>
  )
}
