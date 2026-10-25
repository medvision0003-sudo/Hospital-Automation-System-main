import { useState, useEffect, useMemo } from 'react'
import { fetchSystemConfigs, updateSystemConfigs } from '../../services/systemConfigService'
import './ControlPanel.css'

const CONFIG_METADATA = {
  // Category A: Shift & Attendance
  SHIFT_END_BUFFER_MINUTES: {
    category: 'SHIFT',
    title: 'Shift-End Assignment Buffer',
    unit: 'min',
    min: 0,
    max: 120,
    step: 1,
    icon: 'timer',
  },
  SHIFT_GRACE_PERIOD_MINUTES: {
    category: 'SHIFT',
    title: 'Arrival Grace Period',
    unit: 'min',
    min: 0,
    max: 180,
    step: 5,
    icon: 'alarm_on',
  },
  ABSENTEE_CHECKIN_TIMEOUT_MINUTES: {
    category: 'SHIFT',
    title: 'Absentee Check-In Timeout',
    unit: 'min',
    min: 0,
    max: 180,
    step: 5,
    icon: 'person_off',
  },
  ABSENTEE_SNOOZE_MINUTES: {
    category: 'SHIFT',
    title: 'Absentee Snooze Duration',
    unit: 'min',
    min: 5,
    max: 60,
    step: 5,
    icon: 'snooze',
  },

  // Category B: Workload & Watchdogs
  OVERLOAD_ABOVE_AVG_THRESHOLD: {
    category: 'WORKLOAD',
    title: 'Worker Overload Threshold',
    unit: 'tasks above avg',
    min: 1,
    max: 20,
    step: 1,
    icon: 'equalizer',
  },
  STAFF_SHORTAGE_MINUTES: {
    category: 'WORKLOAD',
    title: 'Staff Shortage Timeout',
    unit: 'min',
    min: 1,
    max: 120,
    step: 1,
    icon: 'warning',
  },
  HANDOVER_REVIEW_TIMEOUT_MINUTES: {
    category: 'WORKLOAD',
    title: 'Handover Review Timeout',
    unit: 'min',
    min: 1,
    max: 120,
    step: 1,
    icon: 'published_with_changes',
  },
  STUCK_PROCESSING_MINUTES: {
    category: 'WORKLOAD',
    title: 'Stuck Event Recovery Timeout',
    unit: 'min',
    min: 1,
    max: 120,
    step: 1,
    icon: 'restart_alt',
  },

  // Category C: AI Engine & Verification
  ENABLE_SOP_LLM_PLANNER: {
    category: 'AI',
    title: 'SOP LLM Planner Engine',
    unit: 'toggle',
    icon: 'psychology',
  },
  MIN_VERIFICATION_CONFIDENCE_SCORE: {
    category: 'AI',
    title: 'Min Verification Confidence Score',
    unit: '%',
    min: 0.10,
    max: 1.00,
    step: 0.05,
    icon: 'verified',
  },
  MAX_PHOTO_VERIFICATION_ATTEMPTS: {
    category: 'AI',
    title: 'Max Photo Verification Attempts',
    unit: 'attempts',
    min: 1,
    max: 10,
    step: 1,
    icon: 'fact_check',
  },
  ENABLE_AUTOMATED_PROOF_APPROVAL: {
    category: 'AI',
    title: 'Automated Proof Approval Engine',
    unit: 'toggle',
    icon: 'auto_awesome',
  },
  ENABLE_ORCHESTRATOR_SELF_CORRECTION: {
    category: 'AI',
    title: 'Orchestrator Self-Correction',
    unit: 'toggle',
    icon: 'build_circle',
  },
  MAX_REFLECTION_ATTEMPTS: {
    category: 'AI',
    title: 'Max Self-Correction Attempts',
    unit: 'attempts',
    min: 1,
    max: 5,
    step: 1,
    icon: 'replay',
  },

  // Category D: Infrastructure
  OUTBOX_POLL_INTERVAL_SECONDS: {
    category: 'INFRASTRUCTURE',
    title: 'Outbox Poll Interval',
    unit: 'sec',
    min: 5,
    max: 300,
    step: 5,
    icon: 'sync',
  },
  OUTBOX_BATCH_LIMIT: {
    category: 'INFRASTRUCTURE',
    title: 'Outbox Sweep Batch Limit',
    unit: 'events',
    min: 1,
    max: 100,
    step: 5,
    icon: 'layers',
  },
}

