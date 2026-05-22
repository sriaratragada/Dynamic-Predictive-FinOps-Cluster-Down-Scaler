import { useState } from 'react'

interface Props {
  onOpenSettings: () => void
}

const DISMISS_KEY = 'finops-demo-banner-dismissed'

export default function DemoBanner({ onOpenSettings }: Props) {
  const [visible, setVisible] = useState(
    () => sessionStorage.getItem(DISMISS_KEY) !== '1'
  )

  if (!visible) return null

  function dismiss() {
    sessionStorage.setItem(DISMISS_KEY, '1')
    setVisible(false)
  }

  return (
    <div className="demo-banner">
      <span className="demo-banner-icon">🧪</span>
      <span className="demo-banner-text">
        Running with <strong>synthetic demo data</strong> — no Kubernetes or
        Prometheus required.
      </span>
      <button className="demo-banner-cta" onClick={onOpenSettings}>
        Connect your cluster →
      </button>
      <button
        className="demo-banner-dismiss"
        onClick={dismiss}
        aria-label="Dismiss"
      >
        ×
      </button>
    </div>
  )
}
