// Office slice — the workroom list that backs the chat conversation list.
import { useQuery } from '@tanstack/react-query'
import { api } from '../client'
import { queryKeys } from './query-keys'

export function useWorkrooms() {
  return useQuery({
    queryKey: queryKeys.office.workrooms(),
    queryFn: () => api.getWorkrooms(),
  })
}
