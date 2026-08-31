import { useMemo, useState } from 'react'
import { Play, ShieldCheck } from 'lucide-react'
import { api } from '../lib/api'
import type { Role, SimulationResult } from '../types'
import { SimulationJourney } from './SimulationJourney'
import { Tooltip } from './Tooltip'

const scenarios = [
  { value: 'success', label: 'Successful capture', detail: 'Definitive approval, balanced posting and webhook outbox.' },
  { value: 'ambiguous', label: 'Ambiguous timeout', detail: 'Processor succeeds but response is lost; recovery prevents a duplicate charge.' },
  { value: 'declined', label: 'Definitive decline', detail: 'No financial posting occurs after an explicit processor rejection.' },
  { value: 'timeout_before', label: 'Pre-submission failure', detail: 'Safe retry classification because the request never reached the processor.' },
  { value: 'high_risk', label: 'High-risk review', detail: 'Authorization succeeds while capture remains blocked for manual review.' },
]

export function PaymentLab({ role, onComplete }: { role: Role; onComplete: () => void }) {
  const [scenario, setScenario] = useState('success')
  const [amount, setAmount] = useState(14990)
  const [key, setKey] = useState(() => `order-${Date.now()}`)
  const [result, setResult] = useState<SimulationResult | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const selected = useMemo(() => scenarios.find(item => item.value === scenario)!, [scenario])

  const run = async () => {
    setLoading(true); setError('')
    try {
      const response = await api.payment(role, { merchant_id: 'mer_demo', amount, currency: 'BRL', customer_reference: 'customer-live-demo', idempotency_key: key, scenario, capture_method: 'automatic' })
      setResult(response); onComplete()
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Simulation failed') }
    finally { setLoading(false) }
  }

  return <>
    <section className="lab-card">
      <div className="lab-intro"><div className="lab-icon"><ShieldCheck /></div><div><span className="eyebrow">Interactive failure laboratory</span><h2>Follow money through every safety boundary</h2><p>Choose an outcome that normally remains hidden in logs. LedgerFlow exposes validation, idempotency, risk, routing, provider ambiguity, accounting and event delivery.</p></div></div>
      <div className="scenario-grid">
        {scenarios.map(item => <button key={item.value} onClick={() => { setScenario(item.value); setKey(`order-${Date.now()}`) }} className={`scenario ${scenario === item.value ? 'selected' : ''}`}><span className="radio"/><strong>{item.label}</strong><small>{item.detail}</small></button>)}
      </div>
      <div className="lab-controls">
        <label><span>Amount (centavos) <Tooltip text="Money is always represented as integer minor units. R$149.90 is sent as 14990, avoiding floating-point errors." /></span><input type="number" min="100" value={amount} onChange={event => setAmount(Number(event.target.value))}/></label>
        <label><span>Idempotency key <Tooltip text="A stable business-operation key ensures retries return the original result instead of creating another charge." /></span><input value={key} onChange={event => setKey(event.target.value)}/></label>
        <div className="selected-scenario"><span>Expected behavior</span><strong>{selected.label}</strong><small>{selected.detail}</small></div>
        <button className="button primary run-button" onClick={run} disabled={loading || role === 'auditor' || role === 'risk_analyst'}><Play size={17}/>{loading ? 'Starting…' : 'Run payment'}</button>
      </div>
      {error && <div className="error-banner">{error}</div>}
      {(role === 'auditor' || role === 'risk_analyst') && <div className="permission-note">This role is intentionally read-only for payment creation. Switch to Merchant owner, Merchant developer, or Operations administrator to run a payment.</div>}
    </section>
    {result && <SimulationJourney result={result} onClose={() => setResult(null)} onReplay={scenario === 'success' ? run : undefined}/>} 
  </>
}

