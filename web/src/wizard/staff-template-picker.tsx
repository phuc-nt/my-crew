// Step 0 of the create flow (v32): template cards are now EXECUTABLE, not just prefill.
// Each card offers "Tạo ngay" (one-click: confirm → POST /api/agents/create-from-template
// — the server builds the spec from the template, the client sends only role_id) and
// "Tuỳ chỉnh…" (the old prefill path through the full wizard, unchanged). A crew banner
// on top creates the whole default crew in ≤3 clicks (preview → confirm). Every create
// still goes through the same validated create_agent door server-side.
import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { ApiError, api } from '../api/client'
import type { CrewCreateResult, CrewPreview, Pack, StaffTemplate } from '../types'

const RUNTIME_LABEL: Record<string, string> = {
  native: 'suy nghĩ 1 lượt',
  create_agent: 'tự dùng công cụ đọc',
  deep_agent: 'hộp cát chuyên sâu',
}

/** Chips describing the template's pre-attached tools — the "tool gắn sẵn" contract. */
function toolChips(t: StaffTemplate): string[] {
  const chips: string[] = []
  if (t.web_search) chips.push('tìm web')
  if (t.academic_search) chips.push('tra cứu paper')
  if (t.has_skills) chips.push('kỹ năng riêng')
  if (t.reports.length > 0) chips.push(`báo cáo: ${t.reports.join(', ')}`)
  chips.push(RUNTIME_LABEL[t.recommended_runtime] ?? t.recommended_runtime)
  return chips
}

