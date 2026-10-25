import { useState, useEffect, useCallback, useRef } from 'react'
import { authFetch } from '../services/apiHelper'
import './EscalationReview.css'

const PAGE_SIZE = 25

function timeAgo(isoStr) {
  if (!isoStr) return 'Never'
  const diff = Date.now() - new Date(isoStr).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'Just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  return `${days}d ago`
}

// Map action_type to a readable badge label
function getTypeBadge(actionType) {
  if (actionType === 'PROOF_REVIEW_REQUIRED') return { label: 'Proof Review', cls: 'badge-proof' }
  if (actionType === 'ESCALATION') return { label: 'Task Escalation', cls: 'badge-escalation' }
  if (actionType === 'MANUAL_SUPERVISOR_ASSIGNMENT') return { label: 'Manual Assignment', cls: 'badge-assignment' }
  if (actionType === 'APPROVAL_GATE:SHIFT_HANDOVER_REVIEW') return { label: 'Shift Handover', cls: 'badge-handover' }
  if (actionType === 'APPROVAL_GATE:EMERGENCY_OVERTIME_ASSIGNED') return { label: 'Emergency Overtime', cls: 'badge-emergency-ot' }
  if (actionType && actionType.startsWith('APPROVAL_GATE:')) return { label: 'Approval Gate', cls: 'badge-approval' }
  return { label: actionType || 'Unknown', cls: 'badge-type' }
}

// Check if an escalation is a shift handover type
function isHandoverType(esc) {
  if (!esc) return false
  return esc.action_type === 'APPROVAL_GATE:SHIFT_HANDOVER_REVIEW' ||
         esc.action_type === 'APPROVAL_GATE:EMERGENCY_OVERTIME_ASSIGNED'
}

// Parse context_state_json safely
function parseContext(esc) {
  if (!esc || !esc.context_state_json) return {}
  try { return JSON.parse(esc.context_state_json) } catch { return {} }
}

// Pending tasks load color
function getLoadColor(count) {
  if (count === 0) return 'load-green'
  if (count <= 2) return 'load-amber'
  return 'load-red'
}

