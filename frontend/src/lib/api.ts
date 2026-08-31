import type { DashboardData, Role, SimulationResult } from '../types'

const request = async <T>(path: string, role: Role, options?: RequestInit): Promise<T> => {
  const response = await fetch(path, {
    ...options,
    headers: { 'Content-Type': 'application/json', 'X-Demo-Role': role, ...options?.headers },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: 'Unexpected request failure' }))
    throw new Error(body.detail ?? `Request failed (${response.status})`)
  }
  return response.json() as Promise<T>
}

export const api = {
  dashboard: (role: Role) => request<DashboardData>('/api/dashboard', role),
  seed: (role: Role, size: string, reset = false) => request<{ created: number }>('/api/demo/seed', role, { method: 'POST', body: JSON.stringify({ size, reset }) }),
  payment: (role: Role, payload: object) => request<SimulationResult>('/api/payments', role, { method: 'POST', body: JSON.stringify(payload) }),
  refund: (role: Role, paymentId: string, payload: object) => request<SimulationResult>(`/api/payments/${paymentId}/refund`, role, { method: 'POST', body: JSON.stringify(payload) }),
  ledger: (role: Role, paymentId: string) => request<{ entries: LedgerEntry[]; balanced: boolean }>(`/api/payments/${paymentId}/ledger`, role),
}

export interface LedgerEntry { id: string; transaction_id: string; account: string; debit: number; credit: number; currency: string; description: string }

