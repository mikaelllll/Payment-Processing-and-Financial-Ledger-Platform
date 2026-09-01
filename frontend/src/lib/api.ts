import type { DashboardData, Role, SimulationResult } from '../types'

export const errorMessage = (detail: unknown, status: number): string => {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail.map(item => {
      if (!item || typeof item !== 'object') return String(item)
      const issue = item as { loc?: unknown[]; msg?: string }
      const field = issue.loc?.filter(part => part !== 'body').join('.')
      return `${field ? `${field}: ` : ''}${issue.msg ?? 'Invalid value'}`
    }).join('; ')
  }
  if (detail && typeof detail === 'object') {
    const issue = detail as { message?: string; msg?: string }
    return issue.message ?? issue.msg ?? `Request failed (${status})`
  }
  return `Request failed (${status})`
}

const request = async <T>(path: string, role: Role, options?: RequestInit): Promise<T> => {
  const response = await fetch(path, {
    ...options,
    headers: { 'Content-Type': 'application/json', 'X-Demo-Role': role, ...options?.headers },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: 'Unexpected request failure' }))
    throw new Error(errorMessage(body.detail, response.status))
  }
  return response.json() as Promise<T>
}

export const api = {
  dashboard: (role: Role) => request<DashboardData>('/api/dashboard', role),
  // Dataset generation belongs to the demo harness rather than the selected
  // read-only persona. The API still enforces that this call uses an authorized
  // operations role, while direct auditor/risk mutation requests remain forbidden.
  seed: (size: string, reset = false) => request<{ created: number }>('/api/demo/seed', 'operations_admin', { method: 'POST', body: JSON.stringify({ size, reset }) }),
  payment: (role: Role, payload: object) => request<SimulationResult>('/api/payments', role, { method: 'POST', body: JSON.stringify(payload) }),
  refund: (role: Role, paymentId: string, payload: object) => request<SimulationResult>(`/api/payments/${paymentId}/refund`, role, { method: 'POST', body: JSON.stringify(payload) }),
  ledger: (role: Role, paymentId: string) => request<{ entries: LedgerEntry[]; balanced: boolean }>(`/api/payments/${paymentId}/ledger`, role),
  workspace: (role: Role) => request<Record<string, unknown>>('/api/workspace', role),
  capture: (role: Role, paymentId: string, amount?: number) => request<Record<string, unknown>>(`/api/payments/${paymentId}/capture`, role, { method: 'POST', body: JSON.stringify({ action: 'capture', amount }) }),
  riskDecision: (role: Role, caseId: string, action: string, note: string) => request<Record<string, unknown>>(`/api/risk-cases/${caseId}/decision`, role, { method: 'POST', body: JSON.stringify({ action, note }) }),
  toggleFraudRule: (role: Role, id: string) => request<Record<string, unknown>>(`/api/fraud-rules/${id}/toggle`, role, { method: 'POST' }),
  createSettlement: (role: Role, amount: number) => request<Record<string, unknown>>('/api/settlements', role, { method: 'POST', body: JSON.stringify({ action: 'create', amount, idempotency_key: `settlement-${Date.now()}` }) }),
  settlementAction: (role: Role, id: string, action: string) => request<Record<string, unknown>>(`/api/settlements/${id}/action`, role, { method: 'POST', body: JSON.stringify({ action }) }),
  disputeAction: (role: Role, id: string, action: string, note: string) => request<Record<string, unknown>>(`/api/disputes/${id}/action`, role, { method: 'POST', body: JSON.stringify({ action, note }) }),
  createApiKey: (role: Role, name: string) => request<Record<string, unknown>>('/api/api-keys', role, { method: 'POST', body: JSON.stringify({ name, value: 'payments:read,payments:write' }) }),
  revokeApiKey: (role: Role, id: string) => request<Record<string, unknown>>(`/api/api-keys/${id}/revoke`, role, { method: 'POST' }),
  createWebhook: (role: Role, url: string) => request<Record<string, unknown>>('/api/webhooks', role, { method: 'POST', body: JSON.stringify({ name: 'Demo endpoint', value: url }) }),
  replayWebhook: (role: Role, id: string) => request<Record<string, unknown>>(`/api/webhook-deliveries/${id}/replay`, role, { method: 'POST' }),
  processorHealth: (role: Role, id: string, action: string) => request<Record<string, unknown>>(`/api/processors/${id}/health`, role, { method: 'POST', body: JSON.stringify({ action }) }),
  resolveReconciliation: (role: Role, id: string, note: string) => request<Record<string, unknown>>(`/api/reconciliation/${id}/resolve`, role, { method: 'POST', body: JSON.stringify({ action: 'resolve', note }) }),
}

export interface LedgerEntry { id: string; transaction_id: string; account: string; debit: number; credit: number; currency: string; description: string }
