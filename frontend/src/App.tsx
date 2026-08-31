import { useCallback, useEffect, useMemo, useState } from 'react'
import { Activity, ArrowDownRight, ArrowUpRight, BookOpen, Boxes, CheckCircle2, Database, Landmark, LayoutDashboard, Menu, RefreshCw, Shield, Sparkles, TerminalSquare, Users, WalletCards, X } from 'lucide-react'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip as ChartTooltip, XAxis, YAxis } from 'recharts'
import { api } from './lib/api'
import type { DashboardData, Payment, Role } from './types'
import { LedgerDrawer } from './components/LedgerDrawer'
import { PaymentLab } from './components/PaymentLab'
import { Tooltip } from './components/Tooltip'

const roles: { value: Role; label: string; short: string }[] = [
  { value: 'merchant_owner', label: 'Merchant owner', short: 'Business, payments and settlements' },
  { value: 'merchant_developer', label: 'Merchant developer', short: 'API behavior and delivery diagnostics' },
  { value: 'operations_admin', label: 'Operations administrator', short: 'Global health and recovery queues' },
  { value: 'risk_analyst', label: 'Risk analyst', short: 'Reviews, signals and disputes' },
  { value: 'auditor', label: 'Read-only auditor', short: 'Ledger proof and immutable history' },
]

const currency = (amount: number) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'BRL' }).format(amount / 100)
const compact = (value: number) => new Intl.NumberFormat('en', { notation: 'compact' }).format(value)

