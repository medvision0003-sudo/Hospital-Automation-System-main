/**
 * NotificationContext
 *
 * Single source of truth for sidebar notification badge counts.
 * Polls relevant endpoints every 8 seconds, pausing when the browser
 * tab is hidden.  Uses Promise.allSettled so a 403 on one endpoint
 * (e.g. non-admin hitting /auth/pending-supervisors) never breaks the
 * other badge counts.
 */
import { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react'
import { authFetch } from '../services/apiHelper'

const NotificationContext = createContext({
  pendingSupervisorsCount: 0,
  pendingSupervisors: [],
  pendingEscalationsCount: 0,
  pendingProofsCount: 0,
  refresh: () => {},
})

const POLL_INTERVAL = 8000

export function NotificationProvider({ children }) {
  const [pendingSupervisors, setPendingSupervisors] = useState([])
  const [pendingEscalationsCount, setPendingEscalationsCount] = useState(0)
  const [pendingProofsCount, setPendingProofsCount] = useState(0)
  const timerRef = useRef(null)

  const refresh = useCallback(async () => {
    const token = localStorage.getItem('access_token')
    if (!token) return

    const role = localStorage.getItem('user_role')

    const promises = []
    const keys = []

    // Admin-only: pending supervisor registrations
    if (role === 'ADMIN') {
      promises.push(authFetch('/auth/pending-supervisors'))
      keys.push('supervisors')
    }

    // Admin + Supervisor: pending escalations
    if (role === 'ADMIN' || role === 'SUPERVISOR') {
      promises.push(authFetch('/escalations/?status_filter=PENDING'))
      keys.push('escalations')
    }

    // Proofs awaiting verification (all authenticated roles)
    promises.push(authFetch('/work-queue/'))
    keys.push('proofs')

    const results = await Promise.allSettled(promises)

    results.forEach((result, i) => {
      if (result.status !== 'fulfilled' || !result.value.ok) return
      const key = keys[i]

      result.value.json().then(data => {
        if (key === 'supervisors') {
          setPendingSupervisors(Array.isArray(data) ? data : [])
        } else if (key === 'escalations') {
          setPendingEscalationsCount(Array.isArray(data) ? data.length : 0)
        } else if (key === 'proofs') {
          // Count work items whose latest proof is PENDING verification
          const count = Array.isArray(data)
            ? data.filter(w => w.verification_status === 'PENDING').length
            : 0
          setPendingProofsCount(count)
        }
      }).catch(() => { /* swallow parse errors silently */ })
    })
  }, [])

  useEffect(() => {
    // Initial fetch
    refresh()

    const startPolling = () => {
      stopPolling()
      timerRef.current = setInterval(() => {
        if (!document.hidden) refresh()
      }, POLL_INTERVAL)
    }

    const stopPolling = () => {
      if (timerRef.current) {
        clearInterval(timerRef.current)
        timerRef.current = null
      }
    }

    // Resume polling immediately when tab becomes visible again
    const handleVisibility = () => {
      if (!document.hidden) refresh()
    }

    startPolling()
    document.addEventListener('visibilitychange', handleVisibility)

    // Re-fetch when auth state changes (login/logout)
    const handleAuth = () => refresh()
    window.addEventListener('authChange', handleAuth)

    return () => {
      stopPolling()
      document.removeEventListener('visibilitychange', handleVisibility)
      window.removeEventListener('authChange', handleAuth)
    }
  }, [refresh])

  return (
    <NotificationContext.Provider
      value={{
        pendingSupervisorsCount: pendingSupervisors.length,
        pendingSupervisors,
        pendingEscalationsCount,
        pendingProofsCount,
        refresh,
      }}
    >
      {children}
    </NotificationContext.Provider>
  )
}

export function useNotifications() {
  return useContext(NotificationContext)
}
