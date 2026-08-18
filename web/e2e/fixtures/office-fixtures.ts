// Typed fixtures for the cockpit smoke tests. TS (not JSON) so the shapes are
// compile-checked against src/types.ts — a drifted payload fails `tsc` instead of
// silently rendering an empty screen.
import type { AgentSummary, AssignStaffPayload, Workroom } from '../../src/types'

const WATCH_TITLE = '[watch:jira-scrum] Theo dõi bảng SCRUM'

/** 22 rooms: 4 distinct + 17 same-title watch runs (16 done, 1 running) + 1 done room. */
export const workroomsFixture: Workroom[] = [
  { room_id: 'room-bao-cao-tuan', title: 'Soạn báo cáo tuần cho sếp', task_count: 1, status: 'dang-chay', updated_at: '2026-07-31T09:30:00Z', last_seq: 0 },
  { room_id: 'room-phan-tich', title: 'Phân tích đối thủ cạnh tranh', task_count: 1, status: 'ket', updated_at: '2026-07-31T08:15:00Z', last_seq: 0 },
  { room_id: 'room-okr', title: 'Tổng hợp OKR quý', task_count: 1, status: 'dang-chay', updated_at: '2026-07-30T16:00:00Z', last_seq: 0 },
  { room_id: 'room-blog', title: 'Viết bài blog sản phẩm', task_count: 1, status: 'xong', updated_at: '2026-07-29T11:00:00Z', last_seq: 0 },
  ...Array.from({ length: 17 }, (_, i): Workroom => {
    const n = 17 - i // watch-jira-17 first (newest), 01 last
    return {
      room_id: `watch-jira-${String(n).padStart(2, '0')}`,
      title: WATCH_TITLE,
      task_count: 1,
      status: n === 17 ? 'dang-chay' : 'xong',
      updated_at: `2026-07-${String(14 + n).padStart(2, '0')}T07:00:00Z`,
      last_seq: 0,
    }
  }),
]

export const assignStaffFixture: AssignStaffPayload = {
  staff: [
    { id: 'tro-ly-pm', domain: 'pm' },
    { id: 'phan-tich-vien', domain: 'analysis' },
    { id: 'kiem-dinh-vien', domain: 'qa' },
  ],
}

export const agentsFixture: AgentSummary[] = [
  { id: 'tro-ly-pm', name: 'Trợ lý PM', enabled: true, last_run: null },
  { id: 'phan-tich-vien', name: 'Phân tích viên', enabled: true, last_run: null },
  { id: 'kiem-dinh-vien', name: 'Kiểm định viên', enabled: true, last_run: null },
]
