// Team view (route /team): all agents with lifecycle controls (pause/resume, delete) +
// the integration health panel. Statuses (budget, pending approvals) are fetched lazily
// per-agent after the agent list loads, mirroring how other views fetch per-selected-agent
// data via api.getAgentStatus. Delete requires the existing ConfirmDialog-style two-step
// confirm; the `default` agent's Delete action is hidden (backend also 400s it).
import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { ApiError, api } from '../api/client'
import { IntegrationHealthPanel } from '../components/IntegrationHealthPanel'
import { CoordinatorHealthBanner } from './office-unified/coordinator-health-banner'
import { KIND_LABEL, RUN_STATUS_LABEL, labelFor } from '../labels'
import { useUiMode } from '../ui-mode-context'
import type {
  AgentStatus,
  AgentSummary,
  TeamAlert,
  TemplateStatusRow,
  TemplateUpgradePreview,
  UnregisteredProfile,
} from '../types'

// 1-click coordinator bootstrap ("Tạo trưởng phòng"): scaffolds an agent from the
// `truong-phong` staff template (role_id) and points `company.yaml::coordinator_id` at
// it. Fixed id — the button is hidden once a coordinator already exists (see
// `coordinatorId` gate below), so a repeat click racing itself is the only collision
// path; that already 409s cleanly via api.createAgent same as the wizard's manual path.
const COORDINATOR_TEMPLATE_ROLE_ID = 'truong-phong'
const COORDINATOR_AGENT_ID = 'truong-phong'

