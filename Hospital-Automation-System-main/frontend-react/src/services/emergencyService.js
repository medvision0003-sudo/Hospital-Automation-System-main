import { authFetch } from './apiHelper'

export async function triggerEmergencyEvent(eventType, payload, sync = true) {
  const response = await authFetch(`/events/?sync=${sync}`, {
    method: 'POST',
    body: JSON.stringify({
      event_type: eventType,
      payload: payload,
    }),
  })
  if (!response.ok) {
    const err = await response.json().catch(() => ({}))
    throw new Error(err.detail || 'Failed to trigger emergency event')
  }
  const data = await response.json()
  if (data.status === 'FAILED') {
    throw new Error(data.error || 'Emergency event execution failed')
  }
  return data
}

export async function fetchWorkQueue() {
  const response = await authFetch('/work-queue/')
  if (!response.ok) {
    throw new Error('Failed to fetch work queue')
  }
  return response.json()
}

export async function fetchAssignments() {
  const response = await authFetch('/assignments/')
  if (!response.ok) {
    throw new Error('Failed to fetch task assignments')
  }
  return response.json()
}

export async function fetchCheckedInResponders() {
  const response = await authFetch('/checkins/')
  if (!response.ok) {
    throw new Error('Failed to fetch responder checkins')
  }
  return response.json()
}

export async function fetchAgentActions() {
  const response = await authFetch('/agent-actions/')
  if (!response.ok) {
    throw new Error('Failed to fetch agent actions')
  }
  return response.json()
}

export async function fetchOrchestratorTraces() {
  const response = await authFetch('/orchestrator-traces/')
  if (!response.ok) {
    throw new Error('Failed to fetch orchestrator traces')
  }
  return response.json()
}
