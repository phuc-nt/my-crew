// The assistant conversation's state: ops turns against /api/ops/chat.
//
// Ported from the standalone /assistant view rather than rewritten — the endpoint
// contract, the availability probe and the command catalog are unchanged. What moved is
// the shape: the hub renders this as one conversation among many, so page furniture
// (page header, a pending chip duplicating the pending column) was left behind, and the
// old view was deleted so there is only one implementation of this conversation.
//
// No SSE here on purpose: an ops reply is one short request/response turn, not a run.
import { useCallback, useEffect, useState } from 'react'
import { api } from '../../../api/client'
import { useLanguage } from '../../../i18n/language-context'
import type { OpsChatCommand } from '../../../types'

export interface OpsTurn {
  who: 'ceo' | 'agent'
  text: string
}

export interface OpsChat {
  /** null while the availability probe is still in flight. */
  available: boolean | null
  unavailableReason: string
  commands: OpsChatCommand[]
  turns: OpsTurn[]
  busy: boolean
  error: string | null
  send: (message: string) => Promise<void>
}

export function useOpsChat(): OpsChat {
  const { t } = useLanguage()
  const [available, setAvailable] = useState<boolean | null>(null)
  const [unavailableReason, setUnavailableReason] = useState('')
  const [commands, setCommands] = useState<OpsChatCommand[]>([])
  const [turns, setTurns] = useState<OpsTurn[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    // The catalog is discoverability only — failing to load it must not block the chat.
    api
      .getOpsChatCommands()
      .then((r) => setCommands(r.commands))
      .catch(() => setCommands([]))
    api
      .opsChatAvailable()
      .then((r) => {
        setAvailable(r.available)
        if (!r.available) setUnavailableReason(r.reason ?? '')
      })
      .catch((e: unknown) => {
        setAvailable(false)
        setUnavailableReason(e instanceof Error ? e.message : t('chat.checkFailed'))
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const send = useCallback(
    async (message: string) => {
      if (!message.trim() || busy) return
      // The CEO's turn appears immediately; only the reply waits on the network.
      setTurns((prev) => [...prev, { who: 'ceo', text: message }])
      setBusy(true)
      setError(null)
      try {
        const res = await api.opsChat(message)
        setTurns((prev) => [...prev, { who: 'agent', text: res.reply }])
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : t('chat.sendFailed'))
      } finally {
        setBusy(false)
      }
    },
    [busy, t],
  )

  return { available, unavailableReason, commands, turns, busy, error, send }
}
