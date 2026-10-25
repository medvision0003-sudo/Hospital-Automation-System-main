import { useState, useEffect, useCallback, useMemo } from 'react'
import './Scheduler.css'
import {
  getDepartments,
  getAllTasks,
  getAllSchedules,
  getUpcomingSchedules,
  createTask,
  createSchedule,
  updateSchedule,
  deleteSchedule as deleteScheduleApi,
  runScheduler,
  getShifts,
} from '../services/schedulerService'

function humanFrequency(type, value) {
  if (type === 'MINUTES') return value === 1 ? 'Every Minute' : `Every ${value} Mins`
  if (type === 'HOURS') return value === 1 ? 'Hourly' : `Every ${value} Hours`
  if (type === 'DAYS') return value === 1 ? 'Daily' : `Every ${value} Days`
  if (type === 'WEEKS') return value === 1 ? 'Weekly' : `Every ${value} Weeks`
  if (type === 'MONTHS') return value === 1 ? 'Monthly' : `Every ${value} Months`
  return `Every ${value} ${type}`
}

function formatTime(dtStr) {
  if (!dtStr) return '—'
  const d = new Date(dtStr)
  const now = new Date()
  const time = d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true })
  if (d.toDateString() === now.toDateString()) return time
  const tomorrow = new Date(now)
  tomorrow.setDate(tomorrow.getDate() + 1)
  if (d.toDateString() === tomorrow.toDateString()) return `Tomorrow ${time}`
  return `${d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} ${time}`
}

function getStatusInfo(nextRun, lastRun) {
  if (!nextRun) return { main: '—', sub: '', urgency: 'ok' }
  const diff = new Date(nextRun) - new Date()
  if (diff < 0) {
    const mins = Math.abs(Math.floor(diff / 60000))
    return {
      main: `Overdue ${mins}m`,
      sub: lastRun ? `Last: ${new Date(lastRun).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true })}` : '',
      urgency: 'overdue',
    }
  }
  const totalMins = Math.floor(diff / 60000)
  if (totalMins < 60) {
    return {
      main: `Due in ${totalMins}m`,
      sub: `Next: ${new Date(nextRun).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true })}`,
      urgency: 'warning',
    }
  }
  const hrs = Math.floor(totalMins / 60)
  const mins = totalMins % 60
  return { main: 'OK Status', sub: `Due in ${hrs}h ${mins}m`, urgency: 'ok' }
}

const PRIORITY_META = {
  CRITICAL: { accent: '#c62828', iconBg: '#fce4ec', iconColor: '#b71c1c', icon: 'monitor_heart', badgeBg: '#c62828', badgeColor: '#fff' },
  HIGH: { accent: '#e67e22', iconBg: '#fff3e0', iconColor: '#e65100', icon: 'medication', badgeBg: '#e67e22', badgeColor: '#fff' },
  MEDIUM: { accent: '#1976d2', iconBg: '#e3f2fd', iconColor: '#1565c0', icon: 'sanitizer', badgeBg: '#1976d2', badgeColor: '#fff' },
  LOW: { accent: '#9e9e9e', iconBg: '#f5f5f5', iconColor: '#757575', icon: 'task', badgeBg: '#9e9e9e', badgeColor: '#fff' },
}

function priorityRank(p) {
  return { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3 }[p] ?? 4
}

function parseFrequency(freqKey) {
  const map = {
    MINUTES: { type: 'MINUTES', value: 1 },
    HOURS: { type: 'HOURS', value: 1 },
    HOURS_2: { type: 'HOURS', value: 2 },
    HOURS_4: { type: 'HOURS', value: 4 },
    DAYS: { type: 'DAYS', value: 1 },
    WEEKS: { type: 'WEEKS', value: 1 },
    MONTHS: { type: 'MONTHS', value: 1 },
  }
  return map[freqKey] || { type: 'HOURS', value: 1 }
}



