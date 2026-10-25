import { useState, useEffect } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { useNotifications } from '../context/NotificationContext'
import './Sidebar.css'

const navItems = [
  { to: '/', icon: 'dashboard', label: 'Dashboard' },
  { to: '/employees', icon: 'badge', label: 'Employees', adminOnly: true },
  { to: '/task-master', icon: 'assignment', label: 'Task Master', adminOnly: true },
  { to: '/control-panel', icon: 'settings', label: 'Control Panel', adminOnly: true },
  { to: '/task-proof', icon: 'verified', label: 'Task Proof', adminOnly: true },
  { to: '/supervisor', icon: 'supervisor_account', label: 'Supervisor' },
  { to: '/shifts', icon: 'schedule', label: 'Shifts', adminOnly: true },
  { to: '/emergency', icon: 'emergency', label: 'Emergency Console' },
  { to: '/scheduler', icon: 'event_upcoming', label: 'Task Scheduler', adminOnly: true },
  { to: '/staff-automation', icon: 'clinical_notes', label: 'Staff Automation' },
  { to: '/workflow', icon: 'schema', label: 'Workflow Console', adminOnly: true },
  { to: '/agents', icon: 'smart_toy', label: 'Agent Management', adminOnly: true },
]

export default function Sidebar() {
  const navigate = useNavigate()
  const [userRole, setUserRole] = useState(localStorage.getItem('user_role') || 'ADMIN')
  const { pendingEscalationsCount, pendingProofsCount } = useNotifications()

  useEffect(() => {
    const handleAuthChange = () => {
      setUserRole(localStorage.getItem('user_role') || 'ADMIN')
    }
    window.addEventListener('storage', handleAuthChange)
    window.addEventListener('authChange', handleAuthChange)
    return () => {
      window.removeEventListener('storage', handleAuthChange)
      window.removeEventListener('authChange', handleAuthChange)
    }
  }, [])

  // Map nav paths to their badge counts
  const badgeCounts = {
    '/supervisor': pendingEscalationsCount,
    '/task-proof': pendingProofsCount,
  }

  const visibleItems = navItems.filter(
    item => !item.adminOnly || userRole === 'ADMIN'
  )

  const handleLogout = () => {
    localStorage.removeItem('user_role')
    localStorage.removeItem('access_token')
    localStorage.removeItem('user_email')
    localStorage.removeItem('user_department_id')
    localStorage.removeItem('user_employee_id')
    window.dispatchEvent(new Event('authChange'))
    navigate('/auth')
  }

  return (
    <aside className="sidebar">
      {/* Brand */}
      <div className="sidebar-brand">
        <span className="material-symbols-outlined brand-icon">monitor_heart</span>
        <div>
          <h1 className="brand-title">Hospital Automation</h1>
          <span className="text-label-md" style={{ color: 'var(--primary)', fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
            Role: {userRole}
          </span>
        </div>
      </div>

      {/* Navigation */}
      <nav className="sidebar-nav">
        {visibleItems.map((item) => {
          const badge = badgeCounts[item.to] || 0
          // Deep-link to escalations tab when escalations are pending
          const linkTo = item.to === '/supervisor' && pendingEscalationsCount > 0
            ? '/supervisor?tab=escalations'
            : item.to
          return (
            <NavLink
              key={item.to}
              to={linkTo}
              end={item.to === '/'}
              className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}
            >
              <span className="material-symbols-outlined">{item.icon}</span>
              <span className="text-label-md">{item.label}</span>
              {badge > 0 && <span className="nav-badge">{badge}</span>}
            </NavLink>
          )
        })}
      </nav>

      {/* Footer */}
      <div className="sidebar-footer">
        <button 
          className="nav-item" 
          onClick={handleLogout}
          style={{ width: '100%', border: 'none', background: 'transparent', textAlign: 'left', cursor: 'pointer' }}
        >
          <span className="material-symbols-outlined">logout</span>
          <span className="text-label-md">Sign Out</span>
        </button>
        <a className="nav-item" href="#">
          <span className="material-symbols-outlined">help</span>
          <span className="text-label-md">Support</span>
        </a>
      </div>
    </aside>
  )
}
