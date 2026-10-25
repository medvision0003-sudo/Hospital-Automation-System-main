import { useState, useEffect, useMemo } from 'react'
import {
  fetchEmployees,
  createEmployee,
  updateEmployee,
  deleteEmployee,
  fetchDepartments
} from '../services/employeeService'
import './EmployeeManagement.css'

export default function EmployeeManagement() {
  const [employees, setEmployees] = useState([])
  const [departments, setDepartments] = useState([])
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [toast, setToast] = useState(null)

  const [searchQuery, setSearchQuery] = useState('')
  const [selectedDeptFilter, setSelectedDeptFilter] = useState('ALL')

  const [isEditing, setIsEditing] = useState(false)
  const [editingId, setEditingId] = useState(null)
  const [deleteTarget, setDeleteTarget] = useState(null)

  const initialFormState = {
    name: '',
    role: '',
    department_id: '',
    phone: '',
    gender: 'MALE',
    skill: '',
    experience_years: 0
  }

  const [formData, setFormData] = useState(initialFormState)

  const showToast = (message, type = 'success') => {
    setToast({ message, type })
    setTimeout(() => setToast(null), 4000)
  }

  const loadData = async () => {
    try {
      setLoading(true)
      const [empData, deptData] = await Promise.all([
        fetchEmployees(),
        fetchDepartments()
      ])
      setEmployees(empData)
      setDepartments(deptData)
    } catch (err) {
      showToast(err.message || 'Failed to load employee records.', 'error')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [])

  const handleInputChange = (e) => {
    const { name, value } = e.target
    setFormData(prev => ({
      ...prev,
      [name]: value
    }))
  }

  const resetForm = () => {
    setFormData(initialFormState)
    setIsEditing(false)
    setEditingId(null)
  }

  const handleEditClick = (emp) => {
    setIsEditing(true)
    setEditingId(emp.employee_id)
    setFormData({
      name: emp.name || '',
      role: emp.role || '',
      department_id: emp.department_id ? String(emp.department_id) : '',
      phone: emp.phone ? String(emp.phone) : '',
      gender: emp.gender || 'MALE',
      skill: emp.skill || '',
      experience_years: emp.experience_years !== undefined ? emp.experience_years : 0
    })
  }

  const handleSubmit = async (e) => {
    e.preventDefault()

    if (!formData.name.trim()) {
      showToast('Employee name is required.', 'error')
      return
    }
    if (!formData.role.trim()) {
      showToast('Employee role is required.', 'error')
      return
    }
    if (!formData.gender) {
      showToast('Gender selection is required.', 'error')
      return
    }

    try {
      setSubmitting(true)
      const payload = {
        name: formData.name.trim(),
        role: formData.role.trim(),
        department_id: formData.department_id ? Number(formData.department_id) : null,
        phone: formData.phone ? Number(formData.phone) : null,
        gender: formData.gender,
        skill: formData.skill ? formData.skill.trim() : null,
        experience_years: Number(formData.experience_years) || 0
      }

      if (isEditing) {
        await updateEmployee(editingId, payload)
        showToast(`Employee EMP-${editingId} updated successfully.`)
      } else {
        await createEmployee(payload)
        showToast('New employee created successfully.')
      }

      resetForm()
      await loadData()
    } catch (err) {
      showToast(err.message || 'Operation failed.', 'error')
    } finally {
      setSubmitting(false)
    }
  }

  const handleDeleteConfirm = async () => {
    if (!deleteTarget) return
    try {
      setSubmitting(true)
      await deleteEmployee(deleteTarget.employee_id)
      showToast(`Employee ${deleteTarget.name} (EMP-${deleteTarget.employee_id}) deleted successfully.`)
      setDeleteTarget(null)
      await loadData()
    } catch (err) {
      showToast(err.message || 'Failed to delete employee.', 'error')
    } finally {
      setSubmitting(false)
    }
  }

  const filteredEmployees = useMemo(() => {
    return employees.filter(emp => {
      const q = searchQuery.toLowerCase().trim()
      const matchesSearch = !q ||
        emp.name?.toLowerCase().includes(q) ||
        emp.role?.toLowerCase().includes(q) ||
        emp.skill?.toLowerCase().includes(q) ||
        String(emp.employee_id).includes(q)

      const matchesDept = selectedDeptFilter === 'ALL' ||
        String(emp.department_id) === String(selectedDeptFilter)

      return matchesSearch && matchesDept
    })
  }, [employees, searchQuery, selectedDeptFilter])

  const totalEmployees = employees.length
  const totalDepts = departments.length


  return (
    <div className="emp-page">
      {toast && (
        <div className={`emp-toast emp-toast-${toast.type}`}>
          <span className="material-symbols-outlined">
            {toast.type === 'success' ? 'check_circle' : 'error'}
          </span>
          <span>{toast.message}</span>
        </div>
      )}

      <div className="emp-header">
        <div>
          <div className="emp-title-row">
            <div className="emp-title-icon-wrap">
              <span className="material-symbols-outlined emp-title-icon">badge</span>
            </div>
            <h2 className="emp-title">Employee Directory</h2>
          </div>
          <p className="emp-subtitle">
            Admin portal for managing hospital employee personal profiles and department assignments.
          </p>
        </div>
      </div>

      <div className="emp-kpi-strip">
        <div className="emp-kpi emp-kpi-total">
          <div className="emp-kpi-text">
            <span className="emp-kpi-label">Total Employees</span>
            <span className="emp-kpi-num">{totalEmployees}</span>
          </div>
          <div className="emp-kpi-icon-wrap">
            <span className="material-symbols-outlined">badge</span>
          </div>
        </div>
        <div className="emp-kpi-divider" />
        <div className="emp-kpi emp-kpi-depts">
          <div className="emp-kpi-text">
            <span className="emp-kpi-label">Departments</span>
            <span className="emp-kpi-num">{totalDepts}</span>
          </div>
          <div className="emp-kpi-icon-wrap">
            <span className="material-symbols-outlined">corporate_fare</span>
          </div>
        </div>
      </div>

      <div className="emp-columns">
        <div className="emp-left-col">
          <div className="emp-table-wrap">
            <div className="emp-table-header">
              <h3 className="emp-section-title">Directory Records</h3>
              <div className="emp-table-actions">
                <input
                  type="text"
                  className="emp-search-input"
                  placeholder="Search by name, role, skill..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                />
                <select
                  className="emp-filter-select"
                  value={selectedDeptFilter}
                  onChange={(e) => setSelectedDeptFilter(e.target.value)}
                >
                  <option value="ALL">All Departments</option>
                  {departments.map(dept => (
                    <option key={dept.department_id} value={dept.department_id}>
                      {dept.department_name || dept.name}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <table className="emp-table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Employee Profile</th>
                  <th>Department</th>
                  <th>Contact</th>
                  <th>Skills & Experience</th>
                  <th style={{ textAlign: 'right' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr>
                    <td colSpan={6} className="emp-empty-td">
                      Loading employee profiles...
                    </td>
                  </tr>
                ) : filteredEmployees.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="emp-empty-td">
                      No employees match the criteria.
                    </td>
                  </tr>
                ) : (
                  filteredEmployees.map(emp => {
                    const skillList = emp.skill ? emp.skill.split(',').map(s => s.trim()).filter(Boolean) : []
                    return (
                      <tr key={emp.employee_id}>
                        <td className="emp-td-id">EMP-{emp.employee_id}</td>
                        <td>
                          <div className="emp-name">{emp.name}</div>
                          <div className="emp-role">{emp.role} • {emp.gender}</div>
                        </td>
                        <td>
                          <span className="emp-dept-badge">
                            {emp.department_name || `Dept #${emp.department_id || 'N/A'}`}
                          </span>
                        </td>
                        <td>
                          {emp.phone ? (
                            <span style={{ fontFamily: 'monospace' }}>+{emp.phone}</span>
                          ) : (
                            <span style={{ color: 'var(--on-surface-variant)', opacity: 0.6 }}>N/A</span>
                          )}
                        </td>
                        <td>
                          <div style={{ fontSize: 12, marginBottom: 4 }}>
                            <strong>{emp.experience_years}</strong> yrs exp
                          </div>
                          <div className="emp-skills-list">
                            {skillList.length > 0 ? (
                              skillList.map((skillItem, i) => (
                                <span key={i} className="emp-skill-tag">
                                  {skillItem}
                                </span>
                              ))
                            ) : (
                              <span style={{ fontSize: 11, color: 'var(--on-surface-variant)', opacity: 0.6 }}>
                                No skills specified
                              </span>
                            )}
                          </div>
                        </td>
                        <td>
                          <div className="emp-td-actions" style={{ justifyContent: 'flex-end' }}>
                            <button
                              className="emp-act-btn emp-act-edit"
                              title="Edit Employee Profile"
                              onClick={() => handleEditClick(emp)}
                            >
                              <span className="material-symbols-outlined" style={{ fontSize: 18 }}>edit</span>
                            </button>
                            <button
                              className="emp-act-btn emp-act-del"
                              title="Delete Employee"
                              onClick={() => setDeleteTarget(emp)}
                            >
                              <span className="material-symbols-outlined" style={{ fontSize: 18 }}>delete</span>
                            </button>
                          </div>
                        </td>
                      </tr>
                    )
                  })
                )}
              </tbody>
            </table>

            <div className="emp-table-footer">
              <span>Showing {filteredEmployees.length} of {totalEmployees} employees</span>
            </div>
          </div>
        </div>

        <div className="emp-right-col">
          <div className="emp-form-card">
            <div className="emp-form-header">
              <h3 className="emp-form-title">
                {isEditing ? `Edit Employee EMP-${editingId}` : 'Add New Employee'}
              </h3>
              {isEditing && (
                <button className="emp-form-cancel-btn" onClick={resetForm} title="Cancel Editing">
                  <span className="material-symbols-outlined">close</span>
                </button>
              )}
            </div>

            <form onSubmit={handleSubmit} className="emp-form-container">
              <div className="emp-form-group">
                <label className="emp-form-label">Full Name *</label>
                <input
                  type="text"
                  name="name"
                  className="emp-form-input"
                  placeholder="e.g. Sarah Jenkins"
                  value={formData.name}
                  onChange={handleInputChange}
                  required
                />
              </div>

              <div className="emp-form-group">
                <label className="emp-form-label">Role *</label>
                <input
                  type="text"
                  name="role"
                  className="emp-form-input"
                  placeholder="e.g. ICU Senior Nurse"
                  value={formData.role}
                  onChange={handleInputChange}
                  required
                />
              </div>

              <div className="emp-form-row">
                <div className="emp-form-group">
                  <label className="emp-form-label">Department</label>
                  <select
                    name="department_id"
                    className="emp-form-select"
                    value={formData.department_id}
                    onChange={handleInputChange}
                  >
                    <option value="">Select Department</option>
                    {departments.map(d => (
                      <option key={d.department_id} value={d.department_id}>
                        {d.department_name || d.name}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="emp-form-group">
                  <label className="emp-form-label">Gender *</label>
                  <select
                    name="gender"
                    className="emp-form-select"
                    value={formData.gender}
                    onChange={handleInputChange}
                    required
                  >
                    <option value="MALE">MALE</option>
                    <option value="FEMALE">FEMALE</option>
                    <option value="OTHER">OTHER</option>
                  </select>
                </div>
              </div>

              <div className="emp-form-row">
                <div className="emp-form-group">
                  <label className="emp-form-label">Phone Number</label>
                  <input
                    type="number"
                    name="phone"
                    className="emp-form-input"
                    placeholder="10-digit number"
                    value={formData.phone}
                    onChange={handleInputChange}
                  />
                </div>

                <div className="emp-form-group">
                  <label className="emp-form-label">Experience (Years)</label>
                  <input
                    type="number"
                    name="experience_years"
                    className="emp-form-input"
                    min="0"
                    value={formData.experience_years}
                    onChange={handleInputChange}
                  />
                </div>
              </div>

              <div className="emp-form-group">
                <label className="emp-form-label">Skills (Comma-separated)</label>
                <input
                  type="text"
                  name="skill"
                  className="emp-form-input"
                  placeholder="e.g. CPR, Triage, Ventilator"
                  value={formData.skill}
                  onChange={handleInputChange}
                />
              </div>

              <button
                type="submit"
                className={`emp-form-submit-btn ${isEditing ? 'emp-form-update-btn' : ''}`}
                disabled={submitting}
              >
                <span className="material-symbols-outlined" style={{ fontSize: 18 }}>
                  {isEditing ? 'save' : 'person_add'}
                </span>
                {submitting
                  ? (isEditing ? 'Updating...' : 'Adding...')
                  : (isEditing ? 'Update Employee' : 'Add Employee')
                }
              </button>
            </form>
          </div>
        </div>
      </div>

      {deleteTarget && (
        <div className="emp-delete-confirm">
          <div className="emp-delete-backdrop" onClick={() => setDeleteTarget(null)} />
          <div className="emp-delete-dialog">
            <h4>Delete Employee Record</h4>
            <p>
              Are you sure you want to delete <strong>{deleteTarget.name}</strong> (EMP-{deleteTarget.employee_id})?
              This action will remove the record from the employee table.
            </p>
            <div className="emp-delete-dialog-actions">
              <button
                className="emp-dialog-cancel-btn"
                onClick={() => setDeleteTarget(null)}
                disabled={submitting}
              >
                Cancel
              </button>
              <button
                className="emp-dialog-delete-btn"
                onClick={handleDeleteConfirm}
                disabled={submitting}
              >
                {submitting ? 'Deleting...' : 'Delete Employee'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
