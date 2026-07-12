// Wizard Step 2: agent id/name + an optional persona helper. Typing role + goals
// regenerates the SOUL.md textarea (deterministic template, no LLM) until the operator
// edits the textarea by hand — after that we stop overwriting their edits. `personaEdited`
// lives in the wizard's shared state (not a local useState) so it survives this step
// unmounting when the operator navigates Back/Next and returns.
import { generateSoulMarkdown } from './persona-template'
import { ID_PATTERN } from './use-create-agent-wizard'
import type { WizardState } from './use-create-agent-wizard'

export function IdentityStep({
  state,
  update,
}: {
  state: WizardState
  update: <K extends keyof WizardState>(key: K, value: WizardState[K]) => void
}) {
  const idValid = state.id === '' || ID_PATTERN.test(state.id)

  function regenerate(role: string, goals: string) {
    if (!state.personaEdited) update('persona', generateSoulMarkdown(role, goals))
  }

  return (
    <section>
      <h3>Bước 2: Danh tính</h3>
      <label>
        Mã agent (chữ thường, không dấu, ví dụ: sales-pm):{' '}
        <input
          value={state.id}
          onChange={(e) => update('id', e.target.value.toLowerCase())}
          placeholder="sales-pm"
        />
      </label>
      {!idValid && (
        <p className="error">Mã chỉ gồm chữ thường/số/gạch, bắt đầu bằng chữ hoặc số (vd: sales-pm)</p>
      )}
      <br />
      <label>
        Tên hiển thị:{' '}
        <input value={state.name} onChange={(e) => update('name', e.target.value)} placeholder="PM Kinh doanh" />
      </label>
      <h4>Gợi ý tính cách (không bắt buộc)</h4>
      <label>
        Vai trò:{' '}
        <input
          value={state.role}
          onChange={(e) => {
            update('role', e.target.value)
            regenerate(e.target.value, state.goals)
          }}
          placeholder="quản lý dự án cho đội Kinh doanh"
        />
      </label>
      <br />
      <label>
        Mục tiêu (mỗi dòng một ý):{' '}
        <textarea
          value={state.goals}
          onChange={(e) => {
            update('goals', e.target.value)
            regenerate(state.role, e.target.value)
          }}
          rows={3}
        />
      </label>
      <h4>Cách nhân sự làm việc (runtime)</h4>
      <label>
        Kiểu vận hành:{' '}
        <select
          value={state.agentRuntime}
          onChange={(e) => update('agentRuntime', e.target.value)}
        >
          <option value="native">Chuẩn — kiểm soát chặt nhất (1 lượt, không tự chạy lệnh)</option>
          <option value="create_agent">Linh hoạt — tự tra cứu nhiều bước (an toàn, chỉ đọc)</option>
          <option value="deep_agent">Chuyên sâu — tự chạy lệnh trong hộp cát (cách ly)</option>
        </select>
      </label>
      <p className="runtime-hint">
        {state.agentRuntime === 'native' &&
          'Chặt nhất: 1 lượt suy nghĩ, không dùng công cụ. Hợp việc cần kiểm soát cao (kiểm định, tài chính).'}
        {state.agentRuntime === 'create_agent' &&
          'Trung bình: tự gọi công cụ ĐỌC nhiều vòng (Jira/GitHub); mọi ghi ra ngoài đi qua cửa audit. Hợp nội dung, PM.'}
        {state.agentRuntime === 'deep_agent' &&
          'Tự do nhất: tự chạy lệnh shell trong hộp cát cách ly (không đụng máy thật). Hợp nghiên cứu sâu. Cần cài Docker.'}
      </p>
      <h4>Chế độ hành động</h4>
      <label>
        Mức tin cậy:{' '}
        <select value={state.trustMode} onChange={(e) => update('trustMode', e.target.value)}>
          <option value="">Theo mặc định công ty</option>
          <option value="autonomous">Tự chủ — hành động ngay, ghi nhật ký audit</option>
          <option value="guarded">Có duyệt — việc nhạy cảm chờ bạn duyệt</option>
        </select>
      </label>
      <p className="runtime-hint">
        {state.trustMode === 'autonomous' &&
          'Agent thực thi ngay không chờ duyệt; bạn hậu kiểm qua nhật ký audit. Lưới an toàn cứng (chống xoá dữ liệu, lộ khoá) luôn bật.'}
        {state.trustMode === 'guarded' &&
          'Việc nhạy cảm (gửi email, sửa Jira, đăng kênh ngoài) xếp hàng ở tab Duyệt chờ bạn.'}
        {state.trustMode === '' &&
          'Dùng thiết lập chung của công ty (TRUST_MODE trong .env, mặc định Tự chủ).'}
      </p>
      <h4>SOUL.md (chỉnh được)</h4>
      <textarea
        className="persona-textarea"
        value={state.persona}
        onChange={(e) => {
          update('personaEdited', true)
          update('persona', e.target.value)
        }}
        rows={8}
      />
    </section>
  )
}
