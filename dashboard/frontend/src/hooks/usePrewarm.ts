import { useCallback, useEffect, useRef, useState } from 'react'
import { sendPrewarmSignal, fetchPrewarmHistory } from '../api'
import type { PrewarmHistoryEntry } from '../api'

interface PrewarmState {
  status: string
  recentSignals: Array<{ signal: string; timestamp: number; result: string }>
}

const DEBOUNCE_MS = 500
const POLL_INTERVAL_MS = 10_000
const INTERACTIVE_SELECTOR = 'button, a, input, textarea, [role="button"]'

export function usePrewarm(enabled: boolean, serviceUrl: string = ''): PrewarmState {
  const [state, setState] = useState<PrewarmState>({
    status: 'idle',
    recentSignals: [],
  })
  const lastFiredRef = useRef<number>(0)
  const enabledRef = useRef(enabled)
  enabledRef.current = enabled
  const serviceUrlRef = useRef(serviceUrl)
  serviceUrlRef.current = serviceUrl

  const fireSignal = useCallback(async (signal: string) => {
    if (!enabledRef.current) return
    const now = Date.now()
    if (now - lastFiredRef.current < DEBOUNCE_MS) return
    lastFiredRef.current = now

    try {
      const result = await sendPrewarmSignal(signal, serviceUrlRef.current || 'default')
      setState(prev => ({
        status: result.status,
        recentSignals: [
          { signal, timestamp: now, result: result.status },
          ...prev.recentSignals,
        ].slice(0, 50),
      }))
    } catch {
      // Silently ignore network errors for pre-warm signals
    }
  }, [])

  useEffect(() => {
    if (!enabled) return

    const handleMouseOver = (e: MouseEvent) => {
      const target = e.target as Element
      if (target?.closest?.(INTERACTIVE_SELECTOR)) {
        fireSignal('hover')
      }
    }

    const handleFocus = (e: FocusEvent) => {
      const target = e.target as Element
      if (target?.tagName === 'INPUT' || target?.tagName === 'TEXTAREA') {
        fireSignal('focus')
      }
    }

    const handleClick = (e: MouseEvent) => {
      const target = e.target as Element
      if (target?.closest?.('form[action*="login"], [data-login], .login-form')) {
        fireSignal('input_focus')
      }
    }

    document.addEventListener('mouseover', handleMouseOver, { passive: true })
    document.addEventListener('focusin', handleFocus, { passive: true })
    document.addEventListener('click', handleClick, { passive: true })

    return () => {
      document.removeEventListener('mouseover', handleMouseOver)
      document.removeEventListener('focusin', handleFocus)
      document.removeEventListener('click', handleClick)
    }
  }, [enabled, fireSignal])

  useEffect(() => {
    if (!enabled) return

    const poll = async () => {
      try {
        const data = await fetchPrewarmHistory()
        const recent = data.history.slice(-50).reverse().map(entry => ({
          signal: entry.signal,
          timestamp: new Date(entry.timestamp).getTime(),
          result: entry.result,
        }))
        setState(prev => ({
          ...prev,
          status: recent.length > 0 ? recent[0].result : 'idle',
          recentSignals: recent,
        }))
      } catch {
        // Silently ignore polling errors
      }
    }

    poll()
    const id = setInterval(poll, POLL_INTERVAL_MS)
    return () => clearInterval(id)
  }, [enabled])

  return state
}
