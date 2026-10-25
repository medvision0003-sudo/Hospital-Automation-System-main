import { useState, useEffect, useRef } from 'react'
import { authFetch } from '../../services/apiHelper'
import './Workflow.css'

// Emergency event types mapped to hospital codes, colors, and descriptions
const EMERGENCY_EVENTS = [
  { value: 'PATIENT_COLLAPSE', code: 'CODE_BLUE',   color: '#2563eb', label: 'Patient Collapse', description: 'Cardiac or respiratory arrest requiring immediate resuscitation' },
  { value: 'FIRE',             code: 'CODE_RED',    color: '#dc2626', label: 'Fire',              description: 'Fire, smoke, or a detected blaze within the facility' },
  { value: 'INFANT_ABDUCTION', code: 'CODE_PINK',   color: '#ec4899', label: 'Infant Abduction',  description: 'Infant or child abduction' },
  { value: 'ACTIVE_SHOOTER',   code: 'CODE_SILVER', color: '#94a3b8', label: 'Active Shooter',    description: 'Active shooter, hostage situation, or an armed intruder' },
  { value: 'COMBATIVE_PERSON', code: 'CODE_PURPLE', color: '#7c3aed', label: 'Combative Person',  description: 'Combative, violent, or aggressive person on the premises' },
  { value: 'BOMB_THREAT',      code: 'CODE_BLACK',  color: '#1e293b', label: 'Bomb Threat',       description: 'Bomb threat or suspicious device' },
  { value: 'HAZMAT_SPILL',     code: 'CODE_ORANGE', color: '#ea580c', label: 'Hazmat Spill',      description: 'Hazardous material spill or chemical release' },
  { value: 'MISSING_PATIENT',  code: 'CODE_YELLOW', color: '#ca8a04', label: 'Missing Patient',   description: 'Missing or eloped patient' },
  { value: 'EVACUATION_ALERT', code: 'CODE_GREEN',  color: '#16a34a', label: 'Evacuation Alert',  description: 'Hospital evacuation or disaster alert' },
  { value: 'MASS_CASUALTY',    code: 'CODE_BROWN',  color: '#78350f', label: 'Mass Casualty',     description: 'Internal (facility-based) disaster or mass casualty influx' },
]

