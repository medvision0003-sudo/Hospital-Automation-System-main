import { authFetch } from './apiHelper'

async function requestJson(path, options) {
  const response = await authFetch(path, options)
  const payload = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = payload?.detail
    const message = typeof detail === 'string'
      ? detail
      : detail?.message || `Request failed (${response.status})`
    throw new Error(message)
  }
  if (payload?.status === 'FAILED') {
    throw new Error(payload.error || 'The backend workflow failed.')
  }
  return payload
}

function getJson(path) {
  return requestJson(path)
}

function postJson(path, body) {
  return requestJson(path, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

function deleteJson(path) {
  return requestJson(path, { method: 'DELETE' })
}

export function localDateString(date = new Date()) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

export async function fetchStaffAutomationData(attendanceDate = localDateString()) {
  const today = localDateString()
  const todayPreviousDate = new Date(`${today}T00:00:00`)
  todayPreviousDate.setDate(todayPreviousDate.getDate() - 1)
  const todayStartDate = localDateString(todayPreviousDate)
  const previousDate = new Date(`${attendanceDate}T00:00:00`)
  previousDate.setDate(previousDate.getDate() - 1)
  const attendanceStartDate = localDateString(previousDate)
  const rosterPaths = [...new Set([
    `/rosters/range?start_date=${encodeURIComponent(todayStartDate)}&end_date=${encodeURIComponent(today)}`,
    `/rosters/range?start_date=${encodeURIComponent(attendanceStartDate)}&end_date=${encodeURIComponent(attendanceDate)}`,
  ])]
  const paths = [
    '/employees/',
    '/checkins/',
    '/shifts/',
    '/departments/',
    '/tasks/',
    '/work-queue/',
    '/assignments/',
    '/agent-actions/',
    '/orchestrator-traces/?limit=50',
    '/outbox-events/?limit=50',
    '/nursing-shift-logs/?limit=500',
    '/nursing-shift-logs/analytics',
    '/approvals/?status_filter=PENDING',
    '/auth/me',
    '/staff-automation/recommendations?limit=100',
    '/staff-automation/rules?limit=100',
    '/staff-automation/audit?limit=100',
    '/whatsapp-communication-status',
  ]
  const [payloads, rosterResults] = await Promise.all([
    Promise.all(paths.map(getJson)),
    Promise.all(rosterPaths.map(getJson)),
  ])
  const [
    employees,
    checkins,
    shifts,
    departments,
    taskTemplates,
    workQueue,
    assignments,
    agentActions,
    traces,
    outboxEvents,
    shiftReports,
    shiftAnalytics,
    pendingApprovals,
    currentUser,
    automationRecommendations,
    automationRules,
    automationAudit,
    communicationStatus,
  ] = payloads
  const rosters = [...new Map(rosterResults.flat().map((roster) => [roster.roster_id, roster])).values()]

  return {
    employees,
    checkins,
    rosters,
    shifts,
    departments,
    taskTemplates,
    workQueue,
    assignments,
    agentActions,
    traces,
    outboxEvents,
    shiftReports,
    shiftAnalytics,
    pendingApprovals,
    currentUser,
    automationRecommendations,
    automationRules,
    automationAudit,
    communicationStatus,
  }
}

export async function fetchMonthlyAttendance(month) {
  const [year, monthNumber] = month.split('-').map(Number)
  if (!year || monthNumber < 1 || monthNumber > 12) {
    throw new Error('Select a valid month for attendance.')
  }

  const startDate = `${year}-${String(monthNumber).padStart(2, '0')}-01`
  const endDate = `${year}-${String(monthNumber).padStart(2, '0')}-${String(new Date(year, monthNumber, 0).getDate()).padStart(2, '0')}`
  const rosterStart = new Date(`${startDate}T00:00:00`)
  rosterStart.setDate(rosterStart.getDate() - 1)
  const checkinEnd = new Date(`${endDate}T00:00:00`)
  checkinEnd.setDate(checkinEnd.getDate() + 1)
  const [employees, checkins, rosters, shifts] = await Promise.all([
    getJson('/employees/'),
    getJson(`/checkins/range?start_date=${encodeURIComponent(startDate)}&end_date=${encodeURIComponent(localDateString(checkinEnd))}`),
    getJson(`/rosters/range?start_date=${encodeURIComponent(localDateString(rosterStart))}&end_date=${encodeURIComponent(endDate)}`),
    getJson('/shifts/'),
  ])

  return { employees, checkins, rosters, shifts }
}

export async function fetchHolidayAttendance(year) {
  const [employees, checkins] = await Promise.all([
    getJson('/employees/'),
    getJson(`/checkins/year?year=${encodeURIComponent(year)}`),
  ])
  return { employees, checkins }
}

function timestampForAttendanceDate(date) {
  const now = new Date()
  const timestamp = new Date(`${date}T00:00:00`)
  timestamp.setHours(now.getHours(), now.getMinutes(), now.getSeconds(), now.getMilliseconds())
  return timestamp.toISOString()
}

export function submitStaffCheckin(employeeId, attendanceDate = localDateString()) {
  return postJson('/events/?sync=true', {
    event_type: 'WORKER_CHECKED_IN',
    payload: {
      employee_id: employeeId,
      occurred_at: timestampForAttendanceDate(attendanceDate),
      trigger_source: 'MANUAL_OVERRIDE',
    },
  })
}

export function submitStaffCheckout(
  employeeId,
  attendanceDate = localDateString(),
  incompleteTaskAction = 'REASSIGN',
) {
  return postJson('/events/?sync=true', {
    event_type: 'WORKER_CHECKED_OUT',
    payload: {
      employee_id: employeeId,
      occurred_at: timestampForAttendanceDate(attendanceDate),
      trigger_source: 'MANUAL_OVERRIDE',
      incomplete_task_action: incompleteTaskAction,
    },
  })
}

export function generateScheduledTasks() {
  return postJson('/scheduler/run', {})
}

export function completeAssignedTask(workId) {
  return postJson('/events/?sync=true', {
    event_type: 'TASK_COMPLETED',
    payload: { work_id: workId },
  })
}

export function submitTaskProof(workId, file) {
  const form = new FormData()
  form.append('file', file)
  return requestJson(`/work-queue/${workId}/submit-proof`, {
    method: 'POST',
    body: form,
  })
}

export function fetchWorkItem(workId) {
  return getJson(`/work-queue/${workId}`)
}

export function createEmergency(payload) {
  return postJson('/events/?sync=true', {
    event_type: 'EMERGENCY_RESPONSE',
    payload,
  })
}

export function createShiftReport(report) {
  return postJson('/nursing-shift-logs/', report)
}

export function createTaskTemplate(template) {
  return postJson('/tasks/', template)
}

export async function updateTaskTemplate(taskId, template) {
  return requestJson(`/tasks/${taskId}`, {
    method: 'PUT',
    body: JSON.stringify(template),
  })
}

export function deleteTaskTemplate(taskId) {
  return deleteJson(`/tasks/${taskId}`)
}

export function requestDynamicTask(request) {
  return postJson('/supervisor-task-requests/', request)
}

export function resolveApproval(approvalId, action, payload) {
  return postJson(`/approvals/${approvalId}/${action}`, payload)
}

export function analyzeShiftReportPatterns() {
  return postJson('/staff-automation/pattern-learning/analyze', {})
}

export function createAutomationRule(recommendationId, payload) {
  return postJson(`/staff-automation/recommendations/${recommendationId}/rules`, payload)
}

export function updateAutomationRule(ruleId, payload) {
  return requestJson(`/staff-automation/rules/${ruleId}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export function reviewAutomationRecommendation(recommendationId, action, payload = {}) {
  return postJson(`/staff-automation/recommendations/${recommendationId}/${action}`, payload)
}

export function reviewAutomationRule(ruleId, action, payload = {}) {
  return postJson(`/staff-automation/rules/${ruleId}/${action}`, payload)
}

export function fetchAutomationRuleEffectiveness(ruleId) {
  return getJson(`/staff-automation/rules/${ruleId}/effectiveness`)
}

export function expireAutomationRules() {
  return postJson('/staff-automation/rules/expire', {})
}
