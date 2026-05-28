import { useState } from 'react'
import type { ConfigData, NLConfigResult } from '../api'
import { parseNaturalLanguageConfig, applyNaturalLanguageConfig } from '../api'

interface Props {
  config: ConfigData
  onSaved: (cfg: ConfigData) => void
}

export default function NLConfigBar({ config, onSaved }: Props) {
  const [prompt, setPrompt] = useState('')
  const [loading, setLoading] = useState(false)
  const [preview, setPreview] = useState<NLConfigResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [applying, setApplying] = useState(false)

  async function handleSubmit() {
    if (!prompt.trim()) return

    if (!config.openai_api_key_set) {
      setError('Set your OpenAI API key in the LLM section below first.')
      return
    }

    setLoading(true)
    setError(null)
    setPreview(null)
    try {
      const result = await parseNaturalLanguageConfig(prompt.trim())
      setPreview(result)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to parse configuration')
    } finally {
      setLoading(false)
    }
  }

  async function handleApply() {
    if (!preview) return
    setApplying(true)
    setError(null)
    try {
      const saved = await applyNaturalLanguageConfig(preview.config)
      onSaved(saved)
      setPreview(null)
      setPrompt('')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to apply changes')
    } finally {
      setApplying(false)
    }
  }

  function handleCancel() {
    setPreview(null)
    setError(null)
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  return (
    <div className="nl-config-bar">
      <div className="nl-config-bar-label">
        <span className="nl-config-bar-icon">AI</span>
        Natural-Language Config
      </div>

      <div className="nl-config-input-row">
        <input
          className="nl-config-input"
          type="text"
          placeholder="Describe your scaling policy in plain English..."
          value={prompt}
          onChange={e => setPrompt(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={loading || applying}
        />
        <button
          className="btn-primary nl-config-submit"
          onClick={handleSubmit}
          disabled={loading || applying || !prompt.trim()}
        >
          {loading ? 'Parsing...' : 'Parse'}
        </button>
      </div>

      {error && (
        <div className="nl-config-error">{error}</div>
      )}

      {preview && (
        <div className="nl-config-preview">
          <div className="nl-config-explanation">{preview.explanation}</div>

          {preview.diff.length > 0 && (
            <div className="nl-config-diff">
              <div className="nl-config-diff-header">Changes</div>
              {preview.diff.map((d, i) => (
                <div key={i} className="nl-config-diff-row">
                  <span className="nl-config-diff-field">{d.field}</span>
                  <span className="nl-config-diff-old">{String(d.old ?? '(unset)')}</span>
                  <span className="nl-config-diff-arrow">&rarr;</span>
                  <span className="nl-config-diff-new">{String(d.new)}</span>
                </div>
              ))}
            </div>
          )}

          <div className="nl-config-actions">
            <button
              className="btn-ghost"
              onClick={handleCancel}
              disabled={applying}
            >
              Cancel
            </button>
            <button
              className="btn-primary"
              onClick={handleApply}
              disabled={applying}
            >
              {applying ? 'Applying...' : 'Apply Changes'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
