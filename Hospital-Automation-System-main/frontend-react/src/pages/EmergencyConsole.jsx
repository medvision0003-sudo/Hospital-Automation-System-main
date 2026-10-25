import { useState, useEffect, useCallback } from 'react'
import {
  triggerEmergencyEvent,
  fetchWorkQueue,
  fetchAssignments,
  fetchCheckedInResponders,
  fetchAgentActions,
  fetchOrchestratorTraces,
} from '../services/emergencyService'
import './EmergencyConsole.css'

const EMERGENCY_CODES = [
  {
    code: 'CODE_BLUE',
    type: 'PATIENT_COLLAPSE',
    title: 'Code Blue',
    desc: 'Patient Collapse / Resuscitation Needed',
    color: '#1e88e5',
    badgeBg: '#e3f2fd',
  },
  {
    code: 'CODE_RED',
    type: 'FIRE',
    title: 'Code Red',
    desc: 'Fire, Smoke or Blaze Hazard',
    color: '#e53935',
    badgeBg: '#ffebee',
  },
  {
    code: 'CODE_PINK',
    type: 'INFANT_ABDUCTION',
    title: 'Code Pink',
    desc: 'Infant / Pediatric Abduction Warning',
    color: '#d81b60',
    badgeBg: '#fce4ec',
  },
  {
    code: 'CODE_SILVER',
    type: 'ACTIVE_SHOOTER',
    title: 'Code Silver',
    desc: 'Active Shooter or Armed Intruder',
    color: '#546e7a',
    badgeBg: '#eceff1',
  },
  {
    code: 'CODE_ORANGE',
    type: 'HAZMAT_SPILL',
    title: 'Code Orange',
    desc: 'Hazardous Chemical / Bio Material Spill',
    color: '#fb8c00',
    badgeBg: '#fff3e0',
  },
  {
    code: 'CODE_YELLOW',
    type: 'MISSING_PATIENT',
    title: 'Code Yellow',
    desc: 'Missing or Eloped Vulnerable Patient',
    color: '#fdd835',
    badgeBg: '#fffde7',
  },
  {
    code: 'CODE_PURPLE',
    type: 'COMBATIVE_PERSON',
    title: 'Code Purple',
    desc: 'Combative, Aggressive or Hostile Person',
    color: '#8e24aa',
    badgeBg: '#f3e5f5',
  },
  {
    code: 'CODE_BLACK',
    type: 'BOMB_THREAT',
    title: 'Code Black',
    desc: 'Bomb Threat or Suspicious Device',
    color: '#212121',
    badgeBg: '#e0e0e0',
  },
  {
    code: 'CODE_GREEN',
    type: 'EVACUATION_ALERT',
    title: 'Code Green',
    desc: 'Facility Evacuation / Disaster Protocol',
    color: '#43a047',
    badgeBg: '#e8f5e9',
  },
  {
    code: 'CODE_BROWN',
    type: 'MASS_CASUALTY',
    title: 'Code Brown',
    desc: 'External Mass Casualty / Influx Alert',
    color: '#6d4c41',
    badgeBg: '#efebe9',
  },
]

