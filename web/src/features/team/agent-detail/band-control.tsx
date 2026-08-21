// v88 P4: the autonomy band dropdown in the agent header — there was NO band badge
// before this phase (band was only settable via chat-ops `set_band`). One click opens
// the select, one click picks a value — the select's own onChange commits immediately
// (no separate Save step; a `<select>` change IS the deliberate action, unlike a free-
// text field where you might still be typing).
import { useSetAgentBand, useAgentBand } from '../../../api/queries/use-agent-detail-queries'
import { useLanguage } from '../../../i18n/language-context'
import type { AgentBand } from '../../../types'

const BAND_LABEL_KEY = {
  supervised: 'agentDetail.bandSupervised',
  normal: 'agentDetail.bandNormal',
  trusted: 'agentDetail.bandTrusted',
} as const

export function BandControl({ id }: { id: string }) {
  const { t } = useLanguage()
  const { data: band } = useAgentBand(id)
  const setBand = useSetAgentBand(id)

  if (!band) return null

  return (
    <label className="agent-band-control" title={t('agentDetail.bandHelp')}>
      {t('agentDetail.fieldBand')}:{' '}
      <select
        value={band.band}
        disabled={setBand.isPending}
        onChange={(e) => setBand.mutate({ band: e.target.value as AgentBand })}
      >
        {(Object.keys(BAND_LABEL_KEY) as AgentBand[]).map((b) => (
          <option key={b} value={b}>
            {t(BAND_LABEL_KEY[b])}
          </option>
        ))}
      </select>
      {setBand.isError && (
        <span className="error"> {t('agentDetail.bandChangeFailed')}</span>
      )}
    </label>
  )
}
