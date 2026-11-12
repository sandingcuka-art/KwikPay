import { useEffect, useState } from 'react'
import { ArrowRight, BarChart3, CreditCard, History, Settings2, ShieldCheck, Store } from 'lucide-react'
import SalesOverview from './SalesOverview'
import ConceptDemo from './ConceptDemo'

type Pot = { label: string; walletAddress: string; percentage: number }
type Amount = { value: string; assetCode: 'ZAR'; assetScale: 2 }
type Plan = { id: string; amount: Amount; legs: { id: string; label: string; percentage: number; walletAddress: string; amount: Amount; status: string }[] }
type Execution = { executionId: string; status: 'CREATED' | 'AWAITING_CONSENT' | 'PROCESSING' | 'COMPLETED' | 'PARTIAL' | 'FAILED'; plan: Plan; legs: { legId: string; status: string; walletStatus?: 'UNVERIFIED'; openPayments?: { sent: string; received: string; observedAt: string } | null }[]; message?: string }
const initialPots: Pot[] = [
  { label: 'Business income', walletAddress: '', percentage: 80 },
  { label: 'Stock reserve', walletAddress: '', percentage: 20 },
]
const money = (value: string) => `R${(BigInt(value) / 100n).toString()}.${(BigInt(value) % 100n).toString().padStart(2, '0')}`
const validAddress = (value: string) => {
  try {
    const url = new URL(value)
    return value === value.trim() && url.protocol === 'https:' && !!url.hostname && !url.username && !url.password && !url.port && !url.search && !url.hash && !/\s/.test(value)
  } catch { return false }
}

// shortcut: browser-only settings belong to this device; use merchant storage when accounts exist.
const loadSettings = (): { pots: Pot[]; version: number } | null => {
  try {
    const data = JSON.parse(localStorage.getItem('kwikpay-pot-settings') || 'null')
    if (!data || !Number.isSafeInteger(data.version) || data.version < 1 || !Array.isArray(data.pots) || data.pots.length !== 2 || data.pots.some((p: Pot) => !p || typeof p.label !== 'string' || !p.label.trim() || typeof p.walletAddress !== 'string' || !validAddress(p.walletAddress) || typeof p.percentage !== 'number' || !Number.isFinite(p.percentage) || p.percentage < 0 || p.percentage > 100) || Math.abs(data.pots.reduce((sum: number, p: Pot) => sum + p.percentage, 0) - 100) > 1e-9) return null
    return data
  } catch { return null }
}

