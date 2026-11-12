import { useState } from 'react'

export default function ConceptDemo({ exit }: { exit: () => void }) {
  const [step, setStep] = useState(0)
  return <>
    <span className="eyebrow">ILLUSTRATIVE EXAMPLE · {step + 1} OF 3</span>
    <h2>{['A customer makes a sale', 'The sale is split into pots', 'The merchant sees the results'][step]}</h2>
    <p className="lede">{['A merchant enters a sale. KwikPay prepares a payment plan using the merchant’s split rules.', 'The example routes 80% to business income and 20% to a stock reserve.', 'An example report brings the sale and its allocations together.'][step]}</p>
    {step === 0 && <div className="concept-sale"><span>Example sale</span><strong>R100.00</strong><small>Customer checkout</small></div>}
    {step === 1 && <><div className="held"><span>Example sale</span><strong>R100.00</strong></div><div className="split-bar concept-bar"><span className="seg blue" style={{ width: '80%' }}/><span className="seg green" style={{ width: '20%' }}/></div><div className="concept-rows"><div><span>Business income · 80%</span><strong>R80.00</strong></div><div><span>Stock reserve · 20%</span><strong>R20.00</strong></div></div><p className="payment-notice">KwikPay holds R0.00 in this example.</p></>}
    {step === 2 && <><div className="report-grid"><div className="report-stat"><span>Example sales</span><strong>1</strong></div><div className="report-stat"><span>Example sales value</span><strong>R100.00</strong></div></div><h3 className="breakdown-title">Example allocation by pot</h3><div className="status-breakdown"><div><span>Business income</span><strong>R80.00</strong></div><div><span>Stock reserve</span><strong>R20.00</strong></div></div></>}
    <p className="concept-disclaimer">Example only. No payment is sent and these figures are not included in your sales or reports.</p>
    <div className="concept-actions">{step > 0 && <button className="secondary" onClick={() => setStep(step - 1)}>Back</button>}{step < 2 ? <button className="primary" onClick={() => setStep(step + 1)}>{step === 0 ? 'See the split' : 'See example report'}</button> : <button className="primary" onClick={exit}>Finish walkthrough</button>}</div>
    <button className="text-button concept-exit" onClick={exit}>Exit example</button>
  </>
}
