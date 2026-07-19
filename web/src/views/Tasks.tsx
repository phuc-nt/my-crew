// Assigned-tasks board (v6 M15b): "Việc đã giao" — every agent's assigned tasks with status
// + history, and a cancel button for open ones. Read-only + cancel; assigning a task is done
// through chat (needs the confirm dialogue). Consumes /api/tasks.
import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import { Button } from '../components/ui/button'
import { EmptyState } from '../components/ui/empty-state'
import { PageHeader } from '../components/ui/page-header'
import type { AgentTasks, AssignedTask } from '../types'

const STATUS_LABEL: Record<AssignedTask['status'], string> = {
  open: 'đang mở',
  running: 'đang chạy',
  done: 'hoàn tất',
  cancelled: 'đã huỷ',
  stalled: 'bị treo',
}

function taskSummary(t: AssignedTask): string {
  if (t.kind === 'watch') return `Theo dõi PR #${String(t.params.number ?? '?')}`
  if (t.kind === 'report') return `Báo cáo định kỳ '${String(t.params.kind ?? '?')}'`
  if (t.kind === 'qa') return `Trả lời định kỳ: ${String(t.params.question ?? '?')}`
  return t.kind
}

export function Tasks() {
  const [agents, setAgents] = useState<AgentTasks[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)

  const load = useCallback(() => {
    api
      .getTasks()
      .then((p) => setAgents(p.agents))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'tải thất bại'))
  }, [])

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
        setError(e instanceof Error ? e.message : 'huỷ thất bại')
      } finally {
        setBusyId(null)
      }
    },
    [load],
  )

  if (error) return <p className="error">Lỗi: {error}</p>
  if (agents === null) return <p>Đang tải…</p>
  if (agents.length === 0)
    return (
      <section>
        <PageHeader title="Việc đã giao" />
        <EmptyState>Chưa có việc nào được giao. Giao việc qua khung Trợ lý (chat).</EmptyState>
      </section>
    )

  return (
    <section className="tasks-board">
      <PageHeader title="Việc đã giao" />
      {agents.map((a) => (
        <div key={a.agent_id} className="tasks-agent">
          <h3>{a.agent_id}</h3>
          <table className="tasks-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Việc</th>
                <th>Trạng thái</th>
                <th>Lần chạy gần nhất</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {a.tasks.map((t) => {
                const last = t.history.at(-1)
                const open = t.status === 'open' || t.status === 'running'
                return (
                  <tr key={t.id}>
                    <td data-label="#">{t.id}</td>
                    <td data-label="Việc">{taskSummary(t)}</td>
                    <td data-label="Trạng thái">{STATUS_LABEL[t.status]}</td>
                    <td className="tasks-last" data-label="Lần chạy gần nhất">{last ? last.summary : '—'}</td>
                    <td>
                      {open && (
                        <Button
                          variant="ghost"
                          onClick={() => void cancel(a.agent_id, t.id)}
                          disabled={busyId === `${a.agent_id}:${t.id}`}
                        >
                          Huỷ
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