export default function EmergencyConsole() {
  const [selectedCode, setSelectedCode] = useState(null)
  const [location, setLocation] = useState('')
  const [notes, setNotes] = useState('')
  const [reportedBy, setReportedBy] = useState('1')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [feedback, setFeedback] = useState(null)

  const [workQueue, setWorkQueue] = useState([])
  const [assignments, setAssignments] = useState([])
  const [responders, setResponders] = useState([])
  const [agentActions, setAgentActions] = useState([])
  const [traces, setTraces] = useState([])
  const [loading, setLoading] = useState(true)

  const loadEmergencyData = useCallback(async () => {
    try {
      const [wqData, assignData, checkinData, actionsData, traceData] = await Promise.allSettled([
        fetchWorkQueue(),
        fetchAssignments(),
        fetchCheckedInResponders(),
        fetchAgentActions(),
        fetchOrchestratorTraces(),
      ])

      if (wqData.status === 'fulfilled') setWorkQueue(wqData.value || [])
      if (assignData.status === 'fulfilled') setAssignments(assignData.value || [])
      if (checkinData.status === 'fulfilled') setResponders(checkinData.value || [])
      if (actionsData.status === 'fulfilled') setAgentActions(actionsData.value || [])
      if (traceData.status === 'fulfilled') setTraces(traceData.value || [])
    } catch (err) {
      console.error('Failed loading emergency console data:', err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadEmergencyData()
    const interval = setInterval(loadEmergencyData, 5000)
    return () => clearInterval(interval)
  }, [loadEmergencyData])

  const handleOpenTriggerModal = (codeObj) => {
    setSelectedCode(codeObj)
    setLocation('')
    setNotes('')
    setReportedBy('1')
    setFeedback(null)
  }

  const handleDispatchEmergency = async (e) => {
    e.preventDefault()
    if (!selectedCode) return

    setIsSubmitting(true)
    setFeedback(null)

    try {
      const parsedReporter = parseInt(reportedBy, 10) || 1
      const payload = {
        emergency_type: selectedCode.type,
        location: location.trim() || 'General Emergency Ward',
        notes: notes.trim() || 'Triggered via Emergency Console',
        reported_by: parsedReporter,
        priority: 'CRITICAL',
      }

      const res = await triggerEmergencyEvent('EMERGENCY_RESPONSE', payload, true)
      if (res.status === 'PARTIAL_SUCCESS') {
        setFeedback({ type: 'success', message: `Emergency ${selectedCode.title} Broadcasted! Tasks created in Work Queue (awaiting staff check-in).` })
      } else {
        setFeedback({ type: 'success', message: `Emergency ${selectedCode.title} Broadcasted & Assigned Successfully!` })
      }
      setSelectedCode(null)
      loadEmergencyData()
    } catch (err) {
      setFeedback({ type: 'error', message: err.message || 'Error broadcasting emergency alert' })
    } finally {
      setIsSubmitting(false)
    }
  }

  const criticalQueue = workQueue.filter(
    (item) => item.priority === 'CRITICAL' || item.priority === 'HIGH'
  )

  const preemptedAssignments = assignments.filter(
    (a) => a.status === 'PREEMPTED'
  )

  const activeEmergency = criticalQueue.find(
    (item) => item.status === 'PENDING_ASSIGNED' || item.status === 'ASSIGNED'
  )

  return (
    <div className="emergency-console-page">
      <div className="emergency-console-header">
        <div>
          <div className="emergency-title-group">
            <span className="material-symbols-outlined emergency-icon">e911_emergency</span>
            <h2 className="text-headline-lg" style={{ margin: 0 }}>Emergency Command Console</h2>
          </div>
          <p className="emergency-subtitle">
            Broadcast emergency hospital codes, auto-trigger SOP workflows, monitor worker preemption, and track AI agent response logs.
          </p>
        </div>
        <div className="emergency-header-actions">
          <button className="refresh-btn" onClick={loadEmergencyData} title="Refresh Live Console">
            <span className="material-symbols-outlined">refresh</span>
          </button>
        </div>
      </div>

      {feedback && (
        <div
          style={{
            padding: '12px 20px',
            borderRadius: '12px',
            marginBottom: '20px',
            background: feedback.type === 'success' ? '#e8f5e9' : '#ffebee',
            color: feedback.type === 'success' ? '#2e7d32' : '#c62828',
            fontWeight: 600,
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
          }}
        >
          <span className="material-symbols-outlined">
            {feedback.type === 'success' ? 'check_circle' : 'error'}
          </span>
          {feedback.message}
        </div>
      )}

      {activeEmergency && (
        <div className="banner-active-emergency">
          <div className="banner-content">
            <span className="material-symbols-outlined banner-icon">warning</span>
            <div className="banner-text">
              <h3>ACTIVE EMERGENCY BROADCAST IN PROGRESS</h3>
              <p>
                {activeEmergency.task?.task_name || 'Emergency Response'} &bull; Department: {activeEmergency.department?.name || 'Emergency'}
              </p>
            </div>
          </div>
          <div className="banner-badge">
            PRIORITY: {activeEmergency.priority}
          </div>
        </div>
      )}

      <h3 className="console-section-title">
        <span className="material-symbols-outlined" style={{ color: '#d32f2f' }}>notifications_active</span>
        Emergency Code Dispatcher (Panic Buttons)
      </h3>

      <div className="code-grid">
        {EMERGENCY_CODES.map((item) => (
          <div
            key={item.code}
            className="code-card"
            style={{ borderLeft: `6px solid ${item.color}` }}
            onClick={() => handleOpenTriggerModal(item)}
          >
            <div>
              <div className="code-card-header">
                <span
                  className="code-badge"
                  style={{ backgroundColor: item.badgeBg, color: item.color }}
                >
                  {item.code}
                </span>
                <span className="material-symbols-outlined" style={{ color: item.color, fontSize: '20px' }}>
                  campaign
                </span>
              </div>
              <h4 className="code-title">{item.title}</h4>
              <p className="code-desc">{item.desc}</p>
            </div>
            <div className="code-card-footer">
              <button
                className="trigger-btn"
                style={{ backgroundColor: item.color }}
                onClick={(e) => {
                  e.stopPropagation()
                  handleOpenTriggerModal(item)
                }}
              >
                Broadcast Code
              </button>
            </div>
          </div>
        ))}
      </div>

      <div className="console-two-col">
        <div className="console-card">
          <div className="card-header-row">
            <h4 className="card-title">
              <span className="material-symbols-outlined" style={{ color: '#1565c0' }}>format_list_bulleted</span>
              Emergency Work Queue & SOP Tasks
            </h4>
            <span style={{ fontSize: '0.8rem', opacity: 0.7 }}>{criticalQueue.length} Active Items</span>
          </div>
          {criticalQueue.length === 0 ? (
            <div className="empty-state">No critical emergency items currently in dispatch queue.</div>
          ) : (
            <div className="item-list">
              {criticalQueue.map((item, idx) => (
                <div key={item.work_id || item.id || idx} className="queue-item-row">
                  <div className="queue-item-main">
                    <span className="queue-item-title">
                      {item.task?.task_name || `Queue Item #${item.work_id || item.id}`}
                    </span>
                    <span className="queue-item-meta">
                      Dept: {item.department?.name || 'N/A'} &bull; Created: {new Date(item.created_at || Date.now()).toLocaleTimeString()}
                    </span>
                  </div>
                  <span className={`status-tag ${item.priority === 'CRITICAL' ? 'critical' : 'pending'}`}>
                    {item.status}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="console-card">
          <div className="card-header-row">
            <h4 className="card-title">
              <span className="material-symbols-outlined" style={{ color: '#ef6c00' }}>flaky</span>
              Preempted Staff Assignments
            </h4>
            <span style={{ fontSize: '0.8rem', opacity: 0.7 }}>{preemptedAssignments.length} Preempted</span>
          </div>
          {preemptedAssignments.length === 0 ? (
            <div className="empty-state">No routine tasks currently preempted for emergency overrides.</div>
          ) : (
            <div className="item-list">
              {preemptedAssignments.map((a, idx) => (
                <div key={a.assignment_id || a.id || idx} className="queue-item-row">
                  <div className="queue-item-main">
                    <span className="queue-item-title">
                      {a.employee?.first_name ? `${a.employee.first_name} ${a.employee.last_name}` : `Worker #${a.employee_id}`}
                    </span>
                    <span className="queue-item-meta">
                      Task: {a.task?.task_name || 'Routine Task'} &bull; Status: PREEMPTED
                    </span>
                  </div>
                  <span className="status-tag preempted">
                    PREEMPTED
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="console-two-col">
        <div className="console-card">
          <div className="card-header-row">
            <h4 className="card-title">
              <span className="material-symbols-outlined" style={{ color: '#2e7d32' }}>badge</span>
              Active Checked-In Responders
            </h4>
            <span style={{ fontSize: '0.8rem', opacity: 0.7 }}>{responders.length} Checked In</span>
          </div>
          {responders.length === 0 ? (
            <div className="empty-state">No checked-in personnel found.</div>
          ) : (
            <div className="item-list">
              {responders.slice(0, 8).map((r, idx) => (
                <div key={r.checkin_id || r.id || r.employee_id || idx} className="queue-item-row">
                  <div className="queue-item-main">
                    <span className="queue-item-title">
                      {r.employee ? `${r.employee.first_name} ${r.employee.last_name}` : `Employee ID #${r.employee_id}`}
                    </span>
                    <span className="queue-item-meta">
                      Role: {r.employee?.role || 'Staff'} &bull; Status: {r.status}
                    </span>
                  </div>
                  <span className="status-tag completed">
                    ACTIVE
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="console-card">
          <div className="card-header-row">
            <h4 className="card-title">
              <span className="material-symbols-outlined" style={{ color: '#8e24aa' }}>smart_toy</span>
              Emergency Agent Trace Log
            </h4>
            <span style={{ fontSize: '0.8rem', opacity: 0.7 }}>{agentActions.length} Actions Recorded</span>
          </div>
          {agentActions.length === 0 ? (
            <div className="empty-state">No recent emergency agent logs.</div>
          ) : (
            <div className="item-list">
              {agentActions.slice(0, 6).map((act, idx) => (
                <div key={act.agent_action_id || act.id || idx} className="queue-item-row">
                  <div className="queue-item-main">
                    <span className="queue-item-title">
                      {act.agent_name || 'EmergencyResponseAgent'} &bull; {act.action_type || 'DISPATCH'}
                    </span>
                    <span className="queue-item-meta">
                      Time: {new Date(act.timestamp || Date.now()).toLocaleTimeString()} &bull; Status: {act.status}
                    </span>
                  </div>
                  <span className="status-tag pending">
                    {act.status}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {selectedCode && (
        <div className="modal-backdrop" onClick={() => setSelectedCode(null)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3 style={{ color: selectedCode.color }}>
                Trigger {selectedCode.title}
              </h3>
              <button className="close-btn" onClick={() => setSelectedCode(null)}>&times;</button>
            </div>
            <form onSubmit={handleDispatchEmergency}>
              <div className="form-group">
                <label>Reporter Employee ID</label>
                <input
                  type="number"
                  className="form-input"
                  placeholder="e.g. 1"
                  value={reportedBy}
                  onChange={(e) => setReportedBy(e.target.value)}
                  required
                />
              </div>

              <div className="form-group">
                <label>Incident Location / Ward / Room</label>
                <input
                  type="text"
                  className="form-input"
                  placeholder="e.g. Emergency Ward A, Room 104"
                  value={location}
                  onChange={(e) => setLocation(e.target.value)}
                  required
                />
              </div>

              <div className="form-group">
                <label>Emergency Notes & Details</label>
                <textarea
                  className="form-input"
                  style={{ height: '80px', resize: 'none' }}
                  placeholder="Describe the condition or situation..."
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                />
              </div>

              <div className="modal-actions">
                <button type="button" className="cancel-btn" onClick={() => setSelectedCode(null)}>
                  Cancel
                </button>
                <button
                  type="submit"
                  className="confirm-dispatch-btn"
                  style={{ backgroundColor: selectedCode.color }}
                  disabled={isSubmitting}
                >
                  {isSubmitting ? 'Broadcasting...' : `Confirm Broadcast (${selectedCode.code})`}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
