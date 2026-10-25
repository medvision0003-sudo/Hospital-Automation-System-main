import { useState, useEffect, useMemo, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  getDepartments,
  getTasks,
  getEmployees,
  getCurrentUser,
  getSupervisorRequests,
  getAssignments,
  getEmployeeAssignments,
  getWorkQueue,
  getEmployeeRosters,
  getEmployeeCheckins,
  preemptAssignment,
} from '../services/supervisorService'
import ShiftScheduler from './ShiftScheduler/ShiftScheduler'
import EscalationReview from './EscalationReview'
import './Supervisor.css'

const VALID_TABS = ['tasks', 'shifts', 'status', 'escalations']

function localDateString(date = new Date()) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

export default function Supervisor() {
  const [searchParams, setSearchParams] = useSearchParams()
  const tabFromUrl = searchParams.get('tab')
  const [activeConsoleTab, setActiveConsoleTab] = useState(
    VALID_TABS.includes(tabFromUrl) ? tabFromUrl : 'tasks'
  )

  // Sync tab state when URL query param changes
  useEffect(() => {
    const urlTab = searchParams.get('tab')
    if (urlTab && VALID_TABS.includes(urlTab) && urlTab !== activeConsoleTab) {
      setActiveConsoleTab(urlTab)
    }
  }, [searchParams, activeConsoleTab])

  // Update URL when tab is changed via button click
  const handleTabChange = (tab) => {
    setActiveConsoleTab(tab)
    setSearchParams(tab === 'tasks' ? {} : { tab })
  }
  
  // Data from backend
  const [departments, setDepartments] = useState([])
  const [allTasks, setAllTasks] = useState([])
  const [supervisorRequests, setSupervisorRequests] = useState([])
  const [currentUser, setCurrentUser] = useState(null)
  const [loadError, setLoadError] = useState('')
  const [isInitialLoading, setIsInitialLoading] = useState(true)

  // Employee Work Status state
  const [employees, setEmployees] = useState([])
  const [workQueue, setWorkQueue] = useState([])
  const [allAssignments, setAllAssignments] = useState([])
  const [selectedDeptId, setSelectedDeptId] = useState('')
  const [selectedEmployeeId, setSelectedEmployeeId] = useState('')
  const [assignments, setAssignments] = useState([])
  const [loadingAssignments, setLoadingAssignments] = useState(false)
  const [statusError, setStatusError] = useState('')

  const [removeConfirm, setRemoveConfirm] = useState(null)

  const [toastMessage, setToastMessage] = useState('')

  const loadConsoleData = useCallback(async () => {
    setLoadError('')
    try {
      const [user, depts, tasks, emps, queue, requests, assignmentRecords] = await Promise.all([
        getCurrentUser(),
        getDepartments(),
        getTasks(),
        getEmployees(),
        getWorkQueue(),
        getSupervisorRequests(),
        getAssignments(),
      ])
      const scopedDepartmentId = user.role === 'SUPERVISOR' ? user.department_id : null
      setCurrentUser(user)
      setDepartments(scopedDepartmentId
        ? depts.filter((department) => department.department_id === scopedDepartmentId)
        : depts)
      setAllTasks(scopedDepartmentId
        ? tasks.filter((task) => task.department_id === scopedDepartmentId)
        : tasks)
      setEmployees(scopedDepartmentId
        ? emps.filter((employee) => employee.department_id === scopedDepartmentId)
        : emps)
      setWorkQueue(scopedDepartmentId
        ? queue.filter((work) => work.department_id === scopedDepartmentId)
        : queue)
      setAllAssignments(assignmentRecords)
      setSupervisorRequests(requests)
      if (scopedDepartmentId) {
        setSelectedDeptId(String(scopedDepartmentId))
      }
    } catch (error) {
      setLoadError(error.message || 'Unable to load Supervisor Console data.')
    } finally {
      setIsInitialLoading(false)
    }
  }, [])

  useEffect(() => {
    loadConsoleData()
  }, [loadConsoleData])

  useEffect(() => {
    if (activeConsoleTab !== 'tasks') return undefined
    const interval = window.setInterval(() => {
      if (document.hidden) return
      Promise.all([getSupervisorRequests(), getWorkQueue(), getAssignments()])
        .then(([requests, queue, assignmentRecords]) => {
          setSupervisorRequests(requests)
          setWorkQueue(currentUser?.role === 'SUPERVISOR' && currentUser.department_id
            ? queue.filter((work) => work.department_id === currentUser.department_id)
            : queue)
          setAllAssignments(assignmentRecords)
        })
        .catch((error) => setLoadError(error.message || 'Unable to refresh automation status.'))
    }, 10000)
    return () => window.clearInterval(interval)
  }, [activeConsoleTab, currentUser])

  const [employeeRosters, setEmployeeRosters] = useState([])
  const [employeeCheckins, setEmployeeCheckins] = useState([])

  const fetchEmployeeData = useCallback(async (employeeId, silent = false) => {
    if (!silent) setLoadingAssignments(true)
    setStatusError('')
    try {
      const [employeeAssignments, rosters, checkins] = await Promise.all([
        getEmployeeAssignments(employeeId),
        getEmployeeRosters(employeeId),
        getEmployeeCheckins(employeeId),
      ])
      setAssignments(employeeAssignments)
      setEmployeeRosters(rosters)
      setEmployeeCheckins(checkins)
    } catch (error) {
      setStatusError(error.message || 'Unable to load employee work status.')
    } finally {
      if (!silent) setLoadingAssignments(false)
    }
  }, [])

  // Fetch assignments, rosters, and checkins for selected employee with auto-polling
  useEffect(() => {
    if (!selectedEmployeeId) {
      setAssignments([])
      setEmployeeRosters([])
      setEmployeeCheckins([])
      setStatusError('')
      return
    }

    const employeeId = Number(selectedEmployeeId)
    fetchEmployeeData(employeeId, false)

    const interval = setInterval(() => {
      if (!document.hidden) {
        fetchEmployeeData(employeeId, true)
      }
    }, 5000)

    return () => clearInterval(interval)
  }, [selectedEmployeeId, fetchEmployeeData])

  const statusEmployees = useMemo(() => {
    if (!selectedDeptId) return []
    return employees.filter((emp) => emp.department_id === Number(selectedDeptId))
  }, [selectedDeptId, employees])

  const selectedEmployee = useMemo(() => {
    if (!selectedEmployeeId) return null
    return employees.find((emp) => emp.employee_id === Number(selectedEmployeeId))
  }, [selectedEmployeeId, employees])

  const latestCheckin = useMemo(() => {
    if (!employeeCheckins || employeeCheckins.length === 0) return null
    const todayCheckins = employeeCheckins.filter((checkin) =>
      checkin.checkin_time && localDateString(new Date(checkin.checkin_time)) === localDateString(),
    )
    return [...todayCheckins].sort((a, b) => new Date(b.checkin_time) - new Date(a.checkin_time))[0] || null
  }, [employeeCheckins])

  const todayRoster = useMemo(() => {
    if (!employeeRosters || employeeRosters.length === 0) return null
    const todayStr = localDateString()
    return employeeRosters.find((r) => r.work_date === todayStr) || null
  }, [employeeRosters])

  const calculatedAvailability = useMemo(() => {
    if (selectedEmployee?.availability !== 'ACTIVE') {
      return {
        label: selectedEmployee?.availability === 'ON_LEAVE' ? 'ON LEAVE' : 'UNAVAILABLE',
        color: '#b91c1c',
        icon: 'person_off',
      }
    }
    if (latestCheckin?.status === 'CHECKED_IN' && !latestCheckin.checkout_time) {
      return { label: 'AVAILABLE', color: '#047857', icon: 'person_check' }
    }
    return { label: 'UNAVAILABLE', color: '#b91c1c', icon: 'person_off' }
  }, [latestCheckin, selectedEmployee])

  const calculatedShiftStatus = useMemo(() => {
    if (latestCheckin) {
      if (latestCheckin.status === 'CHECKED_IN' && !latestCheckin.checkout_time) return { label: 'ACTIVE', color: '#047857', icon: 'badge' }
      if (latestCheckin.status === 'CHECKED_OUT' || latestCheckin.checkout_time) return { label: 'CHECKED OUT', color: '#4b5563', icon: 'logout' }
      if (latestCheckin.status === 'ABSENT') return { label: 'ABSENT', color: '#b91c1c', icon: 'event_busy' }
    }
    if (todayRoster) {
      const st = todayRoster.roster_status || 'NOT CHECKED IN'
      if (st === 'CHECKED_IN') return { label: 'ACTIVE', color: '#047857', icon: 'badge' }
      if (st === 'HALF_DAY') return { label: 'HALF DAY', color: '#b45309', icon: 'schedule' }
      if (st === 'ABSENT') return { label: 'ABSENT', color: '#b91c1c', icon: 'event_busy' }
      if (st === 'SCHEDULED') return { label: 'SCHEDULED', color: '#0369a1', icon: 'calendar_today' }
      if (st === 'COMPLETED') return { label: 'COMPLETED', color: '#047857', icon: 'task_alt' }
      return { label: st.replace('_', ' '), color: '#4b5563', icon: 'badge' }
    }
    return { label: 'NOT CHECKED IN', color: '#4b5563', icon: 'badge' }
  }, [latestCheckin, todayRoster])

  const statusSummary = useMemo(() => {
    const summary = { completed: 0, pending: 0, assigned: 0, inProgress: 0, cancelled: 0, total: assignments.length }
    assignments.forEach((assign) => {
      const status = (assign.assignment_status || '').toUpperCase()
      if (status === 'COMPLETED') summary.completed++
      else if (status === 'PENDING') summary.pending++
      else if (status === 'ASSIGNED') summary.assigned++
      else if (status === 'IN_PROGRESS') summary.inProgress++
      else if (status === 'CANCELLED') summary.cancelled++
    })
    return summary
  }, [assignments])

  const getAssignmentTaskInfo = (assignment) => {
    const workItem = workQueue.find((w) => w.work_id === assignment.work_id)
    const task = workItem ? allTasks.find((t) => t.task_id === workItem.task_id) : null
    return {
      taskName: task ? task.task_name : `Work Item #${assignment.work_id}`,
      priority: workItem ? workItem.priority : 'MEDIUM',
    }
  }

  const generatedWorkItems = useMemo(() => workQueue
    .map((work) => {
      const task = allTasks.find((item) => item.task_id === work.task_id)
      const assignmentsForWork = allAssignments
        .filter((item) => item.work_id === work.work_id)
        .sort((left, right) => right.assignment_id - left.assignment_id)
      const currentAssignment = assignmentsForWork.find((item) =>
        ['PENDING', 'ASSIGNED', 'IN_PROGRESS'].includes(
          String(item.assignment_status || '').toUpperCase()
        )
      ) || assignmentsForWork.find(
        (item) => String(item.assignment_status || '').toUpperCase() === 'COMPLETED'
      )
      const employee = employees.find(
        (item) => item.employee_id === currentAssignment?.employee_id
      )
      return {
        ...work,
        taskName: task?.task_name || `Task #${work.task_id}`,
        employeeName: employee?.name || 'Unassigned',
        assignmentStatus: currentAssignment?.assignment_status || work.queue_status,
      }
    })
    .sort((left, right) => {
      const leftDue = left.due_date ? new Date(left.due_date).getTime() : Infinity
      const rightDue = right.due_date ? new Date(right.due_date).getTime() : Infinity
      return leftDue - rightDue || right.work_id - left.work_id
    }), [workQueue, allAssignments, allTasks, employees])

  return (
    <div className="supervisor-page">
      <div className="supervisor-header">
        <h2>Supervisor Console</h2>
        <p>Manage task publishing and shift rosters across hospital departments.</p>
        <button className="sup-tab-btn" onClick={loadConsoleData} disabled={isInitialLoading}>
          <span className="material-symbols-outlined">refresh</span>
          Refresh
        </button>
      </div>

      {loadError && (
        <div className="supervisor-load-error" role="alert">
          <span>{loadError}</span>
          <button type="button" onClick={loadConsoleData}>Retry</button>
        </div>
      )}
      {isInitialLoading && <div className="supervisor-load-error" role="status">Loading Supervisor Console data…</div>}

      <div className="supervisor-tabs">
        <button
          className={`sup-tab-btn${activeConsoleTab === 'tasks' ? ' active' : ''}`}
          onClick={() => handleTabChange('tasks')}
        >
          <span className="material-symbols-outlined">publish</span>
          Task Publisher
        </button>
        <button
          className={`sup-tab-btn${activeConsoleTab === 'shifts' ? ' active' : ''}`}
          onClick={() => handleTabChange('shifts')}
        >
          <span className="material-symbols-outlined">calendar_month</span>
          Shift Scheduler
        </button>
        <button
          className={`sup-tab-btn${activeConsoleTab === 'status' ? ' active' : ''}`}
          onClick={() => handleTabChange('status')}
        >
          <span className="material-symbols-outlined">badge</span>
          Employee Work Status
        </button>
        <button
          className={`sup-tab-btn${activeConsoleTab === 'escalations' ? ' active' : ''}`}
          onClick={() => handleTabChange('escalations')}
        >
          <span className="material-symbols-outlined">gavel</span>
          Escalation Review
        </button>
      </div>

      {activeConsoleTab === 'escalations' && (
        <div style={{ padding: 0 }}>
          <EscalationReview />
        </div>
      )}

      {activeConsoleTab === 'shifts' && (
        <>
          <div className="supervisor-filters">
            <div className="filter-group">
              <span className="filter-label">Select Department</span>
              <select
                className="filter-select"
                value={selectedDeptId}
                onChange={(e) => setSelectedDeptId(e.target.value)}
              >
                <option value="">Select Department</option>
                {departments.map((department) => (
                  <option key={department.department_id} value={department.department_id}>
                    {department.department_name}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="glass-card" style={{ padding: 0, background: 'transparent', border: 'none', boxShadow: 'none' }}>
            <ShiftScheduler departmentId={selectedDeptId} lockDepartment />
          </div>
        </>
      )}

      {activeConsoleTab === 'status' && (
        <div className="status-console" style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          {statusError && <div className="supervisor-load-error" role="alert">{statusError}</div>}
          <div className="supervisor-filters">
            <div className="filter-group">
              <span className="filter-label">Select Department</span>
              <select
                className="filter-select"
                value={selectedDeptId}
                onChange={(e) => {
                  setSelectedDeptId(e.target.value)
                  setSelectedEmployeeId('')
                }}
              >
                <option value="">Select Department</option>
                {departments.map((d) => (
                  <option key={d.department_id} value={d.department_id}>
                    {d.department_name}
                  </option>
                ))}
              </select>
            </div>

            <div className="filter-group">
              <span className="filter-label">Select Employee</span>
              <select
                className="filter-select"
                value={selectedEmployeeId}
                onChange={(e) => setSelectedEmployeeId(e.target.value)}
                disabled={!selectedDeptId}
              >
                <option value="">Select Employee</option>
                {statusEmployees.map((emp) => (
                  <option key={emp.employee_id} value={emp.employee_id}>
                    {emp.name} ({emp.role})
                  </option>
                ))}
              </select>
            </div>
          </div>

          {selectedEmployeeId ? (
            <div className="status-details" style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
              {/* KPI metrics */}
              <div className="sch-kpi-strip" style={{ margin: '0', background: 'rgba(255, 255, 255, 0.4)', borderRadius: 16, padding: '16px 24px', border: '1px solid var(--outline-variant)' }}>
                <div className="sch-kpi">
                  <span className="sch-kpi-label">TOTAL ASSIGNMENTS</span>
                  <div className="sch-kpi-value-row">
                    <span className="sch-kpi-num">{statusSummary.total}</span>
                  </div>
                </div>
                <div className="sch-kpi-divider" />
                <div className="sch-kpi">
                  <span className="sch-kpi-label">COMPLETED</span>
                  <div className="sch-kpi-value-row">
                    <span className="sch-kpi-num sch-num-green">{statusSummary.completed}</span>
                    <span className="material-symbols-outlined sch-kpi-icon sch-icon-green">check_circle</span>
                  </div>
                </div>
                <div className="sch-kpi-divider" />
                <div className="sch-kpi">
                  <span className="sch-kpi-label">PENDING</span>
                  <div className="sch-kpi-value-row">
                    <span className="sch-kpi-num sch-num-amber">{statusSummary.pending}</span>
                    <span className="material-symbols-outlined sch-kpi-icon sch-icon-amber">schedule</span>
                  </div>
                </div>
                <div className="sch-kpi-divider" />
                <div className="sch-kpi">
                  <span className="sch-kpi-label">ASSIGNED</span>
                  <div className="sch-kpi-value-row">
                    <span className="sch-kpi-num" style={{ color: '#7c3aed' }}>{statusSummary.assigned}</span>
                    <span className="material-symbols-outlined sch-kpi-icon" style={{ color: '#7c3aed' }}>assignment_ind</span>
                  </div>
                </div>
                <div className="sch-kpi-divider" />
                <div className="sch-kpi">
                  <span className="sch-kpi-label">IN PROGRESS</span>
                  <div className="sch-kpi-value-row">
                    <span className="sch-kpi-num" style={{ color: '#1976d2' }}>{statusSummary.inProgress}</span>
                    <span className="material-symbols-outlined sch-kpi-icon" style={{ color: '#1976d2' }}>pending_actions</span>
                  </div>
                </div>
                <div className="sch-kpi-divider" />
                <div className="sch-kpi">
                  <span className="sch-kpi-label">CANCELLED</span>
                  <div className="sch-kpi-value-row">
                    <span className="sch-kpi-num sch-num-red">{statusSummary.cancelled}</span>
                    <span className="material-symbols-outlined sch-kpi-icon sch-icon-red">cancel</span>
                  </div>
                </div>
                <div className="sch-kpi-divider" />
                <div className="sch-kpi">
                  <span className="sch-kpi-label">AVAILABILITY</span>
                  <div className="sch-kpi-value-row">
                    <span className="sch-kpi-num" style={{
                      fontSize: 15,
                      fontWeight: 700,
                      color: calculatedAvailability.color
                    }}>
                      {calculatedAvailability.label}
                    </span>
                    <span className="material-symbols-outlined sch-kpi-icon" style={{ color: calculatedAvailability.color }}>
                      {calculatedAvailability.icon}
                    </span>
                  </div>
                </div>
                <div className="sch-kpi-divider" />
                <div className="sch-kpi">
                  <span className="sch-kpi-label">SHIFT STATUS</span>
                  <div className="sch-kpi-value-row">
                    <span className="sch-kpi-num" style={{
                      fontSize: 15,
                      fontWeight: 700,
                      color: calculatedShiftStatus.color
                    }}>
                      {calculatedShiftStatus.label}
                    </span>
                    <span className="material-symbols-outlined sch-kpi-icon" style={{ color: calculatedShiftStatus.color }}>
                      {calculatedShiftStatus.icon}
                    </span>
                  </div>
                </div>

              </div>

              {/* Tasks List */}
              <div className="glass-card supervisor-table-card">
                {loadingAssignments ? (
                  <div className="loading-center" style={{ padding: 40, textAlign: 'center', display: 'flex', gap: 10, alignItems: 'center', justifyContent: 'center' }}>
                    <span className="material-symbols-outlined" style={{ animation: 'spin 1.5s linear infinite' }}>progress_activity</span>
                    Loading employee tasks...
                  </div>
                ) : assignments.length === 0 ? (
                  <div className="empty-state" style={{ padding: 40, textAlign: 'center' }}>
                    <span className="material-symbols-outlined" style={{ fontSize: 48, opacity: 0.4 }}>task</span>
                    <p style={{ marginTop: 10, color: 'var(--outline)' }}>No tasks assigned to this employee yet.</p>
                  </div>
                ) : (
                  <table className="supervisor-table">
                    <thead>
                      <tr>
                        <th>Task Name</th>
                        <th>Priority</th>
                        <th>Status</th>
                        <th>Assigned At</th>
                        <th>Completed At</th>
                        <th style={{ textAlign: 'right' }}>Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {assignments.map((assign) => {
                        const { taskName, priority } = getAssignmentTaskInfo(assign)
                        const status = assign.assignment_status || 'ASSIGNED'
                        return (
                          <tr key={assign.assignment_id}>
                            <td><strong>{taskName}</strong></td>
                            <td>
                              <span className={`priority-badge ${priority.toLowerCase()}`}>
                                {priority}
                              </span>
                            </td>
                            <td>
                              <span className={`status-chip ${status.toLowerCase()}`} style={{
                                display: 'inline-flex',
                                padding: '4px 10px',
                                borderRadius: 12,
                                fontSize: 11,
                                fontWeight: 700,
                                textTransform: 'uppercase',
                                background: status === 'COMPLETED' ? '#d1fae5' : status === 'CANCELLED' ? '#fee2e2' : status === 'IN_PROGRESS' ? '#e0f2fe' : status === 'ASSIGNED' ? '#ede9fe' : status === 'PENDING' ? '#fef3c7' : '#f3f4f6',
                                color: status === 'COMPLETED' ? '#047857' : status === 'CANCELLED' ? '#b91c1c' : status === 'IN_PROGRESS' ? '#0369a1' : status === 'ASSIGNED' ? '#6d28d9' : status === 'PENDING' ? '#b45309' : '#4b5563',
                              }}>
                                {status}
                              </span>
                            </td>
                            <td>{assign.assigned_at ? new Date(assign.assigned_at).toLocaleString() : '—'}</td>
                            <td>{assign.completed_at ? new Date(assign.completed_at).toLocaleString() : '—'}</td>
                            <td style={{ textAlign: 'right' }}>
                              {status === 'ASSIGNED' ? (
                                <button
                                  className="remove-assignment-btn"
                                  onClick={() => setRemoveConfirm(assign.assignment_id)}
                                >
                                  <span className="material-symbols-outlined">person_remove</span>
                                  Remove Assignment
                                </button>
                              ) : (
                                <button
                                  className="remove-assignment-btn"
                                  disabled
                                  title={
                                    status === 'IN_PROGRESS'
                                      ? 'Tasks in progress cannot be removed'
                                      : `Cannot remove (status: ${status})`
                                  }
                                  style={{ opacity: 0.4, cursor: 'not-allowed' }}
                                >
                                  <span className="material-symbols-outlined">person_remove</span>
                                  Remove Assignment
                                </button>
                              )}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                )}
              </div>

              {removeConfirm !== null && (
                <div className="remove-confirm-overlay">
                  <div className="remove-confirm-dialog">
                    <span className="material-symbols-outlined remove-confirm-icon">help</span>
                    <p className="remove-confirm-msg">Do you really want to remove the work item assigned?</p>
                    <div className="remove-confirm-actions">
                      <button
                        className="remove-confirm-btn confirm"
                        onClick={async () => {
                          const assignmentId = removeConfirm
                          setRemoveConfirm(null)
                          try {
                            const result = await preemptAssignment(assignmentId)
                            const reassigned = result.reassignment_result?.total_assigned || 0
                            const reassignmentFailed = result.reassignment_result?.status === 'FAILED'
                            setToastMessage(reassignmentFailed
                              ? `Error: Assignment removed, but automatic reassignment failed: ${result.reassignment_result.error || 'Please retry or escalate.'}`
                              : `Assignment removed successfully.` +
                                (reassigned > 0 ? ` Task reassigned to another worker.` : ` Task returned to queue.`))
                            await Promise.all([
                              selectedEmployeeId
                                ? getEmployeeAssignments(Number(selectedEmployeeId)).then(setAssignments)
                                : Promise.resolve(),
                              getAssignments().then(setAllAssignments),
                              getWorkQueue().then((queue) => {
                                const scopedQueue = currentUser?.role === 'SUPERVISOR' && currentUser.department_id
                                  ? queue.filter((work) => work.department_id === currentUser.department_id)
                                  : queue
                                setWorkQueue(scopedQueue)
                              }),
                            ])
                          } catch (err) {
                            setToastMessage(`Error: ${err.message}`)
                          }
                          setTimeout(() => setToastMessage(''), 5000)
                        }}
                      >
                        Confirm
                      </button>
                      <button
                        className="remove-confirm-btn cancel"
                        onClick={() => setRemoveConfirm(null)}
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="glass-card empty-state" style={{ padding: 60, textAlign: 'center', background: '#fff', borderRadius: 16, border: '1px solid var(--outline-variant)' }}>
              <span className="material-symbols-outlined" style={{ fontSize: 48, opacity: 0.4 }}>contact_emergency</span>
              <h3 style={{ marginTop: 12, fontSize: 16, fontWeight: 600 }}>No Employee Selected</h3>
              <p style={{ color: 'var(--outline)', marginTop: 8 }}>Please select a department and an employee to view their work status summary.</p>
            </div>
          )}
        </div>
      )}

      {activeConsoleTab === 'tasks' && (
        <>
          <section className="glass-card supervisor-table-card supervisor-request-history">
            <div className="supervisor-request-heading">
              <div>
                <h3>Automated shift tasks</h3>
                <p>Tasks are generated from active shift rules and assigned by Staff Automation.</p>
              </div>
              <button className="sup-tab-btn" onClick={loadConsoleData} disabled={isInitialLoading}>
                <span className="material-symbols-outlined">refresh</span>
                Refresh tasks
              </button>
            </div>
            {generatedWorkItems.length === 0 ? (
              <div className="empty-state">
                <p>No automated tasks are currently in the work queue.</p>
              </div>
            ) : (
              <div className="supervisor-table-scroll">
                <table className="supervisor-table">
                  <thead>
                    <tr>
                      <th>Task</th>
                      <th>Employee</th>
                      <th>Priority</th>
                      <th>Due time</th>
                      <th>Status</th>
                      <th>Proof</th>
                      <th>Verification</th>
                    </tr>
                  </thead>
                  <tbody>
                    {generatedWorkItems.map((work) => (
                      <tr key={work.work_id}>
                        <td>{work.taskName}</td>
                        <td>{work.employeeName}</td>
                        <td>{work.priority || '—'}</td>
                        <td>{work.due_date ? new Date(work.due_date).toLocaleString() : '—'}</td>
                        <td>{work.assignmentStatus || work.queue_status || 'PENDING'}</td>
                        <td>{work.proof_image_path ? 'Submitted' : 'Not submitted'}</td>
                        <td>{work.verification_status || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
          <section className="glass-card supervisor-table-card supervisor-request-history">
            <div className="supervisor-request-heading">
              <div>
                <h3>Submitted task requests</h3>
                <p>Requests are stored and processed asynchronously by the hospital workflow.</p>
              </div>
              <button className="sup-tab-btn" onClick={loadConsoleData} disabled={isInitialLoading}>
                <span className="material-symbols-outlined">refresh</span>
                Refresh status
              </button>
            </div>
            {supervisorRequests.length === 0 ? (
              <div className="empty-state"><p>No task requests have been submitted.</p></div>
            ) : (
              <div className="supervisor-table-scroll">
                <table className="supervisor-table">
                  <thead>
                    <tr>
                      <th>Task</th>
                      <th>Priority</th>
                      <th>Due</th>
                      <th>Submitted</th>
                      <th>Workflow status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {supervisorRequests.map((request) => {
                      const task = allTasks.find((item) => item.task_id === request.task_id)
                      return (
                        <tr key={request.request_id}>
                          <td>{task?.task_name || `Task #${request.task_id}`}</td>
                          <td>{request.priority || task?.priority_category || '—'}</td>
                          <td>{request.due_time ? new Date(request.due_time).toLocaleString() : '—'}</td>
                          <td>{request.created_at ? new Date(request.created_at).toLocaleString() : '—'}</td>
                          <td>
                            <span className={`status-chip ${request.processed_at ? 'completed' : 'pending'}`}>
                              {request.processed_at ? 'PROCESSED' : 'QUEUED'}
                            </span>
                            {request.processed_at && <small>{new Date(request.processed_at).toLocaleString()}</small>}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}

      {toastMessage && (
        <div className={`supervisor-toast ${toastMessage.startsWith('Error') ? 'error' : ''}`}>
          <span className="material-symbols-outlined">
            {toastMessage.startsWith('Error') ? 'error' : 'check_circle'}
          </span>
          <span>{toastMessage}</span>
        </div>
      )}

      <div className="atmospheric-blur"><div className="atmospheric-blur-circle" /></div>
    </div>
  )
}
