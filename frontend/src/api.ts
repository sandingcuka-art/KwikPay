import type { LegacySaleResponse, PaymentPlan, SplitRules } from './types'

const API_BASE = import.meta.env.VITE_CORE_API_URL ?? ''
export const LIVE = import.meta.env.VITE_USE_LIVE_API !== 'false'

const wallets: Record<string, string> = {
  supplier: 'https://wallet.example/supplier',
  salaries: 'https://wallet.example/payroll',
  maintenance: 'https://wallet.example/maintenance',
  profit: 'https://wallet.example/merchant'
}

const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))
const toMinor = (amount: number) => Math.round(amount * 100)

function buildPlan(amount: number, response: LegacySaleResponse, rules: SplitRules): PaymentPlan {
  const percentage: Record<string, number> = {
    supplier: rules.supplier,
    salaries: rules.salaries,
    maintenance: rules.maintenance,
    profit: Math.max(0, 100 - rules.supplier - rules.salaries - rules.maintenance)
  }

  return {
    id: `plan_${crypto.randomUUID().slice(0, 8)}`,
    paymentId: response.payment?.id,
    saleId: response.payment?.id ?? `sale_${crypto.randomUUID().slice(0, 8)}`,
    shopId: 'kwikpay-demo-shop',
    assetCode: 'ZAR',
    assetScale: 2,
    totalMinor: toMinor(amount),
    status: 'PREVIEW',
    legs: Object.entries(response.split).map(([label, value]) => ({
      id: `leg_${crypto.randomUUID().slice(0, 8)}`,
      label,
      amountMinor: toMinor(value),
      percentage: percentage[label] ?? 0,
      walletAddress: wallets[label] ?? 'https://wallet.example/merchant',
      status: 'PENDING'
    }))
  }
}

export async function createPaymentPlan(amount: number, rules: SplitRules): Promise<PaymentPlan> {
  if (LIVE) {
    const response = await fetch(`${API_BASE}/api/sales`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ amount, ...rules, shopId: 'kwikpay-demo-shop', currency: 'ZAR' })
    })
    if (!response.ok) {
      const error = await response.json().catch(() => null)
      throw new Error(error?.detail ?? 'Core API unavailable. Check that the Python server is running.')
    }
    const sale = (await response.json()) as LegacySaleResponse
    return buildPlan(amount, sale, rules)
  }

  await sleep(450)
  const splitTotal = rules.supplier + rules.salaries + rules.maintenance
  if (splitTotal > 100) throw new Error('Split rules cannot exceed 100%')

  const response: LegacySaleResponse = {
    amount,
    split: {
      supplier: amount * (rules.supplier / 100),
      salaries: amount * (rules.salaries / 100),
      maintenance: amount * (rules.maintenance / 100),
      profit: amount * ((100 - splitTotal) / 100)
    }
  }
  return buildPlan(amount, response, rules)
}

export async function executePayment(plan: PaymentPlan): Promise<PaymentPlan> {
  if (LIVE) {
    const response = await fetch(`${API_BASE}/api/payment-executions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(plan)
    })
    if (!response.ok) throw new Error('Payment execution failed')
    return response.json()
  }

  await sleep(650)
  return { ...plan, status: 'AWAITING_CONSENT' }
}

export async function approveConsent(plan: PaymentPlan): Promise<PaymentPlan> {
  if (LIVE) throw new Error('Live customer consent is not implemented yet.')
  await sleep(900)
  return {
    ...plan,
    status: 'COMPLETED',
    legs: plan.legs.map(leg => ({ ...leg, status: 'COMPLETED' }))
  }
}
