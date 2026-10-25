import { authFetch } from './apiHelper'

const API_BASE = ''

export async function fetchEmployees() {
  const res = await authFetch(`${API_BASE}/employees/`)
  if (!res.ok) throw new Error('Failed to fetch employees')
  return res.json()
}

export async function fetchEmployee(employeeId) {
  const res = await authFetch(`${API_BASE}/employees/${employeeId}`)
  if (!res.ok) throw new Error('Failed to fetch employee details')
  return res.json()
}

export async function createEmployee(employeeData) {
  const res = await authFetch(`${API_BASE}/employees/`, {
    method: 'POST',
    body: JSON.stringify(employeeData),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Failed to create employee')
  }
  return res.json()
}

export async function updateEmployee(employeeId, employeeData) {
  const res = await authFetch(`${API_BASE}/employees/${employeeId}`, {
    method: 'PUT',
    body: JSON.stringify(employeeData),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Failed to update employee')
  }
  return res.json()
}

export async function deleteEmployee(employeeId) {
  const res = await authFetch(`${API_BASE}/employees/${employeeId}`, {
    method: 'DELETE',
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Failed to delete employee')
  }
  return res.json()
}

export async function fetchDepartments() {
  const res = await authFetch(`${API_BASE}/departments/`)
  if (!res.ok) throw new Error('Failed to fetch departments')
  return res.json()
}
