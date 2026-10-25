import { authFetch } from './apiHelper'

const API_BASE = ''

export async function getDepartments() {
  const res = await authFetch(`${API_BASE}/departments/`)
  if (!res.ok) throw new Error('Failed to fetch departments')
  return res.json()
}

export async function getRecurringTasks() {
  const res = await authFetch(`${API_BASE}/tasks/`)
  if (!res.ok) throw new Error('Failed to fetch tasks')
  const tasks = await res.json()
  return tasks.filter(t => t.task_type === 'RECURRING')
}

export async function getAllTasks() {
  const res = await authFetch(`${API_BASE}/tasks/`)
  if (!res.ok) throw new Error('Failed to fetch tasks')
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

export async function getAllSchedules() {
  const res = await authFetch(`${API_BASE}/schedules/`)
  if (!res.ok) throw new Error('Failed to fetch schedules')
  return res.json()
}

export async function getUpcomingSchedules() {
  const res = await authFetch(`${API_BASE}/scheduler/upcoming`)
  if (!res.ok) throw new Error('Failed to fetch upcoming schedules')
  return res.json()
}

export async function createSchedule(scheduleData) {
  const res = await authFetch(`${API_BASE}/schedules/`, {
    method: 'POST',
    body: JSON.stringify(scheduleData),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Failed to create schedule')
  }
  return res.json()
}

export async function updateSchedule(scheduleId, updateData) {
  const res = await authFetch(`${API_BASE}/schedules/${scheduleId}`, {
    method: 'PUT',
    body: JSON.stringify(updateData),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Failed to update schedule')
  }
  return res.json()
}

export async function deleteSchedule(scheduleId) {
  const res = await authFetch(`${API_BASE}/schedules/${scheduleId}`, {
    method: 'DELETE',
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Failed to delete schedule')
  }
  return res.json()
}

export async function runScheduler() {
  const res = await authFetch(`${API_BASE}/scheduler/run`, {
    method: 'POST',
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Scheduler run failed')
  }
  return res.json()
}

export async function getShifts(departmentId) {
  const url = departmentId
    ? `${API_BASE}/shifts/?department_id=${departmentId}`
    : `${API_BASE}/shifts/`
  const res = await authFetch(url)
  if (!res.ok) throw new Error('Failed to fetch shifts')
  return res.json()
}