export default function Workflow() {
  // Trace history and selection
  const [history, setHistory] = useState([])
  const [selectedTrace, setSelectedTrace] = useState(null)
  const [loadingHistory, setLoadingHistory] = useState(true)
  const [loadingTrace, setLoadingTrace] = useState(false)
  const [selectedStep, setSelectedStep] = useState(null)

  // Event ingestion form
  const [eventType, setEventType] = useState('WORKER_CHECKED_IN')
  const [employeeId, setEmployeeId] = useState('')
  const [emergencyType, setEmergencyType] = useState('PATIENT_COLLAPSE')
  const [location, setLocation] = useState('ER Ward A, Bay 3')
  const [reportedBy, setReportedBy] = useState('')
  const [taskId, setTaskId] = useState('')
  const [dueOffset, setDueOffset] = useState('ONE_HOUR')
  const [triggering, setTriggering] = useState(false)
  const [simulateError, setSimulateError] = useState('')

  // Reference data
  const [employees, setEmployees] = useState([])
  const [tasks, setTasks] = useState([])

  const [toastMessage, setToastMessage] = useState('')

  const pollRef = useRef(null)

  const showToast = (msg) => {
    setToastMessage(msg)
    setTimeout(() => setToastMessage(''), 4000)
  }

  // Parse JSON safely
  const safeParse = (str, fallback = {}) => {
    if (!str) return fallback
    try { return JSON.parse(str) }
    catch { return fallback }
  }

  // Load trace history
  const fetchHistory = async (showLoading = false) => {
    if (showLoading) setLoadingHistory(true)
    try {
      const res = await authFetch('/orchestrator-traces/?limit=50')
      if (res.ok) setHistory(await res.json())
    } catch (err) {
      console.error('Failed to load trace history:', err)
    } finally {
      if (showLoading) setLoadingHistory(false)
    }
  }

  // Load single trace detail
  const fetchTraceDetails = async (workflowId) => {
    setLoadingTrace(true)
    setSelectedStep(null)
    try {
      const res = await authFetch(`/orchestrator-traces/${workflowId}`)
      if (res.ok) setSelectedTrace(await res.json())
    } catch (err) {
      console.error('Failed to load trace:', err)
      showToast('Error loading trace details.')
    } finally {
      setLoadingTrace(false)
    }
  }

  // Initial load and polling
  useEffect(() => {
    fetchHistory(true)
    pollRef.current = setInterval(() => fetchHistory(false), 5000)

    const loadRefData = async () => {
      try {
        const empRes = await authFetch('/employees/')
        if (empRes.ok) {
          const empData = await empRes.json()
          setEmployees(empData)
          if (empData.length > 0) setEmployeeId(String(empData[0].employee_id))
        }
      } catch { /* backend not running */ }

      try {
        const taskRes = await authFetch('/tasks/')
        if (taskRes.ok) {
          const taskData = await taskRes.json()
          const active = taskData.filter(t => t.task_state === 'ACTIVE')
          setTasks(active)
          if (active.length > 0) setTaskId(String(active[0].task_id))
        }
      } catch { /* backend not running */ }
    }
    loadRefData()

    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [])

  // Trigger event workflow
  const handleTrigger = async (e) => {
    e.preventDefault()
    if (triggering) return
    setTriggering(true)

    let payload = { trigger_source: 'CONSOLE' }

    if (eventType === 'WORKER_CHECKED_IN') {
      if (!employeeId) { showToast('Select an employee.'); setTriggering(false); return }
      payload.employee_id = parseInt(employeeId, 10)
    } else if (eventType === 'EMERGENCY_RESPONSE') {
      if (!reportedBy) { showToast('Enter a reporter ID.'); setTriggering(false); return }
      payload.emergency_type = emergencyType
      payload.location = location
      payload.reported_by = parseInt(reportedBy, 10)
    } else if (eventType === 'DYNAMIC_TASK_REQUEST') {
      if (!taskId) { showToast('Select a task definition.'); setTriggering(false); return }
      payload.task_id = parseInt(taskId, 10)
      const now = new Date()
      if (dueOffset === 'ONE_HOUR') now.setHours(now.getHours() + 1)
      else if (dueOffset === 'TWO_HOURS') now.setHours(now.getHours() + 2)
      else if (dueOffset === 'FOUR_HOURS') now.setHours(now.getHours() + 4)
      else now.setHours(now.getHours() + 24)
      payload.due_date = now.toISOString()
    }

    if (simulateError) {
      payload.simulate_error = simulateError
    }

    try {
      const res = await authFetch('/events/?sync=true', {
        method: 'POST',
        body: JSON.stringify({ event_type: eventType, payload }),
      })
      if (res.ok) {
        const data = await res.json()
        showToast(`Event triggered. Status: ${data.status}`)
        await fetchHistory(false)
        if (data.workflow_id) fetchTraceDetails(data.workflow_id)
      } else {
        const errData = await res.json().catch(() => ({}))
        showToast(`Trigger failed: ${errData.detail || errData.error || 'Server error'}`)
      }
    } catch {
      showToast('Backend not available.')
    }

    setTriggering(false)
  }

  // Derive parsed data from the selected trace
  const plannedSteps = selectedTrace ? safeParse(selectedTrace.planned_steps_json, []) : []
  const executedSteps = selectedTrace ? safeParse(selectedTrace.workflow_execution_json, []) : []
  const producedData = selectedTrace ? safeParse(selectedTrace.produced_outputs_json) : null
  const payloadData = selectedTrace ? safeParse(selectedTrace.input_payload_json) : null
  const resultData = selectedTrace ? safeParse(selectedTrace.final_result_json) : null

  // Build unified visual timeline from planned + executed steps dynamically
  const visualSteps = []
  if (selectedTrace) {
    visualSteps.push({
      label: 'Ingest Event',
      agent: 'EVENT_AGENT',
      status: 'SUCCESS',
      info: 'Event validated and ingested.'
    })

    // 1. Add all executed steps chronologically
    executedSteps.forEach((ex) => {
      if (ex.agent === 'EVENT_AGENT') return // Skip manual first step

      const label = ex.agent === 'SYSTEM_REFLECTION'
        ? 'System Reflection'
        : (ex.capability ? ex.capability.replace(/_/g, ' ') : ex.agent.replace(/_/g, ' '))

      visualSteps.push({
        label: label,
        agent: ex.agent,
        status: ex.status,
        info: ex.capability || ex.message || ex.agent,
        message: ex.message || ''
      })
    })

    // 2. Add any remaining planned steps that haven't executed yet (if workflow is active)
    const terminalStates = ['SUCCESS', 'PARTIAL_SUCCESS', 'FAILED', 'CANCELLED']
    const isTerminal = terminalStates.includes(selectedTrace.execution_status)
    if (!isTerminal) {
      plannedSteps.forEach((planStep) => {
        const alreadyExecuted = executedSteps.some(ex =>
          ex.capability === planStep.capability_name ||
          (!ex.capability && ex.agent === planStep.agent_name)
        )
        if (!alreadyExecuted) {
          visualSteps.push({
            label: planStep.capability_name.replace(/_/g, ' '),
            agent: planStep.agent_name,
            status: 'PENDING',
            info: planStep.capability_name
          })
        }
      })
    }
  }

  // Compute duration string
  const getDuration = (trace) => {
    if (!trace.completed_at || !trace.started_at) return 'N/A'
    const ms = Math.abs(new Date(trace.completed_at) - new Date(trace.started_at))
    return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(2)}s`
  }

  return (
    <div className="workflow-container">
      {/* Sidebar */}
      <aside className="workflow-sidebar">
        <div className="sidebar-header">
          <h2 className="sidebar-title">
            <span className="material-symbols-outlined">history</span>
            Orchestrator History
          </h2>
          <p className="sidebar-subtitle">Recent execution runs (polling every 5s)</p>
        </div>
        <div className="history-list custom-scrollbar">
          {loadingHistory ? (
            <div className="empty-state"><p>Loading history...</p></div>
          ) : history.length === 0 ? (
            <div className="empty-state"><p>No execution runs recorded yet.</p></div>
          ) : (
            history.map((item) => (
              <div
                key={item.workflow_id}
                className={`history-item ${selectedTrace?.workflow_id === item.workflow_id ? 'active' : ''}`}
                onClick={() => fetchTraceDetails(item.workflow_id)}
              >
                <div className="history-item-top">
                  <span className="history-event-type">{item.event_type}</span>
                  <span className={`status-badge ${item.execution_status.toLowerCase()}`}>
                    {item.execution_status}
                  </span>
                </div>
                <div className="history-item-bottom">
                  <span className="history-workflow-id">{item.workflow_id.slice(0, 8)}...</span>
                  <span className="history-time">
                    {new Date(item.started_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                  </span>
                </div>
                {item.error_message && (
                  <div className="history-error-preview">{item.error_message}</div>
                )}
              </div>
            ))
          )}
        </div>
      </aside>

      {/* Main Panel */}
      <main className="workflow-main">
        {/* Event Ingestion Gateway */}
        <section className="section-card">
          <div className="card-title">
            <span className="material-symbols-outlined">bolt</span>
            Event Ingestion Gateway
            {/* Run with live backend */}
          </div>

          <form className="gateway-grid" onSubmit={handleTrigger}>
            <div className="form-group">
              <label className="form-label">Event Type</label>
              <select className="form-select" value={eventType} onChange={(e) => setEventType(e.target.value)} disabled={triggering}>
                <option value="WORKER_CHECKED_IN">WORKER_CHECKED_IN</option>
                <option value="EMERGENCY_RESPONSE">EMERGENCY_RESPONSE</option>
                <option value="DYNAMIC_TASK_REQUEST">DYNAMIC_TASK_REQUEST</option>
              </select>
            </div>

            {eventType === 'WORKER_CHECKED_IN' && (
              <div className="form-group">
                <label className="form-label">Employee</label>
                <select className="form-select" value={employeeId} onChange={(e) => setEmployeeId(e.target.value)} disabled={triggering}>
                  {employees.map(emp => (
                    <option key={emp.employee_id} value={emp.employee_id}>
                      {emp.employee_id} - {emp.name}
                    </option>
                  ))}
                  {employees.length === 0 && <option value="">Loading...</option>}
                </select>
              </div>
            )}

            {eventType === 'EMERGENCY_RESPONSE' && (() => {
              const activeEvent = EMERGENCY_EVENTS.find(e => e.value === emergencyType) || EMERGENCY_EVENTS[0]
              return (
                <>
                  <div className="form-group">
                    <label className="form-label">Emergency Event</label>
                    <select className="form-select" value={emergencyType} onChange={(e) => setEmergencyType(e.target.value)} disabled={triggering}>
                      {EMERGENCY_EVENTS.map(ev => (
                        <option key={ev.value} value={ev.value}>{ev.label} ({ev.code})</option>
                      ))}
                    </select>
                  </div>
                  <div className="form-group" style={{ gridColumn: 'span 2' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 10px', borderRadius: 6, border: `1.5px solid ${activeEvent.color}`, background: `${activeEvent.color}12` }}>
                      <span style={{ width: 10, height: 10, borderRadius: '50%', background: activeEvent.color, flexShrink: 0 }} />
                      <span style={{ fontSize: 11, fontWeight: 700, color: activeEvent.color }}>{activeEvent.code}</span>
                      <span style={{ fontSize: 11, color: 'var(--on-surface-variant)' }}>{activeEvent.description}</span>
                    </div>
                  </div>
                  <div className="form-group">
                    <label className="form-label">Location</label>
                    <input type="text" className="form-input" value={location} onChange={(e) => setLocation(e.target.value)} disabled={triggering} />
                  </div>
                  <div className="form-group">
                    <label className="form-label">Reporter ID</label>
                    <input type="number" className="form-input" placeholder="e.g. 1" value={reportedBy} onChange={(e) => setReportedBy(e.target.value)} disabled={triggering} required />
                  </div>
                </>
              )
            })()}

            {eventType === 'DYNAMIC_TASK_REQUEST' && (
              <>
                <div className="form-group">
                  <label className="form-label">Task Definition</label>
                  <select className="form-select" value={taskId} onChange={(e) => setTaskId(e.target.value)} disabled={triggering}>
                    {tasks.map(t => (
                      <option key={t.task_id} value={t.task_id}>{t.task_name}</option>
                    ))}
                    {tasks.length === 0 && <option value="">Loading...</option>}
                  </select>
                </div>
                <div className="form-group">
                  <label className="form-label">Due Horizon</label>
                  <select className="form-select" value={dueOffset} onChange={(e) => setDueOffset(e.target.value)} disabled={triggering}>
                    <option value="ONE_HOUR">1 Hour</option>
                    <option value="TWO_HOURS">2 Hours</option>
                    <option value="FOUR_HOURS">4 Hours</option>
                    <option value="EOD">24 Hours</option>
                  </select>
                </div>
              </>
            )}

            {/* Diagnostic Simulation Preset Selection */}
            <div className="form-group" style={{ gridColumn: 'span 2' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '10px 14px', borderRadius: 8, background: simulateError ? 'rgba(124, 58, 237, 0.08)' : 'var(--surface-container-high)', border: simulateError ? '1px solid var(--primary)' : '1px solid var(--outline-variant)', transition: 'all 0.2s ease' }}>
                <span className="material-symbols-outlined" style={{ color: simulateError ? 'var(--primary)' : 'var(--outline)' }}>psychology</span>
                <div style={{ flex: 1 }}>
                  <label className="form-label" style={{ margin: 0, fontSize: '11px', color: simulateError ? 'var(--primary)' : 'var(--outline)' }}>
                    Diagnostic Simulation Mode
                  </label>
                  <select
                    className="form-select"
                    style={{ border: 'none', background: 'transparent', padding: '2px 0 0 0', outline: 'none', width: '100%', fontSize: '12px', fontWeight: 600, color: 'var(--on-surface)' }}
                    value={simulateError}
                    onChange={(e) => setSimulateError(e.target.value)}
                    disabled={triggering}
                  >
                    <option value="">Happy Path (No simulated error)</option>
                    <option value="TIMEOUT">Simulate Assignment Timeout (Triggers self-correction)</option>
                    <option value="WORKFORCE_SHORTAGE">Simulate Workforce Shortage (ACLS Nurse Missing)</option>
                  </select>
                </div>
              </div>
            </div>

            <button type="submit" className="trigger-btn" disabled={triggering}>
              <span className="material-symbols-outlined">play_arrow</span>
              {triggering ? 'Ingesting...' : 'Ingest Event'}
            </button>
          </form>
        </section>

        {/* Trace Details */}
        {loadingTrace ? (
          <section className="section-card">
            <div className="empty-state"><p>Loading trace details...</p></div>
          </section>
        ) : !selectedTrace ? (
          <section className="section-card">
            <div className="empty-state">
              <span className="material-symbols-outlined">dashboard_customize</span>
              <p>Select a trace from the sidebar or ingest a new event to inspect execution.</p>
            </div>
          </section>
        ) : (
          <>
            {/* Execution Trace Section */}
            <section className="section-card">
              <div className="card-title">
                <span className="material-symbols-outlined">timeline</span>
                Execution Trace
              </div>

              {/* Metadata Row */}
              <div className="trace-header">
                <div className="meta-group">
                  <span className="meta-label">Workflow ID</span>
                  <span className="meta-value">{selectedTrace.workflow_id}</span>
                </div>
                <div className="meta-group">
                  <span className="meta-label">Event</span>
                  <span className="meta-value">{selectedTrace.event_type}</span>
                </div>
                <div className="meta-group">
                  <span className="meta-label">Source</span>
                  <span className="meta-value">{selectedTrace.trigger_source || 'API'}</span>
                </div>
                <div className="meta-group">
                  <span className="meta-label">Planning Mode</span>
                  <span className={`status-badge ${(selectedTrace.planning_mode || 'STATIC').toLowerCase()}`}>
                    {selectedTrace.planning_mode || 'STATIC'}
                  </span>
                </div>
                <div className="meta-group">
                  <span className="meta-label">Status</span>
                  <span className={`status-badge ${selectedTrace.execution_status.toLowerCase()}`}>
                    {selectedTrace.execution_status}
                  </span>
                </div>
                <div className="meta-group">
                  <span className="meta-label">Duration</span>
                  <span className="meta-value">{getDuration(selectedTrace)}</span>
                </div>
              </div>

              {/* Step Timeline */}
              <div className="timeline-track">
                {visualSteps.map((step, idx) => {
                  const isActive = selectedStep === idx
                  return (
                    <div
                      key={idx}
                      className={`timeline-step ${isActive ? 'active-step' : ''}`}
                      onClick={() => setSelectedStep(isActive ? null : idx)}
                    >
                      <div className={`step-node ${step.status.toLowerCase()}`}>
                        <span className="material-symbols-outlined">
                          {step.agent === 'SYSTEM_REFLECTION' ? 'psychology' :
                           step.status === 'SUCCESS' ? 'check_circle' :
                           step.status === 'PARTIAL_SUCCESS' ? 'published_with_changes' :
                           step.status === 'FAILED' ? 'cancel' : 'pending'}
                        </span>
                      </div>
                      <span className="step-label">{step.label}</span>
                      <span className="step-agent">{step.agent}</span>
                    </div>
                  )
                })}
              </div>

              {/* Step Detail Card */}
              {selectedStep !== null && visualSteps[selectedStep] && (
                <div className="detail-card">
                  <div className="detail-header">
                    <span className="detail-title">{visualSteps[selectedStep].label.toUpperCase()}</span>
                    <span className={`status-badge ${visualSteps[selectedStep].status.toLowerCase()}`}>{visualSteps[selectedStep].status}</span>
                  </div>
                  <div className="detail-body">
                    <p><strong>Agent:</strong> {visualSteps[selectedStep].agent}</p>
                    <p><strong>Capability:</strong> {visualSteps[selectedStep].info}</p>

                    {visualSteps[selectedStep].agent === 'ASSIGNMENT_AGENT' && producedData && (
                      <div className="detail-highlight">
                        <p><strong>Assignment Agent Output</strong></p>
                        {producedData.employee_name && <p>Assigned: {producedData.employee_name} (ID: {producedData.employee_id})</p>}
                        {producedData.assignment_id && <p>Assignment ID: {producedData.assignment_id}</p>}
                        {producedData.total_assigned !== undefined && <p>Total Assigned: {producedData.total_assigned}</p>}
                      </div>
                    )}

                    {visualSteps[selectedStep].agent === 'WORKFORCE_AGENT' && producedData && (
                      <div className="detail-highlight">
                        <p><strong>Workforce Agent Output</strong></p>
                        {producedData.employee_name && <p>Employee: {producedData.employee_name} (ID: {producedData.employee_id})</p>}
                        {producedData.roster_id && <p>Roster ID: {producedData.roster_id}</p>}
                        {producedData.department_name && <p>Department: {producedData.department_name}</p>}
                      </div>
                    )}

                    {visualSteps[selectedStep].agent === 'EMERGENCY_RESPONSE_AGENT' && producedData && (() => {
                      const codeInfo = EMERGENCY_EVENTS.find(e => e.value === producedData.emergency_type)
                      return (
                        <div className="detail-highlight" style={codeInfo ? { borderLeftColor: codeInfo.color } : {}}>
                          <p><strong>Emergency Agent Output</strong></p>
                          {producedData.emergency_type && <p><strong>Internal Event:</strong> {producedData.emergency_type}</p>}
                          {producedData.hospital_code && (
                            <p style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                              <strong>Resolved Protocol:</strong>
                              <span style={codeInfo ? { color: codeInfo.color, fontWeight: 700 } : {}}>{producedData.hospital_code}</span>
                            </p>
                          )}
                          {producedData.protocol_description && <p><strong>Description:</strong> {producedData.protocol_description}</p>}
                          {producedData.location && <p><strong>Location:</strong> {producedData.location}</p>}
                          {producedData.tasks_created !== undefined && <p><strong>Tasks Created:</strong> {producedData.tasks_created}</p>}
                        </div>
                      )
                    })()}

                    {visualSteps[selectedStep].agent === 'TASK_VERIFICATION_AGENT' && producedData && (
                      <div className="detail-highlight" style={{ borderLeftColor: producedData.proof_verified ? '#16a34a' : '#dc2626' }}>
                        <p><strong>Verification Agent Output</strong></p>
                        <p style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                          <strong>Result:</strong>
                          <span className={`status-badge ${producedData.proof_verified ? 'success' : 'failed'}`}>
                            {producedData.proof_verified ? 'VERIFIED' : 'REJECTED'}
                          </span>
                        </p>
                        {producedData.verification_confidence !== undefined && (
                          <p><strong>Confidence:</strong> {(producedData.verification_confidence * 100).toFixed(0)}%</p>
                        )}
                        {producedData.verification_rationale && (
                          <p><strong>Rationale:</strong> {producedData.verification_rationale}</p>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              )}
            </section>

            {/* Intelligent Planner Audit */}
            {(selectedTrace.planning_mode && selectedTrace.planning_mode !== 'STATIC') && (
              <section className="section-card" style={{ borderLeft: '4px solid var(--primary)' }}>
                <div className="card-title">
                  <span className="material-symbols-outlined">psychology</span>
                  Intelligent Planner Audit
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 16, marginBottom: 16 }}>
                  <div className="meta-group">
                    <span className="meta-label" style={{ display: 'block', fontSize: 11, color: 'var(--on-surface-variant)', opacity: 0.7 }}>SOP Referenced</span>
                    <span className="meta-value" style={{ fontWeight: 600, display: 'flex', alignItems: 'center', gap: 6 }}>
                      <span className="material-symbols-outlined" style={{ fontSize: 16, color: 'var(--primary)' }}>description</span>
                      {selectedTrace.sop_referenced}
                    </span>
                  </div>
                  <div className="meta-group">
                    <span className="meta-label" style={{ display: 'block', fontSize: 11, color: 'var(--on-surface-variant)', opacity: 0.7 }}>Planner Status</span>
                    <span className={`status-badge ${selectedTrace.planner_status?.toLowerCase() || 'success'}`}>
                      {selectedTrace.planner_status}
                    </span>
                  </div>
                </div>

                {selectedTrace.validation_errors && (
                  <div className="error-banner" style={{ marginBottom: 16 }}>
                    <span className="material-symbols-outlined">warning</span>
                    <div>
                      <strong>Validation Errors:</strong>
                      <pre style={{ margin: '8px 0 0 0', whiteSpace: 'pre-wrap', fontFamily: 'monospace', fontSize: 11 }}>
                        {selectedTrace.validation_errors}
                      </pre>
                    </div>
                  </div>
                )}

                {selectedTrace.llm_plan_raw && (
                  <div className="console-panel" style={{ marginTop: 8 }}>
                    <span className="console-title">Raw LLM Planner Output</span>
                    <pre className="console-body custom-scrollbar" style={{ margin: 0, padding: 12, borderRadius: 6, maxHeight: 150, overflowY: 'auto', background: 'var(--surface-container-low)', fontSize: 11, fontFamily: 'monospace' }}>
                      {selectedTrace.llm_plan_raw}
                    </pre>
                  </div>
                )}
              </section>
            )}

            {/* Error Banner */}
            {selectedTrace.error_message && (
              <div className="error-banner">
                <span className="material-symbols-outlined">error</span>
                {selectedTrace.error_message}
              </div>
            )}

            {/* JSON Console Panels */}
            <div className="console-grid">
              <div className="console-panel">
                <span className="console-title">Input Payload</span>
                <div className="console-body custom-scrollbar">{JSON.stringify(payloadData, null, 2)}</div>
              </div>
              <div className="console-panel">
                <span className="console-title">Produced Outputs</span>
                <div className="console-body custom-scrollbar">{JSON.stringify(producedData, null, 2)}</div>
              </div>
              <div className="console-panel">
                <span className="console-title">Final Result</span>
                <div className="console-body custom-scrollbar">{JSON.stringify(resultData, null, 2)}</div>
              </div>
            </div>
          </>
        )}
      </main>

      {/* Toast */}
      {toastMessage && (
        <div className="toast-bar">
          <span className="material-symbols-outlined">info</span>
          <span>{toastMessage}</span>
        </div>
      )}
    </div>
  )
}
