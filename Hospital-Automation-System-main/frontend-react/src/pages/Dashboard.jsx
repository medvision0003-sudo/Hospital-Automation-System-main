import { useState, useEffect, useCallback } from 'react'
import KpiCard from '../components/KpiCard'
import DepartmentCard from '../components/DepartmentCard'
import { authFetch } from '../services/apiHelper'
import { useNotifications } from '../context/NotificationContext'
import './Dashboard.css'

const REFRESH_INTERVAL = 5000

export default function Dashboard() {
  const [data, setData] = useState(null)
  const [employeeList, setEmployeeList] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [lastUpdated, setLastUpdated] = useState(null)
  const { pendingSupervisors, refresh: refreshNotifications } = useNotifications()

  const handleApproveSupervisor = async (userId) => {
    try {
      const res = await authFetch(`/auth/approve-supervisor/${userId}`, { method: 'POST' })
      if (res.ok) {
        refreshNotifications()
        fetchDashboard()
      }
    } catch (err) {
      console.error('Failed to approve supervisor:', err)
    }
  }

  const handleRejectSupervisor = async (userId) => {
    try {
      const res = await authFetch(`/auth/reject-supervisor/${userId}`, { method: 'POST' })
      if (res.ok) {
        refreshNotifications()
        fetchDashboard()
      }
    } catch (err) {
      console.error('Failed to reject supervisor:', err)
    }
  }

  const fetchDashboard = useCallback(async () => {
    try {
      const [resDash, resEmp] = await Promise.all([
        authFetch('/dashboard/'),
        authFetch('/employees/')
      ])
      if (!resDash.ok) throw new Error(`API error: ${resDash.status}`)
      const json = await resDash.json()
      setData(json)

      if (resEmp.ok) {
        const empJson = await resEmp.json()
        setEmployeeList(empJson)
      }
      setError(null)
      setLastUpdated(new Date())
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchDashboard()
    const interval = setInterval(() => {
      if (!document.hidden) fetchDashboard()
    }, REFRESH_INTERVAL)
    return () => clearInterval(interval)
  }, [fetchDashboard])

  if (loading && !data) {
    return (
      <div className="dashboard-page">
        <div className="dashboard-loading">
          <span className="material-symbols-outlined loading-spinner">progress_activity</span>
          <p>Loading dashboard metrics...</p>
        </div>
      </div>
    )
  }

  if (error && !data) {
    return (
      <div className="dashboard-page">
        <div className="dashboard-error">
          <span className="material-symbols-outlined">error</span>
          <p>Failed to load dashboard: {error}</p>
          <button className="retry-btn" onClick={fetchDashboard}>Retry</button>
        </div>
      </div>
    )
  }

  const summary = data?.summary || {}
  const operations = data?.operations || {}
  const departments = data?.departments || []
  const recentEvents = data?.recent_events || []
  const employees = operations.employees || {}

  const kpiData = [
    { icon: 'domain', label: 'Active Depts', value: String(summary.total_departments || 0), subtitle: 'Registered', subtitleIcon: 'trending_up' },
    { icon: 'group', label: 'Staff In', value: String(summary.checked_in_workers || 0), subtitle: `${employees.off_shift || 0} off shift` },
    { icon: 'hail', label: 'Available', value: String(employees.available || 0), subtitle: 'Ready for tasks', subtitleIcon: 'dot' },
    { icon: 'assignment_late', label: 'Pending', value: String(summary.pending_tasks || 0), subtitle: `${summary.tasks_in_progress || 0} in progress` },
    { icon: 'warning', label: 'Emergencies', value: String(summary.active_emergencies || 0).padStart(2, '0'), subtitle: summary.active_emergencies > 0 ? 'Action Required' : 'All Clear', subtitleIcon: summary.active_emergencies > 0 ? 'ping' : undefined, variant: summary.active_emergencies > 0 ? 'emergency' : 'default' },
  ]

  // Staff distribution donut data
  const staffTotal = (employees.available || 0) + (employees.busy || 0) + (employees.off_shift || 0)
  const staffDistribution = [
    { label: 'Available', count: employees.available || 0, color: 'var(--primary)' },
    { label: 'Busy', count: employees.busy || 0, color: 'var(--secondary-container)' },
    { label: 'Off Shift', count: employees.off_shift || 0, color: 'var(--outline-variant)' },
  ]

  // SVG donut calculations (circumference = 2 * PI * 80 = ~502)
  const circumference = 2 * Math.PI * 80
  const availableFraction = staffTotal > 0 ? (employees.available || 0) / staffTotal : 0
  const busyFraction = staffTotal > 0 ? (employees.busy || 0) / staffTotal : 0
  const availableArc = circumference * availableFraction
  const busyArc = circumference * busyFraction
  const availableOffset = 0
  const busyOffset = circumference - availableArc

  return (
    <div className="dashboard-page">
      {/* Heading */}
      <div className="dashboard-heading">
        <div className="dashboard-heading-row">
          <div>
            <h2 className="text-headline-lg">Automation Dashboard</h2>
            <p className="text-body-md dashboard-subtitle">Real-time workforce and task queue overview.</p>
          </div>
          <div className="dashboard-actions">
            {lastUpdated && (
              <span className="last-updated-badge">
                <span className="material-symbols-outlined" style={{ fontSize: 14 }}>schedule</span>
                {lastUpdated.toLocaleTimeString()}
              </span>
            )}
            <button className="refresh-btn" onClick={() => { fetchDashboard(); refreshNotifications(); }} title="Refresh now">
              <span className="material-symbols-outlined">refresh</span>
            </button>
          </div>
        </div>
      </div>

      {/* Pending Supervisor Registration Requests Notification Banner */}
      {pendingSupervisors.length > 0 && (
        <div className="supervisor-requests-banner">
          <div className="supervisor-requests-header">
            <div className="supervisor-requests-icon-badge">
              <span className="material-symbols-outlined">notifications_active</span>
            </div>
            <h4 className="supervisor-requests-title">
              Pending Supervisor Registration Requests
              <span className="supervisor-requests-count-badge">{pendingSupervisors.length}</span>
            </h4>
          </div>
          <div className="supervisor-requests-list">
            {pendingSupervisors.map((sup) => (
              <div key={sup.user_id} className="supervisor-request-item">
                <div className="supervisor-request-info">
                  <div className="supervisor-request-avatar">
                    {sup.email ? sup.email.charAt(0).toUpperCase() : 'S'}
                  </div>
                  <div>
                    <div className="supervisor-request-email">{sup.email}</div>
                    <div className="supervisor-request-meta">
                      <span className="supervisor-meta-chip">EMP-{sup.employee_id}</span>
                      {sup.department_name && (
                        <span className="supervisor-meta-chip">Dept: {sup.department_name}</span>
                      )}
                    </div>
                  </div>
                </div>
                <div className="supervisor-request-actions">
                  <button
                    className="btn-approve-request"
                    onClick={() => handleApproveSupervisor(sup.user_id)}
                  >
                    <span className="material-symbols-outlined" style={{ fontSize: '16px' }}>check_circle</span>
                    Approve
                  </button>
                  <button
                    className="btn-reject-request"
                    onClick={() => handleRejectSupervisor(sup.user_id)}
                  >
                    <span className="material-symbols-outlined" style={{ fontSize: '16px' }}>cancel</span>
                    Reject
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Error banner (non-blocking) */}
      {error && data && (
        <div className="dashboard-error-banner">
          <span className="material-symbols-outlined" style={{ fontSize: 16 }}>warning</span>
          Auto-refresh failed. Showing last known data.
        </div>
      )}

      {/* KPI Grid */}
      <div className="kpi-grid">
        {kpiData.map((kpi, i) => (
          <KpiCard key={i} {...kpi} />
        ))}
      </div>

      {/* Dashboard Columns */}
      <div className="dashboard-columns">
        {/* Main: Department Workload */}
        <div className="dashboard-main">
          <div className="section-header">
            <h3 className="text-headline-md">Department Workload</h3>
          </div>
          <div className="dept-grid">
            {departments.length > 0 ? (
              departments.map((dept) => (
                <DepartmentCard
                  key={dept.department_id}
                  name={dept.department_name}
                  description={dept.description}
                  pendingTasks={dept.pending_tasks}
                  assignedTasks={dept.assigned_tasks}
                  availableWorkers={dept.available_workers}
                  totalStaff={dept.total_staff}
                />
              ))
            ) : (
              <p className="empty-state-text">No departments found.</p>
            )}
          </div>


          {/* Recent System Events */}
          <div className="events-section">
            <div className="section-header">
              <h3 className="text-headline-md">Recent System Events</h3>
            </div>
            <div className="events-feed glass-card">
              {recentEvents.length > 0 ? (
                recentEvents.map((evt) => (
                  <div className="event-row" key={evt.event_id}>
                    <div className="event-left">
                      <span className="event-icon material-symbols-outlined">bolt</span>
                      <div>
                        <p className="event-type">{evt.event_log}</p>
                        <p className="event-source">{evt.source_module}</p>
                      </div>
                    </div>
                    <span className="event-time">
                      {new Date(evt.timestamp).toLocaleTimeString()}
                    </span>
                  </div>
                ))
              ) : (
                <p className="empty-state-text">No recent events.</p>
              )}
            </div>
          </div>
        </div>

        {/* Side: Staff Distribution */}
        <div className="dashboard-side">
          <div className="glass-card staff-distribution-card">
            <h3 className="staff-dist-title">Staff Distribution</h3>

            {/* SVG Donut */}
            <div className="donut-container">
              <svg className="donut-svg" viewBox="0 0 192 192">
                <circle className="donut-bg" cx="96" cy="96" r="80" fill="transparent" stroke="rgba(224,227,229,0.3)" strokeWidth="24" />
                {staffTotal > 0 && (
                  <>
                    <circle cx="96" cy="96" r="80" fill="transparent" stroke="var(--primary)" strokeWidth="24"
                      strokeDasharray={`${availableArc} ${circumference - availableArc}`}
                      strokeDashoffset={availableOffset} />
                    <circle cx="96" cy="96" r="80" fill="transparent" stroke="var(--secondary-container)" strokeWidth="24"
                      strokeDasharray={`${busyArc} ${circumference - busyArc}`}
                      strokeDashoffset={-availableArc} />
                  </>
                )}
              </svg>
              <div className="donut-center">
                <p className="donut-total">{staffTotal}</p>
                <p className="donut-label">TOTAL</p>
              </div>
            </div>

            {/* Legend */}
            <div className="staff-legend">
              {staffDistribution.map((item, i) => (
                <div className="legend-row" key={i}>
                  <div className="legend-left">
                    <span className="legend-dot" style={{ background: item.color }} />
                    <span className="text-label-md">{item.label}</span>
                  </div>
                  <span className="legend-count">{item.count}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
