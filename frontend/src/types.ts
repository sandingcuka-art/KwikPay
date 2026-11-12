export type AllocationKey = 'supplier' | 'salaries' | 'maintenance' | 'profit'

export type SplitRules = {
  supplier: number
  salaries: number
  maintenance: number
}

export type SaleSplit = Record<AllocationKey, number>

export type LegacySaleResponse = {
  amount: number
  split: SaleSplit
  payment?: { id: string; status: 'PENDING'; shopId: string }
}

export type PaymentLegStatus = 'PENDING' | 'COMPLETED' | 'FAILED'

export type PaymentLeg = {
  id: string
  label: string
  amountMinor: number
  percentage: number
  walletAddress: string
  status: PaymentLegStatus
}

export type PaymentPlan = {
  id: string
  paymentId?: string
  saleId: string
  shopId: string
  assetCode: 'ZAR'
  assetScale: 2
  totalMinor: number
  status: 'PREVIEW' | 'AWAITING_CONSENT' | 'PROCESSING' | 'COMPLETED' | 'PARTIAL' | 'FAILED'
  legs: PaymentLeg[]
}
