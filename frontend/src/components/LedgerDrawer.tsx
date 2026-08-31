import { useEffect, useState } from 'react'
import { CheckCircle2, X } from 'lucide-react'
import { api, type LedgerEntry } from '../lib/api'
import type { Payment, Role } from '../types'

const money = (value: number, currency: string) => new Intl.NumberFormat('en', { style: 'currency', currency }).format(value / 100)

export function LedgerDrawer({ payment, role, onClose }: { payment: Payment; role: Role; onClose: () => void }) {
  const [entries, setEntries] = useState<LedgerEntry[]>([])
  const [balanced, setBalanced] = useState(false)
  useEffect(() => { api.ledger(role, payment.id).then(data => { setEntries(data.entries); setBalanced(data.balanced) }) }, [payment.id, role])
  return <div className="modal-backdrop"><section className="drawer">
    <header><div><span className="eyebrow">Immutable accounting evidence</span><h2>{payment.id}</h2></div><button className="icon-button" onClick={onClose}><X/></button></header>
    <div className={`balance-proof ${balanced ? 'ok' : ''}`}><CheckCircle2/><div><strong>{balanced ? 'Ledger is balanced' : 'Balance check pending'}</strong><span>Every transaction must have equal debit and credit totals.</span></div></div>
    <div className="ledger-table"><div className="ledger-row header"><span>Account</span><span>Debit</span><span>Credit</span></div>{entries.map(entry => <div className="ledger-row" key={entry.id}><span><strong>{entry.account.replaceAll('_', ' ')}</strong><small>{entry.description}<br/>{entry.transaction_id}</small></span><span>{entry.debit ? money(entry.debit, entry.currency) : '—'}</span><span>{entry.credit ? money(entry.credit, entry.currency) : '—'}</span></div>)}</div>
    {!entries.length && <div className="empty-state">No financial posting exists for this payment state.</div>}
  </section></div>
}

