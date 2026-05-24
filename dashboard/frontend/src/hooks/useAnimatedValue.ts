import { useEffect, useRef, useState } from 'react'

export function useAnimatedValue(target: number, duration = 600): number {
  const [display, setDisplay] = useState(target)
  const startRef = useRef<number | null>(null)
  const fromRef  = useRef(target)
  const frameRef = useRef<number>(0)

  useEffect(() => {
    const from = fromRef.current
    if (from === target) return
    startRef.current = null

    const animate = (ts: number) => {
      if (startRef.current === null) startRef.current = ts
      const elapsed = ts - startRef.current
      const progress = Math.min(elapsed / duration, 1)
      const eased = 1 - Math.pow(1 - progress, 3)
      setDisplay(from + (target - from) * eased)
      if (progress < 1) frameRef.current = requestAnimationFrame(animate)
      else fromRef.current = target
    }

    frameRef.current = requestAnimationFrame(animate)
    return () => cancelAnimationFrame(frameRef.current)
  }, [target, duration])

  return display
}
