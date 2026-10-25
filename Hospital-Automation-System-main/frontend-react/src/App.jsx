import { useState, useEffect, lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { NotificationProvider } from './context/NotificationContext'
import Sidebar from './components/Sidebar'
import Dashboard from './pages/Dashboard'
import Workflow from './pages/Workflow/Workflow'
import TaskProof from './pages/TaskProof/TaskProof'
import Supervisor from './pages/Supervisor'
import Scheduler from './pages/Scheduler'
import TaskMaster from './pages/TaskMaster'
import AgentManagement from './pages/AgentManagement'
import EscalationReview from './pages/EscalationReview'
import ShiftsManagement from './pages/ShiftsManagement'
import EmergencyConsole from './pages/EmergencyConsole'
import ControlPanel from './pages/ControlPanel/ControlPanel'
import EmployeeManagement from './pages/EmployeeManagement'
import Auth from './pages/Auth'
const StaffAutomation = lazy(() => import('./pages/StaffAutomation'))

function PlaceholderPage({ title, icon }) {
  return (
    <div style={{ padding: 32 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
        <span className="material-symbols-outlined" style={{ fontSize: 32, color: 'var(--primary)' }}>{icon}</span>
        <h2 className="text-headline-lg">{title}</h2>
      </div>
      <p className="text-body-md" style={{ color: 'var(--on-surface-variant)', opacity: 0.7 }}>
        This page is under development. Connect it to your FastAPI backend endpoints.
      </p>
    </div>
  )
}

// Client-side RBAC guard: checks token + role before rendering children
function ProtectedRoute({ allowedRoles, children }) {
  const userRole = localStorage.getItem('user_role')

  if (allowedRoles && !allowedRoles.includes(userRole)) {
    const fallback = userRole === 'SUPERVISOR' ? '/supervisor' : '/'
    return <Navigate to={fallback} replace />
  }

  return children
}

export default function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(
    Boolean(localStorage.getItem('access_token'))
  )

  useEffect(() => {
    const handleAuthChange = () => {
      setIsAuthenticated(Boolean(localStorage.getItem('access_token')))
    }
    window.addEventListener('storage', handleAuthChange)
    window.addEventListener('authChange', handleAuthChange)
    return () => {
      window.removeEventListener('storage', handleAuthChange)
      window.removeEventListener('authChange', handleAuthChange)
    }
  }, [])

  return (
    <BrowserRouter>
      {!isAuthenticated ? (
        <Routes>
          <Route path="*" element={<Auth />} />
        </Routes>
      ) : (
        <NotificationProvider>
          <div className="app-layout">
            <Sidebar />
            <main className="main-content">
              <Routes>
                <Route path="/" element={<Dashboard />} />
                <Route path="/employees" element={<ProtectedRoute allowedRoles={['ADMIN']}><EmployeeManagement /></ProtectedRoute>} />
                <Route path="/task-master" element={<ProtectedRoute allowedRoles={['ADMIN']}><TaskMaster /></ProtectedRoute>} />
                <Route path="/task-proof" element={<ProtectedRoute allowedRoles={['ADMIN']}><TaskProof /></ProtectedRoute>} />
                <Route path="/agents" element={<ProtectedRoute allowedRoles={['ADMIN']}><AgentManagement /></ProtectedRoute>} />
                <Route path="/shifts" element={<ProtectedRoute allowedRoles={['ADMIN']}><ShiftsManagement /></ProtectedRoute>} />
                <Route path="/escalation-review" element={<ProtectedRoute allowedRoles={['SUPERVISOR', 'ADMIN']}><EscalationReview /></ProtectedRoute>} />
                <Route path="/scheduler" element={<Scheduler />} />
                <Route path="/emergency" element={<ProtectedRoute allowedRoles={['SUPERVISOR', 'ADMIN']}><EmergencyConsole /></ProtectedRoute>} />
                <Route path="/staff-automation/*" element={<ProtectedRoute allowedRoles={['ADMIN']}><Suspense fallback={<div style={{ padding: 32 }}>Loading Staff Automation…</div>}><StaffAutomation /></Suspense></ProtectedRoute>} />
                <Route path="/control-panel" element={<ProtectedRoute allowedRoles={['ADMIN']}><ControlPanel /></ProtectedRoute>} />
                <Route path="/workflow" element={<ProtectedRoute allowedRoles={['ADMIN']}><Workflow /></ProtectedRoute>} />
                <Route path="/supervisor" element={<Supervisor />} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            </main>
          </div>
        </NotificationProvider>
      )}
    </BrowserRouter>
  )
}
