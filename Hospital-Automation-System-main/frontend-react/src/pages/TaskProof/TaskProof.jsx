import { useState, useEffect, useRef } from 'react'
import { authFetch } from '../../services/apiHelper'
import './TaskProof.css'

const STATUS_CONFIG = {
  PENDING:   { icon: 'hourglass_top', color: '#f59e0b', bg: '#fef3c7', border: '#f59e0b', label: 'Pending' },
  ASSIGNED:  { icon: 'person',        color: '#3b82f6', bg: '#dbeafe', border: '#3b82f6', label: 'Assigned' },
  COMPLETED: { icon: 'check_circle',  color: '#10b981', bg: '#d1fae5', border: '#10b981', label: 'Completed' },
  CANCELLED: { icon: 'cancel',        color: '#ef4444', bg: '#fee2e2', border: '#ef4444', label: 'Cancelled' },
}

const PROOF_STATUS_CONFIG = {
  PENDING:  { icon: 'pending',       color: '#f59e0b', label: 'Awaiting Review' },
  VERIFIED: { icon: 'verified',      color: '#10b981', label: 'Verified' },
  REJECTED: { icon: 'gpp_bad',       color: '#ef4444', label: 'Rejected' },
}

export default function TaskProof() {
  // Sidebar data
  const [workItems, setWorkItems] = useState([])
  const [selectedItem, setSelectedItem] = useState(null)
  const [loadingItems, setLoadingItems] = useState(true)
  const [sidebarFilter, setSidebarFilter] = useState('ALL')

  // Proof submission form
  const [proofFile, setProofFile] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const fileInputRef = useRef(null)

  // Toast
  const [toastMessage, setToastMessage] = useState('')

  const showToast = (msg) => {
    setToastMessage(msg)
    setTimeout(() => setToastMessage(''), 3500)
  }

  // Fetch work queue items
  const fetchWorkItems = async (silent = false) => {
    if (!silent) setLoadingItems(true)
    try {
      const res = await authFetch('/work-queue/')
      if (res.ok) {
        const data = await res.json()
        setWorkItems(data)
        // Refresh selected item if it's still in the list
        if (selectedItem) {
          const updated = data.find(i => i.work_id === selectedItem.work_id)
          if (updated) setSelectedItem(updated)
        }
      }
    } catch { /* backend not running */ }
    setLoadingItems(false)
  }

  useEffect(() => {
    fetchWorkItems()
    const poll = setInterval(() => fetchWorkItems(true), 8000)
    return () => clearInterval(poll)
  }, [])

  // Filter sidebar items
  const filteredItems = workItems.filter(item => {
    if (sidebarFilter === 'ALL') return true
    if (sidebarFilter === 'ASSIGNED') return item.queue_status === 'ASSIGNED'
    if (sidebarFilter === 'HAS_PROOF') return item.verification_status !== null
    if (sidebarFilter === 'VERIFIED') return item.verification_status === 'VERIFIED'
    if (sidebarFilter === 'REJECTED') return item.verification_status === 'REJECTED'
    return true
  })

  // Submit proof
  const handleSubmitProof = async (e) => {
    e.preventDefault()
    if (submitting || !selectedItem) return
    if (!proofFile) {
      showToast('Please upload a proof file.')
      return
    }

    setSubmitting(true)

    try {
      const formData = new FormData()
      if (proofFile) formData.append('file', proofFile)

      const res = await authFetch(`/work-queue/${selectedItem.work_id}/submit-proof`, {
        method: 'POST',
        body: formData,
      })

      if (res.ok) {
        const data = await res.json()
        showToast(`Proof submitted (ID: ${data.proof_id}). Verification in progress...`)
        setProofFile(null)
        if (fileInputRef.current) fileInputRef.current.value = ''
        // Refresh after short delay for outbox processing
        setTimeout(() => fetchWorkItems(true), 2000)
      } else {
        const errData = await res.json().catch(() => ({}))
        showToast(`Submission failed: ${errData.detail || 'Server error'}`)
      }
    } catch {
      showToast('Backend not available.')
    }

    setSubmitting(false)
  }

  // Derive counts
  const assignedCount = workItems.filter(i => i.queue_status === 'ASSIGNED').length
  const proofCount = workItems.filter(i => i.verification_status !== null).length
  const verifiedCount = workItems.filter(i => i.verification_status === 'VERIFIED').length
  const rejectedCount = workItems.filter(i => i.verification_status === 'REJECTED').length

  const queueStatusConfig = STATUS_CONFIG[selectedItem?.queue_status] || STATUS_CONFIG.PENDING
  const proofStatusConfig = selectedItem?.verification_status
    ? PROOF_STATUS_CONFIG[selectedItem.verification_status]
    : null

  return (
    <div className="proof-container">
      {/* Sidebar: Work Queue Items */}
      <aside className="proof-sidebar">
        <div className="proof-sidebar-header">
          <h2 className="proof-sidebar-title">
            <span className="material-symbols-outlined">fact_check</span>
            Work Queue
          </h2>
          <p className="proof-sidebar-subtitle">Select a task to submit or review proof</p>
        </div>

        {/* Stats Strip */}
        <div className="proof-stats-strip">
          <div className="proof-stat" onClick={() => setSidebarFilter('ALL')}>
            <span className="proof-stat-num">{workItems.length}</span>
            <span className="proof-stat-label">Total</span>
          </div>
          <div className="proof-stat" onClick={() => setSidebarFilter('ASSIGNED')}>
            <span className="proof-stat-num" style={{ color: '#3b82f6' }}>{assignedCount}</span>
            <span className="proof-stat-label">Assigned</span>
          </div>
          <div className="proof-stat" onClick={() => setSidebarFilter('VERIFIED')}>
            <span className="proof-stat-num" style={{ color: '#10b981' }}>{verifiedCount}</span>
            <span className="proof-stat-label">Verified</span>
          </div>
          <div className="proof-stat" onClick={() => setSidebarFilter('REJECTED')}>
            <span className="proof-stat-num" style={{ color: '#ef4444' }}>{rejectedCount}</span>
            <span className="proof-stat-label">Rejected</span>
          </div>
        </div>

        {/* Filter Tabs */}
        <div className="proof-filter-tabs">
          {['ALL', 'ASSIGNED', 'HAS_PROOF', 'VERIFIED', 'REJECTED'].map(f => (
            <button
              key={f}
              className={`proof-filter-tab ${sidebarFilter === f ? 'active' : ''}`}
              onClick={() => setSidebarFilter(f)}
            >
              {f === 'HAS_PROOF' ? 'Has Proof' : f.charAt(0) + f.slice(1).toLowerCase()}
            </button>
          ))}
        </div>

        {/* Item List */}
        <div className="proof-item-list custom-scrollbar">
          {loadingItems ? (
            <div className="proof-empty-state"><p>Loading work items...</p></div>
          ) : filteredItems.length === 0 ? (
            <div className="proof-empty-state"><p>No matching work items.</p></div>
          ) : (
            filteredItems.map(item => {
              const statusCfg = STATUS_CONFIG[item.queue_status] || STATUS_CONFIG.PENDING
              const proofCfg = item.verification_status ? PROOF_STATUS_CONFIG[item.verification_status] : null
              const isActive = selectedItem?.work_id === item.work_id

              return (
                <div
                  key={item.work_id}
                  className={`proof-sidebar-item ${isActive ? 'active' : ''}`}
                  onClick={() => setSelectedItem(item)}
                >
                  <div className="proof-item-row">
                    <span className="proof-item-id">WQ-{item.work_id}</span>
                    <span
                      className="proof-item-badge"
                      style={{ background: statusCfg.bg, color: statusCfg.color, borderColor: statusCfg.border }}
                    >
                      <span className="material-symbols-outlined" style={{ fontSize: 12 }}>{statusCfg.icon}</span>
                      {statusCfg.label}
                    </span>
                  </div>
                  <div className="proof-item-row">
                    <span className="proof-item-meta">Task #{item.task_id} | Dept #{item.department_id}</span>
                    {proofCfg && (
                      <span className="proof-item-proof-tag" style={{ color: proofCfg.color }}>
                        <span className="material-symbols-outlined" style={{ fontSize: 11 }}>{proofCfg.icon}</span>
                        {proofCfg.label}
                      </span>
                    )}
                  </div>
                </div>
              )
            })
          )}
        </div>
      </aside>

      {/* Main Panel */}
      <main className="proof-main">
        {!selectedItem ? (
          <div className="proof-empty-main">
            <span className="material-symbols-outlined" style={{ fontSize: 48, opacity: 0.3 }}>verified</span>
            <h3>Task Proof Verification</h3>
            <p>Select a work queue item from the sidebar to submit proof or review verification status.</p>
          </div>
        ) : (
          <>
            {/* Task Detail Header */}
            <section className="proof-detail-card">
              <div className="proof-card-title">
                <span className="material-symbols-outlined">info</span>
                Work Item Details
                <span className="proof-work-id-tag">WQ-{selectedItem.work_id}</span>
              </div>

              <div className="proof-detail-grid">
                <div className="proof-detail-item">
                  <span className="proof-detail-label">Queue Status</span>
                  <span
                    className="proof-detail-badge"
                    style={{ background: queueStatusConfig.bg, color: queueStatusConfig.color, borderColor: queueStatusConfig.border }}
                  >
                    <span className="material-symbols-outlined" style={{ fontSize: 14 }}>{queueStatusConfig.icon}</span>
                    {queueStatusConfig.label}
                  </span>
                </div>
                <div className="proof-detail-item">
                  <span className="proof-detail-label">Task ID</span>
                  <span className="proof-detail-value">{selectedItem.task_id ?? 'N/A'}</span>
                </div>
                <div className="proof-detail-item">
                  <span className="proof-detail-label">Department ID</span>
                  <span className="proof-detail-value">{selectedItem.department_id ?? 'N/A'}</span>
                </div>
                <div className="proof-detail-item">
                  <span className="proof-detail-label">Priority</span>
                  <span className="proof-detail-value">{selectedItem.priority ?? 'N/A'}</span>
                </div>
                <div className="proof-detail-item">
                  <span className="proof-detail-label">Due Date</span>
                  <span className="proof-detail-value">
                    {selectedItem.due_date ? new Date(selectedItem.due_date).toLocaleString() : 'N/A'}
                  </span>
                </div>
                <div className="proof-detail-item">
                  <span className="proof-detail-label">Created</span>
                  <span className="proof-detail-value">
                    {selectedItem.created_at ? new Date(selectedItem.created_at).toLocaleString() : 'N/A'}
                  </span>
                </div>
              </div>
            </section>

            {/* Proof Status Card (if proof exists) */}
            {proofStatusConfig && (
              <section className="proof-detail-card">
                <div className="proof-card-title">
                  <span className="material-symbols-outlined" style={{ color: proofStatusConfig.color }}>
                    {proofStatusConfig.icon}
                  </span>
                  Proof Verification Result
                </div>

                <div className="proof-result-banner" style={{
                  borderColor: proofStatusConfig.color,
                  background: `${proofStatusConfig.color}08`,
                }}>
                  <div className="proof-result-status">
                    <span
                      className="material-symbols-outlined"
                      style={{ fontSize: 28, color: proofStatusConfig.color }}
                    >
                      {proofStatusConfig.icon}
                    </span>
                    <div>
                      <div className="proof-result-title" style={{ color: proofStatusConfig.color }}>
                        {proofStatusConfig.label}
                      </div>
                      {selectedItem.ai_decision && (
                        <div className="proof-result-path">
                          AI decision: {selectedItem.ai_decision}
                        </div>
                      )}
                      <div className="proof-result-path">
                        {selectedItem.proof_image_path || 'No proof path recorded'}
                      </div>
                    </div>
                  </div>

                  {selectedItem.verification_confidence !== null && (
                    <div className="proof-confidence-bar">
                      <span className="proof-confidence-label">Confidence</span>
                      <div className="proof-confidence-track">
                        <div
                          className="proof-confidence-fill"
                          style={{
                            width: `${(selectedItem.verification_confidence ?? 0) * 100}%`,
                            backgroundColor: proofStatusConfig.color,
                          }}
                        />
                      </div>
                      <span className="proof-confidence-pct">
                        {((selectedItem.verification_confidence ?? 0) * 100).toFixed(0)}%
                      </span>
                    </div>
                  )}

                  {selectedItem.verification_rationale && (
                    <div className="proof-rationale">
                      <span className="proof-rationale-label">Rationale</span>
                      <p className="proof-rationale-text">{selectedItem.verification_rationale}</p>
                    </div>
                  )}
                  {selectedItem.verification_attempts > 0 && (
                    <div className="proof-rationale">
                      <span className="proof-rationale-label">Submission attempt</span>
                      <p className="proof-rationale-text">{selectedItem.verification_attempts}</p>
                    </div>
                  )}
                </div>
              </section>
            )}

            {/* Proof Submission Form (only for ASSIGNED items) */}
            {selectedItem.queue_status === 'ASSIGNED' && (
              <section className="proof-detail-card">
                <div className="proof-card-title">
                  <span className="material-symbols-outlined">upload_file</span>
                  Submit Proof of Completion
                </div>

                {selectedItem.verification_status === 'REJECTED' && (
                  <div className="proof-rejection-notice">
                    <span className="material-symbols-outlined">warning</span>
                    Previous proof was rejected. You may resubmit a new proof.
                  </div>
                )}

                <form className="proof-submit-form" onSubmit={handleSubmitProof}>
                  <div className="proof-form-group">
                    <label className="proof-form-label">Upload Proof File</label>
                    <div className="proof-file-drop">
                      <input
                        ref={fileInputRef}
                        type="file"
                        accept="image/*"
                        onChange={(e) => setProofFile(e.target.files?.[0] || null)}
                        disabled={submitting}
                        className="proof-file-input"
                        id="proof-file-input"
                      />
                      <label htmlFor="proof-file-input" className="proof-file-label">
                        <span className="material-symbols-outlined">cloud_upload</span>
                        {proofFile ? proofFile.name : 'Click to upload image'}
                      </label>
                    </div>
                  </div>

                  <button type="submit" className="proof-submit-btn" disabled={submitting}>
                    <span className="material-symbols-outlined">send</span>
                    {submitting ? 'Submitting...' : 'Submit Proof for Verification'}
                  </button>
                </form>
              </section>
            )}

            {/* Completed items info */}
            {selectedItem.queue_status === 'COMPLETED' && !proofStatusConfig && (
              <section className="proof-detail-card">
                <div className="proof-card-title">
                  <span className="material-symbols-outlined" style={{ color: '#10b981' }}>task_alt</span>
                  Task Completed (Manual)
                </div>
                <p className="proof-completed-note">
                  This task was completed via manual/admin override without proof verification.
                </p>
              </section>
            )}
          </>
        )}
      </main>

      {/* Toast */}
      {toastMessage && (
        <div className="proof-toast">
          <span className="material-symbols-outlined">info</span>
          <span>{toastMessage}</span>
        </div>
      )}
    </div>
  )
}
