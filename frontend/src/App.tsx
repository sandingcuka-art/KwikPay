import { useId, useMemo, useState } from 'react'
import {
  ArrowRight,
  BarChart3,
  Check,
  CheckCircle2,
  ChevronLeft,
  CircleDollarSign,
  CreditCard,
  Landmark,
  Package2,
  PiggyBank,
  Settings2,
  ShieldCheck,
  Store,
  Users,
  Wrench,
  Zap
} from 'lucide-react'
import { approveConsent, createPaymentPlan, executePayment, LIVE } from './api'
import type { PaymentPlan, SplitRules } from './types'

type View = 'dashboard' | 'rules' | 'checkout' | 'preview' | 'consent' | 'result'

const money = (minor: number) =>
  new Intl.NumberFormat('en-ZA', { style: 'currency', currency: 'ZAR' }).format(minor / 100)

const legMeta: Record<string, { label: string; icon: typeof Package2; tone: string }> = {
  supplier: { label: 'Stock reserve', icon: Package2, tone: 'blue' },
  salaries: { label: 'Salaries', icon: Users, tone: 'violet' },
  maintenance: { label: 'Maintenance', icon: Wrench, tone: 'amber' },
  profit: { label: 'Available', icon: PiggyBank, tone: 'green' }
}

const demoTransactions = [
  { id: 'KP-1042', time: '19:46', amount: 185.5, status: 'Complete' },
  { id: 'KP-1041', time: '19:21', amount: 72.0, status: 'Complete' },
  { id: 'KP-1040', time: '18:58', amount: 240.0, status: 'Complete' }
]

