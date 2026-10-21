import { useQuery } from '@tanstack/react-query'
import { api, type Params } from './api'
import type { Page, Row, Schema, SiteInfo } from './types'

export const useSite = () =>
  useQuery({ queryKey: ['site'], queryFn: () => api<SiteInfo>('/site'), retry: false, staleTime: 60_000 })

export const useSchema = (resource: string) =>
  useQuery({ queryKey: ['schema', resource], queryFn: () => api<Schema>(`/${resource}/schema`), staleTime: 5 * 60_000 })

export const useList = (resource: string, params: Params) =>
  useQuery({ queryKey: ['list', resource, params], queryFn: () => api<Page>(`/${resource}`, { params }), placeholderData: (p) => p })

export const useRecord = (resource: string, pk: string | undefined) =>
  useQuery({ queryKey: ['record', resource, pk], queryFn: () => api<Row>(`/${resource}/${pk}`), enabled: pk !== undefined })
