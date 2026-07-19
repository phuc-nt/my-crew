// v53 language mode — the ONE dictionary for every FE-static string. No i18n library
// (KISS, mirrors ui-mode-context): `vi` is the source of truth for the key set; the
// `satisfies` constraint makes a missing/extra `en` key a COMPILE error.
//
// BOUNDARY (v1, documented in docs/design-guidelines.md): backend-origin strings
// (health-check labels, friendlyError, clarify questions, alerts) and LLM-generated
// content stay Vietnamese in EN mode — they are data, not layout.
//
// TECHNICAL TERMS stay English in BOTH languages (CEO decision): Captures, Guardrail,
// PIC, deep_agent, sandbox, engine, token(s), MCP, attempt, autonomous/guarded.
//
// Params: `{name}` placeholders, replaced by t(key, params).

const vi = {
  // App chrome
  'nav.office': 'Văn phòng',
  'nav.team': 'Đội',
  'nav.work': 'Duyệt',
  'nav.outputs': 'Kết quả',
  'nav.activity': 'Hoạt động',
  'nav.chat': 'Trợ lý',
  'nav.settings': 'Cài đặt',
  'nav.advanced.overview': 'Tổng quan',
  'nav.advanced.timeline': 'Dòng thời gian',
  'nav.advanced.cost': 'Chi phí',
  'nav.advanced.memory': 'Bộ nhớ',
  'nav.advanced.guardrail': 'Guardrail',
  'nav.advanced.config': 'Cấu hình',
  'nav.advanced.trigger': 'Chạy tay',
  'nav.advanced.captures': 'Captures',
  'nav.advanced.officeLog': 'Nhật ký văn phòng',
  'nav.advancedLabel': 'Nâng cao',
  'chrome.logout': 'Đăng xuất',
  'chrome.modeHigh': '🔬 Kỹ thuật',
  'chrome.modeLow': '👁 Thường',
  'chrome.modeHighTitle': 'Đang: chế độ kỹ thuật — bấm về chế độ thường',
  'chrome.modeLowTitle': 'Đang: chế độ thường — bấm sang chế độ kỹ thuật',
  'chrome.searchPlaceholder': 'tìm lịch sử…',
  'chrome.searchAria': 'Tìm lịch sử làm việc',
  'chrome.searchEmpty': 'Không có kết quả',
  'chrome.theme.light': 'Sáng',
  'chrome.theme.dark': 'Tối',
  'chrome.theme.auto': 'Tự động',

  // Login
  'login.title': 'my-crew',
  'login.password': 'Mật khẩu',
  'login.submit': 'Đăng nhập',
  'login.submitting': 'Đang đăng nhập…',

  // Common / primitives
  'common.loading': 'Đang tải…',
  'common.close': 'Đóng',
  'common.cancel': 'Hủy',
  'common.save': 'Lưu',
  'common.confirm': 'Xác nhận',
  'common.error': 'Lỗi',
} as const

export type UiKey = keyof typeof vi

const en = {
  'nav.office': 'Office',
  'nav.team': 'Team',
  'nav.work': 'Approvals',
  'nav.outputs': 'Outputs',
  'nav.activity': 'Activity',
  'nav.chat': 'Assistant',
  'nav.settings': 'Settings',
  'nav.advanced.overview': 'Overview',
  'nav.advanced.timeline': 'Timeline',
  'nav.advanced.cost': 'Cost',
  'nav.advanced.memory': 'Memory',
  'nav.advanced.guardrail': 'Guardrail',
  'nav.advanced.config': 'Config',
  'nav.advanced.trigger': 'Manual run',
  'nav.advanced.captures': 'Captures',
  'nav.advanced.officeLog': 'Office log',
  'nav.advancedLabel': 'Advanced',
  'chrome.logout': 'Log out',
  'chrome.modeHigh': '🔬 Technical',
  'chrome.modeLow': '👁 Normal',
  'chrome.modeHighTitle': 'Technical mode on — click for normal mode',
  'chrome.modeLowTitle': 'Normal mode on — click for technical mode',
  'chrome.searchPlaceholder': 'search history…',
  'chrome.searchAria': 'Search work history',
  'chrome.searchEmpty': 'No results',
  'chrome.theme.light': 'Light',
  'chrome.theme.dark': 'Dark',
  'chrome.theme.auto': 'Auto',

  'login.title': 'my-crew',
  'login.password': 'Password',
  'login.submit': 'Log in',
  'login.submitting': 'Logging in…',

  'common.loading': 'Loading…',
  'common.close': 'Close',
  'common.cancel': 'Cancel',
  'common.save': 'Save',
  'common.confirm': 'Confirm',
  'common.error': 'Error',
} as const satisfies Record<UiKey, string>

export const DICT = { vi, en } as const
export type Language = keyof typeof DICT
