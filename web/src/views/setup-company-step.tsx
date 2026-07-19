// Setup wizard's company step: name + optional coordinator select, written via
// POST /api/company. Split out of Setup.tsx to keep that file under the project's
// modularization guideline — this is pure presentation, all state/fetch stays in Setup.tsx.
import type { AgentSummary } from '../types'

export function SetupCompanyStep({
  companyName,
  setCompanyName,
  coordinatorId,
  setCoordinatorId,
  agents,
  busy,
  error,
  onBack,
  onNext,
}: {
  companyName: string
  setCompanyName: (v: string) => void
  coordinatorId: string
  setCoordinatorId: (v: string) => void
  agents: AgentSummary[]
  busy: boolean
  error: string | null
  onBack: () => void
  onNext: () => void
}) {
  return (
    <>
      <h1>Công ty</h1>
      <p className="setup-hint">Đặt tên công ty và chọn trưởng phòng điều phối (không bắt buộc).</p>
      <label>
        Tên công ty
        <input value={companyName} onChange={(e) => setCompanyName(e.target.value)} placeholder="Acme JSC" />
      </label>
      <label>
        Trưởng phòng điều phối (không bắt buộc)
        <select value={coordinatorId} onChange={(e) => setCoordinatorId(e.target.value)}>
          <option value="">(chưa chọn)</option>
          {agents.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name} ({a.id})
            </option>
          ))}
        </select>
      </label>
      {error && <p className="error">{error}</p>}
      <div className="setup-actions">
        {/* v53: styled by container element selector (.setup-actions button) — unify in a later pass */}
        <button type="button" disabled={busy} onClick={onBack}>
          Quay lại
        </button>
        <button type="button" className="setup-primary" disabled={busy} onClick={onNext}>
          Tiếp tục
        </button>
      </div>
    </>
  )
}
