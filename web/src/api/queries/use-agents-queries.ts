// Agents slice — the roster the team hub and the office roster both read.
import { useQuery } from '@tanstack/react-query'
import { api } from '../client'
import { queryKeys } from './query-keys'

export function useAgents() {
  return useQuery({
    queryKey: queryKeys.agents.list(),
    queryFn: () => api.getAgents(),
  })
}