export default function App() {
  const [view, setView] = useState<View>('dashboard')
  const [rules, setRules] = useState<SplitRules>({ supplier: 20, salaries: 5, maintenance: 5 })
  const [draftRules, setDraftRules] = useState<SplitRules>(rules)
  const [amount, setAmount] = useState('100.00')
  const [plan, setPlan] = useState<PaymentPlan | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const displayedRules = view === 'rules' ? draftRules : rules
  const used = displayedRules.supplier + displayedRules.salaries + displayedRules.maintenance
  const available = Math.max(0, 100 - used)

  const nav = (next: View) => {
    if (next === 'rules' && view !== 'rules') setDraftRules({ ...rules })
    setError('')
    setView(next)
  }

  const resetSale = (next: 'dashboard' | 'checkout') => {
    setPlan(null)
    setAmount('100.00')
    nav(next)
  }

  const preview = async () => {
    const value = Number(amount)
    if (!Number.isFinite(value) || value <= 0) return setError('Enter a valid sale amount.')
    if (used > 100) return setError('Split rules cannot exceed 100%.')
    setBusy(true)
    setError('')
    try {
      setPlan(await createPaymentPlan(value, rules))
      setView('preview')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not create payment plan')
    } finally {
      setBusy(false)
    }
  }

  const startPayment = async () => {
    if (!plan) return
    setBusy(true)
    setError('')
    try {
      setPlan(await executePayment(plan))
      setView('consent')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not start payment. Try again.')
    } finally {
      setBusy(false)
    }
  }

  const approve = async () => {
    if (!plan) return
    setBusy(true)
    setError('')
    try {
      setPlan(await approveConsent(plan))
      setView('result')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not approve payment. Try again.')
    } finally {
      setBusy(false)
    }
  }

  const todayTotal = useMemo(() => demoTransactions.reduce((a, t) => a + t.amount, 0), [])

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><div className="brand-mark">K</div><div><strong>KwikPay</strong><span>merchant</span></div></div>
        <div className="merchant-card"><div className="avatar"><Store size={20}/></div><div><strong>Nomsa's Corner Shop</strong><span>Khayelitsha · Demo</span></div></div>
        <nav aria-label="Main navigation">
          <NavButton icon={BarChart3} label="Overview" active={view === 'dashboard'} onClick={() => nav('dashboard')} />
          <NavButton icon={CreditCard} label="New sale" active={['checkout','preview','consent','result'].includes(view)} onClick={() => resetSale('checkout')} />
          <NavButton icon={Settings2} label="Split rules" active={view === 'rules'} onClick={() => nav('rules')} />
        </nav>
        <div className="sidebar-foot"><span className="dot"/> {LIVE ? 'Local backend mode' : 'Simulated demo'}<br/><small>{LIVE ? 'Wallet integration pending' : 'No real money moves'}</small></div>
      </aside>

      <main className="main">
        <header className="topbar"><div><span className="eyebrow">KWIKPAY MERCHANT</span><h1>{titleFor(view)}</h1></div><div className="status-pill"><ShieldCheck size={16}/> Non-custodial</div></header>

        {view === 'dashboard' && (
          <section className="page dashboard">
            <div className="hero-card">
              <div><span className="eyebrow light">SAMPLE DASHBOARD</span><h2>{new Intl.NumberFormat('en-ZA',{style:'currency',currency:'ZAR'}).format(todayTotal)}</h2><p>Illustrative sales. New sales use {LIVE ? 'the local backend' : 'the simulated demo'}.</p></div>
              <button className="primary inverse" onClick={() => nav('checkout')}>New sale <ArrowRight size={18}/></button>
            </div>
            <div className="stats-grid">
              <Stat title="Transactions" value="3" hint="All completed" icon={CreditCard}/>
              <Stat title="Stock reserved" value="R99.50" hint={`${rules.supplier}% of sales`} icon={Package2}/>
              <Stat title="Available" value="R348.25" hint={`${available}% after rules`} icon={PiggyBank}/>
            </div>
            <div className="content-grid">
              <div className="panel"><div className="panel-head"><div><span className="eyebrow">ACTIVE RULE</span><h3>Every sale, already sorted</h3></div><button className="ghost" onClick={() => nav('rules')}>Edit</button></div><SplitBar rules={rules}/><div className="rule-legend"><Legend tone="blue" label="Stock" value={rules.supplier}/><Legend tone="violet" label="Salaries" value={rules.salaries}/><Legend tone="amber" label="Maintenance" value={rules.maintenance}/><Legend tone="green" label="Available" value={available}/></div></div>
              <div className="panel"><div className="panel-head"><div><span className="eyebrow">RECENT</span><h3>Sales activity</h3></div></div><div className="tx-list">{demoTransactions.map(tx => <div className="tx" key={tx.id}><div className="tx-icon"><Zap size={16}/></div><div><strong>{tx.id}</strong><span>{tx.time}</span></div><div className="tx-right"><strong>{new Intl.NumberFormat('en-ZA',{style:'currency',currency:'ZAR'}).format(tx.amount)}</strong><span><CheckCircle2 size={13}/> {tx.status}</span></div></div>)}</div></div>
            </div>
          </section>
        )}

        {view === 'rules' && (
          <section className="page narrow">
            <Back onClick={() => nav('dashboard')}/>
            <div className="panel form-panel">
              <span className="eyebrow">MERCHANT BACK OFFICE</span><h2>Configure split rules</h2><p className="lede" id="rules-session">Apply a split for this session. Reloading restores the default split; going Back discards unapplied edits.</p>
              <RuleInput label="Stock reserve" icon={Package2} value={draftRules.supplier} onChange={v => setDraftRules({...draftRules,supplier:v})}/>
              <RuleInput label="Salaries" icon={Users} value={draftRules.salaries} onChange={v => setDraftRules({...draftRules,salaries:v})}/>
              <RuleInput label="Maintenance" icon={Wrench} value={draftRules.maintenance} onChange={v => setDraftRules({...draftRules,maintenance:v})}/>
              <div className="available-row"><div><PiggyBank size={19}/><span>Available to business</span></div><strong>{available}%</strong></div>
              <SplitBar rules={draftRules}/>
              {used > 100 && <div className="error" role="alert">Allocated percentages exceed 100%.</div>}
              <button className="primary full" disabled={used > 100} onClick={() => { setRules({ ...draftRules }); nav('checkout') }}>Use this split <ArrowRight size={18}/></button>
            </div>
          </section>
        )}

        {view === 'checkout' && (
          <section className="page narrow">
            <Back onClick={() => nav('dashboard')}/>
            <div className="panel checkout-panel">
              <div className="checkout-icon"><CircleDollarSign size={28}/></div><span className="eyebrow">POS / CHECKOUT</span><h2>Capture sale</h2><p className="lede">{LIVE ? 'Calculate the split and save a pending payment record. Wallet transfers are not enabled yet.' : 'Enter the total to preview the simulated payment split.'}</p>
              <label className="amount-label" htmlFor="sale-total">Sale total</label><div className="amount-field"><span>R</span><input id="sale-total" value={amount} onChange={e => setAmount(e.target.value)} inputMode="decimal" autoFocus/></div>
              <div className="mini-rule"><span>Active split</span><strong>{rules.supplier}% stock · {rules.salaries}% salaries · {rules.maintenance}% maintenance · {available}% available</strong></div>
              {error && <div className="error" role="alert">{error}</div>}
              <button className="primary full" onClick={preview} disabled={busy}>{busy ? 'Preparing…' : LIVE ? 'Calculate & save sale' : 'Preview split'} <ArrowRight size={18}/></button>
            </div>
          </section>
        )}

        {view === 'preview' && plan && (
          <section className="page narrow wide-mobile">
            <Back onClick={() => nav('checkout')}/>
            <div className="panel">
              {LIVE ? <div className="saved-status" role="status"><CheckCircle2 size={20}/><strong>Sale saved · Payment pending</strong></div> : <span className="eyebrow">PAYMENT PLAN</span>}
              <h2>{money(plan.totalMinor)} sale</h2><p className="lede">{LIVE ? 'Your split is recorded below. No funds have moved.' : `Simulated payment to ${plan.legs.length} destinations. No real money moves.`}</p>
              <div className="legs">{plan.legs.map(leg => <Leg key={leg.id} leg={leg}/>)}</div>
              {LIVE ? <>
                <div className="sale-actions"><button className="primary" onClick={() => resetSale('dashboard')}>Done <Check size={18}/></button><button className="secondary" onClick={() => resetSale('checkout')}>New sale <ArrowRight size={18}/></button></div>
                <p className="payment-notice">Wallet approval and transfers are not available yet.</p>
                <details className="payment-reference"><summary>Payment reference · {plan.paymentId?.slice(0, 8)}</summary><code>{plan.paymentId}</code></details>
              </> : <div className="trust-row"><ShieldCheck size={18}/><div><strong>Non-custodial orchestration</strong><span>Funds move between wallet providers. KwikPay instructs the split.</span></div></div>}
              {error && <div className="error" role="alert">{error}</div>}
              {!LIVE && <button className="primary full" onClick={startPayment} disabled={busy}>{busy ? 'Preparing consent…' : 'Continue to customer approval'} <ArrowRight size={18}/></button>}
            </div>
          </section>
        )}

        {view === 'consent' && plan && (
          <section className="page consent-page">
            <div className="consent-card">
              <div className="wallet-logo"><Landmark size={25}/></div><span className="eyebrow">CUSTOMER WALLET</span><h2>Approve {money(plan.totalMinor)}</h2><p>KwikPay is requesting permission to make this payment on your behalf.</p>
              <div className="consent-details"><div><span>Merchant</span><strong>Nomsa's Corner Shop</strong></div><div><span>Maximum debit</span><strong>{money(plan.totalMinor)}</strong></div><div><span>Payment legs</span><strong>{plan.legs.length}</strong></div></div>
              <div className="consent-note"><ShieldCheck size={17}/> This approval is limited to this payment amount.</div>
              {error && <div className="error" role="alert">{error}</div>}
              <button className="primary full" onClick={approve} disabled={busy}>{busy ? 'Authorising…' : 'Approve payment'} <Check size={18}/></button>
              <button className="text-button" onClick={() => nav('preview')}>Cancel</button>
            </div>
          </section>
        )}

        {view === 'result' && plan && (
          <section className="page narrow wide-mobile">
            <div className="success-hero"><div className="success-icon"><Check size={30}/></div><span className="eyebrow light">PAYMENT COMPLETE</span><h2>{money(plan.totalMinor)}</h2><p>{plan.legs.length} of {plan.legs.length} payment legs completed</p></div>
            <div className="panel result-panel"><div className="legs">{plan.legs.map(leg => <Leg key={leg.id} leg={leg}/>)}</div><div className="held"><span>Funds held by KwikPay</span><strong>R0.00</strong></div><button className="primary full" onClick={() => resetSale('dashboard')}>Done</button></div>
          </section>
        )}
      </main>
    </div>
  )
}

