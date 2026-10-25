/**
 * Supervisor Console API service layer.
 *
 * Isolates all API calls from the page component so the
 * Supervisor.jsx stays focused on UI logic.
 */
import { authFetch } from './apiHelper'

export async function getDepartments() {
  return getJson('/departments/', 'departments')
}

export async function getTasks() {
  return getJson('/tasks/', 'tasks')
}

export async function getCurrentUser() {
  return getJson('/auth/me', 'current user')
}

export async function getSupervisorRequests() {
  return getJson('/supervisor-task-requests/', 'supervisor task requests')
}

async function getJson(path, label) {
  const res = await authFetch(path)
  if (!res.ok) throw new Error(await responseError(res, `Failed to fetch ${label}`))
  return res.json()
}

async function responseError(response, fallback) {
  const payload = await response.json().catch(() => null)
  return typeof payload?.detail === 'string' ? payload.detail : fallback
}

/**
 * Publish a batch of supervisor task requests.
 * @param {Array} tasks - Array of task request objects
 * @returns {{ created: number, requests: Array }}
 */
export async function publishTasks(tasks) {
  const res = await authFetch('/supervisor-task-requests/bulk', {
    method: 'POST',
    body: JSON.stringify(tasks),
  })
  if (!res.ok) {
    throw new Error(await responseError(res, 'Failed to publish tasks'))
  }
  return res.json()
}

export async function getEmployees() {
  return getJson('/employees/', 'employees')
}

export async function getEmployeeAssignments(employeeId) {
  return getJson(`/employees/${employeeId}/assignments`, 'employee assignments')
}

export async function getWorkQueue() {
  return getJson('/work-queue/', 'work queue')
}

export async function getAssignments() {
  return getJson('/assignments/', 'assignments')
}

export async function getEmployeeRosters(employeeId) {
  return getJson(`/rosters/employee/${employeeId}`, 'employee rosters')
}

export async function getEmployeeCheckins(employeeId) {
  return getJson(`/employees/${employeeId}/checkins`, 'employee attendance')
}

/**
 * Preempt (remove) a task assignment from an employee.
 * Only ASSIGNED tasks can be preempted. IN_PROGRESS tasks are rejected.
 * @param {number} assignmentId
 * @returns {{ status, assignment_id, freed_work_id, employee_id, reassignment_result }}
 */
export async function preemptAssignment(assignmentId) {
  const res = await authFetch(`/assignments/${assignmentId}/preempt`, {
    method: 'POST',
  })
  if (!res.ok) {
    throw new Error(await responseError(res, 'Failed to remove assignment'))
  }
  return res.json()
}
