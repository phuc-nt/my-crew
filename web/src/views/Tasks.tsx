// Assigned-tasks board (v6 M15b): "Việc đã giao" — every agent's assigned tasks with status
// + history, and a cancel button for open ones. Read-only + cancel; assigning a task is done
// through chat (needs the confirm dialogue). Consumes /api/tasks.
import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import { Button } from '../components/ui/button'
import { EmptyState } from '../components/ui/empty-state'
import { PageHeader } from '../components/ui/page-header'
import { DICT, type UiKey } from '../i18n/dictionary'
import { useLanguage } from '../i18n/language-context'
import type { AgentTasks, AssignedTask } from '../types'

const STATUS_LABEL_KEY: Record<AssignedTask['status'], UiKey> = {
  open: 'tasks.stateOpen',
  running: 'tasks.stateRunning',
  done: 'tasks.stateDone',
  cancelled: 'tasks.stateCancelled',
  stalled: 'tasks.stateStalled',
}

type Translate = (key: UiKey, params?: Record<string, string | number>) => string

// Optional `t`: only called from within Tasks() today, but the fallback keeps this pure
// function usable without a hook context (matches the pattern used across this sweep).
function taskSummary(task: AssignedTask, t: Translate = (key) => DICT.vi[key]): string {
  if (task.kind === 'watch') return t('tasks.watchSummary', { number: String(task.params.number ?? '?') })
  if (task.kind === 'report') return t('tasks.reportSummary', { kind: String(task.params.kind ?? '?') })
  if (task.kind === 'qa') return t('tasks.qaSummary', { question: String(task.params.question ?? '?') })
  return task.kind
}

export function Tasks() {
  const { t } = useLanguage()
  const [agents, setAgents] = useState<AgentTasks[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)

  const load = useCallback(() => {
    api
      .getTasks()
      .then((p) => setAgents(p.agents))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : t('tasks.loadFailed')))
  }, [t])

  useEffect(() => {
    load()
  }, [load])

  const cancel = useCallback(
    async (agentId: string, taskId: number) => {
      setBusyId(`${agentId}:${taskId}`)
      try {
        await api.cancelTask(agentId, taskId)
        load()
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : t('tasks.cancelFailed'))
      } finally {
        setBusyId(null)
      }
    },
    [load, t],
  )

  if (error) return <p className="error">{t('team.errorPrefix', { message: error })}</p>
  if (agents === null) return <p>{t('common.loading')}</p>
  if (agents.length === 0)
    return (
      <section>
        <PageHeader title={t('tasks.title')} />
        <EmptyState>{t('tasks.empty')}</EmptyState>
      </section>
    )

  return (
    <section className="tasks-board">
      <PageHeader title={t('tasks.title')} />
      {agents.map((a) => (
        <div key={a.agent_id} className="tasks-agent">
          <h3>{a.agent_id}</h3>
          <table className="tasks-table">
            <thead>
              <tr>
                <th>{t('tasks.colIndex')}</th>
                <th>{t('tasks.colTask')}</th>
                <th>{t('tasks.colState')}</th>
                <th>{t('tasks.colLastRun')}</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {a.tasks.map((task) => {
                const last = task.history.at(-1)
                const open = task.status === 'open' || task.status === 'running'
                return (
                  <tr key={task.id}>
                    <td data-label={t('tasks.colIndex')}>{task.id}</td>
                    <td data-label={t('tasks.colTask')}>{taskSummary(task, t)}</td>
                    <td data-label={t('tasks.colState')}>{t(STATUS_LABEL_KEY[task.status])}</td>
                    <td className="tasks-last" data-label={t('tasks.colLastRun')}>{last ? last.summary : '—'}</td>
                    <td>
                      {open && (
                        <Button
                          variant="ghost"
                          onClick={() => void cancel(a.agent_id, task.id)}
                          disabled={busyId === `${a.agent_id}:${task.id}`}
                        >
                          {t('tasks.cancel')}
                        </Button>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      ))}
    </section>
  )
}