export function Team() {
  const [agents, setAgents] = useState<AgentSummary[]>([])
  // v18: profiles on disk that fell out of the registry (recovery list)
  const [orphans, setOrphans] = useState<UnregisteredProfile[]>([])
  const [registering, setRegistering] = useState<string | null>(null)
  const [statuses, setStatuses] = useState<Record<string, AgentStatus>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [opError, setOpError] = useState<string | null>(null)
  const [confirmingDelete, setConfirmingDelete] = useState<string | null>(null)
  const [deletedNote, setDeletedNote] = useState<string | null>(null)
  // v36 P3: template config version-pin — status per agent + the open upgrade preview.
  const [templateStatus, setTemplateStatus] = useState<Record<string, TemplateStatusRow>>({})
  const [upgradePreview, setUpgradePreview] = useState<
    { id: string; preview: TemplateUpgradePreview } | null
  >(null)
  const [upgradeNote, setUpgradeNote] = useState<string | null>(null)
  // agent id -> "profile still disables it" notice after a Resume the profile vetoes
  // (PATCH .../enabled returns effective_enabled=false even though enabled=true).
  const [profileDisabledNotice, setProfileDisabledNotice] = useState<Record<string, boolean>>({})
  // v3 M8: deterministic fleet alerts (budget near cap, stuck approvals, deny spikes).
  const [alerts, setAlerts] = useState<TeamAlert[]>([])
  const [creating, setCreating] = useState(false)
  const [coordinatorId, setCoordinatorId] = useState<string | null | undefined>(undefined) // undefined = not loaded yet
  const [creatingCoordinator, setCreatingCoordinator] = useState(false)
  const { isHigh } = useUiMode()
  const navigate = useNavigate()

  // v9 P2: "+ Tạo nhân sự ảo" prefers the conversational path (chat-ops), but a brand-new CEO
  // may have no admin agent / no ops_operator_id yet — chat is then unavailable and would be a
  // dead-end. Fall back to the wizard so the FIRST agent can always be created. (red-team B3)
  const goCreate = useCallback(async () => {
    setCreating(true)
    try {
      const r = await api.opsChatAvailable()
      navigate(r.available ? '/chat?intent=create-agent' : '/create')
    } catch {
      navigate('/create') // availability check failed → wizard still works
    } finally {
      setCreating(false)
    }
  }, [navigate])

  const loadAgents = useCallback(() => {
    setLoading(true)
    setError(null)
    api
      .getTeamAlerts()
      .then((p) => setAlerts(p.alerts))
      .catch(() => undefined) // alerts are an overlay; their failure must not break the table
    api
      .getAgents()
      .then((list) => {
        setAgents(list)
        for (const a of list) {
          api
            .getAgentStatus(a.id)
            .then((s) => setStatuses((prev) => ({ ...prev, [a.id]: s })))
            .catch(() => undefined) // a single agent's status failing shouldn't break the table
        }
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'không tải được danh sách agent'))
      .finally(() => setLoading(false))
    // v36 P3: which agents have a newer template config (badge overlay; failure is silent).
    api
      .getTemplateStatus()
      .then((p) => setTemplateStatus(Object.fromEntries(p.agents.map((r) => [r.agent_id, r]))))
      .catch(() => undefined)
  }, [])

  const loadCompany = useCallback(() => {
    api
      .getCompany()
      .then((c) => setCoordinatorId(c.coordinator_id))
      .catch(() => setCoordinatorId(null)) // treat "unknown" as "no coordinator yet" — never blocks the button
  }, [])

  useEffect(() => {
    loadAgents()
    loadCompany()
  }, [loadAgents, loadCompany])

  const createCoordinator = useCallback(async () => {
    setCreatingCoordinator(true)
    setOpError(null)
    try {
      const templates = await api.getStaffTemplates()
      const template = templates.templates.find((t) => t.role_id === COORDINATOR_TEMPLATE_ROLE_ID)
      if (!template) throw new Error(`không tìm thấy mẫu "${COORDINATOR_TEMPLATE_ROLE_ID}"`)
      const created = await api.createAgent({
        id: COORDINATOR_AGENT_ID,
        name: template.role,
        domain: template.domain,
        reports: template.reports,
        schedule: {},
        bindings: {},
        ...(template.persona.trim() ? { persona: template.persona } : {}),
      })
      const company = await api.getCompany()
      await api.saveCompany(company.name, created.created.id, company.team_task_cap_usd)
      setCoordinatorId(created.created.id)
      loadAgents()
    } catch (e: unknown) {
      setOpError(e instanceof ApiError ? e.message : e instanceof Error ? e.message : 'tạo trưởng phòng thất bại')
    } finally {
      setCreatingCoordinator(false)
    }
  }, [loadAgents])

  async function toggleEnabled(agent: AgentSummary) {
    setBusyId(agent.id)
    setOpError(null)
    try {
      const res = await api.setAgentEnabled(agent.id, !agent.enabled)
      // Don't trust the optimistic `enabled` value alone — a Resume can flip the
      // registry (enabled: true) while the profile still vetoes the agent
      // (effective_enabled: false). Re-fetch the real list so the table reflects the
      // service gate's actual state, and surface a per-row notice for that case.
      setProfileDisabledNotice((prev) => {
        const next = { ...prev }
        if (res.enabled && !res.effective_enabled) next[agent.id] = true
        else delete next[agent.id]
        return next
      })
      await refreshAgentsOnly()
    } catch (e: unknown) {
      setOpError(e instanceof Error ? e.message : 'thao tác thất bại')
    } finally {
      setBusyId(null)
    }
  }

  async function refreshAgentsOnly() {
    const list = await api.getAgents()
    setAgents(list)
  }

  // v36 P3: open the review dialog (which config fields an upgrade would apply vs keep).
  async function openUpgrade(id: string) {
    setOpError(null)
    try {
      const preview = await api.previewTemplateUpgrade(id)
      setUpgradePreview({ id, preview })
    } catch (e: unknown) {
      setOpError(e instanceof Error ? e.message : 'không xem được nâng cấp')
    }
  }

  async function applyUpgrade(id: string) {
    setBusyId(id)
    setOpError(null)
    try {
      const res = await api.applyTemplateUpgrade(id)
      const n = Object.keys(res.apply).length
      setUpgradeNote(
        n > 0
          ? `Đã nâng cấp ${id}: áp ${n} mục, sao lưu ${res.backup}. Giữ nguyên mục bạn đã tự chỉnh.`
          : `Đã cập nhật phiên bản ${id} (không có mục nào cần áp).`,
      )
      setUpgradePreview(null)
      // Refresh the badge state so the upgraded row loses its badge.
      const p = await api.getTemplateStatus()
      setTemplateStatus(Object.fromEntries(p.agents.map((r) => [r.agent_id, r])))
    } catch (e: unknown) {
      setOpError(e instanceof Error ? e.message : 'nâng cấp thất bại')
    } finally {
      setBusyId(null)
    }
  }

  async function confirmDelete(id: string) {
    setBusyId(id)
    setOpError(null)
    try {
      await api.deleteAgent(id)
      setAgents((prev) => prev.filter((a) => a.id !== id))
      setProfileDisabledNotice((prev) => {
        const next = { ...prev }
        delete next[id]
        return next
      })
      setConfirmingDelete(null)
      setDeletedNote(`Đã xoá ${id}. Hồ sơ agent được giữ lại để lưu trữ.`)
    } catch (e: unknown) {
      setOpError(e instanceof Error ? e.message : 'xoá thất bại')
    } finally {
      setBusyId(null)
    }
  }

  useEffect(() => {
    api.getUnregisteredProfiles().then((p) => setOrphans(p.profiles)).catch(() => setOrphans([]))
  }, [agents.length])

  const registerOrphan = (id: string) => {
    setRegistering(id)
    api.registerExistingProfile(id)
      .then(() => api.getUnregisteredProfiles().then((p) => setOrphans(p.profiles)))
      .then(() => window.location.reload()) // đơn giản: bảng đội + roster nạp lại đủ
      .catch((e: unknown) => setOpError(e instanceof Error ? e.message : 'thêm thất bại'))
      .finally(() => setRegistering(null))
  }

  return (
    <section>
      <IntegrationHealthPanel />
      {/* v49: after creating a crew, the team does nothing until the coordinator daemon runs.
          Surface its state here (same banner + start command as the Office view) so the
          "created a crew but nothing happens" gap is visible, not silent. */}
      <CoordinatorHealthBanner />

      <h2>Đội</h2>
      <div className="team-actions">
        <button type="button" className="btn-link" disabled={creating} onClick={goCreate}>
          + Tạo nhân sự ảo
        </button>
        {/* v32: templates are one-click-executable on the create page's first step —
            this is the fast path ("Tạo ngay" per role, or the whole default crew). */}
        <Link to="/create" className="btn-link">
          ⚡ Tạo nhanh từ mẫu / cả đội
        </Link>
        {coordinatorId === null && (
          <button
            type="button"
            className="btn-link"
            disabled={creatingCoordinator}
            onClick={createCoordinator}
          >
            {creatingCoordinator ? 'Đang tạo…' : '+ Tạo trưởng phòng'}
          </button>
        )}
        <Link to="/company-docs" className="btn-link">
          📄 Kho tài liệu
        </Link>
      </div>
      {alerts.length > 0 && (
        <div className="team-alerts" role="alert">
          {alerts.map((al, i) => (
            <p key={i} className={al.severity === 'high' ? 'error' : 'muted'}>
              {al.severity === 'high' ? '🔴' : '🟡'} <strong>{al.agent_id}</strong>: {al.message}
            </p>
          ))}
        </div>
      )}
      {opError && <p className="error">Lỗi: {opError}</p>}
      {deletedNote && <p className="ok">{deletedNote}</p>}
      {loading && <p>Đang tải…</p>}
      {error && <p className="error">Lỗi: {error}</p>}
      {!loading && !error && agents.length === 0 && (
        <div className="team-empty-hero">
          <p className="muted">Chưa có nhân sự nào.</p>
          <p>
            <Link to="/create" className="btn-link">
              ⚡ Tạo cả đội mẫu trong một lần
            </Link>{' '}
            hoặc chọn từng vai từ mẫu có sẵn.
          </p>
        </div>
      )}
      {!loading && !error && agents.length > 0 && (
        <table className="agents-table">
          <thead>
            <tr>
              <th>Mã</th>
              <th>Tên</th>
              <th>Trạng thái</th>
              <th>Lần chạy gần nhất</th>
              <th>Ngân sách</th>
              <th>Chờ duyệt</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {agents.map((a) => {
              const status = statuses[a.id]
              return (
                <tr key={a.id}>
                  <td data-label="Mã">
                    <Link to={`/agents/${a.id}`}>{a.id}</Link>
                  </td>
                  <td data-label="Tên">
                    {a.name}
                    {templateStatus[a.id]?.upgradable && (
                      <button
                        type="button"
                        className="btn-link template-upgrade-badge"
                        title="Template có bản cấu hình mới — bấm để xem và nâng cấp"
                        onClick={() => openUpgrade(a.id)}
                      >
                        ⬆ bản mới v{templateStatus[a.id].latest_version}
                      </button>
                    )}
                  </td>
                  <td data-label="Trạng thái">
                    {a.enabled ? '✓ bật' : '— tắt'}
                    {profileDisabledNotice[a.id] && (
                      <div className="error health-detail">
                        Agent đang bị tắt trong hồ sơ — bật lại ở Nâng cao › Cấu hình
                      </div>
                    )}
                  </td>
                  <td data-label="Lần chạy gần nhất">
                    {a.last_run
                      ? `${labelFor(KIND_LABEL, a.last_run.kind)} · ${labelFor(RUN_STATUS_LABEL, a.last_run.status)}`
                      : 'chưa chạy'}
                  </td>
                  <td data-label="Ngân sách">
                    <div className="budget-cell">
                      <span>
                        {status
                          ? `$${status.budget.spent.toFixed(2)} / $${status.budget.cap.toFixed(2)}`
                          : '…'}
                      </span>
                      {isHigh && status && (
                        // High mode: a compact budget-usage bar (pure CSS, no chart lib). Warns
                        // (amber→red) as spend nears the cap. Ratio comes from the status.
                        <div
                          className="budget-bar"
                          title={`${Math.round(status.budget.ratio * 100)}% ngân sách`}
                        >
                          <span
                            className={
                              status.budget.ratio >= 1
                                ? 'budget-bar-fill over'
                                : status.budget.ratio >= 0.8
                                  ? 'budget-bar-fill warn'
                                  : 'budget-bar-fill'
                            }
                            style={{ width: `${Math.min(100, status.budget.ratio * 100)}%` }}
                          />
                        </div>
                      )}
                    </div>
                  </td>
                  <td data-label="Chờ duyệt">{status ? status.pending_approvals : '…'}</td>
                  <td>
                    <button type="button" className="btn" disabled={busyId === a.id} onClick={() => toggleEnabled(a)}>
                      {a.enabled ? 'Tạm dừng' : 'Bật lại'}
                    </button>{' '}
                    {a.id !== 'default' && (
                      <button
                        type="button"
                        className="btn btn-danger"
                        disabled={busyId === a.id}
                        onClick={() => setConfirmingDelete(a.id)}
                      >
                        Xoá
                      </button>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}

      {orphans.length > 0 && (
        <section className="team-orphans">
          <h3>Hồ sơ chưa trong đội ({orphans.length})</h3>
          <p className="muted">
            Các hồ sơ này tồn tại trong thư mục profiles/ nhưng chưa được đăng ký vào đội —
            thêm lại để giao việc được cho họ.
          </p>
          <ul>
            {orphans.map((o) => (
              <li key={o.id}>
                <strong>{o.id}</strong> {o.name !== o.id && `(${o.name})`}{' '}
                {o.domain && <span className="muted">— {o.domain}</span>}{' '}
                {o.valid ? (
                  <button
                    type="button" className="btn-link"
                    disabled={registering === o.id}
                    onClick={() => registerOrphan(o.id)}
                  >
                    {registering === o.id ? 'Đang thêm…' : 'Thêm vào đội'}
                  </button>
                ) : (
                  <span className="error">hồ sơ lỗi: {o.error}</span>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
      {confirmingDelete && (
        <div className="confirm-dialog" role="dialog" aria-modal="true" aria-label="Xác nhận xoá">
          <h3>Xoá agent {confirmingDelete}?</h3>
          <p>Agent bị gỡ khỏi danh sách. Hồ sơ của agent vẫn được giữ lại để lưu trữ.</p>
          <button type="button" className="btn btn-danger" disabled={busyId === confirmingDelete} onClick={() => confirmDelete(confirmingDelete)}>
            {busyId === confirmingDelete ? 'Đang xoá…' : 'Xoá'}
          </button>{' '}
          <button type="button" className="btn" disabled={busyId === confirmingDelete} onClick={() => setConfirmingDelete(null)}>
            Huỷ
          </button>
        </div>
      )}
      {upgradeNote && (
        <div className="ok health-detail" role="status">
          {upgradeNote}{' '}
          <button type="button" className="btn-link" onClick={() => setUpgradeNote(null)}>
            đóng
          </button>
        </div>
      )}
      {upgradePreview && (
        <div className="confirm-dialog" role="dialog" aria-modal="true" aria-label="Nâng cấp template">
          <h3>
            Nâng cấp cấu hình {upgradePreview.id} (v{upgradePreview.preview.applied_version} → v
            {upgradePreview.preview.latest_version})
          </h3>
          {Object.keys(upgradePreview.preview.apply).length > 0 ? (
            <p>
              Sẽ áp: <strong>{Object.keys(upgradePreview.preview.apply).join(', ')}</strong>.
            </p>
          ) : (
            <p>Không có mục nào cần áp (bạn đã tự chỉnh hoặc đã mới nhất).</p>
          )}
          {upgradePreview.preview.keep.length > 0 && (
            <p className="muted">
              Giữ nguyên (bạn đã tự chỉnh): {upgradePreview.preview.keep.join(', ')}
            </p>
          )}
          <p className="muted">Hồ sơ hiện tại được sao lưu trước khi ghi.</p>
          <button
            type="button"
            className="btn"
            disabled={busyId === upgradePreview.id}
            onClick={() => applyUpgrade(upgradePreview.id)}
          >
            {busyId === upgradePreview.id ? 'Đang nâng cấp…' : 'Nâng cấp'}
          </button>{' '}
          <button type="button" className="btn" onClick={() => setUpgradePreview(null)}>
            Huỷ
          </button>
        </div>
      )}
    </section>
  )
}