function App() {
  const [role, setRole] = useState<Role>('merchant_owner')
  const [data, setData] = useState<DashboardData | null>(null)
  const [selectedPayment, setSelectedPayment] = useState<Payment | null>(null)
  const [seedOpen, setSeedOpen] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const [loading, setLoading] = useState(true)
  const [notice, setNotice] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    try { setData(await api.dashboard(role)) } finally { setLoading(false) }
  }, [role])
  useEffect(() => { void load() }, [load])

  const chartData = useMemo(() => {
    if (!data) return []
    const buckets = Array.from({ length: 10 }, (_, index) => ({ name: `${9 - index}d`, volume: 0, payments: 0 })).reverse()
    data.payments.forEach((payment, index) => { const target = buckets[index % buckets.length]; target.volume += payment.captured_amount / 100; target.payments += 1 })
    return buckets
  }, [data])

  const seed = async (size: string, reset = false) => {
    try {
      const result = await api.seed(role, size, reset)
      setNotice(`${result.created} deterministic records added. Every financial posting remains balanced.`)
      setSeedOpen(false); await load()
    } catch (error) { setNotice(error instanceof Error ? error.message : 'Could not generate data') }
  }

  const currentRole = roles.find(item => item.value === role)!
  const metrics = data?.metrics
  return <div className="app-shell">
    <aside className={`sidebar ${menuOpen ? 'open' : ''}`}>
      <div className="brand"><div className="brand-mark"><Landmark size={21}/></div><div><strong>LedgerFlow</strong><span>Payment infrastructure</span></div><button className="mobile-close" onClick={() => setMenuOpen(false)}><X/></button></div>
      <nav>
        <a className="active" href="#overview"><LayoutDashboard/>Overview</a>
        <a href="#simulation"><Activity/>Failure laboratory</a>
        <a href="#payments"><WalletCards/>Payments</a>
        <a href="#architecture"><Boxes/>Architecture</a>
      </nav>
      <div className="sidebar-section"><span>System status</span><div className="system-row"><i className="health-dot"/><div><strong>All services healthy</strong><small>PostgreSQL · Redis · workers</small></div></div><div className="system-row"><CheckCircle2/><div><strong>Ledger invariant</strong><small>Debits equal credits</small></div></div></div>
      <div className="sidebar-footer"><a href="/api/docs" target="_blank"><BookOpen/>API documentation</a><a href="https://github.com/mikaelllll/Payment-Processing-and-Financial-Ledger-Platform-example" target="_blank"><TerminalSquare/>Source repository</a></div>
    </aside>
    <main>
      <header className="topbar"><button className="menu-button" onClick={() => setMenuOpen(true)}><Menu/></button><div><span className="breadcrumb">Northstar Outdoor / Production simulation</span></div><div className="top-actions"><button className="button secondary" onClick={() => setSeedOpen(true)}><Database size={16}/>Generate demo data</button><div className="role-select"><Users size={17}/><select value={role} onChange={event => setRole(event.target.value as Role)} aria-label="View as role">{roles.map(item => <option value={item.value} key={item.value}>{item.label}</option>)}</select></div><div className="avatar">{currentRole.label.split(' ').map(word => word[0]).join('').slice(0, 2)}</div></div></header>
      <div className="content">
        {notice && <div className="notice"><CheckCircle2 size={17}/>{notice}<button onClick={() => setNotice('')}><X size={15}/></button></div>}
        <section className="hero" id="overview"><div><span className="eyebrow">Viewing as {currentRole.label}</span><h1>Money movement you can prove.</h1><p>{currentRole.short}. Explore how LedgerFlow keeps payments correct across retries, processor failures and concurrent operations.</p></div><div className="hero-proof"><Shield/><div><strong>Financial integrity live</strong><span>{metrics?.ledger_balanced ? 'All ledger transactions balance' : 'Checking ledger invariant…'}</span></div></div></section>
        <section className="metrics-grid">
          <article><div className="metric-label">Captured volume <Tooltip text="Sum of captured minor units. Authorizations are excluded because reserved money is not yet merchant revenue."/></div><strong>{metrics ? currency(metrics.volume) : '—'}</strong><span className="trend up"><ArrowUpRight/>Simulated lifetime</span></article>
          <article><div className="metric-label">Payment attempts <Tooltip text="Every distinct idempotent operation. Safe replays do not create additional payments."/></div><strong>{metrics ? compact(metrics.payments) : '—'}</strong><span>{metrics?.captured ?? 0} captured</span></article>
          <article><div className="metric-label">Definitive failures <Tooltip text="Failures where the processor outcome is known. Ambiguous responses enter recovery instead of being mislabeled as failed."/></div><strong>{metrics?.failed ?? '—'}</strong><span className="trend down"><ArrowDownRight/>No balance movement</span></article>
          <article><div className="metric-label">Ledger proof <Tooltip text="A global invariant check comparing every debit with every credit across immutable journal entries."/></div><strong className="proof-value">{metrics?.ledger_balanced ? 'Balanced' : 'Checking'}</strong><span>{metrics ? `${currency(metrics.ledger_debits)} each side` : 'Loading journal'}</span></article>
        </section>
        <section className="dashboard-grid">
          <article className="chart-card"><header><div><span className="eyebrow">Captured volume</span><h2>Payment activity</h2></div><button className="icon-button" onClick={load} aria-label="Refresh"><RefreshCw size={17}/></button></header><div className="chart"><ResponsiveContainer width="100%" height="100%"><AreaChart data={chartData}><defs><linearGradient id="volume" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#5ce1c5" stopOpacity={.36}/><stop offset="100%" stopColor="#5ce1c5" stopOpacity={0}/></linearGradient></defs><CartesianGrid stroke="#253147" vertical={false}/><XAxis dataKey="name" stroke="#6f7f99" axisLine={false} tickLine={false}/><YAxis stroke="#6f7f99" axisLine={false} tickLine={false}/><ChartTooltip contentStyle={{background:'#111a2b',border:'1px solid #2d3a52',borderRadius:10}}/><Area type="monotone" dataKey="volume" stroke="#5ce1c5" fill="url(#volume)" strokeWidth={2}/></AreaChart></ResponsiveContainer></div></article>
          <article className="role-card"><span className="eyebrow">Access perspective</span><h2>{currentRole.label}</h2><p>{currentRole.short}</p><div className="role-list">{roles.map(item => <button className={role === item.value ? 'selected' : ''} onClick={() => setRole(item.value)} key={item.value}><span>{item.label}</span><small>{item.short}</small></button>)}</div></article>
        </section>
        <div id="simulation"><PaymentLab role={role} onComplete={load}/></div>
        <section className="table-card" id="payments"><header><div><span className="eyebrow">Operational record</span><h2>Recent payments</h2></div><span>{data?.payments.length ?? 0} visible records</span></header><div className="payments-table"><div className="payment-row header"><span>Payment</span><span>Customer</span><span>Processor</span><span>Status</span><span>Amount</span><span/></div>{data?.payments.map(payment => <div className="payment-row" key={payment.id}><span><strong>{payment.id}</strong><small>{new Date(payment.created_at).toLocaleString()}</small></span><span>{payment.customer_reference}</span><span>{payment.processor.replace('_', ' ')}</span><span><i className={`status ${payment.status}`}>{payment.status.replaceAll('_', ' ')}</i></span><span><strong>{currency(payment.amount)}</strong><small>{payment.currency}</small></span><span><button onClick={() => setSelectedPayment(payment)}>View ledger</button></span></div>)}</div>{!loading && !data?.payments.length && <div className="empty-state">Generate deterministic demo data or run a payment scenario.</div>}</section>
        <section className="architecture-card" id="architecture"><div><span className="eyebrow">System boundaries</span><h2>Built for correctness under failure</h2><p>The platform keeps orchestration, accounting, external processor behavior and asynchronous delivery explicit. Service boundaries follow different consistency requirements—not visual complexity.</p></div><div className="architecture-flow"><div><Sparkles/><strong>Merchant API</strong><span>Validation + idempotency</span></div><b>→</b><div><Shield/><strong>Orchestrator</strong><span>Risk + routing + recovery</span></div><b>→</b><div><Landmark/><strong>Ledger</strong><span>Immutable balanced journal</span></div></div></section>
      </div>
    </main>
    {selectedPayment && <LedgerDrawer payment={selectedPayment} role={role} onClose={() => setSelectedPayment(null)}/>} 
    {seedOpen && <div className="modal-backdrop"><section className="seed-dialog"><header><div><span className="eyebrow">Deterministic dataset</span><h2>Populate the payment platform</h2></div><button className="icon-button" onClick={() => setSeedOpen(false)}><X/></button></header><p>Create consistent payments, refunds and balanced ledger entries for exploring every dashboard perspective.</p><div className="seed-options"><button onClick={() => seed('small')}><strong>Small</strong><span>12 payment records</span></button><button onClick={() => seed('medium')}><strong>Medium</strong><span>60 payment records</span></button><button onClick={() => seed('large')}><strong>Large</strong><span>250 payment records</span></button></div><button className="button danger" onClick={() => seed('medium', true)}>Reset and generate medium dataset</button></section></div>}
  </div>
}

export default App

