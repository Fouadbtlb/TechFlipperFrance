import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from './api';
import type { Category, DealCard, DealDetail, Page, Pin, Teaser } from './types';

export type Sort = 'profit' | 'distance' | 'recent';

export function useFeed(sort: Sort, category: Category | null) {
  return useInfiniteQuery({
    queryKey: ['feed', sort, category],
    initialPageParam: 0,
    queryFn: ({ pageParam }) => {
      const q = new URLSearchParams({ sort, limit: '30', offset: String(pageParam) });
      if (category) q.set('category', category);
      return api<Page<DealCard>>(`/v1/deals?${q}`);
    },
    getNextPageParam: (last) => last.next_offset ?? undefined,
  });
}

export function usePins() {
  return useQuery({ queryKey: ['pins'], queryFn: () => api<{ items: Pin[] }>('/v1/deals/map') });
}

export function useDeal(uid: string) {
  return useQuery({
    queryKey: ['deal', uid],
    queryFn: () => api<DealDetail>(`/v1/deals/${encodeURIComponent(uid)}`),
  });
}

export function useSaved() {
  return useQuery({ queryKey: ['saved'], queryFn: () => api<{ items: DealCard[] }>('/v1/saved') });
}

export function useTeaser() {
  return useQuery({ queryKey: ['teaser'], queryFn: () => api<Teaser>('/v1/teaser') });
}

function invalidateLists(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: ['feed'] });
  qc.invalidateQueries({ queryKey: ['pins'] });
  qc.invalidateQueries({ queryKey: ['saved'] });
}

export function useToggleSave(uid: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (save: boolean) =>
      api(`/v1/saved/${encodeURIComponent(uid)}`, { method: save ? 'PUT' : 'DELETE' }),
    onMutate: (save) => {
      qc.setQueryData<DealDetail>(['deal', uid], (d) => (d ? { ...d, saved: save } : d));
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ['saved'] }),
  });
}

export function useHide(uid: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (reason: 'not_interested' | 'sold') =>
      api(`/v1/hidden/${encodeURIComponent(uid)}`, { method: 'POST', body: JSON.stringify({ reason }) }),
    onSuccess: () => invalidateLists(qc),
  });
}

export function useInvalidateDeals() {
  const qc = useQueryClient();
  return () => invalidateLists(qc);
}
