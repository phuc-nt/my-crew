// Team view (route /team): all agents with lifecycle controls (pause/resume, delete) +
// the integration health panel. Statuses (budget, pending approvals) are fetched lazily
// per-agent after the agent list loads, mirroring how other views fetch per-selected-agent
// data via api.getAgentStatus. Delete requires the existing ConfirmDialog-style two-step
// confirm; the `default` agent's Delete action is hidden (backend also 400s it).
import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { ApiError, api } from '../api/client'
import { IntegrationHealthPanel } from '../components/IntegrationHealthPanel'
import { Button } from '../components/ui/button'
import { EmptyState } from '../components/ui/empty-state'
import { PageHeader } from '../components/ui/page-header'
import { useLanguage } from '../i18n/language-context'
import { CoordinatorHealthBanner } from './office-unified/coordinator-health-banner'
import { KIND_LABEL, RUN_STATUS_LABEL, formatCost, labelFor } from '../labels'
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
  const { t } = useLanguage()
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
      .catch((e: unknown) => setError(e instanceof Error ? e.message : t('team.loadAgentsFailed')))
      .finally(() => setLoading(false))
    // v36 P3: which agents have a newer template config (badge overlay; failure is silent).
    api
      .getTemplateStatus()
      .then((p) => setTemplateStatus(Object.fromEntries(p.agents.map((r) => [r.agent_id, r]))))
      .catch(() => undefined)
  }, [t])

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
      const template = templates.templates.find((tmpl) => tmpl.role_id === COORDINATOR_TEMPLATE_ROLE_ID)
      if (!template) throw new Error(t('team.templateNotFound', { roleId: COORDINATOR_TEMPLATE_ROLE_ID }))
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
      setOpError(e instanceof ApiError ? e.message : e instanceof Error ? e.message : t('team.createCoordinatorFailed'))
    } finally {
      setCreatingCoordinator(false)
    }
  }, [loadAgents, t])

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
      setOpError(e instanceof Error ? e.message : t('team.toggleFailed'))
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
      setOpError(e instanceof Error ? e.message : t('team.upgradePreviewFailed'))
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
          ? t('team.upgradeAppliedNote', { id, n, backup: res.backup })
          : t('team.upgradeNoneNote', { id }),
      )
      setUpgradePreview(null)
      // Refresh the badge state so the upgraded row loses its badge.
      const p = await api.getTemplateStatus()
      setTemplateStatus(Object.fromEntries(p.agents.map((r) => [r.agent_id, r])))
    } catch (e: unknown) {
      setOpError(e instanceof Error ? e.message : t('team.upgradeFailed'))
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
      setDeletedNote(t('team.deletedNote', { id }))
    } catch (e: unknown) {
      setOpError(e instanceof Error ? e.message : t('team.deleteFailed'))
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
      .catch((e: unknown) => setOpError(e instanceof Error ? e.message : t('team.addOrphanFailed')))
      .finally(() => setRegistering(null))
  }

  return (
    <section>
      <IntegrationHealthPanel />
      {/* v49: after creating a crew, the team does nothing until the coordinator daemon runs.
          Surface its state here (same banner + start command as the Office view) so the
          "created a crew but nothing happens" gap is visible, not silent. */}
      <CoordinatorHealthBanner />

      <PageHeader
        title={t('team.title')}
        actions={
          <div className="team-actions">
            <Button variant="ghost" disabled={creating} onClick={goCreate}>
              {t('team.createAgent')}
            </Button>
            {/* v32: templates are one-click-executable on the create page's first step —
                this is the fast path ("Tạo ngay" per role, or the whole default crew). */}
            <Link to="/create" className="btn-link">
              {t('team.quickCreateFromTemplate')}
            </Link>
            {coordinatorId === null && (
              <Button
                variant="ghost"
                disabled={creatingCoordinator}
                onClick={createCoordinator}
              >
                {creatingCoordinator ? t('team.creatingCoordinator') : t('team.createCoordinator')}
              </Button>
            )}
            <Link to="/company-docs" className="btn-link">
              {t('team.docsRepo')}
            </Link>
          </div>
        }
      />
      {alerts.length > 0 && (
        <div className="team-alerts" role="alert">
          {alerts.map((al, i) => (
            <p key={i} className={al.severity === 'high' ? 'error' : 'muted'}>
              {al.severity === 'high' ? '🔴' : '🟡'} <strong>{al.agent_id}</strong>: {al.message}
            </p>
          ))}
        </div>
      )}
      {opError && <p className="error">{t('team.errorPrefix', { message: opError })}</p>}
      {deletedNote && <p className="ok">{deletedNote}</p>}
      {loading && <p>{t('common.loading')}</p>}
      {error && <p className="error">{t('team.errorPrefix', { message: error })}</p>}
      {!loading && !error && agents.length === 0 && (
        <div className="team-empty-hero">
          <EmptyState>{t('team.empty')}</EmptyState>
          <p>
            <Link to="/create" className="btn-link">
              {t('team.emptyCreateWholeCrew')}
            </Link>{' '}
            {t('team.emptyOrPickRole')}
          </p>
        </div>
      )}
      {!loading && !error && agents.length > 0 && (
        <table className="agents-table">
          <thead>
            <tr>
              <th>{t('team.colCode')}</th>
              <th>{t('team.colName')}</th>
              <th>{t('team.colState')}</th>
              <th>{t('team.colLastRun')}</th>
              <th>{t('team.colBudget')}</th>
              <th>{t('team.colPendingApprovals')}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {agents.map((a) => {
              const status = statuses[a.id]
              return (
                <tr key={a.id}>
                  <td data-label={t('team.colCode')}>
                    <Link to={`/agents/${a.id}`}>{a.id}</Link>
                  </td>
                  <td data-label={t('team.colName')}>
                    {a.name}
                    {templateStatus[a.id]?.upgradable && (
                      <Button
                        variant="ghost"
                        className="template-upgrade-badge"
                        title={t('team.templateUpgradeHint')}
                        onClick={() => openUpgrade(a.id)}
                      >
                        {t('team.templateUpgradeBadge', { version: templateStatus[a.id].latest_version })}
                      </Button>
                    )}
                  </td>
                  <td data-label={t('team.colState')}>
                    {a.enabled ? t('team.enabled') : t('team.disabled')}
                    {profileDisabledNotice[a.id] && (
                      <div className="error health-detail">
                        {t('team.profileDisabledNotice')}
                      </div>
                    )}
                  </td>
                  <td data-label={t('team.colLastRun')}>
                    {a.last_run
                      ? `${labelFor(KIND_LABEL, a.last_run.kind)} · ${labelFor(RUN_STATUS_LABEL, a.last_run.status)}`
                      : t('team.neverRun')}
                  </td>
                  <td data-label={t('team.colBudget')}>
                    <div className="budget-cell">
                      <span>
                        {status
                          ? `${formatCost(status.budget.spent)} / ${formatCost(status.budget.cap)}`
                          : '…'}
                      </span>
                      {isHigh && status && (
                        // High mode: a compact budget-usage bar (pure CSS, no chart lib). Warns
                        // (amber→red) as spend nears the cap. Ratio comes from the status.
                        <div
                          className="budget-bar"
                          title={t('team.budgetRatioTitle', { pct: Math.round(status.budget.ratio * 100) })}
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
                  <td data-label={t('team.colPendingApprovals')}>{status ? status.pending_approvals : '…'}</td>
                  <td>
                    <Button variant="ghost" disabled={busyId === a.id} onClick={() => toggleEnabled(a)}>
                      {a.enabled ? t('team.pause') : t('team.resume')}
                    </Button>{' '}
                    {a.id !== 'default' && (
                      <Button
                        variant="danger"
                        disabled={busyId === a.id}
                        onClick={() => setConfirmingDelete(a.id)}
                      >
                        {t('team.delete')}
                      </Button>
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
          <h3>{t('team.orphansTitle', { n: orphans.length })}</h3>
          <p className="muted">
            {t('team.orphansHint')}
          </p>
          <ul>
            {orphans.map((o) => (
              <li key={o.id}>
                <strong>{o.id}</strong> {o.name !== o.id && `(${o.name})`}{' '}
                {o.domain && <span className="muted">— {o.domain}</span>}{' '}
                {o.valid ? (
                  <Button
                    variant="ghost"
                    disabled={registering === o.id}
                    onClick={() => registerOrphan(o.id)}
                  >
                    {registering === o.id ? t('team.orphanAdding') : t('team.orphanAdd')}
                  </Button>
                ) : (
                  <span className="error">{t('team.orphanError', { error: o.error ?? '' })}</span>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
      {confirmingDelete && (
        <div className="confirm-dialog" role="dialog" aria-modal="true" aria-label={t('team.confirmDeleteAria')}>
          <h3>{t('team.confirmDeleteTitle', { id: confirmingDelete })}</h3>
          <p>{t('team.confirmDeleteBody')}</p>
          <Button variant="danger" disabled={busyId === confirmingDelete} onClick={() => confirmDelete(confirmingDelete)}>
            {busyId === confirmingDelete ? t('team.deleting') : t('team.delete')}
          </Button>{' '}
          <Button variant="ghost" disabled={busyId === confirmingDelete} onClick={() => setConfirmingDelete(null)}>
            {t('common.cancel')}
          </Button>
        </div>
      )}
      {upgradeNote && (
        <div className="ok health-detail" role="status">
          {upgradeNote}{' '}
          <Button variant="ghost" onClick={() => setUpgradeNote(null)}>
            {t('team.upgradeNoteClose')}
          </Button>
        </div>
      )}
      {upgradePreview && (
        <div className="confirm-dialog" role="dialog" aria-modal="true" aria-label={t('team.aria.confirmUpgrade')}>
          <h3>
            {t('team.upgradeTitle', {
              id: upgradePreview.id,
              from: upgradePreview.preview.applied_version,
              to: upgradePreview.preview.latest_version,
            })}
          </h3>
          {Object.keys(upgradePreview.preview.apply).length > 0 ? (
            <p>
              {t('team.upgradeWillApplyPrefix')}
              <strong>{Object.keys(upgradePreview.preview.apply).join(', ')}</strong>.
            </p>
          ) : (
            <EmptyState>{t('team.upgradeNoneToApply')}</EmptyState>
          )}
          {upgradePreview.preview.keep.length > 0 && (
            <p className="muted">
              {t('team.upgradeKeep', { fields: upgradePreview.preview.keep.join(', ') })}
            </p>
          )}
          <p className="muted">{t('team.upgradeBackupNote')}</p>
          <Button
            variant="ghost"
            disabled={busyId === upgradePreview.id}
            onClick={() => applyUpgrade(upgradePreview.id)}
          >
            {busyId === upgradePreview.id ? t('team.upgrading') : t('team.upgrade')}
          </Button>{' '}
          <Button variant="ghost" onClick={() => setUpgradePreview(null)}>
            {t('common.cancel')}
          </Button>
        </div>
      )}
    </section>
  )
}