export default function TwoPotApp() {
  const [handoffId] = useState(() => {
    const value = new URLSearchParams(window.location.search).get('execution')
    return value && /^exec_[0-9a-f]{32}$/.test(value) ? value : null
  })
  const [settings] = useState(loadSettings)
  const [view, setView] = useState<'pots' | 'sale' | 'preview' | 'result' | 'simulation' | 'testquote' | 'history' | 'reports' | 'example'>(() => handoffId ? 'result' : sessionStorage.getItem('kwikpay-test-debit') ? 'testquote' : sessionStorage.getItem('kwikpay-execution-id') ? 'result' : 'pots')
  const [pots, setPots] = useState<Pot[]>(settings?.pots ?? initialPots)
  const [draft, setDraft] = useState<Pot[]>((settings?.pots ?? initialPots).map(p => ({ ...p })))
  const [saved, setSaved] = useState(!!settings)
  const [ruleVersion, setRuleVersion] = useState(settings?.version ?? 0)
  const [payer, setPayer] = useState('')
  const [amount, setAmount] = useState('100.00')
  const [plan, setPlan] = useState<Plan | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [execution, setExecution] = useState<Execution | null>(null)
  const [executionId, setExecutionId] = useState<string | null>(() => handoffId ?? sessionStorage.getItem('kwikpay-execution-id'))
  const [simulationStep, setSimulationStep] = useState(0)
  const [testDebit, setTestDebit] = useState(() => sessionStorage.getItem('kwikpay-test-debit') ?? '')
  const apiBase = import.meta.env.VITE_CORE_API_URL ?? ''

  useEffect(() => {
    if (handoffId) {
      sessionStorage.removeItem('kwikpay-test-debit')
      sessionStorage.setItem('kwikpay-execution-id', handoffId)
      window.history.replaceState(null, '', window.location.pathname)
    }
  }, [handoffId])
  useEffect(() => {
    if ((view !== 'result' && view !== 'testquote') || !executionId) return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      try {
        const response = await fetch(`${apiBase}/api/payment-executions/${encodeURIComponent(executionId)}`)
        const body = await response.json()
        if (response.status === 404) { if (!cancelled) setError('Execution record not found.'); return }
        if (!response.ok) throw new Error(body.detail || 'Could not load execution status.')
        if (cancelled) return
        setExecution(body); setError('')
        if (view === 'result' && !['COMPLETED', 'PARTIAL', 'FAILED'].includes(body.status)) timer = setTimeout(poll, 3000)
      } catch (e) {
        if (!cancelled) { setError(e instanceof Error ? e.message : 'Could not load execution status.'); timer = setTimeout(poll, 3000) }
      }
    }
    void poll()
    return () => { cancelled = true; clearTimeout(timer) }
  }, [view, executionId, apiBase])
  useEffect(() => {
    if (view !== 'simulation') return
    setSimulationStep(0)
    const first = setTimeout(() => setSimulationStep(1), 1000)
    const second = setTimeout(() => setSimulationStep(2), 2000)
    return () => { clearTimeout(first); clearTimeout(second) }
  }, [view])
  const editPot = (index: number, patch: Partial<Pot>) => setDraft(current => current.map((pot, i) => i === index ? { ...pot, ...patch } : pot))
  const save = () => {
    if (draft.some(p => !p.label.trim() || !validAddress(p.walletAddress))) return setError('Enter a name and valid HTTPS wallet address for each pot.')
    if (draft.some(p => !Number.isFinite(p.percentage) || p.percentage < 0 || p.percentage > 100) || Math.abs(draft.reduce((sum, p) => sum + p.percentage, 0) - 100) > 1e-9) return setError('Pot percentages must total 100%.')
    const nextPots = draft.map(p => ({ ...p, label: p.label.trim() }))
    const version = ruleVersion + 1
    try { localStorage.setItem('kwikpay-pot-settings', JSON.stringify({ pots: nextPots, version })) }
    catch { return setError('Could not save settings in this browser. Check browser storage and try again.') }
    setPots(nextPots)
    setRuleVersion(version)
    setSaved(true); setError(''); setView('sale')
  }
  const preview = async () => {
    if (!saved) { setView('pots'); return setError('Connect both pots before creating a sale.') }
    const match = /^(\d{1,12})(?:\.(\d{1,2}))?$/.exec(amount.trim())
    if (!match) return setError('Enter a positive amount in rand with at most two decimal places.')
    const minor = BigInt(match[1]) * 100n + BigInt((match[2] || '').padEnd(2, '0'))
    if (minor <= 0n) return setError('Enter a positive sale amount.')
    if (!validAddress(payer)) return setError('Enter a valid HTTPS customer wallet address.')
    setBusy(true); setError('')
    try {
      const response = await fetch(`${import.meta.env.VITE_CORE_API_URL ?? ''}/api/payment-plans`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ shopId: 'demo-shop', saleId: `sale_${crypto.randomUUID()}`, payerWalletAddress: payer,
          amount: { value: minor.toString(), assetCode: 'ZAR', assetScale: 2 }, rule: { version: ruleVersion, destinations: pots } }),
      })
      const body = await response.json()
      if (!response.ok) throw new Error(body.detail || 'Could not create payment plan.')
      setPlan(body); setView('preview')
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not create payment plan.') }
    finally { setBusy(false) }
  }
  const navigate = (target: 'pots' | 'sale' | 'history' | 'reports') => { setError(''); if (target === 'pots') setDraft(pots.map(p => ({ ...p }))); setView(target) }
  const recordExecution = async () => {
    if (!plan) return
    setBusy(true); setError('')
    try {
      const response = await fetch(`${apiBase}/api/payment-executions`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(plan) })
      const body = await response.json()
      if (!response.ok) throw new Error(body.detail || 'Could not create execution record.')
      sessionStorage.setItem('kwikpay-execution-id', body.executionId)
      setExecutionId(body.executionId); setExecution(body); setView('result')
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not create execution record.') }
    finally { setBusy(false) }
  }
  const prepareTest = async () => {
    if (!plan) return
    setBusy(true); setError('')
    try {
      const response = await fetch(`${apiBase}/api/test-payments/prepare`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(plan) })
      const body = await response.json()
      if (!response.ok) throw new Error(body.detail || 'Test Wallet quote failed.')
      sessionStorage.setItem('kwikpay-execution-id', body.executionId)
      sessionStorage.setItem('kwikpay-test-debit', body.debitMinor)
      setExecution(null); setExecutionId(body.executionId); setTestDebit(body.debitMinor); setView('testquote')
    } catch (e) { setError(e instanceof Error ? e.message : 'Test Wallet quote failed.') }
    finally { setBusy(false) }
  }
  const approveTest = async () => {
    if (!executionId) return
    setBusy(true); setError('')
    try {
      const response = await fetch(`${apiBase}/api/test-payments/consent`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ executionId }) })
      const body = await response.json()
      if (!response.ok) throw new Error(body.detail || 'Could not start wallet approval.')
      const target = new URL(body.interactUrl)
      if (target.protocol !== 'https:' || target.hostname !== 'auth.interledger-test.dev' || target.username || target.password || target.port) throw new Error('Unexpected wallet approval address.')
      sessionStorage.removeItem('kwikpay-test-debit')
      window.location.assign(target.href)
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not start wallet approval.') }
    finally { setBusy(false) }
  }
  const openExecution = (id: string) => { sessionStorage.removeItem('kwikpay-test-debit'); sessionStorage.setItem('kwikpay-execution-id', id); setExecution(null); setExecutionId(id); setError(''); setView('result') }
  const closeResult = () => { sessionStorage.removeItem('kwikpay-execution-id'); setExecutionId(null); setExecution(null); navigate('sale') }
  const testEligible = !!plan && payer === 'https://ilp.interledger-test.dev/wikus-customer' && BigInt(plan.amount.value) <= 100000n && plan.legs.length === 2 && plan.legs.every(leg => validAddress(leg.walletAddress) && new URL(leg.walletAddress).hostname === 'ilp.interledger-test.dev' && BigInt(leg.amount.value) > 0n)
  const quotedPlan = plan ?? execution?.plan
  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark">K</div><div><strong>KwikPay</strong><span>merchant</span></div></div>
      <div className="merchant-card"><div className="avatar"><Store size={20}/></div><div><strong>Demo shop</strong><span>Local setup</span></div></div>
      <nav aria-label="Main navigation">
        <button className={`nav-btn ${view === 'pots' ? 'active' : ''}`} aria-current={view === 'pots' ? 'page' : undefined} onClick={() => navigate('pots')}><Settings2 size={19}/> Pots & split</button>
        <button className={`nav-btn ${['sale', 'preview', 'result', 'testquote', 'simulation', 'example'].includes(view) ? 'active' : ''}`} aria-current={['sale', 'preview', 'result', 'testquote', 'simulation', 'example'].includes(view) ? 'page' : undefined} onClick={() => navigate('sale')}><CreditCard size={19}/> New sale</button>
        <button className={`nav-btn ${view === 'history' ? 'active' : ''}`} aria-current={view === 'history' ? 'page' : undefined} onClick={() => navigate('history')}><History size={19}/> Sales</button>
        <button className={`nav-btn ${view === 'reports' ? 'active' : ''}`} aria-current={view === 'reports' ? 'page' : undefined} onClick={() => navigate('reports')}><BarChart3 size={19}/> Reports</button>
      </nav><div className="sidebar-foot">Local demo<br/><small>Test Wallet and simulation</small></div>
    </aside>
    <main className="main"><header className="topbar"><div><span className="eyebrow">KWIKPAY MERCHANT</span><h1>{view === 'pots' ? 'Pots & split' : view === 'sale' ? 'New sale' : view === 'result' ? 'Payment status' : view === 'simulation' ? 'Simulated payment' : view === 'example' ? 'How KwikPay works' : view === 'testquote' ? 'Test Wallet quote' : view === 'history' ? 'Sales history' : view === 'reports' ? 'Reports' : 'Payment preview'}</h1></div><div className="status-pill"><ShieldCheck size={16}/> Local demo</div></header>
      <section className="page narrow"><div className="panel form-panel">
        {(view === 'history' || view === 'reports') && <SalesOverview view={view} apiBase={apiBase} openExecution={openExecution}/>}
        {view === 'example' && <ConceptDemo exit={() => navigate('sale')}/>}
        {view === 'pots' && <><span className="eyebrow">SET UP YOUR POTS</span><h2>Where should each sale go?</h2><p className="lede">Name your pots, connect their wallet addresses and choose a split. Settings are saved in this browser on this device.</p>
          {draft.map((pot, i) => <fieldset className="pot-fields" key={i}><legend>Pot {i + 1}</legend>
            <label htmlFor={`pot-name-${i}`}>Pot name</label><input id={`pot-name-${i}`} value={pot.label} onChange={e => editPot(i, { label: e.target.value })}/>
            <label htmlFor={`pot-wallet-${i}`}>Wallet address</label><input id={`pot-wallet-${i}`} type="url" placeholder="https://..." value={pot.walletAddress} onChange={e => editPot(i, { walletAddress: e.target.value })}/>
            <div className="quick-fill" aria-label={`Test Wallet shortcuts for pot ${i + 1}`}><span>Test addresses</span>{[1, 2, 3].map(n => <button type="button" key={n} onClick={() => editPot(i, { walletAddress: `https://ilp.interledger-test.dev/kwikpay-merch-${n}` })}>Merchant {n}</button>)}</div>
            <label htmlFor={`pot-percent-${i}`}>Percentage</label><input id={`pot-percent-${i}`} type="number" min="0" max="100" value={Number.isNaN(pot.percentage) ? '' : pot.percentage} onChange={e => editPot(i, { percentage: e.target.value === '' ? NaN : Number(e.target.value) })}/>
          </fieldset>)}<p className="payment-notice">A pot is a routing label. Separate addresses do not necessarily mean separate balances.</p>
          {error && <div className="error" role="alert">{error}</div>}<button className="primary full" onClick={save}>Save pots & split <ArrowRight size={18}/></button></>}
        {view === 'sale' && <><span className="eyebrow">CHECKOUT</span><h2>New sale</h2><p className="lede">Prepare a split payment plan. No funds move at this stage.</p>{saved && <div className="saved-status" role="status">Pots and split saved in this browser</div>}
          <label className="amount-label" htmlFor="sale-total">Sale total</label><div className="amount-field"><span>R</span><input id="sale-total" value={amount} inputMode="decimal" onChange={e => setAmount(e.target.value)}/></div>
          <div className="pot-fields"><label htmlFor="payer">Customer wallet address</label><input id="payer" type="url" placeholder="https://..." value={payer} onChange={e => setPayer(e.target.value)}/><div className="quick-fill"><span>Test address</span><button type="button" onClick={() => setPayer('https://ilp.interledger-test.dev/wikus-customer')}>Customer wallet</button></div></div>
          <div className="mini-rule"><span>Current split</span><strong>{saved ? pots.map(p => `${p.label} ${p.percentage}%`).join(' · ') : 'Connect your pots first'}</strong></div>
          {error && <div className="error" role="alert">{error}</div>}<button className="primary full" disabled={busy} onClick={preview}>{busy ? 'Preparing…' : 'Preview split'} <ArrowRight size={18}/></button><button className="secondary full plan-edit" disabled={busy} onClick={() => setView('example')}>See how KwikPay works</button></>}
        {view === 'preview' && plan && <><span className="eyebrow">PAYMENT PLAN</span><h2>{money(plan.amount.value)} sale</h2><p className="lede">Preview only. No payment has been made.</p><div className="legs">{plan.legs.map(leg => <div className="leg" key={leg.id}><div className="leg-icon blue"><Store size={18}/></div><div className="leg-main"><strong>{leg.label}</strong><span className="wallet-desktop">{leg.percentage}% · {leg.walletAddress}</span><details className="wallet-mobile"><summary aria-label={`${leg.percentage}% for ${leg.label}: show wallet address`}><span className="wallet-percent">{leg.percentage}% ·</span><span className="wallet-short">{new URL(leg.walletAddress).pathname.split('/').filter(Boolean).pop() || new URL(leg.walletAddress).hostname}</span><span className="wallet-hint">Details</span></summary><span className="wallet-full">{leg.walletAddress}</span></details></div><div className="leg-amount"><strong>{money(leg.amount.value)}</strong></div></div>)}</div>
          <div className="held"><span>Funds held by KwikPay</span><strong>R0.00</strong></div><p className="payment-notice" role="status">{testEligible ? 'Test Wallet charges are shown after requesting a quote.' : 'Use the Customer wallet shortcut and two Test Wallet destinations with positive amounts. Test sales are limited to R1000.00; you can still simulate this sale below.'}</p>{error && <div className="error" role="alert">{error}</div>}<button className="primary full" disabled={busy || !testEligible} onClick={prepareTest}>{busy ? 'Preparing…' : `Prepare ${money(plan.amount.value)} Test Wallet payment`}</button><button className="secondary full plan-edit" disabled={busy} onClick={() => navigate('sale')}>Edit sale</button><details className="demo-tools"><summary>Demo tools</summary><p>These tools do not send a payment.</p><button className="secondary full" disabled={busy} onClick={() => setView('simulation')}>Simulate split payment</button><button className="secondary full" disabled={busy} onClick={recordExecution}>{busy ? 'Saving…' : 'Create tracking record'}</button></details></>}
        {view === 'testquote' && <><span className="eyebrow">TEST WALLET QUOTE</span><h2>Review test payment</h2>{quotedPlan ? <><p className="lede">The Test Wallet quoted a total debit of {money(testDebit)} for the {money(quotedPlan.amount.value)} split. Test funds only.</p>{quotedPlan.legs.map(leg => <div className="held" key={leg.id}><span>{leg.label}</span><strong>{money(leg.amount.value)}</strong></div>)}</> : !error && <p role="status">Loading payment details…</p>}<p className="payment-notice">Continue to the customer's wallet to approve this payment. The two transfers are tracked separately.</p>{error && <div className="error" role="alert">{error}</div>}<button className="primary full" disabled={busy || !quotedPlan} onClick={approveTest}>{busy ? 'Starting approval…' : 'Continue to Test Wallet'}</button><button className="secondary full" onClick={() => { sessionStorage.removeItem('kwikpay-test-debit'); setTestDebit(''); navigate('sale') }}>Back to sale</button></>}
        {view === 'simulation' && plan && <><span className="eyebrow">SIMULATION ONLY</span><h2>{simulationStep === 2 ? 'Simulated split complete' : 'Simulating split payment'}</h2>
          <p className="lede" role="status">Demo only: no customer approval, provider connection or money movement takes place.</p>
          <div className="legs">{plan.legs.map((leg, index) => <div className="leg" key={leg.id}><div className="leg-icon blue"><Store size={18}/></div><div className="leg-main"><strong>{leg.label}</strong><span>{simulationStep > index ? 'Simulated complete' : 'Simulated pending'}</span></div><div className="leg-amount"><strong>{money(leg.amount.value)}</strong></div></div>)}</div>
          <div className="held"><span>Simulated legs complete</span><strong>{simulationStep} / {plan.legs.length}</strong></div><p className="payment-notice">This result is illustrative and is not a payment record.</p><button className="secondary full" onClick={() => navigate('sale')}>Back to sale</button></>}
        {view === 'result' && <><span className="eyebrow">EXECUTION STATUS</span>{!execution && !error && <p role="status">Loading payment status…</p>}{error && <div className="error" role="alert">{error}</div>}
          {execution && <><h2 aria-live="polite">{execution.status === 'COMPLETED' ? 'Payment complete' : execution.status === 'PARTIAL' ? 'Partially completed' : execution.status === 'FAILED' ? 'Payment failed' : execution.status === 'PROCESSING' ? 'Payment processing' : execution.status === 'AWAITING_CONSENT' ? 'Awaiting approval' : 'Payment not started'}</h2>
            <p className="lede">{execution.status === 'CREATED' ? 'A tracking record is saved. Payment approval and execution are not connected.' : execution.status === 'PROCESSING' ? 'Payment is processing. The Test Wallet transaction status has not been confirmed.' : execution.status === 'AWAITING_CONSENT' ? 'Waiting for customer approval.' : 'See the status of each payment below.'}</p>
            <div className="legs">{execution.plan.legs.map(leg => {
              const result = execution.legs.find(item => item.legId === leg.id)
              const status = result?.status ?? 'PENDING'
              const label = execution.status === 'AWAITING_CONSENT' ? 'Awaiting approval' : status === 'PROCESSING' ? 'Processing' : status === 'PREPARED' ? 'Prepared' : 'Not started'
              return <div className="leg" key={leg.id}><div className="leg-icon blue"><Store size={18}/></div><div className="leg-main"><strong>{leg.label}</strong>
                {status === 'COMPLETED' ? <span>Completed</span> : status === 'FAILED' ? <span>Failed</span> : <details className="pending-status"><summary aria-label={`${label} ${leg.label}: show payment details`}><span className="pending-sprite" aria-hidden="true"><i/><i/><i/></span><span>{label}</span><span className="pending-hint" aria-hidden="true">Details</span></summary><p>{execution.status === 'CREATED' ? 'A tracking record is saved; this payment has not started.' : execution.status === 'AWAITING_CONSENT' ? 'Waiting for wallet approval. This payment is not confirmed.' : status === 'PREPARED' ? 'This payment is prepared and has not been submitted.' : 'This payment has not been confirmed. Check the status for updates.'}</p></details>}
                {(result?.walletStatus || result?.openPayments || execution.legs.some(item => item.walletStatus)) && <div className="payment-evidence"><span><strong>Wallet:</strong> Unverified</span>{result?.openPayments ? <><span><strong>Open Payments observed:</strong> {money(result.openPayments.sent)} sent · {money(result.openPayments.received)} received</span><small>Last observed {new Date(result.openPayments.observedAt).toLocaleString('en-ZA')}. These amounts do not confirm the wallet transaction.</small></> : <span>Open Payments amounts not yet observed</span>}</div>}
              </div><div className="leg-amount"><strong>{money(leg.amount.value)}</strong></div></div>
            })}</div>
            {(execution.status === 'FAILED' || execution.status === 'PARTIAL') && <p className="payment-notice">Review both payment legs before starting another sale; a leg may already have been sent.</p>}
            {execution.status === 'AWAITING_CONSENT' && <button className="primary full" disabled={busy} onClick={approveTest}>{busy ? 'Opening wallet…' : 'Resume wallet approval'}</button>}<div className="held"><span>Completed payments</span><strong>{execution.legs.filter(leg => leg.status === 'COMPLETED').length} / {execution.plan.legs.length}</strong></div><p className="payment-notice">Reference: {execution.executionId}</p></>}
          <button className="secondary full" onClick={closeResult}>Back to sale</button></>}
      </div></section>
    </main>
  </div>
}
