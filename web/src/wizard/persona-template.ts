// Deterministic SOUL.md generator for the create-agent wizard's Step 2 persona helper.
// NO LLM call — a plain string template from role + goals, editable by the operator
// before Create. Kept pure (no React) so it is trivially unit-testable.

export function generateSoulMarkdown(role: string, goals: string): string {
  const trimmedRole = role.trim()
  const trimmedGoals = goals.trim()
  const goalLines = trimmedGoals
    .split('\n')
    .map((g) => g.trim())
    .filter(Boolean)
    .map((g) => `- ${g}`)
    .join('\n')

  return [
    '# SOUL',
    '',
    `You are an agent acting as: ${trimmedRole || '(role not set)'}.`,
    '',
    '## Goals',
    goalLines || '- (no goals set)',
    '',
    '## Voice',
    '- Be concise and factual in reports.',
    '- Ask for approval before any external-facing action.',
  ].join('\n')
}
