// v16: the "task giao xong kẹt im lặng" fix — a red banner whenever the dispatch
// engine (src.runtime.service ticker) is not heartbeating. Polls /api/health/coordinator
// every 30s; renders nothing while alive.
//
// v50: mounted on both /office (office-unified) and /team (Team.tsx, so a freshly created crew
// sees the coordinator state). These are distinct routes — only one is mounted at a time, so
// there is no simultaneous double-poll; a shared poll-context would be over-engineering for a
// single 30s GET. Keep the two mount points; this component is the single source.
import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import type { CoordinatorHealthPayload } from '../../types'

const POLL_MS = 30_000

export function CoordinatorHealthBanner() {
  const [health, setHealth] = useState<CoordinatorHealthPayload | null>(null)

  useEffect(() => {
    let stop = false
    const poll = () => {
      api.getCoordinatorHealth().then((h) => { if (!stop) setHealth(h) }).catch(() => undefined)
    }
    poll()
    const t = setInterval(poll, POLL_MS)
    return () => { stop = true; clearInterval(t) }
  }, [])

  if (!health || health.alive) return null
  if (health.reason === 'no_coordinator') {
    return (
      <div className="office-health-banner office-health-warn">
        Chưa cấu hình trưởng phòng (điều phối viên) — vào Cài đặt / Setup để chọn, đội chưa
        thể nhận việc.
      </div>
    )
  }
  return (
    <div className="office-health-banner office-health-dead">
      Bộ điều phối chưa chạy — việc đã giao sẽ KHÔNG tiến triển. Khởi động bằng:{' '}
      <code>uv run python -m src.runtime.service</code> (hoặc cài dịch vụ nền theo mục A.2
      của hướng dẫn).
    </div>
  )
}