export default function Scheduler() {
  const [upcomingData, setUpcomingData] = useState([])
  const [allSchedules, setAllSchedules] = useState([])
  const [allTasks, setAllTasks] = useState([])
  const [tasksMap, setTasksMap] = useState({})
  const [departments, setDepartments] = useState([])
  const [isRunning, setIsRunning] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [toast, setToast] = useState({ show: false, message: '', type: 'success' })
  const userRole = localStorage.getItem('user_role') || 'ADMIN'

  const showToast = (message, type = 'success') => {
    setToast({ show: true, message, type })
    setTimeout(() => setToast({ show: false, message: '', type: 'success' }), 3000)
  }

  const [formDeptId, setFormDeptId] = useState('')
  const [formTaskId, setFormTaskId] = useState('')
  const [formNewTaskName, setFormNewTaskName] = useState('')
  const [formFrequency, setFormFrequency] = useState('HOURS')
  const [formShiftId, setFormShiftId] = useState('')
  const [deptShifts, setDeptShifts] = useState([])

  const [formPriority, setFormPriority] = useState('Default')

  const loadData = useCallback(async () => {
    try {
      const [upcoming, schedules, tasks, depts] = await Promise.all([
        getUpcomingSchedules(),
        getAllSchedules(),
        getAllTasks(),
        getDepartments(),
      ])
      setUpcomingData(upcoming)
      setAllSchedules(schedules)
      setAllTasks(tasks)
      const m = {}
      tasks.forEach(t => { m[t.task_id] = t })
      setTasksMap(m)
      setDepartments(depts)
    } catch (err) {
      console.error('Failed to load scheduler data', err)
    }
  }, [])

  useEffect(() => {
    loadData()
    const interval = setInterval(loadData, 15000)
    return () => clearInterval(interval)
  }, [loadData])

  useEffect(() => {
    if (departments.length > 0 && !formDeptId) {
      setFormDeptId(departments[0].department_id.toString())
    }
  }, [departments, formDeptId])

  const recurringTasksForDept = useMemo(() => {
    const deptId = parseInt(formDeptId)
    if (!deptId) return []
    return allTasks.filter(t => t.department_id === deptId && t.task_type === 'RECURRING')
  }, [allTasks, formDeptId])

  useEffect(() => {
    setFormTaskId('')
    setFormNewTaskName('')
    setFormShiftId('')
    if (formDeptId) {
      getShifts(parseInt(formDeptId))
        .then(setDeptShifts)
        .catch(() => setDeptShifts([]))
    } else {
      setDeptShifts([])
    }
  }, [formDeptId])

  const handleDeptChange = (val) => {
    setFormDeptId(val)
  }

  const handleTaskChange = (val) => {
    setFormTaskId(val)
    if (val && val !== 'new') {
      const task = tasksMap[parseInt(val)]
      if (task) {

        const p = task.priority_category
        if (p) {
          setFormPriority(p.charAt(0) + p.slice(1).toLowerCase())
        } else {
          setFormPriority('Default')
        }
      }
    } else {

      setFormPriority('Default')
    }
  }

  const handleRunScheduler = async () => {
    setIsRunning(true)
    try {
      await runScheduler()
      await loadData()
    } catch (err) {
      console.error('Scheduler run failed', err)
    } finally {
      setIsRunning(false)
    }
  }

  const handleToggleActive = async (id, active) => {
    try {
      await updateSchedule(id, { is_active: !active })
      await loadData()
    } catch (err) { console.error(err) }
  }

  const handleDelete = async (id) => {
    try {
      await deleteScheduleApi(id)
      showToast('Schedule deleted successfully')
      await loadData()
    } catch (err) {
      console.error(err)
      showToast(err.message || 'Failed to delete schedule', 'error')
    }
  }

  const handleCreateSchedule = async (e) => {
    e.preventDefault()
    if (isSubmitting) return

    if (!formTaskId) {
      alert('Please select a task or choose "+ Create New Task"')
      return
    }
    if (formTaskId === 'new' && !formNewTaskName.trim()) {
      alert('Please enter a name for the new task')
      return
    }

    setIsSubmitting(true)

    try {
      const deptId = parseInt(formDeptId)
      let taskId = null
      let taskName = ''

      if (formTaskId === 'new') {
        taskName = formNewTaskName.trim()
        const priorityEnum = formPriority === 'Default' ? 'MEDIUM' : formPriority.toUpperCase()

        try {
          const newTask = await createTask({
            department_id: deptId,
            task_name: taskName,
            priority_category: priorityEnum,

            task_type: 'RECURRING',
            description: `Scheduled recurring task: ${taskName}`,
          })
          taskId = newTask.task_id
          taskName = newTask.task_name
        } catch (err) {
          alert(`Failed to create task: ${err.message}`)
          return
        }
      } else {
        const task = tasksMap[parseInt(formTaskId)]
        if (!task) {
          alert('Selected task not found. Please refresh and try again.')
          return
        }
        taskId = task.task_id
        taskName = task.task_name
      }

      const { type: freqType, value: freqValue } = parseFrequency(formFrequency)
      const freqLabel = humanFrequency(freqType, freqValue)

      let scheduleName = `${taskName} - ${freqLabel}`
      let suffix = 1
      const existingNames = allSchedules
        .filter(s => s.task_id === taskId)
        .map(s => s.schedule_name.toLowerCase())

      while (existingNames.includes(scheduleName.toLowerCase())) {
        suffix++
        scheduleName = `${taskName} - ${freqLabel} #${suffix}`
      }

      try {
        const payload = {
          task_id: taskId,
          schedule_name: scheduleName,
          frequency_type: freqType,
          frequency_value: freqValue,
        }
        if (formShiftId) payload.shift_id = parseInt(formShiftId)
        await createSchedule(payload)
      } catch (err) {
        alert(`Failed to create schedule: ${err.message}`)
        return
      }

      setFormNewTaskName('')
      setFormTaskId('')
      setFormShiftId('')
      setFormPriority('Default')
      setFormFrequency('HOURS')
      await loadData()
    } catch (err) {
      console.error('Error creating schedule:', err)
      alert('Something went wrong while creating the schedule.')
    } finally {
      setIsSubmitting(false)
    }
  }

  const kpis = useMemo(() => {
    const total = allSchedules.length
    const active = allSchedules.filter(s => s.is_active).length
    const now = new Date()
    const in24h = upcomingData.filter(s => {
      const diff = new Date(s.next_run) - now
      return diff > 0 && diff < 86400000
    }).length
    const overdue = upcomingData.filter(s => new Date(s.next_run) < now).length
    return { total, active, in24h, overdue }
  }, [allSchedules, upcomingData])

  const enrichedUpcoming = useMemo(() => {
    const enriched = upcomingData.map(s => ({ ...s, _task: tasksMap[s.task_id] || {} }))
    enriched.sort((a, b) => priorityRank(a._task?.priority_category || 'LOW') - priorityRank(b._task?.priority_category || 'LOW'))
    return enriched
  }, [upcomingData, tasksMap])

  const tableData = useMemo(() => {
    return allSchedules.map(s => ({ ...s, task_name: tasksMap[s.task_id]?.task_name || '—' }))
  }, [allSchedules, tasksMap])

  return (
    <div className="scheduler-page">
      {toast.show && (
        <div className={`sch-toast ${toast.type === 'error' ? 'sch-toast-error' : 'sch-toast-success'}`}>
          <span className="material-symbols-outlined" style={{ fontSize: 20, fontVariationSettings: "'FILL' 1" }}>
            {toast.type === 'error' ? 'error' : 'check_circle'}
          </span>
          {toast.message}
        </div>
      )}
      <div className="sch-header">
        <div>
          <div className="sch-title-row">
            <span className="material-symbols-outlined sch-title-icon">event_repeat</span>
            <h2 className="sch-title">Task Scheduler</h2>
          </div>
          <p className="sch-subtitle">Manage and monitor recurring hospital task schedules</p>
        </div>
        {userRole === 'ADMIN' && (
          <button className={`sch-run-btn${isRunning ? ' sch-running' : ''}`} onClick={handleRunScheduler} disabled={isRunning}>
            <span className="material-symbols-outlined">{isRunning ? 'hourglass_empty' : 'play_arrow'}</span>
            {isRunning ? 'Running...' : 'Run Scheduler Now'}
          </button>
        )}
      </div>

      <div className="sch-kpi-strip">
        <div className="sch-kpi">
          <span className="sch-kpi-label">TOTAL SCHEDULES</span>
          <div className="sch-kpi-value-row">
            <span className="sch-kpi-num">{kpis.total}</span>
            <span className="sch-kpi-hint">Global tasks</span>
          </div>
        </div>
        <div className="sch-kpi-divider" />
        <div className="sch-kpi">
          <span className="sch-kpi-label">ACTIVE</span>
          <div className="sch-kpi-value-row">
            <span className="sch-kpi-num sch-num-green">{kpis.active}</span>
            <span className="material-symbols-outlined sch-kpi-icon sch-icon-green">check_circle</span>
          </div>
        </div>
        <div className="sch-kpi-divider" />
        <div className="sch-kpi">
          <span className="sch-kpi-label">DUE IN 24H</span>
          <div className="sch-kpi-value-row">
            <span className="sch-kpi-num sch-num-amber">{kpis.in24h}</span>
            <span className="material-symbols-outlined sch-kpi-icon sch-icon-amber">schedule</span>
          </div>
        </div>
        <div className="sch-kpi-divider" />
        <div className="sch-kpi sch-kpi-overdue">
          <span className="sch-kpi-label">OVERDUE</span>
          <div className="sch-kpi-value-row">
            <span className="sch-kpi-num sch-num-red">{kpis.overdue}</span>
            <span className="material-symbols-outlined sch-kpi-icon sch-icon-red">error</span>
          </div>
        </div>
      </div>

      <div className="sch-columns">
        <div className="sch-left-col">
          <h3 className="sch-section-title">Upcoming Schedules</h3>
          {enrichedUpcoming.length === 0 && (
            <p className="sch-empty-msg">No upcoming schedules found.</p>
          )}
          <div className="sch-upcoming-list">
            {enrichedUpcoming.map(sched => {
              const priority = sched._task?.priority_category || 'MEDIUM'
              const meta = PRIORITY_META[priority] || PRIORITY_META.MEDIUM
              const freq = humanFrequency(sched.frequency_type, sched.frequency_value)
              const { main, sub, urgency } = getStatusInfo(sched.next_run, sched.last_run)
              return (
                <div key={sched.schedule_id} className={`sch-up-card sch-accent-${urgency}`} style={{ '--accent-color': meta.accent }}>
                  <div className="sch-up-icon" style={{ background: meta.iconBg }}>
                    <span className="material-symbols-outlined" style={{ color: meta.iconColor, fontSize: 22, fontVariationSettings: "'FILL' 1" }}>{meta.icon}</span>
                  </div>
                  <div className="sch-up-body">
                    <div className="sch-up-name-row">
                      <span className="sch-up-name">{sched.schedule_name}</span>
                      <span className="sch-badge" style={{ background: meta.badgeBg, color: meta.badgeColor }}>{priority}</span>
                    </div>
                    <div className="sch-up-meta">
                      {sched._task?.task_name || '---'}
                      <span className="sch-dot-sep">&#8226;</span>{freq}
                      {sched.shift_name && <><span className="sch-dot-sep">&#8226;</span><span className="sch-shift-tag">{sched.shift_name}</span></>}
                    </div>
                  </div>
                  <div className="sch-up-status">
                    <span className={`sch-status-text sch-urgency-${urgency}`}>{main}</span>
                    <span className="sch-status-sub">{sub}</span>
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        <div className="sch-right-col">
          <div className="sch-form-card">
            <h3 className="sch-form-title">New Schedule</h3>
            <form onSubmit={handleCreateSchedule} className="sch-form-container">
              <div className="sch-form-group">
                <label className="sch-form-label">Department</label>
                <select
                  className="sch-form-select"
                  value={formDeptId}
                  onChange={e => handleDeptChange(e.target.value)}
                  required
                >
                  {departments.length === 0 && <option value="">Loading...</option>}
                  {departments.map(dept => (
                    <option key={dept.department_id} value={dept.department_id}>
                      {dept.department_name}
                    </option>
                  ))}
                </select>
              </div>

              <div className="sch-form-group">
                <label className="sch-form-label">Task Name</label>
                <select
                  className="sch-form-select"
                  value={formTaskId}
                  onChange={e => handleTaskChange(e.target.value)}
                  required
                >
                  <option value="">— Select a task —</option>
                  {recurringTasksForDept.map(t => (
                    <option key={t.task_id} value={t.task_id}>
                      {t.task_name}
                    </option>
                  ))}
                  {userRole === 'ADMIN' && (
                    <option value="new">+ Create New Task...</option>
                  )}
                </select>
              </div>

              {formTaskId === 'new' && (
                <div className="sch-form-group">
                  <label className="sch-form-label">New Task Name</label>
                  <input
                    type="text"
                    className="sch-form-input"
                    placeholder="e.g. WARD ROUND"
                    value={formNewTaskName}
                    onChange={e => setFormNewTaskName(e.target.value.toUpperCase())}
                    required
                  />
                </div>
              )}

              <div className="sch-form-group">
                <label className="sch-form-label">Frequency</label>
                <select
                  className="sch-form-select"
                  value={formFrequency}
                  onChange={e => setFormFrequency(e.target.value)}
                  required
                >
                  <option value="MINUTES">Every Minute</option>
                  <option value="HOURS">Hourly</option>
                  <option value="HOURS_2">Every 2 Hours</option>
                  <option value="HOURS_4">Every 4 Hours</option>
                  <option value="DAYS">Daily</option>
                  <option value="WEEKS">Weekly</option>
                  <option value="MONTHS">Monthly</option>
                </select>
              </div>

              <div className="sch-form-group">
                <label className="sch-form-label">Shift (Optional)</label>
                <select
                  className="sch-form-select"
                  value={formShiftId}
                  onChange={e => setFormShiftId(e.target.value)}
                >
                  <option value="">No shift restriction</option>
                  {deptShifts.map(s => (
                    <option key={s.shift_id} value={s.shift_id}>
                      {s.shift_name} ({s.start_time.slice(0,5)} - {s.end_time.slice(0,5)})
                    </option>
                  ))}
                </select>
              </div>

              <div className="sch-form-group">
                <label className="sch-form-label">Priority</label>
                <select
                  className="sch-form-select"
                  value={formPriority}
                  onChange={e => setFormPriority(e.target.value)}
                  required
                >
                  <option value="Default">Default</option>
                  <option value="Low">Low</option>
                  <option value="Medium">Medium</option>
                  <option value="High">High</option>
                  <option value="Critical">Critical</option>
                </select>
              </div>

              <button type="submit" className="sch-form-submit-btn" disabled={isSubmitting}>
                {isSubmitting ? 'Creating...' : 'Create Schedule'}
              </button>
            </form>
          </div>
        </div>
      </div>

      <div className="sch-all-section">
        <div className="sch-all-head">
          <h3 className="sch-section-title sch-all-title">All Schedules</h3>
        </div>
        <table className="sch-table">
          <thead>
            <tr>
              <th>#</th>
              <th>SCHEDULE NAME</th>
              <th>TASK</th>
              <th>SHIFT</th>
              <th>FREQUENCY</th>
              <th>NEXT RUN</th>
              <th>LAST RUN</th>
              <th>STATUS</th>
              <th>ACTIONS</th>
            </tr>
          </thead>
          <tbody>
            {tableData.length === 0 && (
              <tr><td colSpan={9} className="sch-empty-td">No schedules found</td></tr>
            )}
            {tableData.map((sched, idx) => (
              <tr key={sched.schedule_id}>
                <td className="sch-td-num">{String(idx + 1).padStart(2, '0')}</td>
                <td><span className="sch-td-name">{sched.schedule_name}</span></td>
                <td className="sch-td-task">{sched.task_name}</td>
                <td>{sched.shift_name || '---'}</td>
                <td>{humanFrequency(sched.frequency_type, sched.frequency_value)}</td>
                <td>{formatTime(sched.next_run)}</td>
                <td className="sch-td-muted">{formatTime(sched.last_run)}</td>
                <td>
                  <span
                    className={`sch-chip ${sched.is_active ? 'sch-chip-active' : 'sch-chip-paused'}`}
                    onClick={() => handleToggleActive(sched.schedule_id, sched.is_active)}
                    title={sched.is_active ? 'Click to pause' : 'Click to activate'}
                  >
                    {sched.is_active ? 'ACTIVE' : 'PAUSED'}
                  </span>
                </td>
                <td>
                  <div className="sch-td-actions">
                    <button className="sch-act-btn sch-act-edit" title="Toggle active/paused" onClick={() => handleToggleActive(sched.schedule_id, sched.is_active)}>
                      <span className="material-symbols-outlined" style={{ fontSize: 20 }}>{sched.is_active ? 'pause' : 'play_arrow'}</span>
                    </button>
                    <button className="sch-act-btn sch-act-del" title="Delete schedule" onClick={() => handleDelete(sched.schedule_id)}>
                      <span className="material-symbols-outlined" style={{ fontSize: 20 }}>delete</span>
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
