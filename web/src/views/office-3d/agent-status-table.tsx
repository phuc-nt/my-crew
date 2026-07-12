// 2D fallback for the 3D office scene: a plain table (agent / trạng thái / công việc), rendered
// instead of the Canvas when prefers-reduced-motion is set or the UA looks mobile (see
// use-3d-fallback.ts). No animation — just the same derived desk-state map as a static list.
import type { AgentDeskState, AgentState } from './agent-office-state'

const STATE_LABEL: Record<AgentState, string> = {
  idle: 'Đang chờ',
  assigned: 'Đã nhận việc',
  working: 'Đang làm',
  done: 'Vừa hoàn thành',
}

interface AgentStatusTableProps {
  agentIds: string[]
  desks: Map<string, AgentDeskState>
  // v32 parity with the 3D desks: a row click opens the same target a desk click does.
  onDeskSelect?: (id: string) => void
}

export function AgentStatusTable({ agentIds, desks, onDeskSelect }: AgentStatusTableProps) {
  return (
    <section className="office-3d-scene">
      <h2>Văn phòng 3D</h2>
      <p className="ops-chat-hint">
        Chế độ bảng (thu gọn hoạt ảnh) — cùng dữ liệu trạng thái nhân sự, hiển thị dạng bảng thay
        vì sơ đồ 3D.
      </p>
      {agentIds.length === 0 ? (
        <p className="ops-chat-empty">Chưa có nhân sự nào xuất hiện trong dòng sự kiện.</p>
      ) : (
        <table className="office-3d-fallback-table">
          <thead>
            <tr>
              <th>Nhân sự</th>
              <th>Trạng thái</th>
              <th>Công việc</th>
              <th>Bước</th>
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
                  <td data-label="Nhân sự">{id}</td>
                  <td data-label="Trạng thái">
                    <span className={`office-3d-state office-3d-state-${state}`}>{STATE_LABEL[state]}</span>
                  </td>
                  <td data-label="Công việc">{d?.taskTitle ?? '—'}</td>
                  <td data-label="Bước">{d?.stepTitle ?? '—'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </section>
  )
}
