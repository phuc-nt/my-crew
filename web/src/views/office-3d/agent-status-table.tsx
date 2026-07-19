// 2D fallback for the 3D office scene: a plain table (agent / trạng thái / công việc), rendered
// instead of the Canvas when prefers-reduced-motion is set or the UA looks mobile (see
// use-3d-fallback.ts). No animation — just the same derived desk-state map as a static list.
import { EmptyState } from '../../components/ui/empty-state'
import type { AgentDeskState, AgentState } from './agent-office-state'

const STATE_LABEL: Record<AgentState, string> = {
  idle: 'Đang chờ',
  assigned: 'Đã nhận việc',
  working: 'Đang làm',
  done: 'Vừa hoàn thành',
  error: 'Gặp lỗi',
}

interface AgentStatusTableProps {
  agentIds: string[]
  desks: Map<string, AgentDeskState>
  // v32 parity with the 3D desks: a row click opens the same target a desk click does.
  onDeskSelect?: (id: string) => void
  // Dual-lens P1 parity with the 3D 🔒 badge (high-mode only — parent gates it).
  needsShellAgents?: Set<string>
}

// Verdict cell parity with the 3D flash ring — persistent text here (a static table
// cannot flash): "✓ đạt" or "✗ N lỗi".
export function verdictCellText(desk: AgentDeskState | undefined): string {
  const v = desk?.lastVerdict
  if (!v) return '—'
  return v.verdict === 'passed' ? '✓ đạt' : `✗ ${v.failureCount} lỗi`
}

export function AgentStatusTable({
  agentIds, desks, onDeskSelect, needsShellAgents,
}: AgentStatusTableProps) {
  return (
    <section className="office-3d-scene">
      {/* v37: h3 not h2 — this is a subsection of the Office page, whose own <h2>"Văn phòng"
          is the page title; two stacked h2s read as a duplicate title in the 2D fallback. */}
      <h3>Văn phòng 3D</h3>
      <p className="ops-chat-hint">
        Chế độ bảng (thu gọn hoạt ảnh) — cùng dữ liệu trạng thái nhân sự, hiển thị dạng bảng thay
        vì sơ đồ 3D.
      </p>
      {agentIds.length === 0 ? (
        <EmptyState>Chưa có nhân sự nào xuất hiện trong dòng sự kiện.</EmptyState>
      ) : (
        <table className="office-3d-fallback-table">
          <thead>
            <tr>
              <th>Nhân sự</th>
              <th>Trạng thái</th>
              <th>Công việc</th>
              <th>Bước</th>
              <th>Kiểm định</th>
            </tr>
          </thead>
          <tbody>
            {agentIds.map((id) => {
              const d = desks.get(id)
              const state: AgentState = d?.state ?? 'idle'
              return (
                <tr
                  key={id}
                  onClick={onDeskSelect ? () => onDeskSelect(id) : undefined}
                  style={onDeskSelect ? { cursor: 'pointer' } : undefined}
                  title={onDeskSelect ? 'Bấm để mở' : undefined}
                >
                  <td data-label="Nhân sự">
                    {needsShellAgents?.has(id) ? '🔒 ' : ''}
                    {id}
                  </td>
                  <td data-label="Trạng thái">
                    <span className={`office-3d-state office-3d-state-${state}`}>{STATE_LABEL[state]}</span>
                  </td>
                  <td data-label="Công việc">{d?.taskTitle ?? '—'}</td>
                  <td data-label="Bước">{d?.stepTitle ?? '—'}</td>
                  <td data-label="Kiểm định">{verdictCellText(d)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </section>
  )
}
