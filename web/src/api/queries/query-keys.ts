// Query key factory, grouped by domain.
//
// Keys are built here and nowhere else so the SSE→invalidate bridge can name the
// same slice a component subscribed to. An inline key literal in a component would
// be invisible to the bridge and would silently stop updating on live events.
export const queryKeys = {
  agents: {
    all: ['agents'] as const,
    list: () => [...queryKeys.agents.all, 'list'] as const,
    status: (agentId: string) => [...queryKeys.agents.all, 'status', agentId] as const,
  },
  approvals: {
    all: ['approvals'] as const,
    /** Fleet-wide flat index — the queue shown in both the chat pane and the work hub. */
    pending: () => [...queryKeys.approvals.all, 'pending'] as const,
    /** Today's auto-delivered runs — what the trust ladder ran without asking. */
    autoApproved: () => [...queryKeys.approvals.all, 'auto-approved'] as const,
  },
  office: {
    all: ['office'] as const,
    workrooms: () => [...queryKeys.office.all, 'workrooms'] as const,
    room: (roomId: string) => [...queryKeys.office.all, 'room', roomId] as const,
  },
  artifacts: {
    all: ['artifacts'] as const,
    /** Every task+step in one room — the drawer's index. */
    room: (roomId: string) => [...queryKeys.artifacts.all, 'room', roomId] as const,
    /** One step's produced text. 404s for a step that produced none (e.g. a review). */
    step: (taskId: string, seq: number) =>
      [...queryKeys.artifacts.all, 'step', taskId, seq] as const,
    /** The recorder's raw event log for one step — the 🔬 view. */
    transcript: (taskId: string, seq: number) =>
      [...queryKeys.artifacts.all, 'transcript', taskId, seq] as const,
  },
  tasks: {
    all: ['tasks'] as const,
    board: () => [...queryKeys.tasks.all, 'board'] as const,
    detail: (taskId: string) => [...queryKeys.tasks.all, 'detail', taskId] as const,
  },
  outputs: {
    all: ['outputs'] as const,
    list: () => [...queryKeys.outputs.all, 'list'] as const,
  },
  schedule: {
    all: ['schedule'] as const,
    upcoming: () => [...queryKeys.schedule.all, 'upcoming'] as const,
  },
  team: {
    all: ['team'] as const,
    company: () => [...queryKeys.team.all, 'company'] as const,
    alerts: () => [...queryKeys.team.all, 'alerts'] as const,
    templates: () => [...queryKeys.team.all, 'templates'] as const,
    templateStatus: () => [...queryKeys.team.all, 'template-status'] as const,
    crews: () => [...queryKeys.team.all, 'crews'] as const,
    crewPreview: (crewId: string) => [...queryKeys.team.all, 'crew-preview', crewId] as const,
    unregistered: () => [...queryKeys.team.all, 'unregistered'] as const,
  },
  clarify: {
    all: ['clarify'] as const,
    pending: () => [...queryKeys.clarify.all, 'pending'] as const,
  },
} as const
