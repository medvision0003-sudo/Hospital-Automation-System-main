import { useState, useEffect, useCallback, useMemo } from 'react'
import './TaskMaster.css'
import {
  getAllTasks,
  createTask,
  updateTask,
  deleteTask,
  getDepartments,
  uploadTasksExcel,
  downloadExcelTemplate,
} from '../services/taskMasterService'

export default function TaskMaster() {
  const [tasks, setTasks] = useState([])
  const [departments, setDepartments] = useState([])
  const [deptMap, setDeptMap] = useState({})
  const [filterDept, setFilterDept] = useState('all')
  const [toast, setToast] = useState({ show: false, message: '', type: 'success' })
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [editingTask, setEditingTask] = useState(null)
  const [deleteTarget, setDeleteTarget] = useState(null)

  const [showExcelModal, setShowExcelModal] = useState(false)
  const [selectedFile, setSelectedFile] = useState(null)
  const [isUploadingExcel, setIsUploadingExcel] = useState(false)
  const [excelUploadResult, setExcelUploadResult] = useState(null)
  const [excelError, setExcelError] = useState(null)

  const [formDeptId, setFormDeptId] = useState('')
  const [formName, setFormName] = useState('')
  const [formDesc, setFormDesc] = useState('')
  const [formRole, setFormRole] = useState('')
  const [formSkill, setFormSkill] = useState('')
  const [formPriority, setFormPriority] = useState('MEDIUM')
  const [formEstTime, setFormEstTime] = useState('')
  const [formSuggestedStartTime, setFormSuggestedStartTime] = useState('')
  const [formDueTime, setFormDueTime] = useState('')
  const [formType, setFormType] = useState('RECURRING')
  const [formRequiresProof, setFormRequiresProof] = useState(false)

  const showToast = (message, type = 'success') => {
    setToast({ show: true, message, type })
    setTimeout(() => setToast({ show: false, message: '', type: 'success' }), 3000)
  }

  const loadData = useCallback(async () => {
    try {
      const [tasksData, deptsData] = await Promise.all([
        getAllTasks(),
        getDepartments(),
      ])
      setTasks(tasksData)
      setDepartments(deptsData)
      const m = {}
      deptsData.forEach(d => { m[d.department_id] = d.department_name })
      setDeptMap(m)
    } catch (err) {
      console.error('Failed to load data', err)
    }
  }, [])

  useEffect(() => {
    loadData()
  }, [loadData])

  useEffect(() => {
    if (departments.length > 0 && !formDeptId) {
      setFormDeptId(departments[0].department_id.toString())
    }
  }, [departments, formDeptId])

  const resetForm = () => {
    setEditingTask(null)
    setFormName('')
    setFormDesc('')
    setFormRole('')
    setFormSkill('')
    setFormPriority('MEDIUM')
    setFormEstTime('')
    setFormSuggestedStartTime('')
    setFormDueTime('')
    setFormType('RECURRING')
    setFormRequiresProof(false)
    if (departments.length > 0) {
      setFormDeptId(departments[0].department_id.toString())
    }
  }

  const handleEdit = (task) => {
    setEditingTask(task)
    setFormDeptId(task.department_id ? task.department_id.toString() : '')
    setFormName(task.task_name)
    setFormDesc(task.description || '')
    setFormRole(task.required_role || '')
    setFormSkill(task.required_skill || '')
    setFormPriority(task.priority_category || 'MEDIUM')
    setFormEstTime(task.estimated_time ? task.estimated_time.toString() : '')
    setFormSuggestedStartTime(task.suggested_start_time?.slice(0, 5) || '')
    setFormDueTime(task.due_time?.slice(0, 5) || '')
    setFormType(task.task_type)
    setFormRequiresProof(Boolean(task.requires_proof))
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (isSubmitting) return
    if (!formName.trim()) return

    setIsSubmitting(true)
    try {
      const payload = {
        department_id: parseInt(formDeptId) || null,
        task_name: formName.trim(),
        description: formDesc.trim() || null,
        required_role: formRole.trim() || null,
        required_skill: formSkill.trim() || null,
        priority_category: formPriority,
        estimated_time: formEstTime ? parseInt(formEstTime) : null,
        suggested_start_time: formSuggestedStartTime || null,
        due_time: formDueTime || null,
        task_type: formType,
        requires_proof: formRequiresProof,
      }

      if (editingTask) {
        await updateTask(editingTask.task_id, payload)
        showToast(`Task "${formName.trim()}" updated successfully`)
      } else {
        await createTask(payload)
        showToast(`Task "${formName.trim()}" created successfully`)
      }

      resetForm()
      await loadData()
    } catch (err) {
      showToast(err.message || 'Operation failed', 'error')
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleDelete = async () => {
    if (!deleteTarget) return
    try {
      await deleteTask(deleteTarget.task_id)
      showToast(`Task "${deleteTarget.task_name}" deleted`)
      setDeleteTarget(null)
      if (editingTask && editingTask.task_id === deleteTarget.task_id) {
        resetForm()
      }
      await loadData()
    } catch (err) {
      showToast(err.message || 'Failed to delete', 'error')
    }
  }

  const handleToggleState = async (task) => {
    const newState = task.task_state === 'ACTIVE' ? 'INACTIVE' : 'ACTIVE'
    try {
      await updateTask(task.task_id, { task_state: newState })
      await loadData()
    } catch (err) {
      showToast(err.message || 'Failed to update state', 'error')
    }
  }

  const handleFileSelect = (e) => {
    const file = e.target.files[0]
    if (!file) return
    if (!file.name.toLowerCase().endsWith('.xlsx')) {
      setExcelError('Only .xlsx files are accepted. Please select a valid Excel file.')
      setSelectedFile(null)
      return
    }
    setExcelError(null)
    setSelectedFile(file)
  }

  const handleUploadExcel = async () => {
    if (!selectedFile) return
    setIsUploadingExcel(true)
    setExcelError(null)
    setExcelUploadResult(null)

    try {
      const result = await uploadTasksExcel(selectedFile)
      setExcelUploadResult(result)
      if (result.imported_count > 0) {
        showToast(`Successfully imported ${result.imported_count} task(s)`)
        await loadData()
      } else {
        showToast('Import completed with 0 tasks added', 'error')
      }
    } catch (err) {
      setExcelError(err.message || 'Failed to upload Excel file')
    } finally {
      setIsUploadingExcel(false)
    }
  }

  const handleDownloadTemplate = async () => {
    try {
      await downloadExcelTemplate()
    } catch (err) {
      showToast(err.message || 'Failed to download template', 'error')
    }
  }

  const filteredTasks = useMemo(() => {
    if (filterDept === 'all') return tasks
    return tasks.filter(t => t.department_id === parseInt(filterDept))
  }, [tasks, filterDept])

  const kpis = useMemo(() => {
    const total = tasks.length
    const active = tasks.filter(t => t.task_state === 'ACTIVE').length
    const recurring = tasks.filter(t => t.task_type === 'RECURRING').length
    const event = tasks.filter(t => t.task_type === 'EVENT_TEMPLATE').length
    return { total, active, recurring, event }
  }, [tasks])

  return (
    <div className="tm-page">
      {toast.show && (
        <div className={`tm-toast ${toast.type === 'error' ? 'tm-toast-error' : 'tm-toast-success'}`}>
          <span className="material-symbols-outlined" style={{ fontSize: 20, fontVariationSettings: "'FILL' 1" }}>
            {toast.type === 'error' ? 'error' : 'check_circle'}
          </span>
          {toast.message}
        </div>
      )}

      <div className="tm-header">
        <div>
          <div className="tm-title-row">
            <div className="tm-title-icon-wrap">
              <span className="material-symbols-outlined tm-title-icon">assignment</span>
            </div>
            <div>
              <h2 className="tm-title">Task Master</h2>
              <p className="tm-subtitle">Register and manage all hospital task templates</p>
            </div>
          </div>
        </div>
      </div>

      <div className="tm-kpi-strip">
        <div className="tm-kpi tm-kpi-total">
          <div className="tm-kpi-text">
            <span className="tm-kpi-label">TOTAL TASKS</span>
            <span className="tm-kpi-num">{kpis.total}</span>
          </div>
          <div className="tm-kpi-icon-wrap">
            <span className="material-symbols-outlined">assignment</span>
          </div>
        </div>
        <div className="tm-kpi-divider" />
        <div className="tm-kpi tm-kpi-active">
          <div className="tm-kpi-text">
            <span className="tm-kpi-label">ACTIVE</span>
            <span className="tm-kpi-num">{kpis.active}</span>
          </div>
          <div className="tm-kpi-icon-wrap">
            <span className="material-symbols-outlined">check_circle</span>
          </div>
        </div>
        <div className="tm-kpi-divider" />
        <div className="tm-kpi tm-kpi-recurring">
          <div className="tm-kpi-text">
            <span className="tm-kpi-label">RECURRING</span>
            <span className="tm-kpi-num">{kpis.recurring}</span>
          </div>
          <div className="tm-kpi-icon-wrap">
            <span className="material-symbols-outlined">event_repeat</span>
          </div>
        </div>
        <div className="tm-kpi-divider" />
        <div className="tm-kpi tm-kpi-event">
          <div className="tm-kpi-text">
            <span className="tm-kpi-label">EVENT TEMPLATE</span>
            <span className="tm-kpi-num">{kpis.event}</span>
          </div>
          <div className="tm-kpi-icon-wrap">
            <span className="material-symbols-outlined">bolt</span>
          </div>
        </div>
      </div>

      <div className="tm-columns">
        <div className="tm-left-col">
          <div className="tm-table-wrap">
            <div className="tm-table-header">
              <h3 className="tm-section-title">All Tasks</h3>
              <div className="tm-table-actions">
                <button
                  type="button"
                  className="tm-btn-excel"
                  onClick={() => {
                    setShowExcelModal(true)
                    setExcelUploadResult(null)
                    setExcelError(null)
                    setSelectedFile(null)
                  }}
                  title="Import tasks from Excel spreadsheet (.xlsx)"
                >
                  <span className="material-symbols-outlined" style={{ fontSize: 18 }}>upload_file</span>
                  Import Excel (.xlsx)
                </button>
                <select
                  className="tm-filter-select"
                  value={filterDept}
                  onChange={e => setFilterDept(e.target.value)}
                >
                  <option value="all">All Departments</option>
                  {departments.map(d => (
                    <option key={d.department_id} value={d.department_id}>
                      {d.department_name}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <table className="tm-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>TASK NAME</th>
                  <th>PRIORITY</th>
                  <th>TYPE</th>
                  <th>PROOF</th>
                  <th>SCHEDULES</th>
                  <th>STATE</th>
                  <th>ACTIONS</th>
                </tr>
              </thead>
              <tbody>
                {filteredTasks.length === 0 && (
                  <tr><td colSpan={8} className="tm-empty-td">No tasks found</td></tr>
                )}
                {filteredTasks.map((task, idx) => {
                  const priority = (task.priority_category || 'MEDIUM').toUpperCase()
                  const scheduleCount = task.schedules ? task.schedules.length : 0
                  const isActive = task.task_state === 'ACTIVE'
                  const isEvent = task.task_type === 'EVENT_TEMPLATE'

                  return (
                    <tr key={task.task_id}>
                      <td className="tm-td-num">{String(idx + 1).padStart(3, '0')}</td>
                      <td>
                        <div className="tm-task-name">{task.task_name}</div>
                        <div className="tm-task-dept-row">
                          <span className="tm-task-dept">{deptMap[task.department_id] || '—'}</span>
                          {task.required_role && (
                            <span className="tm-skill-tag" title={`Required Role: ${task.required_role}`}>
                              {task.required_role}
                            </span>
                          )}
                          {task.required_skill && (
                            <span className="tm-skill-tag" title={`Required Skill: ${task.required_skill}`}>
                              <span className="material-symbols-outlined" style={{ fontSize: 13 }}>psychology</span>
                              {task.required_skill}
                            </span>
                          )}
                        </div>
                        <div className="tm-task-dept-row">
                          {task.estimated_time ? `${task.estimated_time} min` : 'Duration not set'}
                          {' · '}
                          {task.suggested_start_time?.slice(0, 5) || 'Start not set'}
                          {' - '}
                          {task.due_time?.slice(0, 5) || 'Due time not set'}
                        </div>
                      </td>
                      <td>
                        <span className={`tm-badge tm-badge-${priority.toLowerCase()}`}>
                          {priority}
                        </span>
                      </td>
                      <td>
                        <span className={`tm-type-cell ${isEvent ? 'tm-type-event' : 'tm-type-recurring'}`}>
                          <span className="material-symbols-outlined tm-type-icon">
                            {isEvent ? 'bolt' : 'event_repeat'}
                          </span>
                          {isEvent ? 'Event Template' : 'Recurring'}
                        </span>
                      </td>
                      <td>{task.requires_proof ? 'Required' : 'Optional'}</td>
                      <td>
                        <span className={`tm-schedule-count ${scheduleCount === 0 ? 'tm-schedule-none' : ''}`}>
                          {isEvent ? '—' : (scheduleCount > 0 ? String(scheduleCount).padStart(2, '0') : '0')}
                        </span>
                      </td>
                      <td>
                        <button
                          className={`tm-state-toggle ${isActive ? 'tm-state-active' : 'tm-state-inactive'}`}
                          onClick={() => handleToggleState(task)}
                          title={isActive ? 'Click to deactivate' : 'Click to activate'}
                        />
                      </td>
                      <td>
                        <div className="tm-td-actions">
                          <button
                            className="tm-act-btn tm-act-edit"
                            title="Edit task"
                            onClick={() => handleEdit(task)}
                          >
                            <span className="material-symbols-outlined" style={{ fontSize: 18 }}>edit</span>
                          </button>
                          <button
                            className="tm-act-btn tm-act-del"
                            title="Delete task"
                            onClick={() => setDeleteTarget(task)}
                          >
                            <span className="material-symbols-outlined" style={{ fontSize: 18 }}>delete</span>
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            {filteredTasks.length > 0 && (
              <div className="tm-table-footer">
                <span>Showing {filteredTasks.length} of {tasks.length} tasks</span>
              </div>
            )}
          </div>
        </div>

        <div className="tm-right-col">
          <div className="tm-form-card">
            <div className="tm-form-header">
              <h3 className="tm-form-title">
                {editingTask ? 'Edit Task' : 'New Task Template'}
              </h3>
              {editingTask && (
                <button className="tm-form-cancel-btn" onClick={resetForm} title="Cancel edit">
                  <span className="material-symbols-outlined" style={{ fontSize: 20 }}>close</span>
                </button>
              )}
            </div>
            <form onSubmit={handleSubmit} className="tm-form-container">
              <div className="tm-form-group">
                <label className="tm-form-label">Department</label>
                <select
                  className="tm-form-select"
                  value={formDeptId}
                  onChange={e => setFormDeptId(e.target.value)}
                  required
                >
                  {departments.length === 0 && <option value="">Loading...</option>}
                  {departments.map(d => (
                    <option key={d.department_id} value={d.department_id}>
                      {d.department_name}
                    </option>
                  ))}
                </select>
              </div>

              <div className="tm-form-group">
                <label className="tm-form-label">Task Name</label>
                <input
                  type="text"
                  className="tm-form-input"
                  placeholder="e.g. Daily Ward Sanitization"
                  value={formName}
                  onChange={e => setFormName(e.target.value)}
                  required
                />
              </div>

              <div className="tm-form-group">
                <label className="tm-form-label">Description</label>
                <textarea
                  className="tm-form-textarea"
                  placeholder="Detailed workflow instructions..."
                  value={formDesc}
                  onChange={e => setFormDesc(e.target.value)}
                />
              </div>

              <div className="tm-form-group">
                <label className="tm-form-label">
                  <input
                    type="checkbox"
                    checked={formRequiresProof}
                    onChange={e => setFormRequiresProof(e.target.checked)}
                  />{' '}
                  Require verified proof before completion
                </label>
              </div>

              <div className="tm-form-group">
                <label className="tm-form-label">Required Role</label>
                <input
                  type="text"
                  className="tm-form-input"
                  placeholder="e.g. Nurse, Doctor, Technician"
                  value={formRole}
                  onChange={e => setFormRole(e.target.value)}
                />
              </div>

              <div className="tm-form-group">
                <label className="tm-form-label">Required Skill</label>
                <input
                  type="text"
                  className="tm-form-input"
                  placeholder="e.g. ACLS, ICU, TRAUMA"
                  value={formSkill}
                  onChange={e => setFormSkill(e.target.value)}
                />
              </div>

              <div className="tm-form-row">
                <div className="tm-form-group">
                  <label className="tm-form-label">Suggested Start Time</label>
                  <input
                    type="time"
                    className="tm-form-input"
                    value={formSuggestedStartTime}
                    onChange={e => setFormSuggestedStartTime(e.target.value)}
                  />
                </div>
                <div className="tm-form-group">
                  <label className="tm-form-label">Due Time</label>
                  <input
                    type="time"
                    className="tm-form-input"
                    value={formDueTime}
                    onChange={e => setFormDueTime(e.target.value)}
                  />
                </div>
              </div>

              <div className="tm-form-group">
                <label className="tm-form-label">Task Type</label>
                <select
                  className="tm-form-select"
                  value={formType}
                  onChange={e => setFormType(e.target.value)}
                  required
                >
                  <option value="RECURRING">Recurring</option>
                  <option value="EVENT_TEMPLATE">Event Template</option>
                </select>
              </div>

              <div className="tm-form-row">
                <div className="tm-form-group">
                  <label className="tm-form-label">Priority</label>
                  <select
                    className="tm-form-select"
                    value={formPriority}
                    onChange={e => setFormPriority(e.target.value)}
                    required
                  >
                    <option value="LOW">Low</option>
                    <option value="MEDIUM">Medium</option>
                    <option value="HIGH">High</option>
                    <option value="CRITICAL">Critical</option>
                  </select>
                </div>
                <div className="tm-form-group">
                  <label className="tm-form-label">Estimated Time (min)</label>
                  <input
                    type="number"
                    className="tm-form-input"
                    placeholder="30"
                    min="1"
                    value={formEstTime}
                    onChange={e => setFormEstTime(e.target.value)}
                  />
                </div>
              </div>

              <button
                type="submit"
                className={`tm-form-submit-btn ${editingTask ? 'tm-form-update-btn' : ''}`}
                disabled={isSubmitting}
              >
                <span className="material-symbols-outlined" style={{ fontSize: 20 }}>
                  {editingTask ? 'save' : 'add_circle'}
                </span>
                {isSubmitting ? 'Saving...' : editingTask ? 'Update Task' : 'Create Template'}
              </button>
            </form>
          </div>
        </div>
      </div>

      {deleteTarget && (
        <div className="tm-delete-confirm">
          <div className="tm-delete-backdrop" onClick={() => setDeleteTarget(null)} />
          <div className="tm-delete-dialog">
            <h4>Delete Task?</h4>
            <p>
              Are you sure you want to delete <strong>"{deleteTarget.task_name}"</strong>?
              This will also remove all linked schedules.
            </p>
            <div className="tm-delete-dialog-actions">
              <button className="tm-dialog-cancel-btn" onClick={() => setDeleteTarget(null)}>
                Cancel
              </button>
              <button className="tm-dialog-delete-btn" onClick={handleDelete}>
                Delete
              </button>
            </div>
          </div>
        </div>
      )}

      {showExcelModal && (
        <div className="tm-modal-overlay">
          <div className="tm-modal-card">
            <div className="tm-modal-header">
              <div className="tm-modal-title-wrap">
                <span className="material-symbols-outlined tm-excel-modal-icon">table_view</span>
                <div>
                  <h3 className="tm-modal-title">Bulk Import Tasks (.xlsx)</h3>
                  <p className="tm-modal-subtitle">Upload an Excel spreadsheet matching Task Master database fields</p>
                </div>
              </div>
              <button
                type="button"
                className="tm-modal-close"
                onClick={() => setShowExcelModal(false)}
                disabled={isUploadingExcel}
              >
                <span className="material-symbols-outlined">close</span>
              </button>
            </div>

            <div className="tm-modal-body">
              <div className="tm-template-banner">
                <span className="material-symbols-outlined" style={{ color: 'var(--primary)' }}>download_for_offline</span>
                <div className="tm-template-info">
                  <strong>Need the exact Excel format?</strong>
                  <span>Download a sample .xlsx template formatted with database table headers.</span>
                </div>
                <button
                  type="button"
                  className="tm-btn-template"
                  onClick={handleDownloadTemplate}
                >
                  Download Template
                </button>
              </div>

              <div className="tm-dropzone">
                <input
                  type="file"
                  id="excelFileInput"
                  accept=".xlsx, application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                  onChange={handleFileSelect}
                  className="tm-file-input"
                  disabled={isUploadingExcel}
                />
                <label htmlFor="excelFileInput" className="tm-dropzone-label">
                  <span className="material-symbols-outlined tm-dropzone-icon">cloud_upload</span>
                  {selectedFile ? (
                    <div className="tm-selected-file-info">
                      <strong>{selectedFile.name}</strong>
                      <span>{(selectedFile.size / 1024).toFixed(1)} KB</span>
                    </div>
                  ) : (
                    <div>
                      <strong>Click to select or drop .xlsx file</strong>
                      <span className="tm-dropzone-hint">Strictly .xlsx files accepted (Max 5MB / 500 rows)</span>
                    </div>
                  )}
                </label>
              </div>

              {excelError && (
                <div className="tm-excel-error-banner">
                  <span className="material-symbols-outlined">error</span>
                  {excelError}
                </div>
              )}

              {excelUploadResult && (
                <div className="tm-results-panel">
                  <h4 className="tm-results-title">Import Summary</h4>
                  <div className="tm-results-stats">
                    <div className="tm-stat-chip tm-chip-processed">
                      <span>Processed</span>
                      <strong>{excelUploadResult.total_processed}</strong>
                    </div>
                    <div className="tm-stat-chip tm-chip-imported">
                      <span>Imported</span>
                      <strong>{excelUploadResult.imported_count}</strong>
                    </div>
                    <div className="tm-stat-chip tm-chip-skipped">
                      <span>Skipped</span>
                      <strong>{excelUploadResult.skipped_count}</strong>
                    </div>
                    <div className="tm-stat-chip tm-chip-failed">
                      <span>Failed</span>
                      <strong>{excelUploadResult.failed_count}</strong>
                    </div>
                  </div>

                  {((excelUploadResult.errors && excelUploadResult.errors.length > 0) ||
                    (excelUploadResult.skips && excelUploadResult.skips.length > 0)) && (
                    <div className="tm-results-details">
                      <h5 className="tm-details-heading">Row Details & Issues</h5>
                      <div className="tm-issues-list custom-scrollbar">
                        {excelUploadResult.errors && excelUploadResult.errors.map((err, i) => (
                          <div key={`err-${i}`} className="tm-issue-item tm-issue-error">
                            <span className="tm-row-badge">Row {err.row}</span>
                            <span className="tm-issue-text">{err.reason}</span>
                          </div>
                        ))}
                        {excelUploadResult.skips && excelUploadResult.skips.map((sk, i) => (
                          <div key={`skip-${i}`} className="tm-issue-item tm-issue-skip">
                            <span className="tm-row-badge tm-skip-badge">Row {sk.row}</span>
                            <span className="tm-issue-text">{sk.reason}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>

            <div className="tm-modal-footer">
              <button
                type="button"
                className="tm-btn-cancel"
                onClick={() => setShowExcelModal(false)}
                disabled={isUploadingExcel}
              >
                Close
              </button>
              <button
                type="button"
                className="tm-btn-submit-excel"
                onClick={handleUploadExcel}
                disabled={!selectedFile || isUploadingExcel}
              >
                {isUploadingExcel ? (
                  <>
                    <span className="material-symbols-outlined tm-spin">sync</span>
                    Importing...
                  </>
                ) : (
                  'Upload & Import'
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
