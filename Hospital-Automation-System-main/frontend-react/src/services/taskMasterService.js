import { authFetch } from './apiHelper'

const API_BASE = ''

export async function getAllTasks() {
  const res = await authFetch(`${API_BASE}/tasks/`)
  if (!res.ok) throw new Error('Failed to fetch tasks')
  return res.json()
}

export async function getTask(taskId) {
  const res = await authFetch(`${API_BASE}/tasks/${taskId}`)
  if (!res.ok) throw new Error('Failed to fetch task')
  return res.json()
}

export async function createTask(taskData) {
  const res = await authFetch(`${API_BASE}/tasks/`, {
    method: 'POST',
    body: JSON.stringify(taskData),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Failed to create task')
  }
  return res.json()
}

export async function updateTask(taskId, taskData) {
  const res = await authFetch(`${API_BASE}/tasks/${taskId}`, {
    method: 'PUT',
    body: JSON.stringify(taskData),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Failed to update task')
  }
  return res.json()
}

export async function deleteTask(taskId) {
  const res = await authFetch(`${API_BASE}/tasks/${taskId}`, {
    method: 'DELETE',
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Failed to delete task')
  }
  return res.json()
}

export async function getDepartments() {
  const res = await authFetch(`${API_BASE}/departments/`)
  if (!res.ok) throw new Error('Failed to fetch departments')
  return res.json()
}

export async function uploadTasksExcel(file) {
  const formData = new FormData()
  formData.append('file', file)

  const res = await authFetch(`${API_BASE}/tasks/bulk-upload`, {
    method: 'POST',
    body: formData,
  })

  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Failed to upload Excel file')
  }

  return res.json()
}

export async function downloadExcelTemplate() {
  const res = await authFetch(`${API_BASE}/tasks/excel-template`)
  if (!res.ok) throw new Error('Failed to download Excel template')

  const blob = await res.blob()
  const url = window.URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'task_master_template.xlsx'
  document.body.appendChild(a)
  a.click()
  a.remove()
  window.URL.revokeObjectURL(url)
}
