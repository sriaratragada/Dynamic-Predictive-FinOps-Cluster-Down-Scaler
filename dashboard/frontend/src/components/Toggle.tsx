interface ToggleProps {
  checked: boolean
  onChange: (v: boolean) => void
  disabled?: boolean
}

export default function Toggle({ checked, onChange, disabled }: ToggleProps) {
  return (
    <button
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      type="button"
      className={`toggle ${checked ? 'toggle-on' : 'toggle-off'}`}
      onClick={() => !disabled && onChange(!checked)}
    >
      <span className="toggle-thumb" />
    </button>
  )
}
