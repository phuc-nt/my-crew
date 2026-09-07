// Query slice for the system hub's own reads.
import { useQuery } from '@tanstack/react-query'
import { api } from '../client'
import { queryKeys } from './query-keys'

/** Fleet-wide spend — the one budget number the backend serves for the whole team. */
export function useFleetBudget() {
  return useQuery({
    queryKey: queryKeys.system.budget(),
    queryFn: () => api.getFleetBudget(),
    staleTime: 60_000,
  })
}

/** Routing retro (sprint vs team, who decided, how sprints ended). */
export function useRouteStats() {
  return useQuery({
    queryKey: queryKeys.system.routeStats(),
    queryFn: () => api.getRouteStats(),
    staleTime: 60_000,
  })
}

/** Per-tool call health pooled over every agent's audit trail, last `days` days. */
export function useToolStats(days: number) {
  return useQuery({
    queryKey: queryKeys.system.toolStats(days),
    queryFn: () => api.getToolStats(days),
    staleTime: 60_000,
  })
}

/** Spend and volume per engine, last `days` days. */
export function useEngineCosts(days: number) {
  return useQuery({
    queryKey: queryKeys.system.engineCosts(days),
    queryFn: () => api.getEngineCosts(days),
    staleTime: 60_000,
  })
}

/** Coordinator heartbeat, polled — one query so every consumer sees the same beat. */
export function useCoordinatorHealth() {
  return useQuery({
    queryKey: queryKeys.system.coordinatorHealth(),
    queryFn: () => api.getCoordinatorHealth(),
    refetchInterval: 30_000,
    staleTime: 15_000,
    retry: false,
  })
}

export function useConnections() {
  return useQuery({
    queryKey: queryKeys.system.connections(),
    queryFn: () => api.getConnections(),
  })
}

export function useCompanyDocs() {
  return useQuery({
    queryKey: queryKeys.system.companyDocs(),
    queryFn: () => api.listCompanyDocs(),
  })
}

export function useCompany() {
  return useQuery({
    queryKey: queryKeys.team.company(),
    queryFn: () => api.getCompany(),
  })
}
