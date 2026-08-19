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
