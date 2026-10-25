import { useState, useEffect, useCallback, useMemo } from 'react'
import {
  getDepartments,
  getShifts,
  createShift,
  updateShift,
  deleteShift,
} from '../services/rosterService'
import './ShiftsManagement.css'

function formatShiftTime(start, end) {
  if (!start || !end) return ''
  const formatTime = (tStr) => {
    const parts = String(tStr).split(':')
    if (parts.length < 2) return tStr
    let h = parseInt(parts[0], 10)
    const m = parts[1]
    const ampm = h >= 12 ? 'PM' : 'AM'
    h = h % 12 || 12
    const hStr = h < 10 ? `0${h}` : `${h}`
    return `${hStr}:${m} ${ampm}`
  }
  return `${formatTime(start)} – ${formatTime(end)}`
}

function getShiftBadgeClass(shiftName) {
  const name = (shiftName || '').toLowerCase()
  if (name.includes('morning')) return 'morning'
  if (name.includes('afternoon')) return 'afternoon'
  if (name.includes('evening')) return 'evening'
  if (name.includes('night')) return 'night'
  return 'custom'
}

export default function ShiftsManagement() {
  const [departments, setDepartments] = useState([])
  const [shifts, setShifts] = useState([])
  const [loading, setLoading] = useState(true)
  const [toast, setToast] = useState({ show: false, message: '', type: 'success' })

  // Modal State
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [modalMode, setModalMode] = useState('CREATE')
  const [editingShiftId, setEditingShiftId] = useState(null)
  const [deletingShift, setDeletingShift] = useState(null)
  
  // Form State
  const [formDeptId, setFormDeptId] = useState('GLOBAL')
  const [formShiftName, setFormShiftName] = useState('')
  const [formStartTime, setFormStartTime] = useState('07:00')
  const [formEndTime, setFormEndTime] = useState('15:00')
  const [submitting, setSubmitting] = useState(false)

  const showToast = (message, type = 'success') => {
    setToast({ show: true, message, type })
    setTimeout(() => setToast({ show: false, message: '', type: 'success' }), 3000)
  }

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const [depts, shs] = await Promise.all([
        getDepartments(),
        getShifts(),
      ])
      setDepartments(depts)
      setShifts(shs)
    } catch (err) {
      console.error('Failed to load shift management data:', err)
      showToast('Failed to load shifts or departments', 'error')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadData()
  }, [loadData])

  // Group shifts: global templates and department-specific
  const globalShifts = useMemo(() => shifts.filter(s => s.department_id === null), [shifts])

  const departmentGroups = useMemo(() => {
    const deptShiftMap = {}
    shifts.forEach(s => {
      if (s.department_id !== null) {
        if (!deptShiftMap[s.department_id]) deptShiftMap[s.department_id] = []
        deptShiftMap[s.department_id].push(s)
      }
    })

    return departments.map(dept => ({
      department: dept,
      shifts: deptShiftMap[dept.department_id] || [],
    }))
  }, [shifts, departments])

  const handleOpenCreateModal = (preselectedDeptId) => {
    setModalMode('CREATE')
    setEditingShiftId(null)
    setFormDeptId(preselectedDeptId != null ? String(preselectedDeptId) : 'GLOBAL')
    setFormShiftName('')
    setFormStartTime('07:00')
    setFormEndTime('15:00')
    setIsModalOpen(true)
  }

  const handleOpenEditModal = (shift) => {
    setModalMode('EDIT')
    setEditingShiftId(shift.shift_id)
    setFormDeptId(shift.department_id ? String(shift.department_id) : 'GLOBAL')
    setFormShiftName(shift.shift_name)
    const cleanTime = (tStr) => String(tStr || '').slice(0, 5)
    setFormStartTime(cleanTime(shift.start_time) || '07:00')
    setFormEndTime(cleanTime(shift.end_time) || '15:00')
    setIsModalOpen(true)
  }

  const handleCloseModal = () => {
    setIsModalOpen(false)
    setSubmitting(false)
  }

  const handleSubmitForm = async (e) => {
    e.preventDefault()
    if (!formShiftName.trim()) {
      showToast('Please enter a shift name', 'error')
      return
    }

    setSubmitting(true)
    try {
      const payload = {
        department_id: formDeptId === 'GLOBAL' ? null : Number(formDeptId),
        shift_name: formShiftName.trim(),
        start_time: formStartTime.length === 5 ? `${formStartTime}:00` : formStartTime,
        end_time: formEndTime.length === 5 ? `${formEndTime}:00` : formEndTime,
      }

      if (modalMode === 'CREATE') {
        await createShift(payload)
        showToast(`Shift "${payload.shift_name}" created successfully`)
      } else {
        await updateShift(editingShiftId, payload)
        showToast(`Shift "${payload.shift_name}" updated successfully`)
      }

      handleCloseModal()
      loadData()
    } catch (err) {
      console.error('Shift save error:', err)
      showToast(err.message || 'Failed to save shift', 'error')
    } finally {
      setSubmitting(false)
    }
  }

  const handleDeleteShift = (shift) => {
    setDeletingShift(shift)
  }

  const handleConfirmDelete = async () => {
    if (!deletingShift) return
    const shift = deletingShift
    setDeletingShift(null)
    try {
      await deleteShift(shift.shift_id)
      showToast(`Shift "${shift.shift_name}" deleted successfully`)
      loadData()
    } catch (err) {
      console.error('Shift delete error:', err)
      showToast(err.message || 'Failed to delete shift', 'error')
    }
  }

  // Reusable shift card renderer
  const renderShiftCard = (shift) => {
    const badgeClass = getShiftBadgeClass(shift.shift_name)
    return (
      <div key={shift.shift_id} className={`shift-card border-${badgeClass}`}>
        <div className="shift-card-header">
          <span className={`shift-dept-tag ${badgeClass}`}>
            {shift.shift_name}
          </span>
          <div className="shift-actions">
            <button
              className="action-icon-btn edit"
              title="Edit Shift"
              onClick={() => handleOpenEditModal(shift)}
            >
              <span className="material-symbols-outlined">edit</span>
            </button>
            <button
              className="action-icon-btn delete"
              title="Delete Shift"
              onClick={() => handleDeleteShift(shift)}
            >
              <span className="material-symbols-outlined">delete</span>
            </button>
          </div>
        </div>

        <div className="shift-card-body">
          <div className="shift-time-range">
            <span className="material-symbols-outlined">schedule</span>
            <span className="time-text">
              {formatShiftTime(shift.start_time, shift.end_time)}
            </span>
          </div>
        </div>

        <div className="shift-card-footer">
          <span className="raw-time-chip">
            Start: {String(shift.start_time).slice(0, 5)}
          </span>
          <span className="raw-time-chip">
            End: {String(shift.end_time).slice(0, 5)}
          </span>
        </div>
      </div>
    )
  }

  return (
    <div className="shifts-mgmt-page">
      {/* Top Header */}
      <header className="shifts-header">
        <div className="header-left">
          <h2>
            <span className="material-symbols-outlined">schedule</span>
            Shift Management Console
          </h2>
          <p>Configure department shift definitions, working hours, and operational schedules.</p>
        </div>

        <div className="header-right">
          <button className="btn-add-shift" onClick={() => handleOpenCreateModal()}>
            <span className="material-symbols-outlined">add</span>
            Add New Shift
          </button>
        </div>
      </header>

      {/* Main Content */}
      <div className="shifts-content-card">
        {loading ? (
          <div className="loading-center">
            <span className="material-symbols-outlined spinner">progress_activity</span>
            Loading shifts...
          </div>
        ) : (
          <div className="dept-shift-sections">
            {/* Global / Standard Templates Section */}
            <div className="dept-section">
              <div className="dept-section-header">
                <div className="dept-section-title">
                  <span className="material-symbols-outlined">public</span>
                  <h3>Global / Standard Templates</h3>
                  <span className="shift-count-badge">{globalShifts.length}</span>
                </div>
                <button className="btn-add-dept-shift" onClick={() => handleOpenCreateModal('GLOBAL')}>
                  <span className="material-symbols-outlined">add</span>
                  Add Template
                </button>
              </div>
              {globalShifts.length > 0 ? (
                <div className="shifts-row">
                  {globalShifts.map(renderShiftCard)}
                </div>
              ) : (
                <div className="dept-empty-notice">
                  <span className="material-symbols-outlined">info</span>
                  No global shift templates defined yet.
                </div>
              )}
            </div>

            {/* Department-Specific Sections */}
            {departmentGroups.map(({ department, shifts: deptShifts }) => (
              <div key={department.department_id} className="dept-section">
                <div className="dept-section-header">
                  <div className="dept-section-title">
                    <span className="material-symbols-outlined">domain</span>
                    <h3>{department.department_name}</h3>
                    <span className="shift-count-badge">
                      {deptShifts.length > 0 ? deptShifts.length : 'Standard'}
                    </span>
                  </div>
                  <button
                    className="btn-add-dept-shift"
                    onClick={() => handleOpenCreateModal(department.department_id)}
                  >
                    <span className="material-symbols-outlined">add</span>
                    Add Shift
                  </button>
                </div>
                {deptShifts.length > 0 ? (
                  <div className="shifts-row">
                    {deptShifts.map(renderShiftCard)}
                  </div>
                ) : (
                  <div className="dept-empty-notice">
                    <span className="material-symbols-outlined">check_circle</span>
                    Uses Standard Shift Templates
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Modal Dialog for Create & Edit */}
      {isModalOpen && (
        <div className="modal-backdrop">
          <div className="modal-container">
            <div className="modal-header">
              <h3>
                <span className="material-symbols-outlined">
                  {modalMode === 'CREATE' ? 'add_circle' : 'edit_square'}
                </span>
                {modalMode === 'CREATE' ? 'Add New Shift Definition' : 'Edit Shift Definition'}
              </h3>
              <button className="close-btn" onClick={handleCloseModal}>
                <span className="material-symbols-outlined">close</span>
              </button>
            </div>

            <form onSubmit={handleSubmitForm} className="modal-form">
              <div className="form-group">
                <label>Department</label>
                <select
                  value={formDeptId}
                  onChange={(e) => setFormDeptId(e.target.value)}
                >
                  <option value="GLOBAL">Global / Standard Template</option>
                  {departments.map(d => (
                    <option key={d.department_id} value={String(d.department_id)}>
                      {d.department_name}
                    </option>
                  ))}
                </select>
              </div>

              <div className="form-group">
                <label>Shift Name</label>
                <input
                  type="text"
                  placeholder="e.g. Morning Shift"
                  value={formShiftName}
                  onChange={(e) => setFormShiftName(e.target.value)}
                  required
                />
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label>Start Time</label>
                  <input
                    type="time"
                    value={formStartTime}
                    onChange={(e) => setFormStartTime(e.target.value)}
                    required
                  />
                </div>

                <div className="form-group">
                  <label>End Time</label>
                  <input
                    type="time"
                    value={formEndTime}
                    onChange={(e) => setFormEndTime(e.target.value)}
                    required
                  />
                </div>
              </div>

              <div className="modal-actions">
                <button
                  type="button"
                  className="btn-cancel"
                  onClick={handleCloseModal}
                  disabled={submitting}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn-submit"
                  disabled={submitting}
                >
                  {submitting ? 'Saving...' : modalMode === 'CREATE' ? 'Create Shift' : 'Save Changes'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {deletingShift && (
        <div className="modal-backdrop">
          <div className="modal-container delete-confirm-modal" style={{ maxWidth: 440 }}>
            <div className="modal-header warning-header" style={{ borderBottom: '1px solid #fee2e2', background: '#fef2f2' }}>
              <h3 style={{ color: '#991b1b' }}>
                <span className="material-symbols-outlined" style={{ color: '#dc2626' }}>warning</span>
                Confirm Shift Deletion
              </h3>
              <button className="close-btn" onClick={() => setDeletingShift(null)}>
                <span className="material-symbols-outlined">close</span>
              </button>
            </div>
            <div className="modal-body" style={{ padding: '24px 20px', textAlign: 'center' }}>
              <div style={{ fontSize: '15px', fontWeight: 600, color: '#0f172a', marginBottom: '8px' }}>
                Are you sure to delete the selected shift?
              </div>
              <div style={{ fontSize: '13px', color: '#64748b', background: '#f8fafc', padding: '10px 14px', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
                <strong style={{ color: '#0f172a' }}>{deletingShift.shift_name}</strong>
                <div style={{ marginTop: 2, fontSize: '12px', opacity: 0.8 }}>
                  ({formatShiftTime(deletingShift.start_time, deletingShift.end_time)})
                </div>
              </div>
            </div>
            <div className="modal-actions" style={{ padding: '14px 20px', background: '#f8fafc', borderTop: '1px solid #e2e8f0', justifyContent: 'flex-end', gap: 10 }}>
              <button className="btn-cancel" onClick={() => setDeletingShift(null)}>
                Cancel
              </button>
              <button
                type="button"
                className="btn-danger"
                onClick={handleConfirmDelete}
                style={{ backgroundColor: '#dc2626', color: '#ffffff', border: 'none', borderRadius: '8px', padding: '0 18px', height: '38px', fontWeight: 600, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6 }}
              >
                <span className="material-symbols-outlined" style={{ fontSize: 18 }}>delete</span>
                Confirm Delete
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Toast Alert */}
      {toast.show && (
        <div className={`toast-bar ${toast.type}`}>
          <span className="material-symbols-outlined">
            {toast.type === 'error' ? 'error' : 'check_circle'}
          </span>
          <span>{toast.message}</span>
        </div>
      )}
    </div>
  )
}
