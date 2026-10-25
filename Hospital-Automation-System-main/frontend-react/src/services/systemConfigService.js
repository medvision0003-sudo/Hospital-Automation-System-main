import { authFetch } from './apiHelper'

const API_BASE = '/system-config'

export async function fetchSystemConfigs() {
  const response = await authFetch(`${API_BASE}/`)
  if (!response.ok) {
    const errData = await response.json().catch(() => ({}))
    throw new Error(errData.detail || 'Failed to fetch system configurations.')
  }
  return response.json()
}

export async function updateSystemConfigs(updates) {
  const response = await authFetch(`${API_BASE}/`, {
    method: 'PUT',
    body: JSON.stringify({ updates }),
  })
  if (!response.ok) {
    const errData = await response.json().catch(() => ({}))
    throw new Error(errData.detail || 'Failed to update system configurations.')
  }
  return response.json()
}
