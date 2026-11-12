import { useEffect, useState } from 'react'

type Amount = { value: string; assetCode: 'ZAR'; assetScale: 2 }
type HistoryItem = { executionId: string; createdAt: string; status: string; source: 'tracking' | 'test_wallet'; amount: Amount; legs: { label: string; amount: Amount; status: string }[] }
type Overview = { history: HistoryItem[]; summary: { recordCount: number; completedTestSales: number; completedSalesValue: string; confirmedReceipts: string; statusCounts: Record<string, number>; confirmedByPot: { label: string; value: string }[] } }
const money = (value: string) => `R${(BigInt(value) / 100n).toString()}.${(BigInt(value) % 100n).toString().padStart(2, '0')}`
const statusName = (status: string) => ({ CREATED: 'Not started', AWAITING_CONSENT: 'Awaiting approval', PROCESSING: 'Processing', COMPLETED: 'Completed', PARTIAL: 'Partial', FAILED: 'Failed', PENDING: 'Pending', PREPARED: 'Prepared' }[status] ?? status)

export default function SalesOverview({ view, apiBase, openExecution }: { view: 'history' | 'reports'; apiBase: string; openExecution: (id: string) => void }) {
  const [data, setData] = useState<Overview | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [refresh, setRefresh] = useState(0)
  const [page, setPage] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true); setError('')
    fetch(`${apiBase}/api/sales-overview?offset=${page * 100}`, { signal: controller.signal })
      .then(async response => { if (response.status === 401 || response.status === 403) throw new Error('You do not have access to sales data.'); if (!response.ok) throw new Error('Could not load sales data.'); return response.json() })
      .then(body => setData(body))
      .catch(err => { if (!controller.signal.aborted) setError(err instanceof Error ? err.message : 'Could not load sales data.') })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [apiBase, refresh, page])
  return <>
    <div className="overview-head"><div><span className="eyebrow">{view === 'history' ? 'RECENT ACTIVITY' : 'SALES OVERVIEW'}</span><h2>{view === 'history' ? 'Sales history' : 'Reports'}</h2></div><button className="ghost" onClick={() => setRefresh(n => n + 1)} disabled={loading}>Refresh</button></div>
    <p className="lede">{view === 'history' ? 'Saved payment records from this local database. Simulations are not recorded.' : 'All-time totals from this local database. Test Wallet payments remain processing until their wallet transaction status can be verified.'}</p>
    {loading && <p role="status">Loading sales data…</p>}
    {error && <div className="error" role="alert">{error} <button className="text-button" onClick={() => setRefresh(n => n + 1)}>Try again</button></div>}
    {!loading && !error && data && (view === 'history' ? <>
      {data.history.length === 0 ? <p className="empty-state">No saved sales yet. Create a tracking record or prepare a Test Wallet payment to see it here.</p> : <>
        <p className="overview-caption">Showing {page * 100 + 1}–{page * 100 + data.history.length} of {data.summary.recordCount} records, newest first.</p>
        <div className="history-list">{data.history.map(item => <button type="button" className="history-item" key={item.executionId} onClick={() => openExecution(item.executionId)}>
          <span className="history-line"><strong>{money(item.amount.value)}</strong><span className={`history-status ${item.status.toLowerCase()}`}>{statusName(item.status)}</span></span>
          <span className="history-meta">{new Date(item.createdAt).toLocaleString('en-ZA', { dateStyle: 'medium', timeStyle: 'short' })} · {item.source === 'test_wallet' ? 'Test Wallet' : 'Tracking only'}</span>
          {item.source === 'test_wallet' && item.status === 'PROCESSING' && <span className="history-meta">Wallet transaction status unverified</span>}
          <span className="history-legs">{item.legs.map((leg, i) => <span key={i}>{leg.label}: {money(leg.amount.value)} · {statusName(leg.status)}</span>)}</span>
          <span className="history-ref">{item.executionId}</span>
        </button>)}</div>
        {data.summary.recordCount > 100 && <div className="history-pagination"><button className="ghost" disabled={page === 0} onClick={() => setPage(n => n - 1)}>Previous</button><button className="ghost" disabled={(page + 1) * 100 >= data.summary.recordCount} onClick={() => setPage(n => n + 1)}>Next</button></div>}
      </>}
    </> : <>
      {data.summary.recordCount === 0 ? <p className="empty-state">No sales records yet. Reports will appear when you create a payment record.</p> : <>
        <div className="report-grid">
          <div className="report-stat"><span>Completed test sales</span><strong>{data.summary.completedTestSales}</strong><small>Both legs confirmed</small></div>
          <div className="report-stat"><span>Completed sales value</span><strong>{money(data.summary.completedSalesValue)}</strong><small>Test Wallet sales</small></div>
          <div className="report-stat"><span>Confirmed receipts</span><strong>{money(data.summary.confirmedReceipts)}</strong><small>Includes confirmed legs of partial sales</small></div>
          <div className="report-stat"><span>Saved records</span><strong>{data.summary.recordCount}</strong><small>Includes tracking-only records</small></div>
        </div>
        {data.summary.confirmedByPot.length > 0 && <><h3 className="breakdown-title">Confirmed by pot</h3><div className="status-breakdown">{data.summary.confirmedByPot.map(pot => <div key={pot.label}><span>{pot.label}</span><strong>{money(pot.value)}</strong></div>)}</div></>}
        <h3 className="breakdown-title">Record statuses</h3><div className="status-breakdown">{Object.entries(data.summary.statusCounts).map(([status, count]) => <div key={status}><span>{statusName(status)}</span><strong>{count}</strong></div>)}</div>
        <p className="payment-notice">Amounts are test funds. Observed Open Payments amounts do not confirm a wallet transaction. Unverified and tracking-only records are excluded from completed sales and confirmed receipts.</p>
      </>}
    </>)}
  </>
}
