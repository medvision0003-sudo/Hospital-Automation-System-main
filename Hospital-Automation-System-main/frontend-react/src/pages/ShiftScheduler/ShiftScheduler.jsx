import { useState, useEffect, useCallback, useMemo } from 'react'
import './ShiftScheduler.css'
import {
  getDepartments,
  getEmployees,
  getShifts,
  getRostersRange,
  bulkSaveRosters,
} from '../../services/rosterService'

// Get Monday to Sunday of the week containing date `d`
function getWeekDays(d) {
  const current = new Date(d)
  const day = current.getDay()
  const diff = current.getDate() - day + (day === 0 ? -6 : 1) // Adjust when day is Sunday
  const monday = new Date(current.setDate(diff))
  
  const days = []
  for (let i = 0; i < 7; i++) {
    const next = new Date(monday)
    next.setDate(monday.getDate() + i)
    days.push(next)
  }
  return days
}

function formatDateString(d) {
  const year = d.getFullYear()
  const month = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function getShiftClass(shiftName) {
  const name = (shiftName || '').toLowerCase()
  if (name.includes('morning')) return 'morning'
  if (name.includes('afternoon')) return 'afternoon'
  if (name.includes('evening')) return 'evening'
  if (name.includes('night')) return 'night'
  return 'off'
}

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

export default function ShiftScheduler({ departmentId, lockDepartment }) {
  const [departments, setDepartments] = useState([])
  const [employees, setEmployees] = useState([])
  const [shifts, setShifts] = useState([])
  const [rosterEntries, setRosterEntries] = useState([])
  
  // Internal department selection (used in standalone/admin mode)
  const [internalDeptId, setInternalDeptId] = useState('')
  const [currentDate, setCurrentDate] = useState(new Date())
  const [selectedBrush, setSelectedBrush] = useState(null)
  const [activeCell, setActiveCell] = useState(null)
  
  // UI status
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [toast, setToast] = useState({ show: false, message: '', type: 'success' })
  
  // Track local edits before saving
  const [localChanges, setLocalChanges] = useState({})
  const [isLocked, setIsLocked] = useState(true)

  // Resolve active department: locked mode uses prop, standalone uses internal state
  const activeDeptId = lockDepartment ? departmentId : internalDeptId

  const showToast = (message, type = 'success') => {
    setToast({ show: true, message, type })
    setTimeout(() => setToast({ show: false, message: '', type: 'success' }), 3000)
  }

  // Calculate current week days
  const weekDays = useMemo(() => getWeekDays(currentDate), [currentDate])
  const weekStart = weekDays[0]
  const weekEnd = weekDays[6]

  // Fetch departments and employees on mount (shifts loaded reactively below)
  useEffect(() => {
    async function loadMetadata() {
      try {
        const [depts, emps] = await Promise.all([
          getDepartments(),
          getEmployees(),
        ])
        setDepartments(depts)
        setEmployees(emps)
        
        // Auto-select first department in standalone mode only
        if (!lockDepartment && depts.length > 0) {
          setInternalDeptId(depts[0].department_id)
        }
      } catch (err) {
        console.error('Metadata fetch failed:', err)
        showToast('Failed to load metadata', 'error')
      }
    }
    loadMetadata()
  }, [lockDepartment])

  // Reactive shift loading when activeDeptId changes
  useEffect(() => {
    if (!activeDeptId) {
      setShifts([])
      return
    }
    getShifts(activeDeptId)
      .then(setShifts)
      .catch((err) => {
        console.error('Failed to load shifts for department:', err)
        showToast('Failed to load shift definitions', 'error')
      })
  }, [activeDeptId])

  // Fetch rosters when week range or department changes
  const fetchRosters = useCallback(async () => {
    if (!activeDeptId) return
    setLoading(true)
    try {
      const rosters = await getRostersRange(
        formatDateString(weekStart),
        formatDateString(weekEnd),
        Number(activeDeptId)
      )
      setRosterEntries(rosters)
      setLocalChanges({})
    } catch (err) {
      console.error('Roster fetch failed:', err)
      showToast('Failed to load shift schedule', 'error')
    } finally {
      setLoading(false)
    }
  }, [activeDeptId, weekStart, weekEnd])

  useEffect(() => {
    fetchRosters()
  }, [fetchRosters])

  // Filter employees belonging to the active department
  const filteredEmployees = useMemo(() => {
    if (!activeDeptId) return []
    return employees.filter(e => e.department_id === Number(activeDeptId))
  }, [activeDeptId, employees])

  // Roster lookup helper
  const getRosterCellInfo = useCallback((employeeId, dateStr) => {
    const changeKey = `${employeeId}_${dateStr}`
    
    if (changeKey in localChanges) {
      const localVal = localChanges[changeKey]
      return {
        shifts: localVal.map(entry => ({
          ...entry,
          shift: shifts.find(s => s.shift_id === entry.shift_id),
        })),
        isModified: true,
      }
    }

    const dbEntries = rosterEntries.filter(
      r => r.employee_id === employeeId && r.work_date === dateStr
    )
    return {
      shifts: dbEntries.map(entry => ({
        ...entry,
        shift: shifts.find(s => s.shift_id === entry.shift_id),
      })),
      isModified: false,
    }
  }, [localChanges, rosterEntries, shifts])

  const applyShiftToCell = (employeeId, dateStr, shiftId, toggleExisting = false) => {
    const changeKey = `${employeeId}_${dateStr}`
    const currentEntries = getRosterCellInfo(employeeId, dateStr).shifts
    setLocalChanges(prev => {
      const copy = { ...prev }
      if (shiftId === 'off') {
        copy[changeKey] = []
      } else {
        const numericShiftId = Number(shiftId)
        const existingEntries = currentEntries.map(({ shift: _shift, ...entry }) => entry)
        const existingIndex = existingEntries.findIndex(entry => entry.shift_id === numericShiftId)
        if (toggleExisting && existingIndex >= 0) {
          existingEntries.splice(existingIndex, 1)
        } else if (existingIndex < 0) {
          existingEntries.push({
            employee_id: employeeId,
            shift_id: numericShiftId,
            work_date: dateStr,
            roster_status: 'SCHEDULED',
          })
        }
        copy[changeKey] = existingEntries
      }
      return copy
    })
    setActiveCell(null)
  }

  const handleCellClick = (employeeId, dateStr) => {
    if (saving || loading) return
    if (selectedBrush !== null) {
      applyShiftToCell(employeeId, dateStr, selectedBrush, true)
      return
    }
    setActiveCell({ employeeId, dateStr })
    setIsLocked(false)
  }

  const handleShiftSelection = (shiftId) => {
    if (activeCell) {
      applyShiftToCell(activeCell.employeeId, activeCell.dateStr, shiftId)
      return
    }
    setSelectedBrush(shiftId)
  }

  // Save changes to backend
  const handleSaveChanges = async () => {
    if (Object.keys(localChanges).length === 0) return true
    setSaving(true)
    const items = Object.entries(localChanges).flatMap(([key, val]) => {
      const [empId, dateStr] = key.split('_')
      if (val.length === 0) {
        return [{
          employee_id: Number(empId),
          shift_id: null,
          work_date: dateStr,
          roster_status: 'SCHEDULED',
        }]
      }
      return val
    })

    try {
      await bulkSaveRosters(items)
      showToast('Shift scheduled successfully')
      await fetchRosters()
      return true
    } catch (err) {
      console.error('Bulk save failed:', err)
      showToast(err.message || 'Failed to save shift schedules', 'error')
      return false
    } finally {
      setSaving(false)
    }
  }

  // Reset local changes
  const handleResetChanges = () => {
    setLocalChanges({})
  }

  // Week navigation helpers
  const handlePrevWeek = () => {
    const next = new Date(currentDate)
    next.setDate(currentDate.getDate() - 7)
    setCurrentDate(next)
  }

  const handleNextWeek = () => {
    const next = new Date(currentDate)
    next.setDate(currentDate.getDate() + 7)
    setCurrentDate(next)
  }

  const handleGoToday = () => {
    setCurrentDate(new Date())
  }

  const changesCount = Object.keys(localChanges).length

  // Empty state when no department is selected in locked mode
  if (lockDepartment && !activeDeptId) {
    return (
      <div className="scheduler-page">
        <div className="empty-state" style={{ minHeight: 300 }}>
          <span className="material-symbols-outlined" style={{ fontSize: 48, color: 'var(--outline)' }}>calendar_month</span>
          <h3>Select a Department</h3>
          <p>Select a department from the filters above to view and manage the shift scheduler.</p>
        </div>
      </div>
    )
  }

  return (
    <div className="scheduler-page">
      {/* Header controls */}
      <header className="scheduler-header">
        <div className="header-left">
          <h2>
            <span className="material-symbols-outlined">event_upcoming</span>
            Shift Scheduling Console
          </h2>
          <p>Schedule rosters and shifts weekly for your department staff.</p>
        </div>
        
        <div className="header-controls">
          {/* Department selector: only visible in standalone/admin mode */}
          {!lockDepartment && (
            <select
              className="control-select"
              value={internalDeptId}
              onChange={(e) => setInternalDeptId(e.target.value)}
            >
              <option value="" disabled>Select Department</option>
              {departments.map(d => (
                <option key={d.department_id} value={d.department_id}>
                  {d.department_name}
                </option>
              ))}
            </select>
          )}

          <div className="week-navigator">
            <button className="nav-btn" onClick={handlePrevWeek} title="Previous Week">
              <span className="material-symbols-outlined">chevron_left</span>
            </button>
            <span className="week-display">
              {weekStart.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} – {weekEnd.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
            </span>
            <button className="nav-btn" onClick={handleNextWeek} title="Next Week">
              <span className="material-symbols-outlined">chevron_right</span>
            </button>
            <button className="nav-btn" onClick={handleGoToday} title="Go to Today" style={{ marginLeft: 4 }}>
              <span className="material-symbols-outlined">today</span>
            </button>
          </div>
        </div>
      </header>

      {/* Roster Brush Toolbar */}
      <section className="painter-toolbar">
        <div className="painter-left">
          <div className="painter-label">
            <span className="material-symbols-outlined" style={{ fontSize: 18 }}>brush</span>
            Shift Brush (click to add/remove):
          </div>
          <div className="brush-palette" style={{ opacity: isLocked ? 0.5 : 1, pointerEvents: isLocked ? 'none' : 'auto' }}>
            <button
              className={`brush-btn${selectedBrush === 'off' ? ' active' : ''}`}
              onClick={() => handleShiftSelection('off')}
              disabled={saving}
            >
              <span className="brush-color off" />
              Off / Clear
            </button>
            {shifts.map(s => (
                <button
                  key={s.shift_id}
                  className={`brush-btn${selectedBrush === s.shift_id ? ' active' : ''}`}
                  onClick={() => handleShiftSelection(s.shift_id)}
                  disabled={saving}
                >
                  <span className={`brush-color ${getShiftClass(s.shift_name)}`} />
                  <span>{s.shift_name}</span>
                  <span style={{ fontSize: '11px', opacity: 0.75, fontWeight: 500 }}>
                    ({formatShiftTime(s.start_time, s.end_time)})
                  </span>
                </button>
              ))}
          </div>
        </div>

        {activeCell && (
          <div className="cell-assignment-picker" role="group" aria-label="Choose a shift for this roster cell">
            <span>
              Assign shift to {employees.find(employee => employee.employee_id === activeCell.employeeId)?.name || `Employee ${activeCell.employeeId}`} on {activeCell.dateStr}
            </span>
            <div className="brush-palette">
              {shifts.map(shift => (
                <button
                  key={shift.shift_id}
                  type="button"
                  className="brush-btn"
                  onClick={() => handleShiftSelection(shift.shift_id)}
                  disabled={saving}
                >
                  <span className={`brush-color ${getShiftClass(shift.shift_name)}`} />
                  <span>{shift.shift_name}</span>
                  <span style={{ fontSize: '11px', opacity: 0.75, fontWeight: 500 }}>
                    ({formatShiftTime(shift.start_time, shift.end_time)})
                  </span>
                </button>
              ))}
              <button
                type="button"
                className="brush-btn"
                onClick={() => handleShiftSelection('off')}
                disabled={saving}
              >
                <span className="brush-color off" />
                Off / Clear
              </button>
              <button
                type="button"
                className="brush-btn"
                onClick={() => setActiveCell(null)}
                disabled={saving}
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        <div className="painter-right">
          {isLocked ? (
            <button className="btn-edit-lock btn-primary" onClick={() => setIsLocked(false)}>
              <span className="material-symbols-outlined">edit</span>
              Edit Schedule
            </button>
          ) : (
            <div className="painter-actions" style={{ display: 'flex', gap: 10 }}>
              <button className="btn-secondary" onClick={() => { handleResetChanges(); setActiveCell(null); setIsLocked(true); }}>
                Cancel
              </button>
              <button className="btn-primary" onClick={async () => {
                const saved = await handleSaveChanges();
                if (saved) {
                  setActiveCell(null);
                  setIsLocked(true);
                }
              }} disabled={saving || Object.keys(localChanges).length === 0}>
                <span className="material-symbols-outlined">save</span>
                {saving ? 'Saving...' : 'Save & Lock'}
              </button>
            </div>
          )}
        </div>
      </section>

      {/* Schedule Weekly Grid */}
      <div className="grid-card">
        {loading ? (
          <div className="loading-center">
            <span className="material-symbols-outlined">progress_activity</span>
            Loading roster schedule...
          </div>
        ) : filteredEmployees.length === 0 ? (
          <div className="empty-state">
            <span className="material-symbols-outlined">groups</span>
            <h3>No Employees Found</h3>
            <p>There are no employees registered in this department to schedule.</p>
          </div>
        ) : (
          <div className="grid-table-container custom-scrollbar">
            <table className="grid-table">
              <thead>
                <tr>
                  <th>Employee</th>
                  {weekDays.map((day, idx) => (
                    <th key={idx}>
                      {day.toLocaleDateString('en-US', { weekday: 'short' })}
                      <div style={{ fontSize: 12, marginTop: 2, fontWeight: 500 }}>
                        {day.getDate()}
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filteredEmployees.map(employee => (
                  <tr key={employee.employee_id}>
                    <td>
                      <div className="employee-meta">
                        <span>{employee.name}</span>
                        <span className="employee-role">{employee.role}</span>
                      </div>
                    </td>
                    {weekDays.map((day, dIdx) => {
                      const dateStr = formatDateString(day)
                      const cellInfo = getRosterCellInfo(employee.employee_id, dateStr)
                      return (
                        <td key={dIdx} style={{ padding: 4 }}>
                          <div
                            role="button"
                            tabIndex={0}
                            aria-label={`${employee.name}, ${dateStr}, ${cellInfo.shifts.map(entry => entry.shift?.shift_name).filter(Boolean).join(', ') || 'no shift assigned'}. Select to assign or change shift`}
                            className={`roster-cell${cellInfo?.isModified ? ' modified' : ''}${isLocked ? ' locked' : ''}`}
                            onClick={() => handleCellClick(employee.employee_id, dateStr)}
                            onKeyDown={(event) => {
                              if (event.key === 'Enter' || event.key === ' ') {
                                event.preventDefault()
                                handleCellClick(employee.employee_id, dateStr)
                              }
                            }}
                          >
                            {cellInfo.isModified && <span className="mod-dot" />}
                            {cellInfo.shifts.length > 0 ? (
                              <div className="roster-cell-shifts">
                                {cellInfo.shifts.map(entry => (
                                  <span
                                    key={entry.shift_id}
                                    className={`shift-badge ${getShiftClass(entry.shift?.shift_name)}`}
                                    title={`${entry.shift?.shift_name || 'Shift'} — ${entry.roster_status}`}
                                  >
                                    <span>{entry.shift?.shift_name}</span>
                                    <span className="shift-badge-time">
                                      {formatShiftTime(entry.shift?.start_time, entry.shift?.end_time)}
                                    </span>
                                  </span>
                                ))}
                              </div>
                            ) : (
                              <span className="cell-empty">+</span>
                            )}
                          </div>
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>


      {/* Toast Alert */}
      {toast.show && (
        <div className="toast-bar">
          <span className="material-symbols-outlined">
            {toast.type === 'error' ? 'error' : 'check_circle'}
          </span>
          <span>{toast.message}</span>
        </div>
      )}
    </div>
  )
}