export default function ControlPanel() {
  const [configs, setConfigs] = useState([])
  const [drafts, setDrafts] = useState({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [toast, setToast] = useState(null)

  const loadConfigs = async () => {
    try {
      setLoading(true)
      setError(null)
      const data = await fetchSystemConfigs()
      setConfigs(data)
      const initialDrafts = {}
      data.forEach(item => {
        initialDrafts[item.config_key] = item.config_value
      })
      setDrafts(initialDrafts)
    } catch (err) {
      setError(err.message || 'Failed to load system configurations.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadConfigs()
  }, [])

  const isDirty = useMemo(() => {
    if (!configs.length) return false
    return configs.some(item => drafts[item.config_key] !== item.config_value)
  }, [configs, drafts])

  const handleValueChange = (key, newValue) => {
    setDrafts(prev => ({
      ...prev,
      [key]: String(newValue)
    }))
  }

  const handleReset = () => {
    const initialDrafts = {}
    configs.forEach(item => {
      initialDrafts[item.config_key] = item.config_value
    })
    setDrafts(initialDrafts)
  }

  const handleSave = async () => {
    try {
      setSaving(true)
      setError(null)
      const updates = Object.keys(drafts)
        .filter(key => {
          const original = configs.find(c => c.config_key === key)
          return original && original.config_value !== drafts[key]
        })
        .map(key => ({
          config_key: key,
          config_value: drafts[key],
        }))

      if (updates.length === 0) return

      const updatedList = await updateSystemConfigs(updates)
      setConfigs(updatedList)
      const newDrafts = {}
      updatedList.forEach(item => {
        newDrafts[item.config_key] = item.config_value
      })
      setDrafts(newDrafts)

      setToast({ type: 'success', message: 'System configurations updated successfully!' })
      setTimeout(() => setToast(null), 4000)
    } catch (err) {
      setError(err.message || 'Failed to save configuration changes.')
    } finally {
      setSaving(false)
    }
  }

  // Logical sanity validation
  const gracePeriod = parseInt(drafts['SHIFT_GRACE_PERIOD_MINUTES'] || '30', 10)
  const absenteeTimeout = parseInt(drafts['ABSENTEE_CHECKIN_TIMEOUT_MINUTES'] || '30', 10)
  const hasTimingConflict = gracePeriod > absenteeTimeout

  // Group config keys by category
  const renderCard = (categoryKey, categoryTitle, categoryIcon) => {
    const items = configs.filter(c => {
      const meta = CONFIG_METADATA[c.config_key]
      return meta && meta.category === categoryKey
    })

    if (!items.length) return null

    return (
      <div className="config-card">
        <div className="card-header">
          <span className="material-symbols-outlined card-icon">{categoryIcon}</span>
          <h3 className="card-title">{categoryTitle}</h3>
        </div>
        <div className="card-body">
          {items.map(item => {
            const key = item.config_key
            const meta = CONFIG_METADATA[key] || {}
            const val = drafts[key] !== undefined ? drafts[key] : item.config_value
            const isBool = item.value_type === 'boolean'
            const isFloat = item.value_type === 'float'

            return (
              <div key={key} className="config-row">
                <div className="config-label-container">
                  <div className="config-label-row">
                    <span className="material-symbols-outlined row-icon">{meta.icon || 'tune'}</span>
                    <span className="config-label">{meta.title || key}</span>
                    <span className="tooltip-wrapper" title={item.description || ''}>
                      <span className="material-symbols-outlined tooltip-icon">info</span>
                    </span>
                  </div>
                  <span className="config-desc">{item.description}</span>
                </div>

                <div className="config-input-container">
                  {isBool ? (
                    <div className="toggle-wrapper">
                      <button
                        type="button"
                        className={`switch-toggle ${val === 'true' ? 'active' : ''}`}
                        onClick={() => handleValueChange(key, val === 'true' ? 'false' : 'true')}
                        aria-label={`Toggle ${meta.title || key}`}
                      >
                        <span className="switch-thumb" />
                      </button>
                      <span className={`switch-status ${val === 'true' ? 'active' : ''}`}>
                        {val === 'true' ? 'ENABLED' : 'DISABLED'}
                      </span>
                    </div>
                  ) : (
                    <div className="slider-control">
                      <div className="slider-row">
                        <input
                          type="range"
                          min={meta.min}
                          max={meta.max}
                          step={meta.step}
                          value={val}
                          className="config-slider"
                          onChange={(e) => handleValueChange(key, e.target.value)}
                        />
                        <span className="value-badge">
                          {isFloat
                            ? `${Math.round(parseFloat(val) * 100)}%`
                            : `${val} ${meta.unit}`}
                        </span>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    )
  }

  if (loading) {
    return (
      <div className="control-panel-container loading-state">
        <span className="material-symbols-outlined spinning">progress_activity</span>
        <p>Loading System Configurations...</p>
      </div>
    )
  }

  return (
    <div className="control-panel-container">
      <div className="panel-header">
        <div>
          <h1 className="panel-title">
            <span className="material-symbols-outlined header-icon">settings</span>
            System Control Panel
          </h1>
          <p className="panel-subtitle">
            Configure dynamic operational thresholds, autonomous watcher intervals, and AI engine flags.
          </p>
        </div>
        <button className="btn-refresh" onClick={loadConfigs} disabled={saving}>
          <span className="material-symbols-outlined">refresh</span>
          Reload
        </button>
      </div>

      {toast && (
        <div className={`toast-notification ${toast.type}`}>
          <span className="material-symbols-outlined">check_circle</span>
          {toast.message}
        </div>
      )}

      {error && (
        <div className="alert-error">
          <span className="material-symbols-outlined">error</span>
          {error}
        </div>
      )}

      {hasTimingConflict && (
        <div className="alert-warning">
          <span className="material-symbols-outlined">warning</span>
          <strong>Timing Conflict Warning:</strong> Arrival Grace Period ({gracePeriod} min) exceeds Absentee Check-In Timeout ({absenteeTimeout} min). Workers will be marked absent before grace period expires.
        </div>
      )}

      <div className="config-grid">
        {renderCard('SHIFT', 'Shift & Attendance Thresholds', 'schedule')}
        {renderCard('WORKLOAD', 'Workload & Autonomous Watchdogs', 'auto_graph')}
        {renderCard('AI', 'AI Engine & Task Verification', 'smart_toy')}
        {renderCard('INFRASTRUCTURE', 'Background Outbox Infrastructure', 'hub')}
      </div>

      {/* Floating Save Bar */}
      {isDirty && (
        <div className="floating-save-bar">
          <div className="save-bar-info">
            <span className="material-symbols-outlined warning-icon">edit_note</span>
            <span>You have unsaved configuration changes.</span>
          </div>
          <div className="save-bar-actions">
            <button className="btn-secondary" onClick={handleReset} disabled={saving}>
              Reset
            </button>
            <button className="btn-primary" onClick={handleSave} disabled={saving || hasTimingConflict}>
              {saving ? 'Saving...' : 'Save Changes'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
