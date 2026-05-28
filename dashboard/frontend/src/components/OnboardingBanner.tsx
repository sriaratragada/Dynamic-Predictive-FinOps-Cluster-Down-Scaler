import { useState } from 'react'
import type { ConfigData, ControllerStatus } from '../api'

interface Props {
  config: ConfigData
  controllerStatus: ControllerStatus | null
  onNavigate: (page: string) => void
}

export default function OnboardingBanner({ config, controllerStatus, onNavigate }: Props) {
  const [dismissed, setDismissed] = useState(false)

  const steps = [
    {
      label: 'Connect a cluster',
      done: config.demo_mode || (controllerStatus?.connected ?? false),
      action: () => onNavigate('cluster'),
      hint: 'or stay in Demo Mode to explore',
    },
    {
      label: 'Set your schedule',
      done: config.business_hours_start !== '07:00' || config.business_hours_end !== '19:00' || config.business_days !== '0,1,2,3,4',
      hint: 'business hours, days, timezone',
    },
    {
      label: 'Enable dry-run mode',
      done: config.dry_run,
      hint: 'watch what would happen for a week before going live',
    },
    {
      label: 'Add critical apps to safelist',
      done: !!config.exclude_deployments,
      hint: 'Settings → App Safelist',
    },
    {
      label: 'Turn on features',
      done: config.enable_prewarm || config.enable_prophet || config.enable_metric_override,
      action: () => onNavigate('features'),
      hint: 'start with Metric Override for extra safety',
    },
  ]

  const completedCount = steps.filter(s => s.done).length
  const allDone = completedCount === steps.length

  if (dismissed || allDone) return null

  return (
    <div className="onboarding-banner" data-reveal="0">
      <div className="onboarding-header">
        <div>
          <div className="onboarding-tag">// GET STARTED</div>
          <div className="onboarding-title">Welcome to FinOps Scaler</div>
          <div className="onboarding-desc">
            {completedCount === 0
              ? 'Complete these steps to start saving on your Kubernetes cluster.'
              : `${completedCount} of ${steps.length} steps done — you're making progress.`}
          </div>
        </div>
        <button className="onboarding-dismiss" onClick={() => setDismissed(true)} title="Dismiss">×</button>
      </div>
      <div className="onboarding-steps">
        {steps.map((step, i) => (
          <div
            key={i}
            className={`onboarding-step ${step.done ? 'onboarding-step--done' : ''}`}
            onClick={step.action}
            style={step.action ? { cursor: 'pointer' } : undefined}
          >
            <div className="onboarding-step-check">
              {step.done ? '✓' : (i + 1)}
            </div>
            <div>
              <div className="onboarding-step-label">{step.label}</div>
              {step.hint && <div className="onboarding-step-hint">{step.hint}</div>}
            </div>
          </div>
        ))}
      </div>
      <div className="onboarding-progress">
        <div className="onboarding-progress-bar" style={{ width: `${(completedCount / steps.length) * 100}%` }} />
      </div>
    </div>
  )
}
