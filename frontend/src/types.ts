export type Role = 'merchant_owner' | 'merchant_developer' | 'operations_admin' | 'risk_analyst' | 'auditor'

export interface Payment {
  id: string
  merchant_id: string
  amount: number
  currency: string
  status: string
  processor: string
  captured_amount: number
  refunded_amount: number
  customer_reference: string
  created_at: string
}

export interface SimulationStep {
  key: string
  title: string
  detail: string
  status: 'success' | 'warning' | 'error' | 'info'
  duration_ms: number
  evidence?: string
}

export interface SimulationResult {
  run_id: string
  payment: Payment
  replayed: boolean
  steps: SimulationStep[]
}

export interface DashboardData {
  metrics: { payments: number; captured: number; failed: number; volume: number; ledger_balanced: boolean; ledger_debits: number; ledger_credits: number }
  payments: Payment[]
  role: Role
}