export function StaffTemplatePicker({
  onApply,
  onSkip,
}: {
  onApply: (template: StaffTemplate, pack: Pack) => void
  onSkip: () => void
}) {
  const [templates, setTemplates] = useState<StaffTemplate[]>([])
  const [packs, setPacks] = useState<Pack[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  // one-click state: which card is asking for confirm / creating / done
  const [confirming, setConfirming] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [createdMsg, setCreatedMsg] = useState<Record<string, string>>({})
  // crew state
  const [crew, setCrew] = useState<CrewPreview | null>(null)
  const [crewOpen, setCrewOpen] = useState(false)
  const [crewBusy, setCrewBusy] = useState(false)
  const [crewResult, setCrewResult] = useState<CrewCreateResult | null>(null)
  // Conflict retry: id taken → one more click creates `<role_id>-2` (a second staffer
  // of the same role) instead of dead-ending on the 409 message.
  const [conflictOf, setConflictOf] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([api.getStaffTemplates(), api.getPacks()])
      .then(([t, p]) => {
        setTemplates(t.templates)
        setPacks(p.packs)
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'không tải được mẫu nhân sự'))
      .finally(() => setLoading(false))
    api.getCrewPreview().then(setCrew).catch(() => setCrew(null)) // no crew.yaml ⇒ no banner
  }, [])

  if (loading) return <p>Đang tải…</p>

  // A fetch failure must not dead-end the wizard: manual path stays reachable.
  if (error && templates.length === 0) {
    return (
      <section>
        <p className="error">Lỗi: {error}</p>
        <div className="wizard-nav">
          <button type="button" onClick={onSkip}>
            Bỏ qua, tự chọn
          </button>
        </div>
      </section>
    )
  }

  function customize(template: StaffTemplate) {
    const pack = packs.find((p) => p.id === template.domain)
    if (!pack) {
      setError(`mẫu "${template.role}" dùng loại nhân sự "${template.domain}" chưa cài — chọn thủ công`)
      return
    }
    onApply(template, pack)
  }

  async function quickCreate(t: StaffTemplate, idOverride?: string) {
    setBusy(t.role_id)
    setError(null)
    try {
      const out = idOverride
        ? await api.createFromTemplate(t.role_id, idOverride)
        : await api.createFromTemplate(t.role_id)
      setCreatedMsg((m) => ({ ...m, [t.role_id]: `Đã tạo "${out.id}". ${out.hint}` }))
      setConfirming(null)
      setConflictOf(null)
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'tạo từ mẫu thất bại'
      if (!idOverride && e instanceof ApiError && e.status === 409) {
        setConflictOf(t.role_id)
      }
      setError(msg)
    } finally {
      setBusy(null)
    }
  }

  async function crewCreate() {
    setCrewBusy(true)
    setError(null)
    try {
      setCrewResult(await api.createCrew())
    } catch (e) {
      setError(e instanceof Error ? e.message : 'tạo đội thất bại')
    } finally {
      setCrewBusy(false)
    }
  }

  const missingCount = crew ? crew.members.filter((m) => !m.exists).length : 0

  return (
    <section>
      <h3>Chọn mẫu nhân sự</h3>
      {error && <p className="error">Lỗi: {error}</p>}

      {crew && missingCount > 0 && !crewResult && (
        <div className="crew-banner">
          <strong>{crew.crew}</strong> — tạo cả đội {missingCount} nhân sự trong một lần
          {!crewOpen ? (
            <button type="button" onClick={() => setCrewOpen(true)}>
              Tạo cả đội ({missingCount})
            </button>
          ) : (
            <div className="crew-preview">
              <ul>
                {crew.members.map((m) => (
                  <li key={m.role_id}>
                    {m.role} ({m.role_id}){m.role_id === crew.coordinator ? ' — trưởng phòng điều phối' : ''}
                    {m.exists ? ' · đã có, bỏ qua' : ''}
                  </li>
                ))}
              </ul>
              <button type="button" disabled={crewBusy} onClick={() => void crewCreate()}>
                {crewBusy ? 'Đang tạo…' : `Xác nhận tạo ${missingCount} nhân sự`}
              </button>{' '}
              <button type="button" onClick={() => setCrewOpen(false)}>
                Thôi
              </button>
            </div>
          )}
        </div>
      )}
      {crewResult && (
        <div className="crew-banner">
          ✅ Đã tạo {crewResult.created.length} nhân sự
          {crewResult.skipped.length > 0 ? ` (bỏ qua ${crewResult.skipped.length} đã có)` : ''}
          {crewResult.coordinator_id ? ` — trưởng phòng: ${crewResult.coordinator_id}` : ''}
          {crewResult.failed.length > 0 && (
            <p className="error">
              Lỗi: {crewResult.failed.map((f) => `${f.role_id} (${f.error})`).join('; ')}
            </p>
          )}
          <p>
            Điền token vào .env nếu vai cần, rồi xem <Link to="/team">trang Đội</Link>.
          </p>
        </div>
      )}

      {templates.length === 0 ? (
        <p className="muted">Chưa có mẫu nhân sự nào — tự chọn ở bước tiếp theo.</p>
      ) : (
        <div className="staff-template-grid">
          {templates.map((t) => (
            <div key={t.role_id} className="staff-template-card">
              <strong>{t.role}</strong>
              <div className="muted">loại nhân sự: {t.domain}</div>
              <div className="template-chips">
                {toolChips(t).map((c) => (
                  <span key={c} className="chip">
                    {c}
                  </span>
                ))}
              </div>
              {createdMsg[t.role_id] ? (
                <p className="muted">✅ {createdMsg[t.role_id]}</p>
              ) : confirming === t.role_id ? (
                <div>
                  <p className="muted">Tạo nhân sự "{t.role_id}" với cấu hình chuẩn của mẫu?</p>
                  <button type="button" disabled={busy === t.role_id} onClick={() => void quickCreate(t)}>
                    {busy === t.role_id ? 'Đang tạo…' : 'Xác nhận'}
                  </button>{' '}
                  <button type="button" onClick={() => setConfirming(null)}>
                    Thôi
                  </button>
                  {conflictOf === t.role_id && (
                    <p className="muted">
                      Đã có "{t.role_id}" rồi.{' '}
                      <button
                        type="button"
                        disabled={busy === t.role_id}
                        onClick={() => void quickCreate(t, `${t.role_id}-2`)}
                      >
                        Tạo thêm "{t.role_id}-2"
                      </button>
                    </p>
                  )}
                </div>
              ) : (
                <div>
                  <button type="button" onClick={() => setConfirming(t.role_id)}>
                    Tạo ngay
                  </button>{' '}
                  <button type="button" className="chip" onClick={() => customize(t)}>
                    Tuỳ chỉnh…
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
      <div className="wizard-nav">
        <button type="button" onClick={onSkip}>
          Bỏ qua, tự chọn
        </button>
      </div>
    </section>
  )
}