export default function EscalationReview() {
  const [escalations, setEscalations] = useState([])
  const [counts, setCounts] = useState({ total: 0, pending: 0, resolved: 0 })
  const [employees, setEmployees] = useState([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState('ALL')
  const [currentPage, setCurrentPage] = useState(1)
  const [selectedEscalation, setSelectedEscalation] = useState(null)
  const [selectedEmployee, setSelectedEmployee] = useState('')
  const [resolutionNotes, setResolutionNotes] = useState('')
  const [resolutionAction, setResolutionAction] = useState('RESOLVE')
  const [rejectionReason, setRejectionReason] = useState('')
  const [extendPreset, setExtendPreset] = useState('PLUS_2_HOURS')
  const [resolving, setResolving] = useState(false)
  const [toastMessage, setToastMessage] = useState(null)
  const [showConfirmBanner, setShowConfirmBanner] = useState(false)
  const [handoverChoice, setHandoverChoice] = useState('')
  const [overtimeDuration, setOvertimeDuration] = useState('ONE_HOUR')
  const [proofImageSrc, setProofImageSrc] = useState(null)
  // Absentee resolution state
  const [pendingDeptTasks, setPendingDeptTasks] = useState([])
  const [selectedWorkIds, setSelectedWorkIds] = useState([])
  const [loadingPendingTasks, setLoadingPendingTasks] = useState(false)
  const loadInProgress = useRef(false)

  // Fetch proof image as authenticated blob URL when selectedEscalation changes
  useEffect(() => {
    let revoke = null
    const path = selectedEscalation?.proof_image_path
    if (path) {
      const urlPath = path.startsWith('uploads/')
        ? `/${path}`
        : `/uploads/${path}`
      authFetch(urlPath)
        .then(res => {
          if (res.ok) return res.blob()
          return null
        })
        .then(blob => {
          if (blob) {
            const objectUrl = URL.createObjectURL(blob)
            revoke = objectUrl
            setProofImageSrc(objectUrl)
          } else {
            setProofImageSrc(null)
          }
        })
        .catch(() => setProofImageSrc(null))
    } else {
      setProofImageSrc(null)
    }
    return () => {
      if (revoke) URL.revokeObjectURL(revoke)
    }
  }, [selectedEscalation?.proof_image_path])

  const loadData = useCallback(async ({ silent = false } = {}) => {
    if (loadInProgress.current) return
    loadInProgress.current = true
    if (!silent) setLoading(true)
    try {
      const params = new URLSearchParams({
        limit: String(PAGE_SIZE),
        offset: String((currentPage - 1) * PAGE_SIZE),
      })
      if (filter !== 'ALL') params.set('status_filter', filter)
      const [escRes, empRes] = await Promise.all([
        authFetch(`/escalations/?${params.toString()}`),
        authFetch('/employees/'),
      ])
      const userRole = localStorage.getItem('user_role') || 'ADMIN'
      const userDeptId = localStorage.getItem('user_department_id')

      if (escRes.ok) {
        const data = await escRes.json()
        const updatedCounts = {
          total: Number(escRes.headers.get('X-Escalation-Total-Count') || data.length),
          pending: Number(escRes.headers.get('X-Escalation-Pending-Count') || 0),
          resolved: Number(escRes.headers.get('X-Escalation-Resolved-Count') || 0),
        }
        setCounts(updatedCounts)
        setEscalations(data)
        const visibleCount = filter === 'PENDING'
          ? updatedCounts.pending
          : filter === 'RESOLVED'
            ? updatedCounts.resolved
            : updatedCounts.total
        const lastPage = Math.max(1, Math.ceil(visibleCount / PAGE_SIZE))
        if (currentPage > lastPage) setCurrentPage(lastPage)
      }
      if (empRes.ok) {
        const empData = await empRes.json()
        if (userRole === 'SUPERVISOR' && userDeptId) {
          setEmployees(empData.filter((emp) => String(emp.department_id) === String(userDeptId)))
        } else {
          setEmployees(empData)
        }
      }
    } catch (err) {
      console.error('Failed to load escalation review data:', err)
    } finally {
      if (!silent) setLoading(false)
      loadInProgress.current = false
    }
  }, [currentPage, filter])

  useEffect(() => {
    loadData()
    const interval = setInterval(() => {
      if (!document.hidden) loadData({ silent: true })
    }, 30000)
    return () => clearInterval(interval)
  }, [loadData])

  const filteredEscalations = escalations
  const activeCount = filter === 'PENDING'
    ? counts.pending
    : filter === 'RESOLVED'
      ? counts.resolved
      : counts.total
  const pageCount = Math.max(1, Math.ceil(activeCount / PAGE_SIZE))
  const firstVisible = activeCount === 0 ? 0 : (currentPage - 1) * PAGE_SIZE + 1
  const lastVisible = Math.min(currentPage * PAGE_SIZE, activeCount)

  const pendingCount = counts.pending
  const resolvedCount = counts.resolved

  // Filter candidate workers by the escalation's department
  const departmentCandidates = selectedEscalation
    ? employees.filter(emp => emp.department_id === selectedEscalation.department_id)
    : []

  const handleOpenResolveModal = (esc) => {
    setSelectedEscalation(esc)
    setResolutionNotes('')
    setSelectedEmployee('')
    setRejectionReason('')
    setExtendPreset('PLUS_2_HOURS')
    setShowConfirmBanner(false)
    setHandoverChoice('')
    setOvertimeDuration('ONE_HOUR')

    // Set default resolution action based on escalation type
    const isAbsentee = esc.decision_summary && esc.decision_summary.includes('STAFF_ABSENT')
    if (isHandoverType(esc)) {
      setResolutionAction('HANDOVER_REVIEW')
    } else if (esc.action_type === 'PROOF_REVIEW_REQUIRED') {
      setResolutionAction('APPROVE_PROOF')
    } else if (esc.action_type === 'ESCALATION' && esc.decision_summary && esc.decision_summary.includes('TIMEOUT')) {
      setResolutionAction('EXTEND_DEADLINE')
    } else if (esc.source_type === 'APPROVAL_REQUEST') {
      setResolutionAction('APPROVE_WORKFLOW')
    } else if (isAbsentee) {
      setResolutionAction('SNOOZE_ABSENTEE')
    } else {
      setResolutionAction('ASSIGN_WORKER')
    }

    // Fetch pending department tasks for absentee escalations
    setPendingDeptTasks([])
    setSelectedWorkIds([])
    if (isAbsentee && esc.department_id) {
      setLoadingPendingTasks(true)
      authFetch(`/departments/${esc.department_id}/work-queue`)
        .then(res => res.ok ? res.json() : [])
        .then(data => {
          const pending = (data || []).filter(t => t.queue_status === 'PENDING_ASSIGNED')
          setPendingDeptTasks(pending)
          setSelectedWorkIds(pending.map(t => t.work_id))
        })
        .catch(() => setPendingDeptTasks([]))
        .finally(() => setLoadingPendingTasks(false))
    }
  }

  const handleSelectCard = (empId) => {
    setSelectedEmployee(String(empId))
    setShowConfirmBanner(true)
  }

  const handleResolveSubmit = async (e) => {
    e.preventDefault()
    if (!selectedEscalation) return
    setResolving(true)

    try {
      // Shift handover resolution path
      if (isHandoverType(selectedEscalation) && handoverChoice) {
        const payload = {
          supervisor_notes: resolutionNotes,
          choice: handoverChoice,
          overtime_duration: handoverChoice === 'CHOICE_A' ? overtimeDuration : undefined,
        }

        const res = await authFetch(`/approvals/${selectedEscalation.source_id}/resume`, {
          method: 'POST',
          body: JSON.stringify(payload)
        })

        if (res.ok) {
          const label = handoverChoice === 'CHOICE_A' ? 'Overtime granted' : 'Tasks preempted & carried forward'
          setToastMessage(`Handover #${selectedEscalation.source_id}: ${label}.`)
          setSelectedEscalation(null)
          loadData()
          setTimeout(() => setToastMessage(null), 4000)
        } else {
          const errData = await res.json().catch(() => ({}))
          alert(errData.detail || 'Failed to resolve handover.')
        }
      }
      // Standard approval request path
      else if (selectedEscalation.source_type === 'APPROVAL_REQUEST') {
        const endpoint = resolutionAction === 'REJECT_WORKFLOW'
          ? `/approvals/${selectedEscalation.source_id}/reject`
          : `/approvals/${selectedEscalation.source_id}/resume`

        const res = await authFetch(endpoint, {
          method: 'POST',
          body: JSON.stringify({
            supervisor_notes: resolutionNotes,
          })
        })

        if (res.ok) {
          setToastMessage(`Approval #${selectedEscalation.source_id} ${resolutionAction === 'REJECT_WORKFLOW' ? 'rejected' : 'approved'}.`)
          setSelectedEscalation(null)
          loadData()
          setTimeout(() => setToastMessage(null), 4000)
        } else {
          const errData = await res.json().catch(() => ({}))
          alert(errData.detail || 'Failed to process approval.')
        }
      } else {
        // AgentActionLog escalation resolution
        const payload = {
          resolution_notes: resolutionNotes,
          resolution_action: resolutionAction,
          assigned_employee_id: selectedEmployee ? parseInt(selectedEmployee, 10) : null,
          work_id: selectedEscalation?.work_id ?? null,
          rejection_reason: rejectionReason || null,
          extend_preset: resolutionAction === 'EXTEND_DEADLINE' ? extendPreset : null,
          selected_work_ids: (resolutionAction === 'SNOOZE_ABSENTEE' || resolutionAction === 'REALLOCATE_ABSENTEE_TASKS')
            ? selectedWorkIds
            : null,
        }

        const res = await authFetch(`/escalations/${selectedEscalation.source_id}/resolve`, {
          method: 'POST',
          body: JSON.stringify(payload)
        })

        if (res.ok) {
          setToastMessage(`Escalation #${selectedEscalation.source_id} resolved successfully.`)
          setSelectedEscalation(null)
          loadData()
          setTimeout(() => setToastMessage(null), 4000)
        } else {
          const errData = await res.json().catch(() => ({}))
          alert(errData.detail || 'Failed to resolve escalation.')
        }
      }
    } catch (err) {
      console.error('Error resolving escalation:', err)
      alert('Network error while resolving escalation.')
    } finally {
      setResolving(false)
    }
  }

  // Determine which resolution form sections to show
  const isProofReview = selectedEscalation?.action_type === 'PROOF_REVIEW_REQUIRED'
  const isTimeoutReview = selectedEscalation?.action_type === 'ESCALATION' &&
    selectedEscalation?.decision_summary?.includes('TIMEOUT')
  const isHandover = isHandoverType(selectedEscalation)
  const isApprovalGate = selectedEscalation?.source_type === 'APPROVAL_REQUEST' && !isHandover
  const isAbsenteeReview = selectedEscalation?.decision_summary?.includes('STAFF_ABSENT')
  const isAssignmentReview = !isProofReview && !isTimeoutReview && !isApprovalGate && !isHandover && !isAbsenteeReview
  const handoverCtx = isHandover ? parseContext(selectedEscalation) : {}

  // Get selected employee details for confirmation banner
  const selectedEmpDetails = selectedEmployee
    ? employees.find(emp => emp.employee_id === parseInt(selectedEmployee, 10))
    : null

  return (
    <div className="escalation-page">
      <header className="page-header">
        <div>
          <div className="title-row">
            <span className="material-symbols-outlined header-icon">gavel</span>
            <h1 className="text-headline-lg">Escalation Review</h1>
          </div>
          <p className="text-body-md page-subtitle">
            Human-in-the-loop review console for task escalations, proof reviews, watcher alerts, and approval gates.
          </p>
        </div>
        <button className="btn btn-secondary refresh-btn" onClick={loadData}>
          <span className="material-symbols-outlined">refresh</span> Refresh
        </button>
      </header>

      {toastMessage && (
        <div className="toast-notification">
          <span className="material-symbols-outlined">check_circle</span>
          <span>{toastMessage}</span>
        </div>
      )}

      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-header">
            <span className="text-label-md">Total Reports</span>
            <span className="material-symbols-outlined stat-icon icon-blue">history</span>
          </div>
          <div className="stat-value">{counts.total}</div>
        </div>

        <div className="stat-card urgent">
          <div className="stat-header">
            <span className="text-label-md">Pending Human Review</span>
            <span className="material-symbols-outlined stat-icon icon-red">warning</span>
          </div>
          <div className="stat-value">{pendingCount}</div>
        </div>

        <div className="stat-card">
          <div className="stat-header">
            <span className="text-label-md">Resolved Escalations</span>
            <span className="material-symbols-outlined stat-icon icon-green">task_alt</span>
          </div>
          <div className="stat-value">{resolvedCount}</div>
        </div>
      </div>

      <div className="controls-bar">
        <div className="tabs">
          <button
            className={`tab-btn ${filter === 'ALL' ? 'active' : ''}`}
            onClick={() => { setFilter('ALL'); setCurrentPage(1) }}
          >
            All Reports ({counts.total})
          </button>
          <button
            className={`tab-btn ${filter === 'PENDING' ? 'active' : ''}`}
            onClick={() => { setFilter('PENDING'); setCurrentPage(1) }}
          >
            Pending Review ({pendingCount})
          </button>
          <button
            className={`tab-btn ${filter === 'RESOLVED' ? 'active' : ''}`}
            onClick={() => { setFilter('RESOLVED'); setCurrentPage(1) }}
          >
            Resolved ({resolvedCount})
          </button>
        </div>
      </div>

      {!loading && activeCount > PAGE_SIZE && (
        <div className="pagination-controls">
          <span>Showing {firstVisible}-{lastVisible} of {activeCount}</span>
          <div className="pagination-actions">
            <button
              className="pagination-btn"
              onClick={() => setCurrentPage(page => Math.max(1, page - 1))}
              disabled={currentPage === 1}
            >
              Previous
            </button>
            <span>Page {currentPage} of {pageCount}</span>
            <button
              className="pagination-btn"
              onClick={() => setCurrentPage(page => Math.min(pageCount, page + 1))}
              disabled={currentPage >= pageCount}
            >
              Next
            </button>
          </div>
        </div>
      )}

      <div className="table-card">
        {loading ? (
          <div className="loading-state">
            <span className="material-symbols-outlined spinner">progress_activity</span>
            <p>Loading escalation reports...</p>
          </div>
        ) : filteredEscalations.length === 0 ? (
          <div className="empty-state">
            <span className="material-symbols-outlined">verified_user</span>
            <h3>No Escalation Reports Found</h3>
            <p>All task assignments and specialization requirements are fulfilled or resolved.</p>
          </div>
        ) : (
          <table className="escalation-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Timestamp</th>
                <th>Department</th>
                <th>Type</th>
                <th>Issue Summary</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredEscalations.map(item => {
                const badge = getTypeBadge(item.action_type)
                return (
                  <tr key={`${item.source_type}-${item.source_id}`} className={!item.is_resolved ? 'pending-row' : ''}>
                    <td className="id-cell">#{item.source_id}</td>
                    <td className="time-cell">{timeAgo(item.action_timestamp)}</td>
                    <td className="dept-cell-text">{item.department_name}</td>
                    <td>
                      <span className={`badge ${badge.cls}`}>{badge.label}</span>
                    </td>
                    <td className="summary-cell">
                      <p className="summary-text">{item.decision_summary || 'No details provided'}</p>
                    </td>
                    <td>
                      {item.is_resolved ? (
                        <span className="badge badge-success">
                          <span className="material-symbols-outlined icon-small">check</span> Resolved
                        </span>
                      ) : (
                        <span className="badge badge-danger">
                          <span className="material-symbols-outlined icon-small">pending</span> Pending
                        </span>
                      )}
                    </td>
                    <td>
                      {!item.is_resolved ? (
                        <button
                          className="btn btn-primary resolve-action-btn"
                          onClick={() => handleOpenResolveModal(item)}
                        >
                          Review & Resolve
                        </button>
                      ) : (
                        <span className="resolved-text">
                          <span className="material-symbols-outlined icon-small">check_circle</span> Complete
                        </span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* Resolution Modal */}
      {selectedEscalation && (
        <div className="modal-backdrop">
          <div className="modal-content">
            <div className="modal-header">
              <div className="modal-title-row">
                <span className="material-symbols-outlined icon-red">gavel</span>
                <h3>Resolve Report #{selectedEscalation.source_id}</h3>
              </div>
              <button
                className="close-btn"
                onClick={() => setSelectedEscalation(null)}
              >
                <span className="material-symbols-outlined">close</span>
              </button>
            </div>

            <form onSubmit={handleResolveSubmit} className="modal-body">
              <div className="info-box">
                <strong>Report Details:</strong>
                <p>{selectedEscalation.decision_summary}</p>
                <small>Department: {selectedEscalation.department_name}</small>
                {selectedEscalation.task_name && <p>Task: {selectedEscalation.task_name}</p>}
                {selectedEscalation.proof_employee_id && <p>Employee ID: {selectedEscalation.proof_employee_id}</p>}
                {selectedEscalation.ai_decision && <p>AI decision: {selectedEscalation.ai_decision}</p>}
                {selectedEscalation.verification_confidence !== null && selectedEscalation.verification_confidence !== undefined && (
                  <p>AI confidence: {(selectedEscalation.verification_confidence * 100).toFixed(0)}%</p>
                )}
                {selectedEscalation.verification_rationale && <p>AI reasoning: {selectedEscalation.verification_rationale}</p>}
                {selectedEscalation.verification_attempts && <p>Proof attempt: {selectedEscalation.verification_attempts}</p>}
              </div>

              {/* Task Proof Photo Preview for Supervisor Review */}
              {(isProofReview || selectedEscalation?.proof_image_path) && (
                <div className="proof-preview-box">
                  <div className="proof-preview-header">
                    <span className="material-symbols-outlined icon-blue">image</span>
                    <strong>Submitted Task Completion Proof Photo:</strong>
                  </div>
                  {selectedEscalation.proof_image_path ? (
                    <div className="proof-media-container">
                      <img
                        src={proofImageSrc || ''}
                        alt="Task Completion Proof"
                        className="proof-image-preview"
                        style={proofImageSrc ? {} : { display: 'none' }}
                        onError={(e) => {
                          e.target.style.display = 'none';
                        }}
                      />
                      <div className="proof-path-badge">
                        <span className="material-symbols-outlined">photo_library</span>
                        <code>{selectedEscalation.proof_image_path}</code>
                      </div>
                    </div>
                  ) : (
                    <p className="no-proof-text">Proof path: Attached in report summary</p>
                  )}
                </div>
              )}

              {/* Action selector for non-approval types */}
              {!isApprovalGate && (
                <div className="form-group">
                  <label className="text-label-md">Resolution Action</label>
                  <select
                    className="form-control"
                    value={resolutionAction}
                    onChange={(e) => setResolutionAction(e.target.value)}
                  >
                    {isProofReview && (
                      <>
                        <option value="APPROVE_PROOF">Approve & Complete Task</option>
                        <option value="REJECT_PROOF">Reject & Request Resubmission</option>
                      </>
                    )}
                    {isTimeoutReview && (
                      <>
                        <option value="EXTEND_DEADLINE">Extend Deadline</option>
                        <option value="ASSIGN_WORKER">Force Assign Worker</option>
                        <option value="CANCEL_TASK">Cancel Task</option>
                      </>
                    )}
                    {isAssignmentReview && (
                      <>
                        <option value="ASSIGN_WORKER">Assign Worker</option>
                        <option value="EXTEND_DEADLINE">Extend Deadline</option>
                        <option value="CANCEL_TASK">Cancel Task</option>
                        <option value="RUN_ASSIGNMENT_CYCLE">Trigger Automated Assignment Cycle</option>
                      </>
                    )}
                    {isAbsenteeReview && (
                      <>
                        <option value="SNOOZE_ABSENTEE">Snooze & Wait for Worker</option>
                        <option value="REALLOCATE_ABSENTEE_TASKS">Reallocate Tasks (Release to Queue)</option>
                      </>
                    )}
                  </select>
                </div>
              )}

              {/* Shift handover resolution UI */}
              {isHandover && (
                <div className="handover-panel">
                  <div className="handover-context-box">
                    <div className="handover-context-header">
                      <span className="material-symbols-outlined icon-amber">schedule</span>
                      <strong>Shift Handover Context</strong>
                    </div>
                    <div className="handover-context-grid">
                      <div className="context-item">
                        <span className="context-label">Employee</span>
                        <span className="context-value">{handoverCtx.employee_name || 'N/A'}</span>
                      </div>
                      <div className="context-item">
                        <span className="context-label">Department</span>
                        <span className="context-value">{handoverCtx.department_name || 'N/A'}</span>
                      </div>
                      <div className="context-item">
                        <span className="context-label">Shift End</span>
                        <span className="context-value">{handoverCtx.shift_end_time ? new Date(handoverCtx.shift_end_time).toLocaleTimeString() : 'N/A'}</span>
                      </div>
                      <div className="context-item">
                        <span className="context-label">Unstarted Tasks</span>
                        <span className="context-value badge-count">{(handoverCtx.assigned_work_ids || []).length}</span>
                      </div>
                      <div className="context-item">
                        <span className="context-label">In Progress Tasks</span>
                        <span className="context-value badge-count">{(handoverCtx.in_progress_work_ids || []).length}</span>
                      </div>
                    </div>
                  </div>

                  <div className="handover-choices">
                    <div
                      className={`choice-card choice-a ${handoverChoice === 'CHOICE_A' ? 'selected' : ''}`}
                      onClick={() => setHandoverChoice('CHOICE_A')}
                    >
                      <div className="choice-icon">
                        <span className="material-symbols-outlined">more_time</span>
                      </div>
                      <div className="choice-content">
                        <h4>Choice A: Grant Overtime</h4>
                        <p>Worker stays and completes all assigned tasks within an extended shift window.</p>
                      </div>
                      {handoverChoice === 'CHOICE_A' && (
                        <span className="material-symbols-outlined choice-check">check_circle</span>
                      )}
                    </div>

                    <div
                      className={`choice-card choice-b ${handoverChoice === 'CHOICE_B' ? 'selected' : ''}`}
                      onClick={() => setHandoverChoice('CHOICE_B')}
                    >
                      <div className="choice-icon">
                        <span className="material-symbols-outlined">swap_horiz</span>
                      </div>
                      <div className="choice-content">
                        <h4>Choice B: Preempt & Carry Forward</h4>
                        <p>Unstarted (ASSIGNED) tasks are preempted and reassigned to the incoming shift. In-progress tasks stay with the worker.</p>
                      </div>
                      {handoverChoice === 'CHOICE_B' && (
                        <span className="material-symbols-outlined choice-check">check_circle</span>
                      )}
                    </div>
                  </div>

                  {handoverChoice === 'CHOICE_A' && (
                    <div className="form-group overtime-duration-group">
                      <label className="text-label-md">Overtime Duration</label>
                      <select
                        className="form-control"
                        value={overtimeDuration}
                        onChange={(e) => setOvertimeDuration(e.target.value)}
                      >
                        <option value="ONE_HOUR">+1 Hour</option>
                        <option value="TWO_HOURS">+2 Hours</option>
                        <option value="FOUR_HOURS">+4 Hours</option>
                      </select>
                    </div>
                  )}
                </div>
              )}

              {/* Approval gate actions */}
              {isApprovalGate && (
                <div className="form-group">
                  <label className="text-label-md">Approval Decision</label>
                  <select
                    className="form-control"
                    value={resolutionAction}
                    onChange={(e) => setResolutionAction(e.target.value)}
                  >
                    <option value="APPROVE_WORKFLOW">Approve & Resume</option>
                    <option value="REJECT_WORKFLOW">Reject</option>
                  </select>
                </div>
              )}

              {/* Football Player Card selector for manual assignment */}
              {(resolutionAction === 'ASSIGN_WORKER') && (
                <div className="form-group">
                  <label className="text-label-md">
                    Select Worker ({selectedEscalation.department_name} Department)
                  </label>
                  {departmentCandidates.length === 0 ? (
                    <p className="no-candidates-text">No eligible workers in this department.</p>
                  ) : (
                    <div className="player-card-grid">
                      {departmentCandidates.map(emp => (
                        <div
                          key={emp.employee_id}
                          className={`player-card ${selectedEmployee === String(emp.employee_id) ? 'selected' : ''}`}
                          onClick={() => handleSelectCard(emp.employee_id)}
                        >
                          <div className="card-avatar">
                            <span className="material-symbols-outlined">person</span>
                          </div>
                          <div className="card-name">{emp.name}</div>
                          <div className="card-role-badge">{emp.role || 'Staff'}</div>
                          <div className="card-stats-row">
                            <span className={`card-load-badge ${getLoadColor(emp.pending_task || 0)}`}>
                              {emp.pending_task || 0} Pending
                            </span>
                            <span className="card-urgent-badge">
                              {emp.high_critical_count || 0} Urgent
                            </span>
                          </div>
                          {emp.experience_years > 0 && (
                            <div className="card-experience" style={{ fontSize: 12, color: '#6b7280', marginTop: 4 }}>
                              <span className="material-symbols-outlined" style={{ fontSize: 14, verticalAlign: 'middle', marginRight: 2 }}>work_history</span>
                              {emp.experience_years} yrs exp
                            </div>
                          )}
                          {emp.skill && (
                            <div className="card-skills">
                              {emp.skill.split(',').map((s, i) => (
                                <span key={i} className="skill-tag">{s.trim()}</span>
                              ))}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Selection confirmation banner */}
                  {showConfirmBanner && selectedEmpDetails && (
                    <div className="selection-confirm-banner">
                      <span className="material-symbols-outlined">how_to_reg</span>
                      <span>
                        Selected Candidate: <strong>{selectedEmpDetails.name}</strong>
                        {' '}({selectedEmpDetails.role || 'Staff'})
                        {' '} -- Click "Confirm & Assign Worker" below to finalize.
                      </span>
                    </div>
                  )}
                </div>
              )}

              {/* Rejection reason for proof rejection */}
              {resolutionAction === 'REJECT_PROOF' && (
                <div className="form-group">
                  <label className="text-label-md">Rejection Reason</label>
                  <textarea
                    className="form-control"
                    rows="2"
                    value={rejectionReason}
                    onChange={(e) => setRejectionReason(e.target.value)}
                    placeholder="Describe why the proof is being rejected..."
                    required
                  />
                </div>
              )}

              {/* Deadline extension preset dropdown */}
              {resolutionAction === 'EXTEND_DEADLINE' && (
                <div className="form-group">
                  <label className="text-label-md">Extend Deadline</label>
                  <select
                    className="form-control"
                    value={extendPreset}
                    onChange={(e) => setExtendPreset(e.target.value)}
                  >
                    <option value="PLUS_1_HOUR">+1 Hour</option>
                    <option value="PLUS_2_HOURS">+2 Hours</option>
                    <option value="PLUS_4_HOURS">+4 Hours</option>
                    <option value="PLUS_8_HOURS">+8 Hours</option>
                    <option value="END_OF_DAY">End of Day (11:59 PM)</option>
                  </select>
                </div>
              )}

              {/* Pending department tasks checklist for absentee resolution */}
              {isAbsenteeReview && (resolutionAction === 'SNOOZE_ABSENTEE' || resolutionAction === 'REALLOCATE_ABSENTEE_TASKS') && (
                <div className="form-group">
                  <label className="text-label-md">
                    Select tasks to allocate to other workers immediately:
                  </label>
                  {loadingPendingTasks ? (
                    <p className="no-candidates-text">Loading pending tasks...</p>
                  ) : pendingDeptTasks.length === 0 ? (
                    <p className="no-candidates-text">No pending tasks in the department queue.</p>
                  ) : (
                    <div className="absentee-task-checklist">
                      <div className="checklist-header">
                        <label className="checklist-select-all">
                          <input
                            type="checkbox"
                            checked={selectedWorkIds.length === pendingDeptTasks.length}
                            onChange={(e) => {
                              if (e.target.checked) {
                                setSelectedWorkIds(pendingDeptTasks.map(t => t.work_id))
                              } else {
                                setSelectedWorkIds([])
                              }
                            }}
                          />
                          Select All ({pendingDeptTasks.length} tasks)
                        </label>
                      </div>
                      {pendingDeptTasks.map(task => (
                        <label key={task.work_id} className="checklist-item">
                          <input
                            type="checkbox"
                            checked={selectedWorkIds.includes(task.work_id)}
                            onChange={(e) => {
                              if (e.target.checked) {
                                setSelectedWorkIds(prev => [...prev, task.work_id])
                              } else {
                                setSelectedWorkIds(prev => prev.filter(id => id !== task.work_id))
                              }
                            }}
                          />
                          <span className="checklist-task-name">
                            {task.task_name || `Work #${task.work_id}`}
                          </span>
                          <span className={`checklist-priority priority-${(task.priority || 'medium').toLowerCase()}`}>
                            {task.priority || 'MEDIUM'}
                          </span>
                        </label>
                      ))}
                    </div>
                  )}
                </div>
              )}

              <div className="form-group">
                <label className="text-label-md">Resolution Notes (Optional)</label>
                <textarea
                  className="form-control"
                  rows="3"
                  value={resolutionNotes}
                  onChange={(e) => setResolutionNotes(e.target.value)}
                  placeholder="Enter resolution details (optional)..."
                />
              </div>

              <div className="modal-footer">
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setSelectedEscalation(null)}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={
                    resolving ||
                    (resolutionAction === 'ASSIGN_WORKER' && !selectedEmployee) ||
                    (isHandover && !handoverChoice)
                  }
                >
                  {resolving
                    ? 'Submitting...'
                    : isHandover && handoverChoice === 'CHOICE_A'
                      ? 'Grant Overtime'
                      : isHandover && handoverChoice === 'CHOICE_B'
                        ? 'Preempt & Carry Forward'
                        : resolutionAction === 'ASSIGN_WORKER'
                          ? 'Confirm & Assign Worker'
                          : resolutionAction === 'CANCEL_TASK'
                            ? 'Confirm Cancel Task'
                            : 'Confirm & Resolve'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
