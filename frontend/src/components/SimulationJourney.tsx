import { useEffect, useState } from 'react'
import { AlertTriangle, Check, Clock3, Info, RotateCcw, X } from 'lucide-react'
import type { SimulationResult } from '../types'

const icons = { success: Check, warning: AlertTriangle, error: X, info: Info }

export function SimulationJourney({ result, onClose, onReplay }: { result: SimulationResult; onClose: () => void; onReplay?: () => void }) {
  const [visible, setVisible] = useState(0)
  useEffect(() => {
    setVisible(0)
    const timers = result.steps.map((_, index) => window.setTimeout(() => setVisible(index + 1), index * 520 + 250))
    return () => timers.forEach(clearTimeout)
  }, [result])

  const finished = visible >= result.steps.length
  return <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Payment safety journey">
    <section className="journey-panel">
      <header className="journey-header">
        <div><span className="eyebrow">Execution trace · {result.run_id}</span><h2>Payment safety journey</h2><p>Every critical decision is exposed as the request moves across trust boundaries.</p></div>
        <button className="icon-button" onClick={onClose} aria-label="Close simulation"><X /></button>
      </header>
      <div className="journey-summary">
        <div><span>Payment</span><strong>{result.payment.id}</strong></div>
        <div><span>Current state</span><strong className={`status ${result.payment.status}`}>{result.payment.status.replaceAll('_', ' ')}</strong></div>
        <div><span>Processor</span><strong>{result.payment.processor}</strong></div>
        <div><span>Mode</span><strong>{result.replayed ? 'Safe replay' : 'New execution'}</strong></div>
      </div>
      <div className="journey-list">
        {result.steps.map((item, index) => {
          const Icon = icons[item.status]
          const shown = index < visible
          return <article className={`journey-step ${shown ? 'shown' : ''} ${item.status}`} key={`${item.key}-${index}`}>
            <div className="step-marker">{shown ? <Icon size={17} /> : <Clock3 size={16} />}</div>
            <div><div className="step-heading"><strong>{item.title}</strong><span>{item.duration_ms} ms</span></div><p>{item.detail}</p>{item.evidence && <code>{item.evidence}</code>}</div>
          </article>
        })}
      </div>
      <footer className="journey-footer">
        <span>{finished ? `Completed with state: ${result.payment.status}` : 'Processing trace…'}</span>
        <div>{onReplay && finished && <button className="button secondary" onClick={onReplay}><RotateCcw size={16} />Replay same idempotency key</button>}<button className="button primary" onClick={onClose} disabled={!finished}>Done</button></div>
      </footer>
    </section>
  </div>
}