function titleFor(view: View) {
  if (view === 'preview' && LIVE) return 'Sale saved'
  if (view === 'rules') return 'Split rules'
  if (view === 'dashboard') return 'Overview'
  if (view === 'result') return 'Payment result'
  return 'New sale'
}

function NavButton({icon:Icon,label,active,onClick}:{icon:any,label:string,active:boolean,onClick:()=>void}) { return <button className={`nav-btn ${active?'active':''}`} title={label} aria-current={active ? 'page' : undefined} onClick={onClick}><Icon size={19}/>{label}</button> }
function Back({onClick}:{onClick:()=>void}) { return <button className="back" onClick={onClick}><ChevronLeft size={17}/> Back</button> }
function Stat({title,value,hint,icon:Icon}:{title:string,value:string,hint:string,icon:any}) { return <div className="stat"><div className="stat-icon"><Icon size={20}/></div><span>{title}</span><strong>{value}</strong><small>{hint}</small></div> }
function Legend({tone,label,value}:{tone:string,label:string,value:number}) { return <div className="legend"><span className={`legend-dot ${tone}`}/><span>{label}</span><strong>{value}%</strong></div> }
function SplitBar({rules}:{rules:SplitRules}) { const available=Math.max(0,100-rules.supplier-rules.salaries-rules.maintenance); return <div className="split-bar"><span className="seg blue" style={{width:`${rules.supplier}%`}}/><span className="seg violet" style={{width:`${rules.salaries}%`}}/><span className="seg amber" style={{width:`${rules.maintenance}%`}}/><span className="seg green" style={{width:`${available}%`}}/></div> }
function RuleInput({label,icon:Icon,value,onChange}:{label:string,icon:any,value:number,onChange:(n:number)=>void}) {
  const id = useId()
  return <div className="rule-input"><label htmlFor={id}><div className="rule-icon"><Icon size={18}/></div><strong>{label}</strong></label><div className="percent-field"><input id={id} type="number" min="0" max="100" value={value} aria-describedby="rules-session" onChange={e=>onChange(Math.max(0,Number(e.target.value)))}/><span>%</span></div></div>
}
function Leg({leg}:{leg:PaymentPlan['legs'][number]}) { const meta=legMeta[leg.label]??legMeta.profit; const Icon=meta.icon; return <div className="leg"><div className={`leg-icon ${meta.tone}`}><Icon size={18}/></div><div className="leg-main"><strong>{meta.label}</strong><span>{leg.percentage}% · {leg.walletAddress.replace('https://','')}</span></div><div className="leg-amount"><strong>{money(leg.amountMinor)}</strong>{leg.status==='COMPLETED'&&<span><CheckCircle2 size={14}/> Sent</span>}</div></div> }
