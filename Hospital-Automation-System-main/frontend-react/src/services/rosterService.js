import { authFetch } from './apiHelper'

export async function getDepartments() {
  const res = await authFetch('/departments/')
  if (!res.ok) throw new Error('Failed to fetch departments')
  return res.json()
}

export async function getEmployees() {
  const res = await authFetch('/employees/')
  if (!res.ok) throw new Error('Failed to fetch employees')
  return res.json()
}

export async function getShifts(departmentId) {
  let url = '/shifts/'
  if (departmentId) {
    url += `?department_id=${departmentId}`
  }
  const res = await authFetch(url)
  if (!res.ok) throw new Error('Failed to fetch shifts')
  return res.json()
}

export async function createShift(data) {
  const res = await authFetch('/shifts/', {
    method: 'POST',
    body: JSON.stringify(data),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Failed to create shift')
  }
  return res.json()
}

export async function updateShift(shiftId, data) {
  const res = await authFetch(`/shifts/${shiftId}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Failed to update shift')
  }
  return res.json()
}

export async function deleteShift(shiftId) {
  const res = await authFetch(`/shifts/${shiftId}`, {
    method: 'DELETE',
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Failed to delete shift')
  }
  return res.json()
}

export async function getRostersRange(startDate, endDate, departmentId) {
  let url = `/rosters/range?start_date=${startDate}&end_date=${endDate}`
  if (departmentId) {
    url += `&department_id=${departmentId}`
  }
  const res = await authFetch(url)
  if (!res.ok) throw new Error('Failed to fetch rosters')
  return res.json()
}

export async function bulkSaveRosters(items) {
  const res = await authFetch('/rosters/bulk', {
    method: 'POST',
    body: JSON.stringify({ items }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Failed to bulk save rosters')
  }
  return res.json()
}
