import { useEffect, useState } from 'react'
import { QRCodeSVG } from 'qrcode.react'

type Pot = { label: string; amount: string; percentage: number }
type Leg = { label: string; amount: string; status?: string; walletStatus?: string; openPayments?: { sent: string; received: string } | null }
type Request = { checkoutUrl?: string; status: string; amount: string; expiresAt: number; pots: Pot[]; legs?: Leg[]; executionId?: string; paymentStatus?: string }
const money = (value: string) => `R${(BigInt(value) / 100n).toString()}.${(BigInt(value) % 100n).toString().padStart(2, '0')}`

async function readRequest(path: string, init?: RequestInit): Promise<Request> {
  const response = await fetch(path, { ...init, credentials: 'same-origin', referrerPolicy: 'no-referrer', cache: 'no-store' })
  if (response.status === 401 || response.status === 403) throw new Error('Dashboard access was denied. Sign in and try again.')
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(response.status === 400 && typeof body?.detail === 'string' ? body.detail : 'Could not load the payment request. Check Sales before starting another.')
  }
  return response.json()
}

export default function MerchantTerminal() {
  const [request, setRequest] = useState<Request | null>(null)
  const [requestPath, setRequestPath] = useState('')
  const [creating, setCreating] = useState(false)
  const [amount, setAmount] = useState('3.00')
  const [error, setError] = useState('')
  const [pollError, setPollError] = useState(false)
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (!requestPath) return
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      try {
        const next = await readRequest(requestPath, { signal: controller.signal })
        if (!controller.signal.aborted) { setRequest(next); setPollError(false) }
      } catch {
        if (!controller.signal.aborted) setPollError(true)
      } finally {
        if (!controller.signal.aborted) { setNow(Date.now()); timer = setTimeout(poll, 3000) }
      }
    }
    timer = setTimeout(poll, 3000)
    return () => { controller.abort(); clearTimeout(timer) }
  }, [requestPath])

  const create = async () => {
    const match = /^(\d{1,2})(?:\.(\d{1,2}))?$/.exec(amount.trim())
    const minor = match ? Number(match[1]) * 100 + Number((match[2] || '').padEnd(2, '0')) : 0
    if (minor < 2 || minor > 1000) { setError('Enter an amount from R0.02 to R10.00, with at most two decimal places.'); return }
    setCreating(true); setError(''); setPollError(false)
    try {
      const created = await readRequest('/api/dashboard/requests', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ amount: String(minor) }) })
      const url = new URL(created.checkoutUrl || '', window.location.origin)
      if (url.origin !== window.location.origin || url.search || url.hash || !/^\/api\/mobile-test\/requests\/[A-Za-z0-9_-]{32}$/.test(url.pathname)) throw new Error('The request address was invalid. Check Sales before starting another.')
      setRequestPath(url.pathname); setRequest(created); setNow(Date.now())
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not create the sale. Check Sales before starting another.') }
    finally { setCreating(false) }
  }

  const state = request?.status
  const expired = state === 'EXPIRED' || (state === 'AWAITING_CUSTOMER' && !!request && request.expiresAt * 1000 <= now)
  const failed = state === 'PREPARATION_FAILED' || state === 'FAILED' || request?.paymentStatus === 'FAILED' || request?.paymentStatus === 'PARTIAL'
  const observed = request?.legs?.length === 2 && request.legs.every(leg => leg.status !== 'FAILED' && leg.openPayments && /^\d+$/.test(leg.openPayments.sent) && BigInt(leg.openPayments.sent) > 0n && leg.openPayments.received === leg.amount)
  const canStartAnother = expired || failed || observed
  const heading = expired ? 'Request expired' : failed ? 'Payment needs attention' : state === 'AWAITING_CUSTOMER' ? 'Waiting for customer' : state === 'AWAITING_CONSENT' ? 'Waiting for wallet approval' : observed ? 'Transfer amounts recorded' : 'Checking payment details'

  return <>
    <div className="overview-head"><div><h2>Start a Test Wallet sale</h2><p className="lede">Create a request for the customer to scan with the KwikPay Android app.</p></div></div>
    {!request && <form onSubmit={e => { e.preventDefault(); void create() }}><div className="terminal-amount"><label htmlFor="sale-amount">Sale amount (ZAR)</label><input id="sale-amount" type="text" inputMode="decimal" value={amount} maxLength={12} onChange={e => { setAmount(e.target.value); setError('') }} aria-describedby="amount-help"/><small id="amount-help">Enter R0.02 to R10.00. Each pot must receive at least R0.01.</small></div><p className="payment-notice">The API applies your saved pot split. The customer reviews and approves the payment in their wallet.</p><button type="submit" className="primary full" disabled={creating}>{creating ? 'Creating request…' : 'Create sale request'}</button></form>}
    {error && <div className="error" role="alert">{error}</div>}
    {request && <>
      <div className="terminal-head"><div><span className="eyebrow">SALE TOTAL</span><strong>{money(request.amount)}</strong></div><span className="history-status" role="status">{heading}</span></div>
      {!expired && state === 'AWAITING_CUSTOMER' && <div className="terminal-qr"><QRCodeSVG value={window.location.origin + requestPath} size={240} marginSize={4} title="Customer payment request QR code"/><strong>Scan with KwikPay Customer</strong><span>This request expires in five minutes.</span></div>}
      {pollError && <div className="error" role="alert">Status is temporarily unavailable. Retrying; check Sales before attempting another payment.</div>}
      <div className="terminal-legs">{request.pots.map((pot, i) => { const leg = request.legs?.[i]; return <div className="terminal-leg" key={i}><div><strong>{pot.label}</strong><span>{pot.percentage}% · planned {money(pot.amount)}</span>{leg?.openPayments && <small>Open Payments: {money(leg.openPayments.sent)} sent · {money(leg.openPayments.received)} received</small>}</div><strong>{money(pot.amount)}</strong></div> })}</div>
      {state === 'AWAITING_CONSENT' && <p className="payment-notice">The customer must review and approve the request in their wallet.</p>}
      {state === 'PROCESSING' && <p className="payment-notice">Wallet settlement is not automatically verified. Check the Test Wallet before repeating a payment.</p>}
      {failed && <p className="payment-notice">Check Sales and the Test Wallet before attempting another payment.</p>}
      {canStartAnother && <button className="primary full" onClick={() => { setRequestPath(''); setRequest(null); setError('') }}>Start another sale</button>}
    </>}
  </>
}
