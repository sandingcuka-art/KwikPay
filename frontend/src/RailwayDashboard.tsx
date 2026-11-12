import { useEffect, useState } from 'react'
import { ArrowRight, BarChart3, History, Settings2, ShieldCheck, Store, QrCode, Download } from 'lucide-react'
import MerchantTerminal from './MerchantTerminal'
import AndroidDownloads from './AndroidDownloads'

type Pot = { label: string; walletAddress: string; percentage: number }
type Settings = { version: number; pots: Pot[] }
type Observation = { sent: string; received: string; observedAt: string }
type Incoming = { id: string; completed: boolean; received: string; observedAt: string }
type Sale = { executionId: string; createdAt: string; status: string; requestStatus: string; amount: string; legs: { legId: string; label: string; planned: string; walletAddress: string; status: string; walletStatus: string; openPayments: Observation | null; incomingPayment: Incoming | null; manuallyVerifiedAt: string | null }[] }
type Overview = { history: Sale[]; summary: { recordCount: number; observedSent: string; observedReceived: string; observedByPot: { label: string; value: string }[] } }
type Page = 'terminal' | 'pots' | 'history' | 'reports' | 'apps'

const money = (value: string) => `R${(BigInt(value) / 100n).toString()}.${(BigInt(value) % 100n).toString().padStart(2, '0')}`
const status = (sale: Sale) => sale.requestStatus === 'EXPIRED' ? 'Request expired' : sale.status === 'FAILED' || sale.status === 'PARTIAL' || sale.requestStatus === 'PREPARATION_FAILED' ? 'Needs attention' : sale.requestStatus === 'AWAITING_CONSENT' ? 'Approval not recorded' : sale.legs.length > 0 && sale.legs.every(leg => leg.manuallyVerifiedAt) ? 'Manually verified by merchant' : sale.legs.length === 2 && sale.legs.every(leg => leg.status !== 'FAILED' && leg.incomingPayment?.completed && leg.incomingPayment.received === leg.planned) ? 'Incoming payments completed' : sale.requestStatus === 'PROCESSING' ? 'Wallet settlement unverified' : 'Checking payment details'

async function read<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { ...init, credentials: 'same-origin' })
  if (response.status === 401 || response.status === 403) throw new Error('Dashboard access was denied. Sign in and try again.')
  const body = await response.json()
  if (!response.ok) throw new Error(body.detail || 'The request could not be completed.')
  return body as T
}

