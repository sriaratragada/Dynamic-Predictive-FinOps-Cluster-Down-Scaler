import type { ConfigData, StatusData } from '../api'

interface Props {
  config:  ConfigData
  status:  StatusData | null
  onEdit:  () => void
}

const DAY_ABR = ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN']

function parseDays(str: string): number[] {
  return str.split(',').map(s => parseInt(s.trim())).filter(n => !isNaN(n)).sort((a, b) => a - b)
}

function formatDays(str: string): string {
  const days = parseDays(str)
  if (days.length === 0) return '—'
  // Contiguous range?
  const contiguous = days.every((d, i) => i === 0 || d === days[i - 1] + 1)
  if (contiguous && days.length >= 2) {
    return `${DAY_ABR[days[0]]}–${DAY_ABR[days[days.length - 1]]}`
  }
  return days.map(d => DAY_ABR[d] ?? '?').join(' · ')
}

function getNextEvent(config: ConfigData, status: StatusData | null): string {
  if (!status) return '—'
  try {
    const partsArr = new Intl.DateTimeFormat('en-US', {
      timeZone: config.timezone || 'UTC',
      hour: '2-digit', minute: '2-digit', hour12: false,
    }).formatToParts(new Date())
    const parts    = Object.fromEntries(partsArr.map(p => [p.type, p.value]))
    const nowMins  = parseInt(parts.hour) * 60 + parseInt(parts.minute)

    const [sh, sm] = config.business_hours_start.split(':').map(Number)
    const [eh, em] = config.business_hours_end.split(':').map(Number)
    const startMins  = sh * 60 + sm
    const endMins    = eh * 60 + em
    const prewarm    = config.prewarm_minutes ?? 15

    const diff = (target: number) => {
      const d = target > nowMins ? target - nowMins : target + 1440 - nowMins
      const h = Math.floor(d / 60), m = d % 60
      return h > 0 ? `${h}h ${m}m` : `${m}m`
    }

    return status.scaled_down
      ? `scale-up in ${diff(startMins - prewarm)}`
      : `scale-down in ${diff(endMins)}`
  } catch {
    return '—'
  }
}

export default function ScheduleStrip({ config, status, onEdit }: Props) {
  const hibernating = status?.scaled_down ?? false
  const next        = getNextEvent(config, status)

  return (
    <div className="schedule-strip" data-reveal="1">
      {/* Mode pill */}
      <div className={`schedule-state schedule-state--${hibernating ? 'idle' : 'active'}`}>
        <span className="schedule-state-dot" />
        {hibernating ? 'HIBERNATING' : 'ACTIVE'}
      </div>

      <div className="schedule-strip-sep" />

      <div className="schedule-kv">
        <span className="schedule-k">SCHEDULE</span>
        <span className="schedule-v">
          {formatDays(config.business_days)} · {config.business_hours_start}–{config.business_hours_end}
        </span>
      </div>

      <div className="schedule-kv">
        <span className="schedule-k">TZ</span>
        <span className="schedule-v">{config.timezone || 'UTC'}</span>
      </div>

      <div className="schedule-kv">
        <span className="schedule-k">NEXT</span>
        <span className="schedule-v schedule-next">{next}</span>
      </div>

      <button className="schedule-edit-btn" onClick={onEdit}>
        Edit schedule ›
      </button>
    </div>
  )
}
