import { useEffect, useState } from 'react'
import { Download } from 'lucide-react'

type AppRelease = { name: string; filename: string; version: string; bytes: number; sha256: string; minSdk: number }
type Manifest = { apps: AppRelease[] }

export default function AndroidDownloads() {
  const [manifest, setManifest] = useState<Manifest | null>(null)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setError(''); setManifest(null)
    fetch('/downloads/manifest.json', { credentials: 'same-origin', cache: 'no-store', signal: controller.signal })
      .then(async response => {
        if (!response.ok) throw new Error(response.status === 401 || response.status === 403 ? 'Dashboard access was denied. Sign in and try again.' : 'App downloads are unavailable.')
        const data = await response.json() as Manifest
        const names = ['kwikpay-customer-0.2.0.apk', 'kwikpay-merchant-0.2.2.apk']
        if (!Array.isArray(data.apps) || data.apps.length !== 2 || data.apps.some(app => !names.includes(app.filename) || !/^[a-f0-9]{64}$/.test(app.sha256) || !Number.isInteger(app.bytes) || app.bytes <= 0)) throw new Error('App release information is unavailable.')
        setManifest(data)
      })
      .catch(e => { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : 'App downloads are unavailable.') })
    return () => controller.abort()
  }, [retry])

  return <>
    <h2>Install KwikPay on Android</h2>
    <p className="lede">Signed Test Wallet demo apps for your team. Sign in to this dashboard on the phone, then download the app you need.</p>
    {!manifest && !error && <p role="status">Loading app downloads…</p>}
    {error && <div className="error" role="alert">{error} <button className="text-button" onClick={() => setRetry(n => n + 1)}>Try again</button></div>}
    {manifest && <div className="app-download-list">{manifest.apps.map(app => <article className="app-download-card" key={app.filename}>
      <h3>{app.name}</h3>
      <p>{app.filename.includes('merchant') ? 'Create Test Wallet requests up to R10 and see merchant history. A merchant access key is required.' : 'Scan a merchant request and approve using your own Test Wallet.'}</p>
      <div className="app-download-meta"><span>Version {app.version}</span><span>{(app.bytes / 1024 / 1024).toFixed(1)} MB</span><span>Android API {app.minSdk}+</span></div>
      <a className="primary app-download-link" href={`/downloads/${app.filename}`} download><Download size={17}/> Download APK</a>
      <span className="app-download-hash">SHA-256: <code>{app.sha256}</code></span>
    </article>)}</div>}
    <h3>Install on your phone</h3>
    <ol className="app-download-guide"><li>Open this dashboard on your Android phone and download the APK.</li><li>Open the downloaded file. If Android asks, allow installs from your browser and review the app details.</li><li>For the merchant app, ask the demo owner for the merchant access key and enter it in Merchant access. For the customer app, add your own Test Wallet address in Wallet settings.</li></ol>
    <p className="payment-notice">These are Test Wallet demo apps. Wallet addresses and payment status are sent to the KwikPay demo service and Interledger. Contact your demo organiser for support. Existing debug-signed installs cannot be updated by these APKs; preserve any local history before removing an old install.</p>
  </>
}