export default function RailwayDashboard() {
  const [page, setPage] = useState<Page>('pots')
  const [settings, setSettings] = useState<Settings | null>(null)
  const [overview, setOverview] = useState<Overview | null>(null)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [refresh, setRefresh] = useState(0)
  const [verifying, setVerifying] = useState('')
  const [refreshError, setRefreshError] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true); setError('')
    if (page === 'terminal' || page === 'apps') { setLoading(false); return () => controller.abort() }
    if (page === 'pots') {
      read<Settings>('/api/dashboard/config', { signal: controller.signal }).then(setSettings).catch(e => { if (!controller.signal.aborted) setError(e.message) }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    } else {
      read<Overview>('/api/dashboard/sales-overview', { signal: controller.signal }).then(setOverview).catch(e => { if (!controller.signal.aborted) setError(e.message) }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    }
    return () => controller.abort()
  }, [page, refresh])

  useEffect(() => {
    if (page !== 'history' && page !== 'reports') return
    const controller = new AbortController()
    const timer = window.setInterval(() => {
      read<Overview>('/api/dashboard/sales-overview', { signal: controller.signal })
        .then(data => { if (!controller.signal.aborted) { setOverview(data); setRefreshError('') } })
        .catch(() => { if (!controller.signal.aborted) setRefreshError('Automatic refresh failed. Check your connection; the displayed results may be out of date.') })
    }, 15000)
    return () => { controller.abort(); window.clearInterval(timer) }
  }, [page])

  const edit = (index: number, changes: Partial<Pot>) => setSettings(current => current && ({ ...current, pots: current.pots.map((pot, i) => i === index ? { ...pot, ...changes } : pot) }))
  const save = async () => {
    if (!settings) return
    if (settings.pots.some(p => !p.label.trim() || !Number.isInteger(p.percentage) || p.percentage < 1 || p.percentage > 99) || settings.pots.reduce((sum, p) => sum + p.percentage, 0) !== 100) {
      setError('Give each pot a name and a whole percentage from 1 to 99. Percentages must total 100%.'); return
    }
    setSaving(true); setError(''); setMessage('')
    try {
      const updated = await read<Settings>('/api/dashboard/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(settings) })
      setSettings(updated); setMessage('Split saved. New mobile requests will use these settings.')
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not save the split.') }
    finally { setSaving(false) }
  }
  const navigate = (next: Page) => { setPage(next); setMessage(''); setError(''); setRefreshError('') }
  const verifyLeg = async (sale: Sale, leg: Sale['legs'][number]) => {
    const verified = !leg.manuallyVerifiedAt
    const prompt = verified
      ? `Have you checked that ${money(leg.planned)} to ${leg.walletAddress} is COMPLETED in the Test Wallet?\n\nThis records your manual confirmation. KwikPay has not automatically verified the wallet.`
      : `Remove your manual confirmation for ${leg.label}? This does not change the payment.`
    if (!window.confirm(prompt)) return
    setVerifying(leg.legId); setError(''); setMessage('')
    try {
      await read(`/api/dashboard/sales/${sale.executionId}/manual-verification`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ legId: leg.legId, verified }) })
      setMessage(verified ? 'Manual wallet confirmation saved.' : 'Manual confirmation removed.')
      setRefresh(n => n + 1)
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not save the confirmation.') }
    finally { setVerifying('') }
  }
  const title = page === 'apps' ? 'Android apps' : page === 'terminal' ? 'New sale' : page === 'pots' ? 'Pots & split' : page === 'history' ? 'Sales history' : 'Reports'

  return <div className="app-shell hosted-dashboard">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark">K</div><div><strong>KwikPay</strong><span>merchant</span></div></div>
      <div className="merchant-card"><div className="avatar"><Store size={20}/></div><div><strong>Demo shop</strong><span>Test Wallet</span></div></div>
      <nav aria-label="Main navigation">
        <button className={`nav-btn ${page === 'terminal' ? 'active' : ''}`} onClick={() => navigate('terminal')}><QrCode size={19}/> New sale</button>
        <button className={`nav-btn ${page === 'pots' ? 'active' : ''}`} onClick={() => navigate('pots')}><Settings2 size={19}/> Pots & split</button>
        <button className={`nav-btn ${page === 'history' ? 'active' : ''}`} onClick={() => navigate('history')}><History size={19}/> Sales</button>
        <button className={`nav-btn ${page === 'reports' ? 'active' : ''}`} onClick={() => navigate('reports')}><BarChart3 size={19}/> Reports</button>
        <button className={`nav-btn ${page === 'apps' ? 'active' : ''}`} onClick={() => navigate('apps')}><Download size={19}/> Apps</button>
      </nav><div className="sidebar-foot">Test Wallet trial<br/><small>Dashboard: up to R10</small></div>
    </aside>
    <main className="main"><header className="topbar"><div><span className="eyebrow">KWIKPAY MERCHANT</span><h1>{title}</h1></div><div className="status-pill"><ShieldCheck size={16}/> Test Wallet</div></header>
      <section className="page narrow" hidden={page !== 'terminal'}><div className="panel form-panel"><MerchantTerminal /></div></section>
      {page === 'apps' && <section className="page narrow"><div className="panel form-panel"><AndroidDownloads /></div></section>}
      {page !== 'terminal' && page !== 'apps' && <section className="page narrow"><div className="panel form-panel">
        {loading && <p role="status">Loading {page === 'pots' ? 'split settings' : 'payment records'}…</p>}
        {error && <div className="error" role="alert">{error} <button className="text-button" onClick={() => setRefresh(n => n + 1)}>Refresh</button></div>}
        {message && <div className="saved-status" role="status">{message}</div>}
        {refreshError && <div className="error" role="alert">{refreshError}</div>}
        {!loading && page === 'pots' && settings && <>
          <h2>Where should each sale go?</h2><p className="lede">These settings are stored by the API. The merchant app loads them, and each new request keeps its own split.</p>
          {settings.pots.map((pot, i) => <fieldset className="pot-fields" key={i}><legend>Pot {i + 1}</legend>
            <label htmlFor={`pot-name-${i}`}>Pot name</label><input id={`pot-name-${i}`} maxLength={60} value={pot.label} onChange={e => edit(i, { label: e.target.value })}/>
            <label htmlFor={`pot-wallet-${i}`}>Test Wallet address</label><input id={`pot-wallet-${i}`} type="url" value={pot.walletAddress} onChange={e => edit(i, { walletAddress: e.target.value })}/>
            <div className="quick-fill"><span>Test addresses</span>{[1, 2, 3].map(n => <button type="button" key={n} onClick={() => edit(i, { walletAddress: `https://ilp.interledger-test.dev/kwikpay-merch-${n}` })}>Merchant {n}</button>)}</div>
            <label htmlFor={`pot-percent-${i}`}>Percentage</label><input id={`pot-percent-${i}`} type="number" min="1" max="99" step="1" value={Number.isNaN(pot.percentage) ? '' : pot.percentage} onChange={e => edit(i, { percentage: e.target.value === '' ? NaN : Number(e.target.value) })}/>
          </fieldset>)}
          <p className="payment-notice">Use two Test Wallet addresses and whole percentages totalling 100%. Addresses may share the same underlying balance. Dashboard sales are limited to R10 during this trial.</p>
          <button className="primary full" disabled={saving} onClick={save}>{saving ? 'Saving…' : 'Save pots & split'} <ArrowRight size={18}/></button>
        </>}
        {!loading && !error && page !== 'pots' && overview && <>
          <div className="overview-head"><div><h2>{title}</h2></div><button className="ghost" onClick={() => setRefresh(n => n + 1)}>Refresh</button></div>
          {page === 'history' ? <>
            <p className="lede">Mobile Test Wallet requests, newest first. Results refresh automatically every 15 seconds.</p>
            {overview.history.length === 0 ? <p className="empty-state">No mobile payment records yet.</p> : <div className="history-list">{overview.history.map(sale => <article className="history-item" key={sale.executionId}>
              <span className="history-line"><strong>{money(sale.amount)}</strong><span className="history-status">{status(sale)}</span></span>
              <span className="history-meta">{new Date(sale.createdAt).toLocaleString('en-ZA', { dateStyle: 'medium', timeStyle: 'short' })} · Test Wallet</span>
              <div className="history-legs">{sale.legs.map(leg => <div key={leg.legId} className="manual-verification-leg"><span><strong>{leg.label}</strong> · planned {money(leg.planned)}{leg.openPayments ? ` · Open Payments: ${money(leg.openPayments.sent)} sent, ${money(leg.openPayments.received)} received` : ' · amounts not yet observed'}{leg.incomingPayment && <><br/>Incoming payment {leg.incomingPayment.completed ? 'completed' : 'pending'} · ID <code title={leg.incomingPayment.id}>{leg.incomingPayment.id.split('/').pop()}</code></>}<br/>{leg.manuallyVerifiedAt ? `Manually verified by merchant · ${new Date(leg.manuallyVerifiedAt).toLocaleString('en-ZA', { dateStyle: 'medium', timeStyle: 'short' })}` : 'Wallet status not automatically verified'}</span>{(leg.manuallyVerifiedAt || (leg.openPayments && leg.status !== 'FAILED' && BigInt(leg.openPayments.sent) > 0n && leg.openPayments.received === leg.planned)) && <button type="button" className="ghost" disabled={!!verifying} onClick={() => verifyLeg(sale, leg)}>{verifying === leg.legId ? 'Saving…' : leg.manuallyVerifiedAt ? 'Remove confirmation' : 'Confirm wallet completed'}</button>}</div>)}</div>
              <span className="history-ref">{sale.executionId}</span>
            </article>)}</div>}
            {overview.summary.recordCount > overview.history.length && <p className="payment-notice">Showing the latest {overview.history.length} of {overview.summary.recordCount} records.</p>}
          </> : <>
            <p className="lede">All-time mobile Test Wallet records. Reported amounts are Open Payments observations, not verified wallet settlement.</p>
            <div className="report-grid">
              <div className="report-stat"><span>Payment records</span><strong>{overview.summary.recordCount}</strong><small>Mobile Test Wallet</small></div>
              <div className="report-stat"><span>Observed sent</span><strong>{money(overview.summary.observedSent)}</strong><small>Open Payments</small></div>
              <div className="report-stat"><span>Observed received</span><strong>{money(overview.summary.observedReceived)}</strong><small>Open Payments</small></div>
            </div>
            {overview.summary.observedByPot.length > 0 && <><h3 className="breakdown-title">Observed received by pot</h3><div className="status-breakdown">{overview.summary.observedByPot.map(pot => <div key={pot.label}><span>{pot.label}</span><strong>{money(pot.value)}</strong></div>)}</div></>}
            <p className="payment-notice">Wallet settlement is not automatically verified. Merchant confirmations are recorded separately on each sale.</p>
          </>}
        </>}
      </div></section>}
    </main>
  </div>
}
