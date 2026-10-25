import { Fragment, useCallback, useEffect, useMemo, useState } from 'react'
import './StaffAutomation.css'
import {
  MAHARASHTRA_HOLIDAYS_2026,
  MAHARASHTRA_HOLIDAY_DATES_2026,
} from '../data/maharashtraHolidays2026'
import {
  analyzeShiftReportPatterns,
  completeAssignedTask,
  createEmergency,
  createShiftReport,
  createAutomationRule,
  createTaskTemplate,
  deleteTaskTemplate,
  fetchHolidayAttendance,
  fetchMonthlyAttendance,
  fetchStaffAutomationData,
  fetchWorkItem,
  fetchAutomationRuleEffectiveness,
  expireAutomationRules,
  localDateString,
  reviewAutomationRecommendation,
  reviewAutomationRule,
  submitStaffCheckin,
  submitStaffCheckout,
  submitTaskProof,
  updateAutomationRule,
  updateTaskTemplate,
} from '../services/staffAutomationService'

const pageTabs = [
  { id: 'overview', label: 'Daily Overview', icon: 'space_dashboard' },
  { id: 'attendance', label: 'Staff Attendance', icon: 'how_to_reg' },
  { id: 'monthlyAttendance', label: 'Monthly Attendance', icon: 'calendar_month' },
  { id: 'holidayCount', label: 'Holiday Count', icon: 'celebration' },
  { id: 'tasks', label: 'Tasks', icon: 'task_alt' },
  { id: 'workload', label: 'Live Task Workload', icon: 'groups' },
  { id: 'workflow', label: 'Workflow & Approvals', icon: 'account_tree' },
]

const SHIFT_LOG_KEYS = {
  nurseName: '1. Nurse Name',
  date: '2. Date',
  shift: '3. Shift',
  ward: '4. Ward / Area',
  patients: '5. Total Patients Under Your Care (Enter a number)',
  admission: '6. Any New Admission During Shift?',
  discharge: '7. Any Discharge During Shift?',
  critical: '8. Any Critical Patient During Shift?',
  shifted: '9. Any Patient Shifted to ICU / Higher Center?',
  bedDetails: '10. If Yes to Q9, Mention Bed Number / Patient Name',
  emergency: '16. Any Emergency During Shift?',
  emergencyType: '17. Type of Emergency (Select all that apply)',
  medication: '11. Were All Medicines Given on Time?',
  delayReason: '12. Reason for Medication Delay (Select all that apply)',
  clinicalIssue: '13. Any IV Line / Catheter / Dressing Issue?',
  issueDetails: '14. Mention Issue Briefly (IV/Catheter/Dressing)',
  procedures: '15. Procedures Done During Shift (Select all that apply)',
  infection: '18. Any Infection Control Issue?',
  biomedical: '19. Any Biomedical Waste Issue?',
  equipment: '20. Any Equipment Malfunction?',
  equipmentName: '21. Mention Equipment Name (If malfunction occurred)',
  handover: '22. Was Proper Handover Given?',
  pendingTasks: '23. Pending Tasks for Next Shift (Specify details)',
  consumables: '24. Consumables Running Low (Select all that apply)',
  staffing: '25. Staffing Status',
  rating: '26. Overall Shift Rating',
  concerns: '27. Suggestions / Concerns',
}

const ATTENDABLE_ROSTER_STATUSES = new Set(['SCHEDULED', 'CHECKED_IN', 'HALF_DAY', 'ABSENT', 'OVERTIME'])
const CHECKIN_ELIGIBLE_ROSTER_STATUSES = new Set(['SCHEDULED', 'ABSENT', 'HALF_DAY', 'OVERTIME', 'CHECKED_IN'])
const SHIFT_CHECKIN_GRACE_MINUTES = 30

function Icon({ children }) {
  return <span className="material-symbols-outlined">{children}</span>
}

function StatusPill({ value }) {
  const label = value || 'UNKNOWN'
  const key = String(label).toLowerCase().replaceAll('_', '-').replaceAll(' ', '-')
  return <span className={`sa-pill sa-pill-${key}`}>{String(label).replaceAll('_', ' ')}</span>
}

function ActionButton({ children, onClick, secondary = false, danger = false, disabled = false, type = 'button' }) {
  const className = `sa-button${secondary ? ' secondary' : ''}${danger ? ' danger' : ''}`
  return <button type={type} className={className} onClick={onClick} disabled={disabled}>{children}</button>
}

function Field({ label, children, className = '' }) {
  return <label className={`sa-field ${className}`}><span>{label}</span>{children}</label>
}

function displayDateTime(value) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString()
}

function latestBy(items, key, timestampKey) {
  const result = new Map()
  for (const item of items || []) {
    const id = item[key]
    if (id == null) continue
    const previous = result.get(id)
    if (!previous || String(item[timestampKey] || '') > String(previous[timestampKey] || '')) {
      result.set(id, item)
    }
  }
  return result
}

function rosterShiftWindow(roster, shift) {
  const start = new Date(`${roster.work_date}T${shift.start_time}`)
  const end = new Date(`${roster.work_date}T${shift.end_time}`)
  if (end <= start) end.setDate(end.getDate() + 1)
  return { start, end }
}

function checkinMatchesRoster(checkin, roster, shift) {
  if (!checkin?.checkin_time || !roster || !shift) return false
  const checkinTime = new Date(checkin.checkin_time)
  if (Number.isNaN(checkinTime.getTime())) return false
  const { start, end } = rosterShiftWindow(roster, shift)
  start.setMinutes(start.getMinutes() - SHIFT_CHECKIN_GRACE_MINUTES)
  return start <= checkinTime && checkinTime < end
}

function formatShiftTime(value) {
  if (!value) return '—'
  const [hours, minutes] = value.split(':').map(Number)
  const date = new Date()
  date.setHours(hours, minutes, 0, 0)
  return date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

function buildLiveData(data) {
  const shifts = new Map(data.shifts.map((shift) => [shift.shift_id, shift]))
  const rosters = new Map()
  for (const roster of data.rosters) {
    const entries = rosters.get(roster.employee_id) || []
    entries.push(roster)
    rosters.set(roster.employee_id, entries)
  }
  const checkinsByEmployee = new Map()
  for (const checkin of data.checkins) {
    const entries = checkinsByEmployee.get(checkin.employee_id) || []
    entries.push(checkin)
    checkinsByEmployee.set(checkin.employee_id, entries)
  }
  const assignmentByWork = latestBy(data.assignments, 'work_id', 'assigned_at')
  const tasksById = new Map(data.taskTemplates.map((task) => [task.task_id, task]))
  const departments = new Map(data.departments.map((department) => [department.department_id, department.department_name]))
  const now = new Date()

  const staff = data.employees.map((employee) => {
    const entries = rosters.get(employee.employee_id) || []
    const currentEntries = entries
      .map((roster) => ({ roster, shift: shifts.get(roster.shift_id) }))
      .filter(({ shift }) => Boolean(shift))
      .filter(({ roster }) => ATTENDABLE_ROSTER_STATUSES.has(roster.roster_status))
      .filter(({ roster, shift }) => rosterShiftWindow(roster, shift).start <= now
        && now < rosterShiftWindow(roster, shift).end)
      .sort((a, b) => b.roster.roster_id - a.roster.roster_id)
    const upcomingEntries = entries
      .map((roster) => ({ roster, shift: shifts.get(roster.shift_id) }))
      .filter(({ shift }) => Boolean(shift))
      .filter(({ roster }) => ATTENDABLE_ROSTER_STATUSES.has(roster.roster_status))
      .filter(({ roster, shift }) => roster.work_date === localDateString()
        && rosterShiftWindow(roster, shift).start > now)
      .sort((a, b) => rosterShiftWindow(a.roster, a.shift).start - rosterShiftWindow(b.roster, b.shift).start)
    const selected = currentEntries[0] || upcomingEntries[0] || null
    const roster = selected?.roster
    const shift = selected?.shift || null
    const checkin = (checkinsByEmployee.get(employee.employee_id) || [])
      .filter((entry) => !roster || checkinMatchesRoster(entry, roster, shift))
      .sort((a, b) => String(b.checkin_time || '').localeCompare(String(a.checkin_time || '')))[0]
    const activeCheckin = checkin?.status === 'CHECKED_IN' && !checkin.checkout_time
    const availability = employee.availability || 'ACTIVE'
    let status = 'NOT SCHEDULED'
    if (availability === 'ON_LEAVE') status = 'ON_LEAVE'
    else if (availability !== 'ACTIVE') status = 'UNAVAILABLE'
    else if (activeCheckin) status = 'CHECKED IN'
    else if (checkin?.status === 'CHECKED_OUT' || checkin?.checkout_time) status = 'CHECKED_OUT'
    else if (roster?.roster_status === 'ABSENT') status = 'ABSENT'
    else if (roster?.roster_status === 'SCHEDULED') status = 'SCHEDULED'

    const activeTaskCount = data.assignments.filter((assignment) =>
      assignment.employee_id === employee.employee_id
      && ['PENDING', 'ASSIGNED', 'IN_PROGRESS'].includes(assignment.assignment_status),
    ).length
    const completedTaskCount = data.assignments.filter((assignment) =>
      assignment.employee_id === employee.employee_id
      && assignment.assignment_status === 'COMPLETED',
    ).length

    const currentAvailability = availability === 'ON_LEAVE'
      ? 'ON_LEAVE'
      : availability !== 'ACTIVE'
        ? 'UNAVAILABLE'
        : status === 'ABSENT'
          ? 'ABSENT'
          : status === 'CHECKED_OUT'
            ? 'CHECKED_OUT'
            : activeCheckin && currentEntries.length
              ? activeTaskCount > 0 ? 'BUSY' : 'AVAILABLE'
              : roster
                ? 'SCHEDULED'
                : 'UNAVAILABLE'

    return {
      id: employee.employee_id,
      name: employee.name,
      role: employee.role || '—',
      department: employee.department_name || departments.get(employee.department_id) || '—',
      skill: employee.skill || '—',
      experienceYears: employee.experience_years || 0,
      status,
      availability: currentAvailability,
      shiftName: shift?.shift_name || '—',
      shiftTime: shift ? `${formatShiftTime(shift.start_time)} – ${formatShiftTime(shift.end_time)}` : '—',
      checkinTime: checkin?.checkin_time || null,
      checkoutTime: checkin?.checkout_time || null,
      attendanceSource: checkin?.device_id?.startsWith('MANUAL_OVERRIDE_')
        || checkin?.device_id?.startsWith('CHECKIN_')
        ? 'DEMO / MANUAL OVERRIDE'
        : checkin ? 'ATTENDANCE DEVICE' : null,
      workDurationMinutes: checkin?.checkout_time && checkin?.checkin_time
        ? Math.max(0, Math.round((new Date(checkin.checkout_time) - new Date(checkin.checkin_time)) / 60000))
        : null,
      hasActiveCheckin: activeCheckin,
      rosterStatus: roster?.roster_status || null,
      rosterId: roster?.roster_id || null,
      activeTaskCount,
      completedTaskCount,
    }
  })

  const tasks = data.workQueue.map((work) => {
    const assignment = assignmentByWork.get(work.work_id)
    const employee = assignment
      ? data.employees.find((person) => person.employee_id === assignment.employee_id)
      : null
    const staffMember = assignment
      ? staff.find((person) => person.id === assignment.employee_id)
      : null
    const template = tasksById.get(work.task_id)
    return {
      id: work.work_id,
      name: template?.task_name || `Work item ${work.work_id}`,
      description: template?.description || '',
      skill: template?.required_skill || '',
      requiresProof: Boolean(template?.requires_proof),
      department: departments.get(work.department_id) || '—',
      priority: work.priority || template?.priority_category || '—',
      status: assignment?.assignment_status || work.queue_status || 'UNKNOWN',
      assignedEmployee: employee?.name || null,
      employeeId: assignment?.employee_id || null,
      shiftName: work.shift_id
        ? shifts.get(work.shift_id)?.shift_name || staffMember?.shiftName || '—'
        : staffMember?.shiftName || '—',
      dueDate: work.due_date,
      createdAt: work.created_at,
      assignedAt: assignment?.assigned_at || null,
      completedAt: assignment?.completed_at || null,
      queueStatus: work.queue_status,
      proofStatus: work.verification_status,
      proofConfidence: work.verification_confidence,
      proofRationale: work.verification_rationale,
      proofEmployeeId: work.proof_employee_id,
      assignmentId: assignment?.assignment_id || null,
      assignment,
      work,
    }
  })

  const staffWithTasks = staff.map((person) => ({
    ...person,
    assignedTasks: tasks.filter((task) => task.employeeId === person.id),
  }))

  return { staff: staffWithTasks, tasks }
}

function buildAttendanceStaff(data, staff, attendanceDate) {
  const shifts = new Map(data.shifts.map((shift) => [shift.shift_id, shift]))
  const rosters = new Map()
  for (const roster of data.rosters) {
    const entries = rosters.get(roster.employee_id) || []
    entries.push(roster)
    rosters.set(roster.employee_id, entries)
  }

  return staff.map((person) => {
    const employeeCheckins = data.checkins.filter((entry) => entry.employee_id === person.id)
    const rosterCandidates = (rosters.get(person.id) || [])
      .filter((entry) => ATTENDABLE_ROSTER_STATUSES.has(entry.roster_status))
      .filter((entry) => {
        if (entry.work_date === attendanceDate) return true
        const shift = shifts.get(entry.shift_id)
        if (!shift || shift.end_time > shift.start_time) return false
        const nextWorkDate = new Date(`${entry.work_date}T00:00:00`)
        nextWorkDate.setDate(nextWorkDate.getDate() + 1)
        return localDateString(nextWorkDate) === attendanceDate
          && employeeCheckins.some((checkin) => (
            checkin.status === 'CHECKED_IN'
            && !checkin.checkout_time
            && checkinMatchesRoster(checkin, entry, shift)
          ))
      })
      .sort((left, right) => right.roster_id - left.roster_id)
    const activeCheckinRoster = rosterCandidates.find((entry) => {
      const shift = shifts.get(entry.shift_id)
      return shift && employeeCheckins.some((checkin) => (
        checkin.status === 'CHECKED_IN'
        && !checkin.checkout_time
        && checkinMatchesRoster(checkin, entry, shift)
      ))
    })
    const roster = activeCheckinRoster
      || rosterCandidates.find((entry) => entry.work_date === attendanceDate)
      || null
    const shift = roster ? shifts.get(roster.shift_id) : null
    const checkin = employeeCheckins
      .filter((entry) => roster && shift
        ? checkinMatchesRoster(entry, roster, shift)
        : entry.checkin_time && localDateString(new Date(entry.checkin_time)) === attendanceDate)
      .sort((left, right) => String(right.checkin_time || '').localeCompare(String(left.checkin_time || '')))[0]
    const hasActiveCheckin = checkin?.status === 'CHECKED_IN' && !checkin.checkout_time
    let status = 'NOT SCHEDULED'
    if (person.status === 'ON_LEAVE') status = 'ON_LEAVE'
    else if (person.availability === 'UNAVAILABLE') status = 'UNAVAILABLE'
    else if (hasActiveCheckin) status = 'CHECKED IN'
    else if (checkin?.status === 'CHECKED_OUT' || checkin?.checkout_time) status = 'CHECKED_OUT'
    else if (roster?.roster_status === 'ABSENT') status = 'ABSENT'
    else if (roster?.roster_status === 'SCHEDULED') status = 'SCHEDULED'

    const availability = status === 'ON_LEAVE' || status === 'UNAVAILABLE'
      ? status
      : status === 'ABSENT'
        ? 'ABSENT'
        : status === 'CHECKED_OUT'
          ? 'CHECKED_OUT'
          : hasActiveCheckin
            ? person.activeTaskCount > 0 ? 'BUSY' : 'AVAILABLE'
            : roster ? 'SCHEDULED' : 'UNAVAILABLE'

    return {
      ...person,
      status,
      availability,
      shiftName: shift?.shift_name || '—',
      shiftTime: shift ? `${formatShiftTime(shift.start_time)} – ${formatShiftTime(shift.end_time)}` : '—',
      checkinTime: checkin?.checkin_time || null,
      checkoutTime: checkin?.checkout_time || null,
      attendanceSource: checkin?.device_id?.startsWith('MANUAL_OVERRIDE_')
        || checkin?.device_id?.startsWith('CHECKIN_')
        ? 'DEMO / MANUAL OVERRIDE'
        : checkin ? 'ATTENDANCE DEVICE' : null,
      workDurationMinutes: checkin?.checkout_time && checkin?.checkin_time
        ? Math.max(0, Math.round((new Date(checkin.checkout_time) - new Date(checkin.checkin_time)) / 60000))
        : null,
      hasActiveCheckin,
      canCheckIn: Boolean(
        roster
        && CHECKIN_ELIGIBLE_ROSTER_STATUSES.has(roster.roster_status)
        && !hasActiveCheckin
        && person.status !== 'ON_LEAVE'
        && person.availability !== 'UNAVAILABLE',
      ),
      rosterStatus: roster?.roster_status || null,
      rosterId: roster?.roster_id || null,
    }
  })
}

function monthDates(month) {
  const [year, monthNumber] = month.split('-').map(Number)
  const daysInMonth = new Date(year, monthNumber, 0).getDate()
  return Array.from({ length: daysInMonth }, (_, index) => {
    const date = new Date(year, monthNumber - 1, index + 1)
    return {
      value: localDateString(date),
      day: date.getDate(),
      weekday: date.toLocaleDateString(undefined, { weekday: 'short' }),
    }
  })
}

function exactTime(value) {
  if (!value) return null
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return null
  return new Intl.DateTimeFormat(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23',
  }).format(date)
}

function monthlyShiftWindow(roster, shift) {
  if (!shift?.start_time || !shift?.end_time) return null
  const start = new Date(`${roster.work_date}T${shift.start_time}`)
  const end = new Date(`${roster.work_date}T${shift.end_time}`)
  if (end <= start) end.setDate(end.getDate() + 1)
  return { start, end }
}

function attendanceCodeForCheckin(checkin, roster, shift) {
  const window = monthlyShiftWindow(roster, shift)
  const checkinTime = new Date(checkin.checkin_time)
  const graceEnd = new Date(window.start.getTime() + SHIFT_CHECKIN_GRACE_MINUTES * 60000)
  const halfDayEnd = new Date(window.start.getTime() + 2 * 60 * 60000)

  if (checkinTime <= graceEnd) return 'P'
  if (checkinTime <= halfDayEnd) return 'L'
  return 'Z'
}

function buildMonthlyAttendanceRows(data, month) {
  if (!data) return []

  const days = monthDates(month)
  const shifts = new Map(data.shifts.map((shift) => [shift.shift_id, shift]))
  const rostersByDay = new Map()
  for (const roster of data.rosters) {
    const key = `${roster.employee_id}|${roster.work_date}`
    const entries = rostersByDay.get(key) || []
    entries.push(roster)
    rostersByDay.set(key, entries)
  }

  const now = new Date()
  const today = localDateString(now)
  const checkinsByRoster = new Map()
  for (const checkin of data.checkins) {
    if (!checkin.checkin_time) continue
    const checkinTime = new Date(checkin.checkin_time)
    if (Number.isNaN(checkinTime.getTime())) continue
    const candidates = data.rosters
      .filter((roster) => roster.employee_id === checkin.employee_id && roster.roster_status !== 'CANCELLED')
      .map((roster) => ({ roster, shift: shifts.get(roster.shift_id) }))
      .filter(({ shift }) => Boolean(shift))
      .map(({ roster, shift }) => ({
        roster,
        window: monthlyShiftWindow(roster, shift),
      }))
    const active = candidates
      .filter(({ window }) => window.start <= checkinTime && checkinTime < window.end)
      .sort((left, right) => right.roster.roster_id - left.roster.roster_id)
    const upcoming = candidates
      .filter(({ roster, window }) => (
        roster.work_date === localDateString(checkinTime)
        && checkinTime < window.start
      ))
      .sort((left, right) => left.window.start - right.window.start)
    const selected = active[0] || upcoming[0]
    if (!selected) continue
    const entries = checkinsByRoster.get(selected.roster.roster_id) || []
    entries.push(checkin)
    checkinsByRoster.set(selected.roster.roster_id, entries)
  }

  return data.employees
    .map((employee) => ({
      ...employee,
      days: days.map((day) => {
        const key = `${employee.employee_id}|${day.value}`
        const rosters = (rostersByDay.get(key) || [])
          .map((roster) => ({ roster, shift: shifts.get(roster.shift_id) }))
          .filter(({ shift }) => Boolean(shift))
          .sort((left, right) => left.shift.start_time.localeCompare(right.shift.start_time))
        const shiftEntries = rosters.map(({ roster, shift }) => {
          const window = monthlyShiftWindow(roster, shift)
          const rosterCheckins = (checkinsByRoster.get(roster.roster_id) || [])
            .slice()
            .sort((left, right) => String(left.checkin_time).localeCompare(String(right.checkin_time)))
          const checkin = rosterCheckins[0] || null
          let code = ''

          if (checkin) {
            code = attendanceCodeForCheckin(checkin, roster, shift)
          } else if (roster.roster_status === 'HALF_DAY') {
            code = 'Z'
          } else if (roster.roster_status !== 'CANCELLED') {
            const absentCutoff = new Date(window.start.getTime() + 2 * 60 * 60000)
            if (day.value < today && window.end <= now) code = 'A'
            else if (day.value === today && now >= absentCutoff) code = 'A'
          }

          return {
            shiftName: shift.shift_name,
            code,
            checkins: rosterCheckins.map((entry) => ({
              checkin: exactTime(entry.checkin_time),
              checkout: exactTime(entry.checkout_time),
            })),
          }
        })

        if (!shiftEntries.length) {
          shiftEntries.push({
            shiftName: 'No shift',
            code: '',
            checkins: [],
          })
        }

        return {
          ...day,
          holiday: MAHARASHTRA_HOLIDAYS_2026.find((holiday) => holiday.date === day.value) || null,
          shiftEntries,
        }
      }),
    }))
    .sort((left, right) => left.name.localeCompare(right.name))
}

function buildHolidayAttendanceRows(data) {
  if (!data) return []

  const presentDatesByEmployee = new Map()
  for (const checkin of data.checkins) {
    if (!checkin.checkin_time) continue
    const date = localDateString(new Date(checkin.checkin_time))
    if (!MAHARASHTRA_HOLIDAY_DATES_2026.has(date)) continue
    const dates = presentDatesByEmployee.get(checkin.employee_id) || new Set()
    dates.add(date)
    presentDatesByEmployee.set(checkin.employee_id, dates)
  }

  return data.employees
    .map((employee) => ({
      ...employee,
      holidayDates: [...(presentDatesByEmployee.get(employee.employee_id) || [])].sort(),
    }))
    .map((employee) => ({ ...employee, holidayCount: employee.holidayDates.length }))
    .sort((left, right) => (
      right.holidayCount - left.holidayCount || left.name.localeCompare(right.name)
    ))
}

function groupStaffByDepartment(staffRows) {
  const groups = new Map()
  for (const staffRow of staffRows) {
    const department = staffRow.department_name || 'Unassigned department'
    const rows = groups.get(department) || []
    rows.push(staffRow)
    groups.set(department, rows)
  }
  return [...groups.entries()].sort(([left], [right]) => left.localeCompare(right))
}

export default function StaffAutomation() {
  const [tab, setTab] = useState('overview')
  const [snapshot, setSnapshot] = useState(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [actionError, setActionError] = useState('')
  const [working, setWorking] = useState(false)
  const [toast, setToast] = useState('')
  const [staffFilter, setStaffFilter] = useState('All')
  const [attendanceDepartmentFilter, setAttendanceDepartmentFilter] = useState('All departments')
  const [attendanceSearch, setAttendanceSearch] = useState('')
  const [attendanceDate, setAttendanceDate] = useState(localDateString())
  const [attendanceMonth, setAttendanceMonth] = useState(() => localDateString().slice(0, 7))
  const [monthlyDepartmentFilter, setMonthlyDepartmentFilter] = useState('All departments')
  const [monthlyAttendance, setMonthlyAttendance] = useState(null)
  const [monthlyAttendanceLoading, setMonthlyAttendanceLoading] = useState(false)
  const [monthlyAttendanceError, setMonthlyAttendanceError] = useState('')
  const [monthlyAttendanceRefresh, setMonthlyAttendanceRefresh] = useState(0)
  const [holidayDepartmentFilter, setHolidayDepartmentFilter] = useState('All departments')
  const [holidayAttendance, setHolidayAttendance] = useState(null)
  const [holidayAttendanceLoading, setHolidayAttendanceLoading] = useState(false)
  const [holidayAttendanceError, setHolidayAttendanceError] = useState('')
  const [holidayAttendanceRefresh, setHolidayAttendanceRefresh] = useState(0)
  const [workloadFilter, setWorkloadFilter] = useState('All staff')
  const [workloadDepartmentFilter, setWorkloadDepartmentFilter] = useState('All departments')
  const [workloadSearch, setWorkloadSearch] = useState('')
  const [taskFilter, setTaskFilter] = useState('All')
  const [emergencyOpen, setEmergencyOpen] = useState(false)
  const [checkoutPerson, setCheckoutPerson] = useState(null)
  const [proofUploadStatus, setProofUploadStatus] = useState({})
  const [templateFormOpen, setTemplateFormOpen] = useState(false)
  const [editingTemplate, setEditingTemplate] = useState(null)
  const [ruleEffectiveness, setRuleEffectiveness] = useState({})

  const load = useCallback(async () => {
    setLoadError('')
    try {
      const result = await fetchStaffAutomationData(attendanceDate)
      setSnapshot(result)
    } catch (error) {
      setLoadError(error.message || 'Unable to load Staff Automation data.')
    } finally {
      setLoading(false)
    }
  }, [attendanceDate])

  useEffect(() => {
    load()
    const interval = window.setInterval(() => {
      if (!document.hidden) load()
    }, 30000)
    return () => window.clearInterval(interval)
  }, [load])

  useEffect(() => {
    if (tab !== 'monthlyAttendance') return undefined

    let active = true
    const refresh = async () => {
      setMonthlyAttendanceLoading(true)
      setMonthlyAttendanceError('')
      try {
        const result = await fetchMonthlyAttendance(attendanceMonth)
        if (active) setMonthlyAttendance({ month: attendanceMonth, data: result })
      } catch (error) {
        if (active) setMonthlyAttendanceError(error.message || 'Unable to load monthly attendance.')
      } finally {
        if (active) setMonthlyAttendanceLoading(false)
      }
    }

    refresh()
    const interval = window.setInterval(() => {
      if (!document.hidden) refresh()
    }, 30000)
    return () => {
      active = false
      window.clearInterval(interval)
    }
  }, [tab, attendanceMonth, monthlyAttendanceRefresh])

  useEffect(() => {
    if (tab !== 'holidayCount') return undefined

    let active = true
    const refresh = async () => {
      setHolidayAttendanceLoading(true)
      setHolidayAttendanceError('')
      try {
        const result = await fetchHolidayAttendance(2026)
        if (active) setHolidayAttendance(result)
      } catch (error) {
        if (active) setHolidayAttendanceError(error.message || 'Unable to load holiday attendance.')
      } finally {
        if (active) setHolidayAttendanceLoading(false)
      }
    }

    refresh()
    const interval = window.setInterval(() => {
      if (!document.hidden) refresh()
    }, 30000)
    return () => {
      active = false
      window.clearInterval(interval)
    }
  }, [tab, holidayAttendanceRefresh])

  useEffect(() => {
    if (!toast) return undefined
    const timeout = window.setTimeout(() => setToast(''), 3500)
    return () => window.clearTimeout(timeout)
  }, [toast])

  const live = useMemo(() => snapshot ? buildLiveData(snapshot) : { staff: [], tasks: [] }, [snapshot])
  const staff = live.staff
  const tasks = live.tasks
  const attendanceStaff = useMemo(
    () => snapshot ? buildAttendanceStaff(snapshot, staff, attendanceDate) : [],
    [snapshot, staff, attendanceDate],
  )
  const monthlyDays = useMemo(() => monthDates(attendanceMonth), [attendanceMonth])
  const monthlyAttendanceData = monthlyAttendance?.month === attendanceMonth
    ? monthlyAttendance.data
    : null
  const monthlyDepartments = useMemo(
    () => [...new Set((monthlyAttendanceData?.employees || [])
      .map((employee) => employee.department_name)
      .filter(Boolean))].sort((left, right) => left.localeCompare(right)),
    [monthlyAttendanceData],
  )
  const monthlyAttendanceRows = useMemo(
    () => buildMonthlyAttendanceRows(monthlyAttendanceData, attendanceMonth)
      .filter((employee) => monthlyDepartmentFilter === 'All departments'
        || employee.department_name === monthlyDepartmentFilter),
    [monthlyAttendanceData, attendanceMonth, monthlyDepartmentFilter],
  )
  const monthlyAttendanceGroups = useMemo(
    () => groupStaffByDepartment(monthlyAttendanceRows),
    [monthlyAttendanceRows],
  )
  const monthlyAttendanceSummary = useMemo(() => {
    const summary = monthlyAttendanceRows
      .flatMap((employee) => employee.days.flatMap((day) => day.shiftEntries))
      .reduce((counts, shift) => {
        if (shift.code) counts[shift.code] = (counts[shift.code] || 0) + 1
        return counts
      }, { P: 0, A: 0, H: 0, L: 0, Z: 0 })
    summary.H = monthlyAttendanceRows
      .reduce((total, employee) => total + employee.days.filter((day) => day.holiday).length, 0)
    return summary
  }, [monthlyAttendanceRows])
  const holidayDepartments = useMemo(
    () => [...new Set((holidayAttendance?.employees || [])
      .map((employee) => employee.department_name)
      .filter(Boolean))].sort((left, right) => left.localeCompare(right)),
    [holidayAttendance],
  )
  const holidayAttendanceRows = useMemo(
    () => buildHolidayAttendanceRows(holidayAttendance)
      .filter((employee) => holidayDepartmentFilter === 'All departments'
        || employee.department_name === holidayDepartmentFilter),
    [holidayAttendance, holidayDepartmentFilter],
  )
  const holidayAttendanceGroups = useMemo(
    () => groupStaffByDepartment(holidayAttendanceRows),
    [holidayAttendanceRows],
  )
  const holidayStaffByDate = useMemo(() => {
    const result = new Map(MAHARASHTRA_HOLIDAYS_2026.map((holiday) => [holiday.date, new Set()]))
    for (const checkin of holidayAttendance?.checkins || []) {
      if (!checkin.checkin_time) continue
      const date = localDateString(new Date(checkin.checkin_time))
      if (result.has(date)) result.get(date).add(checkin.employee_id)
    }
    return result
  }, [holidayAttendance])
  const totalHolidayWorkCredits = holidayAttendanceRows
    .reduce((total, employee) => total + employee.holidayCount, 0)
  const attendanceDepartments = [...new Set(attendanceStaff.map((person) => person.department).filter(Boolean))]
    .sort((first, second) => first.localeCompare(second))
  const workloadDepartments = [...new Set(staff.map((person) => person.department).filter(Boolean))]
    .sort((first, second) => first.localeCompare(second))
  const filteredStaff = attendanceStaff.filter((person) => {
    const matchesStatus = staffFilter === 'All' || person.status === staffFilter
    const matchesDepartment = attendanceDepartmentFilter === 'All departments'
      || person.department === attendanceDepartmentFilter
    const query = attendanceSearch.trim().toLowerCase()
    const matchesSearch = !query || [
      person.name,
      person.id,
      person.role,
      person.department,
      person.shiftName,
      person.skill,
    ].some((value) => String(value || '').toLowerCase().includes(query))
    return matchesStatus && matchesDepartment && matchesSearch
  })
  const filteredWorkloadStaff = staff.filter((person) => {
    const matchesDepartment = workloadDepartmentFilter === 'All departments'
      || person.department === workloadDepartmentFilter
    const query = workloadSearch.trim().toLowerCase()
    const matchesSearch = !query || [
      person.name,
      person.id,
      person.role,
      person.department,
      person.skill,
    ].some((value) => String(value || '').toLowerCase().includes(query))
    const matchesFilter = workloadFilter === 'All staff'
      || (workloadFilter === 'With active tasks' && person.activeTaskCount > 0)
      || (workloadFilter === 'No active tasks' && person.activeTaskCount === 0)
    return matchesDepartment && matchesSearch && matchesFilter
  })
  const attendanceSummary = {
    checkedIn: attendanceStaff.filter((person) => person.status === 'CHECKED IN').length,
    scheduled: attendanceStaff.filter((person) => person.status === 'SCHEDULED').length,
    absent: attendanceStaff.filter((person) => person.status === 'ABSENT').length,
    checkedOut: attendanceStaff.filter((person) => person.status === 'CHECKED_OUT').length,
  }
  const filteredTasks = tasks.filter((task) => taskFilter === 'All' || task.status === taskFilter)
  const activeTasks = tasks.filter((task) => !['COMPLETED', 'CANCELLED'].includes(task.status))
  const completedTasks = tasks.filter((task) => task.status === 'COMPLETED')
  const overdueTasks = activeTasks.filter((task) => task.dueDate && new Date(task.dueDate) < new Date())
  const presentStaff = staff.filter((person) => person.status === 'PRESENT').length
  const absentStaff = staff.filter((person) => person.status === 'ABSENT').length
  const completionRate = tasks.length ? Math.round(completedTasks.length / tasks.length * 100) : 0

  const perform = async (operation, successMessage) => {
    setWorking(true)
    setActionError('')
    try {
      const result = await operation()
      setToast(typeof successMessage === 'function' ? successMessage(result) : successMessage)
      await load()
      return true
    } catch (error) {
      setActionError(error.message || 'The operation failed.')
      return false
    } finally {
      setWorking(false)
    }
  }

  const handleCheckin = (person) => perform(
    () => submitStaffCheckin(person.id, attendanceDate),
    `Demo/manual check-in workflow completed for ${person.name}.`,
  )

  const handleCheckout = async (person, incompleteTaskAction) => {
    const result = await perform(
      () => submitStaffCheckout(person.id, attendanceDate, incompleteTaskAction),
      (checkout) => {
        const reassigned = checkout.reassigned_work_ids?.length || 0
        const pending = checkout.pending_work_ids?.length || 0
        return `Demo/manual check-out recorded for ${person.name}. ${reassigned} task(s) reassigned; ${pending} left pending.`
      },
    )
    if (result) setCheckoutPerson(null)
  }

  const handleTaskComplete = (task) => perform(
    () => completeAssignedTask(task.id),
    `Task ${task.id} completed through the Task Management workflow.`,
  )

  const handleProofUpload = async (task, event) => {
    const file = event.currentTarget.files?.[0]
    event.currentTarget.value = ''
    if (!file) return

    setProofUploadStatus((current) => ({ ...current, [task.id]: 'Uploading proof…' }))
    const uploaded = await perform(
      () => submitTaskProof(task.id, file),
      'Proof uploaded to the backend. Verification is running.',
    )
    if (!uploaded) {
      setProofUploadStatus((current) => ({ ...current, [task.id]: 'Upload failed.' }))
      return
    }

    setProofUploadStatus((current) => ({ ...current, [task.id]: 'Verification pending…' }))
    try {
      let workItem
      for (let attempt = 0; attempt < 10; attempt += 1) {
        workItem = await fetchWorkItem(task.id)
        if (['VERIFIED', 'REJECTED'].includes(workItem.verification_status)) break
        await new Promise((resolve) => setTimeout(resolve, 1000))
      }
      const status = workItem?.verification_status || 'PENDING'
      const message = status === 'VERIFIED'
        ? `${workItem.verification_rationale?.startsWith('DEMO_MODE') ? 'Demo verification' : 'Verification'} completed: proof verified${workItem.verification_confidence == null ? '' : ` (${Math.round(workItem.verification_confidence * 100)}% confidence)`}.`
        : status === 'REJECTED'
          ? `Proof verification rejected: ${workItem.verification_rationale || 'Please upload new evidence.'}`
          : 'Proof was stored; verification is still pending. Refresh the task later to check its result.'
      setProofUploadStatus((current) => ({ ...current, [task.id]: message }))
      setToast(message)
      await load()
    } catch (error) {
      setActionError(error.message || 'Unable to read the proof verification result.')
      setProofUploadStatus((current) => ({ ...current, [task.id]: 'Proof submitted; status could not be refreshed.' }))
    }
  }

  const handlePatternAnalysis = () => perform(
    () => analyzeShiftReportPatterns(),
    'Historical pattern analysis completed. New recommendations require supervisor review.',
  )

  const handleExpireRules = () => perform(
    () => expireAutomationRules(),
    'Expired rules were disabled and recorded in the lifecycle audit.',
  )

  const handleCreateAutomationRule = async (event, recommendation) => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const expiresAt = String(form.get('expires_at') || '')
    await perform(
      () => createAutomationRule(recommendation.recommendation_id, {
        task_id: Number(form.get('task_id')),
        priority: String(form.get('priority') || '') || null,
        due_offset: String(form.get('due_offset')),
        expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
        review_notes: String(form.get('review_notes') || '').trim() || null,
      }),
      'A pending rule was created. It will not run until an employee-linked supervisor approves it.',
    )
  }

  const handleAutomationRuleEdit = async (event, rule) => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const expiresAt = String(form.get('expires_at') || '')
    await perform(
      () => updateAutomationRule(rule.rule_id, {
        task_id: Number(form.get('task_id')),
        priority: String(form.get('priority') || '') || null,
        due_offset: String(form.get('due_offset')),
        expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
      }),
      'Pending rule updated and audit logged.',
    )
  }

  const handleRuleEffectiveness = async (ruleId) => {
    setWorking(true)
    setActionError('')
    try {
      const result = await fetchAutomationRuleEffectiveness(ruleId)
      setRuleEffectiveness((previous) => ({ ...previous, [ruleId]: result }))
    } catch (error) {
      setActionError(error.message || 'Unable to load automation rule effectiveness.')
    } finally {
      setWorking(false)
    }
  }

  const handleTemplateSubmit = async (event) => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const template = {
      task_name: String(form.get('task_name') || '').trim(),
      description: String(form.get('description') || '').trim() || null,
      department_id: form.get('department_id') ? Number(form.get('department_id')) : null,
      priority_category: form.get('priority_category'),
      task_type: form.get('task_type'),
      required_role: String(form.get('required_role') || '').trim() || null,
      required_skill: String(form.get('required_skill') || '').trim() || null,
      estimated_time: form.get('estimated_time') ? Number(form.get('estimated_time')) : null,
      suggested_start_time: String(form.get('suggested_start_time') || '') || null,
      due_time: String(form.get('due_time') || '') || null,
      requires_proof: form.get('requires_proof') === 'on',
    }
    const saved = await perform(
      () => editingTemplate
        ? updateTaskTemplate(editingTemplate.task_id, template)
        : createTaskTemplate(template),
      editingTemplate ? 'Task template updated.' : 'Task template created.',
    )
    if (saved) {
      setTemplateFormOpen(false)
      setEditingTemplate(null)
    }
  }

  const handleReportSubmit = async (event) => {
    event.preventDefault()
    const formElement = event.currentTarget
    const form = new FormData(formElement)
    const nurseName = String(form.get('nurse_name') || '').trim()
    const shiftDate = String(form.get('shift_date') || '')
    const shiftName = String(form.get('shift_name') || '').trim()
    const wardArea = String(form.get('ward_area') || '').trim()
    const answers = {
      [SHIFT_LOG_KEYS.nurseName]: nurseName,
      [SHIFT_LOG_KEYS.date]: shiftDate,
      [SHIFT_LOG_KEYS.shift]: shiftName,
      [SHIFT_LOG_KEYS.ward]: wardArea,
      [SHIFT_LOG_KEYS.patients]: String(form.get('patients') || ''),
      [SHIFT_LOG_KEYS.admission]: String(form.get('admission') || ''),
      [SHIFT_LOG_KEYS.discharge]: String(form.get('discharge') || ''),
      [SHIFT_LOG_KEYS.critical]: String(form.get('critical') || ''),
      [SHIFT_LOG_KEYS.shifted]: String(form.get('shifted') || ''),
      [SHIFT_LOG_KEYS.bedDetails]: String(form.get('bed_details') || ''),
      [SHIFT_LOG_KEYS.emergency]: String(form.get('emergency') || ''),
      [SHIFT_LOG_KEYS.emergencyType]: String(form.get('emergency_type') || ''),
      [SHIFT_LOG_KEYS.medication]: String(form.get('medication') || ''),
      [SHIFT_LOG_KEYS.delayReason]: String(form.get('delay_reason') || ''),
      [SHIFT_LOG_KEYS.clinicalIssue]: String(form.get('clinical_issue') || ''),
      [SHIFT_LOG_KEYS.issueDetails]: String(form.get('issue_details') || ''),
      [SHIFT_LOG_KEYS.procedures]: String(form.get('procedures') || ''),
      [SHIFT_LOG_KEYS.infection]: String(form.get('infection') || ''),
      [SHIFT_LOG_KEYS.biomedical]: String(form.get('biomedical') || ''),
      [SHIFT_LOG_KEYS.equipment]: String(form.get('equipment') || ''),
      [SHIFT_LOG_KEYS.equipmentName]: String(form.get('equipment_name') || ''),
      [SHIFT_LOG_KEYS.handover]: String(form.get('handover') || ''),
      [SHIFT_LOG_KEYS.pendingTasks]: String(form.get('pending_tasks') || ''),
      [SHIFT_LOG_KEYS.consumables]: String(form.get('consumables') || ''),
      [SHIFT_LOG_KEYS.staffing]: String(form.get('staffing') || ''),
      [SHIFT_LOG_KEYS.rating]: String(form.get('rating') || ''),
      [SHIFT_LOG_KEYS.concerns]: String(form.get('concerns') || ''),
    }
    const saved = await perform(
      () => createShiftReport({
        nurse_name: nurseName,
        shift_date: shiftDate,
        shift_name: shiftName,
        ward_area: wardArea,
        answers,
      }),
      'Shift report saved.',
    )
    if (saved) formElement.reset()
  }

  const handleEmergencySubmit = async (event) => {
    event.preventDefault()
    const formElement = event.currentTarget
    const form = new FormData(formElement)
    const result = await perform(
      () => createEmergency({
        emergency_type: String(form.get('emergency_type')),
        location: String(form.get('location') || '').trim(),
        reported_by: snapshot.currentUser.email,
      }),
      'Emergency workflow submitted to the backend.',
    )
    if (result) {
      setEmergencyOpen(false)
      formElement.reset()
    }
  }

  const renderLoadingOrError = () => {
    if (loading) return <section className="sa-panel" aria-live="polite">Loading live Staff Automation data…</section>
    if (loadError) {
      return (
        <section className="sa-panel" role="alert">
          <h2>Unable to load live Staff Automation data</h2>
          <p>{loadError}</p>
          <ActionButton onClick={load}>Retry</ActionButton>
        </section>
      )
    }
    return null
  }

  const renderOverview = () => {
    const analytics = snapshot.shiftAnalytics
    return <>
      <div className="sa-hero">
        <div>
          <span className="sa-eyebrow">LIVE OPERATIONS · {localDateString()}</span>
          <h2>Staff Automation</h2>
          <p>Check staff in or out. The automation agents handle the rest.</p>
        </div>
      </div>
      <div className="sa-stats-grid">
        {[
          ['group', 'Staff records', staff.length, 'Live employee database', 'blue'],
          ['how_to_reg', 'Checked in today', presentStaff, `${absentStaff} explicitly marked absent`, 'green'],
          ['assignment', 'Active work items', activeTasks.length, 'Live work queue', 'blue'],
          ['task_alt', 'Completed work items', completedTasks.length, `${completionRate}% of loaded work items`, 'green'],
          ['schedule', 'Overdue work items', overdueTasks.length, 'Calculated from recorded due times', 'red'],
          ['emergency', 'Critical work items', tasks.filter((task) => task.priority === 'CRITICAL').length, 'Live work queue priority', 'red'],
          ['summarize', 'Historical shift reports', analytics.total_records, 'Historical data only', 'amber'],
          ['monitor_heart', 'Historical average patients', analytics.average_patients_per_shift ?? '—', 'Patients per reported shift', 'amber'],
        ].map(([icon, label, value, note, color]) => (
          <div className={`sa-stat sa-stat-${color}`} key={label}>
            <div className="sa-stat-top"><span>{label}</span><Icon>{icon}</Icon></div>
            <strong>{value}</strong><small>{note}</small>
          </div>
        ))}
      </div>
      <section className="sa-panel">
        <div className="sa-panel-heading"><div><h3>Historical operations</h3><p>Imported reports are not current attendance or workload.</p></div></div>
        <div className="sa-workload-grid">
          <div className="sa-workload-tile"><strong>Emergency reports</strong><span>{analytics.emergency_occurrences} · {analytics.emergency_rate_percent}%</span></div>
          <div className="sa-workload-tile"><strong>Medication delays</strong><span>{analytics.medication_delay_occurrences} · {analytics.medication_delay_rate_percent}%</span></div>
          <div className="sa-workload-tile"><strong>Equipment issues</strong><span>{analytics.equipment_issue_occurrences} · {analytics.equipment_issue_rate_percent}%</span></div>
          <div className="sa-workload-tile"><strong>Handover issues</strong><span>{analytics.handover_issue_occurrences} · {analytics.handover_issue_rate_percent}%</span></div>
        </div>
      </section>
    </>
  }

  const renderWorkload = () => {
    const activeAssignmentCount = staff.reduce((total, person) => total + person.activeTaskCount, 0)
    const staffWithWork = staff.filter((person) => person.activeTaskCount > 0).length
    const unassignedCount = tasks.filter((task) => task.status === 'PENDING_ASSIGNED').length

    return <>
      <div className="sa-page-heading">
        <div><h2>Live task workload</h2><p>See active assignments by staff member and review task details from the live work queue.</p></div>
      </div>
      <div className="sa-stats-grid sa-workload-summary">
        {[
          ['assignment', 'Active assignments', activeAssignmentCount, 'Currently assigned or in progress', 'blue'],
          ['group', 'Staff with active work', staffWithWork, `of ${staff.length} staff members`, 'green'],
          ['hourglass_top', 'Awaiting assignment', unassignedCount, 'Pending in the live work queue', 'amber'],
          ['task_alt', 'Completed assignments', staff.reduce((total, person) => total + person.completedTaskCount, 0), 'Recorded across staff', 'blue'],
        ].map(([icon, label, value, note, color]) => (
          <div className={`sa-stat sa-stat-${color}`} key={label}>
            <div className="sa-stat-top"><span>{label}</span><Icon>{icon}</Icon></div>
            <strong>{value}</strong><small>{note}</small>
          </div>
        ))}
      </div>
      <section className="sa-panel sa-workload-panel">
        <div className="sa-panel-heading sa-workload-toolbar">
          <div><h3>Staff workload <span className="sa-count">{filteredWorkloadStaff.length}</span></h3><p>Workload refreshes with the live Staff Automation data.</p></div>
          <div className="sa-workload-filters">
            <label className="sa-search-field">
              <Icon>search</Icon>
              <input
                type="search"
                value={workloadSearch}
                onChange={(event) => setWorkloadSearch(event.target.value)}
                placeholder="Search staff, role, or skill"
                aria-label="Search workload staff"
              />
            </label>
            <select className="sa-department-filter" value={workloadDepartmentFilter} onChange={(event) => setWorkloadDepartmentFilter(event.target.value)} aria-label="Filter workload department">
              <option>All departments</option>
              {workloadDepartments.map((department) => <option key={department}>{department}</option>)}
            </select>
            <select value={workloadFilter} onChange={(event) => setWorkloadFilter(event.target.value)} aria-label="Filter workload staff">
              {['All staff', 'With active tasks', 'No active tasks'].map((value) => <option key={value}>{value}</option>)}
            </select>
          </div>
        </div>
        {filteredWorkloadStaff.length ? <div className="sa-workload-grid sa-live-workload-grid">
          {filteredWorkloadStaff.map((person) => (
            <article className="sa-workload-card" key={person.id}>
              <div className="sa-workload-card-header">
                <span className="sa-avatar">{person.name.split(/\s+/).map((part) => part[0]).join('').slice(0, 2)}</span>
                <div className="sa-workload-person">
                  <strong>{person.name}</strong>
                  <span>{person.role} <i>·</i> {person.department}</span>
                </div>
                <StatusPill value={person.availability} />
              </div>
              <div className="sa-workload-card-metrics">
                <div><strong>{person.activeTaskCount}</strong><span>Active tasks</span></div>
                <div><strong>{person.completedTaskCount}</strong><span>Completed</span></div>
                <div><strong>{person.experienceYears}</strong><span>Years exp.</span></div>
              </div>
              <div className="sa-workload-skills"><Icon>psychology</Icon><span>{person.skill || 'No skills listed'}</span></div>
              {person.assignedTasks.length ? <details className="sa-workload-details">
                <summary><span>View assigned tasks</span><span>{person.assignedTasks.length}</span></summary>
                <ul className="sa-dashboard-task-list">
                  {person.assignedTasks.map((task) => (
                    <li key={task.id}>
                      <span>{task.name}</span>
                      <StatusPill value={task.status} />
                      <small>{task.skill ? `Required skill: ${task.skill} · ` : ''}Due {displayDateTime(task.dueDate)}</small>
                    </li>
                  ))}
                </ul>
              </details> : <p className="sa-workload-empty"><Icon>check_circle</Icon>No active assignments</p>}
            </article>
          ))}
        </div> : <div className="sa-empty">{staff.length ? 'No staff match the selected search or filter.' : 'No staff records available.'}</div>}
      </section>
    </>
  }

  const renderAttendance = () => (
    <>
      {checkoutPerson && (() => {
        const incompleteTasks = checkoutPerson.assignedTasks.filter(
          (task) => ['ASSIGNED', 'IN_PROGRESS'].includes(task.status),
        )
        const pendingProofs = incompleteTasks.filter((task) => task.proofStatus === 'PENDING')
        return <div className="sa-modal-backdrop" role="presentation" onClick={(event) => {
          if (event.target === event.currentTarget && !working) setCheckoutPerson(null)
        }}>
          <section className="sa-modal" role="dialog" aria-modal="true" aria-labelledby="checkout-dialog-title">
            <div className="sa-modal-heading"><h2 id="checkout-dialog-title">Check out {checkoutPerson.name}</h2></div>
            {incompleteTasks.length
              ? <p>You have {incompleteTasks.length} incomplete task(s). {pendingProofs.length ? `${pendingProofs.length} task(s) are awaiting proof verification; checkout can continue.` : ''}</p>
              : <p>All assigned tasks are completed. Confirm checkout?</p>}
            {incompleteTasks.length > 0 && <ul className="sa-checkout-task-list">
              {incompleteTasks.map((task) => <li key={task.id}>{task.name} · {task.status}{task.proofStatus ? ` · proof ${task.proofStatus}` : ''}</li>)}
            </ul>}
            <div className="sa-modal-actions">
              {incompleteTasks.length > 0 && <ActionButton
                disabled={working}
                onClick={() => handleCheckout(checkoutPerson, 'REASSIGN')}
              >Reassign Tasks &amp; Check Out</ActionButton>}
              {incompleteTasks.length > 0 && <ActionButton
                secondary
                disabled={working}
                onClick={() => handleCheckout(checkoutPerson, 'KEEP_PENDING')}
              >Keep Tasks Pending</ActionButton>}
              {incompleteTasks.length === 0 && <ActionButton
                disabled={working}
                onClick={() => handleCheckout(checkoutPerson, 'REASSIGN')}
              >Confirm Check Out</ActionButton>}
              <ActionButton secondary disabled={working} onClick={() => setCheckoutPerson(null)}>Cancel</ActionButton>
            </div>
          </section>
        </div>
      })()}
      <div className="sa-page-heading">
        <div><h2>Staff attendance</h2><p>Monitor roster attendance and staff availability. Demo/manual check-in and check-out controls use the same attendance workflow as registered devices.</p></div>
        <a className="sa-link-button" href="/supervisor?tab=shifts">Manage roster</a>
      </div>
      <div className="sa-stats-grid sa-attendance-summary">
        {[
          ['how_to_reg', 'Checked in', attendanceSummary.checkedIn, 'Currently on shift', 'green'],
          ['schedule', 'Scheduled', attendanceSummary.scheduled, 'Awaiting check-in', 'blue'],
          ['person_off', 'Absent', attendanceSummary.absent, 'Marked absent', 'red'],
          ['logout', 'Checked out', attendanceSummary.checkedOut, 'Shift attendance recorded', 'amber'],
        ].map(([icon, label, value, note, color]) => (
          <div className={`sa-stat sa-stat-${color}`} key={label}>
            <div className="sa-stat-top"><span>{label}</span><Icon>{icon}</Icon></div>
            <strong>{value}</strong><small>{note}</small>
          </div>
        ))}
      </div>
      <section className="sa-panel">
        <div className="sa-panel-heading">
          <div>
            <h3>Daily roster <span className="sa-count">{filteredStaff.length}</span></h3>
            <p>Roster and attendance for {new Date(`${attendanceDate}T00:00:00`).toLocaleDateString()}.</p>
          </div>
          <div className="sa-attendance-controls">
            <label className="sa-attendance-date">
              <span>Attendance date</span>
              <input
                type="date"
                value={attendanceDate}
                max={localDateString()}
                onChange={(event) => {
                  if (event.target.value) setAttendanceDate(event.target.value)
                }}
                aria-label="Select attendance date"
              />
            </label>
            <label className="sa-field sa-attendance-department-filter"><span>Department</span>
              <select value={attendanceDepartmentFilter} onChange={(event) => setAttendanceDepartmentFilter(event.target.value)} aria-label="Filter attendance department">
                <option>All departments</option>
                {attendanceDepartments.map((department) => <option key={department}>{department}</option>)}
              </select>
            </label>
            <label className="sa-field sa-attendance-status-filter"><span>Attendance status</span>
              <select value={staffFilter} onChange={(event) => setStaffFilter(event.target.value)} aria-label="Filter staff status">
                {['All', ...new Set(attendanceStaff.map((person) => person.status))].map((value) => <option key={value}>{value}</option>)}
              </select>
            </label>
          </div>
        </div>
        <label className="sa-search-field sa-attendance-search">
          <Icon>search</Icon>
          <input
            type="search"
            value={attendanceSearch}
            onChange={(event) => setAttendanceSearch(event.target.value)}
            placeholder="Search by name, employee ID, department, or skill"
            aria-label="Search staff attendance"
          />
        </label>
        <div className="sa-table-wrap"><table className="sa-table sa-attendance-table">
          <thead><tr>{['Staff member', 'Shift', 'Attendance', 'Workload', 'Actions'].map((label) => <th key={label}>{label}</th>)}</tr></thead>
          <tbody>{filteredStaff.map((person) => (
            <tr className="sa-attendance-row" key={person.id}>
              <td className="sa-attendance-person-cell">
                <div className="sa-attendance-person">
                  <span className="sa-avatar">{person.name.split(/\s+/).map((part) => part[0]).join('').slice(0, 2)}</span>
                  <div><strong>{person.name}</strong><small>{person.role} · {person.department}</small><small>ID {person.id} · Skills: {person.skill}</small></div>
                </div>
              </td>
              <td><strong>{person.shiftName}</strong><small>{person.shiftTime}</small></td>
              <td><StatusPill value={person.status} />
                {person.checkinTime && <small className="sa-attendance-time">In {displayDateTime(person.checkinTime)}</small>}
                {person.checkoutTime && <small className="sa-attendance-time">Out {displayDateTime(person.checkoutTime)}</small>}
                {person.workDurationMinutes !== null && <small className="sa-attendance-time">Duration {Math.floor(person.workDurationMinutes / 60)}h {person.workDurationMinutes % 60}m</small>}
                {person.attendanceSource && <small className="sa-attendance-source">{person.attendanceSource}</small>}
              </td>
              <td>
                <span className="sa-attendance-task-count">{person.activeTaskCount}</span>
                <span className="sa-attendance-task-label">active task{person.activeTaskCount === 1 ? '' : 's'}</span>
                {person.assignedTasks.length > 0 && <details className="sa-attendance-task-details">
                  <summary>View tasks <span>{person.assignedTasks.length}</span></summary>
                  <ul className="sa-staff-task-list">
                    {person.assignedTasks.map((task) => (
                      <li key={task.id}>
                        <strong>{task.name}</strong>
                        <StatusPill value={task.status} />
                        <small>{task.skill ? `Skill: ${task.skill} · ` : ''}Due: {displayDateTime(task.dueDate)}</small>
                      </li>
                    ))}
                  </ul>
                </details>}
              </td>
              <td className="sa-attendance-actions">
                <ActionButton
                  disabled={working || !person.canCheckIn}
                  onClick={() => handleCheckin(person)}
                ><Icon>login</Icon>Check in</ActionButton>
                <ActionButton
                  secondary
                  disabled={working || !person.hasActiveCheckin}
                  onClick={() => setCheckoutPerson(person)}
                ><Icon>logout</Icon>Check out</ActionButton>
              </td>
            </tr>
          ))}</tbody>
        </table></div>
        {!filteredStaff.length && <div className="sa-empty">No staff records found.</div>}
      </section>
    </>
  )

  const renderMonthlyAttendance = () => {
    const monthLabel = new Date(`${attendanceMonth}-01T00:00:00`).toLocaleDateString(
      undefined,
      { month: 'long', year: 'numeric' },
    )

    return <>
      <div className="sa-page-heading">
        <div>
          <h2>Monthly attendance</h2>
          <p>Daily attendance codes and recorded check-in/check-out times for the selected month.</p>
        </div>
        <div className="sa-monthly-controls">
          <label className="sa-field">
            <span>Month</span>
            <input
              type="month"
              value={attendanceMonth}
              onChange={(event) => {
                if (event.target.value) setAttendanceMonth(event.target.value)
              }}
              aria-label="Select attendance month"
            />
          </label>
          <label className="sa-field sa-department-select">
            <span>Department</span>
            <select
              value={monthlyDepartmentFilter}
              onChange={(event) => setMonthlyDepartmentFilter(event.target.value)}
              aria-label="Filter monthly attendance by department"
            >
              <option>All departments</option>
              {monthlyDepartments.map((department) => <option key={department}>{department}</option>)}
            </select>
          </label>
          <ActionButton secondary onClick={() => setMonthlyAttendanceRefresh((value) => value + 1)}>
            <Icon>refresh</Icon>Refresh
          </ActionButton>
        </div>
      </div>
      {monthlyAttendanceError && <div className="sa-info-banner" role="alert">
        <Icon>error</Icon><span>{monthlyAttendanceError}</span>
        <button className="sa-link-button" onClick={() => setMonthlyAttendanceRefresh((value) => value + 1)}>Retry</button>
      </div>}
      <div className="sa-stats-grid sa-monthly-summary">
        {[
          ['P', 'Present', monthlyAttendanceSummary.P, 'green'],
          ['L', 'Late', monthlyAttendanceSummary.L, 'amber'],
          ['A', 'Absent', monthlyAttendanceSummary.A, 'red'],
          ['H', 'Holiday', monthlyAttendanceSummary.H, 'blue'],
          ['Z', 'Half time', monthlyAttendanceSummary.Z, 'amber'],
        ].map(([code, label, value, color]) => (
          <div className={`sa-stat sa-stat-${color}`} key={code}>
            <div className="sa-stat-top"><span>{label}</span><span className={`sa-monthly-code sa-monthly-code-${code.toLowerCase()}`}>{code}</span></div>
            <strong>{value}</strong><small>Staff-days in {monthLabel}</small>
          </div>
        ))}
      </div>
      <section className="sa-panel sa-monthly-panel">
        <div className="sa-panel-heading">
          <div>
            <h3>{monthLabel} attendance <span className="sa-count">{monthlyAttendanceRows.length} staff</span></h3>
            <p>Each shift is tracked separately. Future shifts stay blank until their start time; recorded times are shown in your local time.</p>
          </div>
          {monthlyAttendanceLoading && <span className="sa-monthly-loading" role="status">Refreshing…</span>}
        </div>
        <div className="sa-monthly-legend" aria-label="Attendance code legend">
          <span><b className="sa-monthly-code sa-monthly-code-p">P</b> Present</span>
          <span><b className="sa-monthly-code sa-monthly-code-l">L</b> Late</span>
          <span><b className="sa-monthly-code sa-monthly-code-a">A</b> Absent</span>
          <span><b className="sa-monthly-code sa-monthly-code-h">H</b> Maharashtra public holiday</span>
          <span><b className="sa-monthly-code sa-monthly-code-z">Z</b> Half time</span>
        </div>
        <div className="sa-monthly-table-wrap">
          <table className="sa-monthly-table">
            <thead>
              <tr>
                <th className="sa-monthly-staff-column">Staff member</th>
                <th className="sa-monthly-department-column">Department</th>
                {monthlyDays.map((day) => (
                  <th key={day.value} title={day.value}>
                    <span>{day.day}</span><small>{day.weekday}</small>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {monthlyAttendanceGroups.map(([department, employees]) => (
                <Fragment key={department}>
                  <tr className="sa-monthly-department-heading">
                    <th colSpan={monthlyDays.length + 2}>{department}<span>{employees.length} staff</span></th>
                  </tr>
                  {employees.map((employee) => (
                    <tr key={employee.employee_id}>
                      <th scope="row" className="sa-monthly-staff-column">
                        <strong>{employee.name}</strong>
                        <small>{employee.role} · ID {employee.employee_id}</small>
                      </th>
                      <td className="sa-monthly-department-column">{employee.department_name || '—'}</td>
                      {employee.days.map((day) => (
                        <td key={day.value} className="sa-monthly-day-cell">
                          {day.holiday && (
                            <span
                              className="sa-monthly-holiday"
                              title={`${day.holiday.name} · ${day.holiday.type}`}
                            >H</span>
                          )}
                          {day.shiftEntries.map((entry, index) => (
                            <div
                              className="sa-monthly-shift-entry"
                              key={`${day.value}-${entry.shiftName}-${index}`}
                              title={`${entry.shiftName}: ${entry.code || 'Not recorded'}${entry.checkins.map((times) => ` · In ${times.checkin || '—'} · Out ${times.checkout || '—'}`).join('')}`}
                            >
                              {day.shiftEntries.length > 1 && <small className="sa-monthly-shift-name">{entry.shiftName}</small>}
                              <span className={`sa-monthly-code${entry.code ? ` sa-monthly-code-${entry.code.toLowerCase()}` : ' sa-monthly-code-empty'}`}>
                                {entry.code || '—'}
                              </span>
                              {entry.checkins.map((times, timeIndex) => (
                                <span className="sa-monthly-times" key={`${day.value}-${entry.shiftName}-${timeIndex}`}>
                                  <small>In {times.checkin || '—'}</small>
                                  <small>Out {times.checkout || '—'}</small>
                                </span>
                              ))}
                            </div>
                          ))}
                        </td>
                      ))}
                    </tr>
                  ))}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
        {!monthlyAttendanceLoading && !monthlyAttendanceError && !monthlyAttendanceRows.length
          && <div className="sa-empty">No staff found for this department.</div>}
      </section>
    </>
  }

  const renderHolidayCount = () => {
    const workingStaff = holidayAttendanceRows.filter((employee) => employee.holidayCount > 0).length
    return <>
      <div className="sa-page-heading">
        <div>
          <h2>Holiday count · Maharashtra · 2026</h2>
          <p>One holiday-work credit per staff member for each listed holiday date with a recorded check-in.</p>
        </div>
        <div className="sa-monthly-controls">
          <label className="sa-field sa-department-select">
            <span>Department</span>
            <select
              value={holidayDepartmentFilter}
              onChange={(event) => setHolidayDepartmentFilter(event.target.value)}
              aria-label="Filter holiday count by department"
            >
              <option>All departments</option>
              {holidayDepartments.map((department) => <option key={department}>{department}</option>)}
            </select>
          </label>
          <ActionButton secondary onClick={() => setHolidayAttendanceRefresh((value) => value + 1)}>
            <Icon>refresh</Icon>Refresh
          </ActionButton>
        </div>
      </div>
      {holidayAttendanceError && <div className="sa-info-banner" role="alert">
        <Icon>error</Icon><span>{holidayAttendanceError}</span>
        <button className="sa-link-button" onClick={() => setHolidayAttendanceRefresh((value) => value + 1)}>Retry</button>
      </div>}
      <div className="sa-stats-grid sa-holiday-summary">
        {[
          ['Holiday dates', MAHARASHTRA_HOLIDAYS_2026.length, 'Maharashtra holidays in 2026', 'blue'],
          ['Staff who worked holidays', workingStaff, `of ${holidayAttendanceRows.length} filtered staff`, 'green'],
          ['Holiday-work credits', totalHolidayWorkCredits, 'One per employee per holiday date', 'amber'],
        ].map(([label, value, note, color]) => (
          <div className={`sa-stat sa-stat-${color}`} key={label}>
            <div className="sa-stat-top"><span>{label}</span><Icon>celebration</Icon></div>
            <strong>{value}</strong><small>{note}</small>
          </div>
        ))}
      </div>
      <section className="sa-panel sa-monthly-panel">
        <div className="sa-panel-heading">
          <div>
            <h3>Holiday work by staff <span className="sa-count">{holidayAttendanceRows.length}</span></h3>
            <p>A check-in on any listed holiday counts once for that staff member and date.</p>
          </div>
          {holidayAttendanceLoading && <span className="sa-monthly-loading" role="status">Refreshing…</span>}
        </div>
        <div className="sa-monthly-table-wrap">
          <table className="sa-monthly-table sa-holiday-count-table">
            <thead><tr><th className="sa-monthly-staff-column">Staff member</th><th className="sa-monthly-department-column">Department</th><th>Holiday days worked</th><th>Dates worked</th></tr></thead>
            <tbody>{holidayAttendanceGroups.map(([department, employees]) => (
              <Fragment key={department}>
                <tr className="sa-monthly-department-heading"><th colSpan={4}>{department}<span>{employees.length} staff</span></th></tr>
                {employees.map((employee) => (
                  <tr key={employee.employee_id}>
                    <th scope="row" className="sa-monthly-staff-column">
                      <strong>{employee.name}</strong>
                      <small>{employee.role} · ID {employee.employee_id}</small>
                    </th>
                    <td className="sa-monthly-department-column">{employee.department_name || '—'}</td>
                    <td><strong>{employee.holidayCount}</strong> / {MAHARASHTRA_HOLIDAYS_2026.length}</td>
                    <td className="sa-holiday-worked-dates">
                      {employee.holidayDates.length
                        ? employee.holidayDates.map((date) => {
                          const holiday = MAHARASHTRA_HOLIDAYS_2026.find((entry) => entry.date === date)
                          return <span key={date}>{new Date(`${date}T00:00:00`).toLocaleDateString()} · {holiday?.name}</span>
                        })
                        : <span>None recorded</span>}
                    </td>
                  </tr>
                ))}
              </Fragment>
            ))}</tbody>
          </table>
        </div>
        {!holidayAttendanceLoading && !holidayAttendanceError && !holidayAttendanceRows.length
          && <div className="sa-empty">No staff found for this department.</div>}
      </section>
      <section className="sa-panel sa-monthly-panel">
        <div className="sa-panel-heading">
          <div><h3>2026 Maharashtra holiday calendar <span className="sa-count">{MAHARASHTRA_HOLIDAYS_2026.length}</span></h3><p>H marks these dates in Monthly Attendance. Staff check-ins are counted above.</p></div>
        </div>
        <div className="sa-monthly-table-wrap">
          <table className="sa-monthly-table sa-holiday-calendar-table">
            <thead><tr><th>Date</th><th>Holiday</th><th>Type</th><th>Staff checked in</th></tr></thead>
            <tbody>{MAHARASHTRA_HOLIDAYS_2026.map((holiday) => (
              <tr key={holiday.date}>
                <td>{new Date(`${holiday.date}T00:00:00`).toLocaleDateString()}</td>
                <td>{holiday.name}</td>
                <td>{holiday.type}</td>
                <td>{holidayStaffByDate.get(holiday.date)?.size || 0}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </section>
    </>
  }

  const renderTasks = () => (
    <>
      <div className="sa-page-heading"><div><h2>Live work queue</h2><p>Tasks, assignments, due times, and proof state from backend records. Work is generated and assigned automatically.</p></div></div>
      <section className="sa-panel">
        <div className="sa-panel-heading">
          <div><h3>Work items <span className="sa-count">{filteredTasks.length}</span></h3><p>Task completion is submitted to the existing orchestrator workflow.</p></div>
          <select value={taskFilter} onChange={(event) => setTaskFilter(event.target.value)} aria-label="Filter work status">
            {['All', ...new Set(tasks.map((task) => task.status))].map((value) => <option key={value}>{value}</option>)}
          </select>
        </div>
        <div className="sa-task-grid">
          {filteredTasks.map((task) => (
            <article className={`sa-task-card${task.priority === 'CRITICAL' ? ' critical' : ''}`} key={task.id}>
              <div className="sa-task-card-top"><StatusPill value={task.priority} /><StatusPill value={task.status} /></div>
              <h3>{task.name}</h3><p>{task.description || 'No description recorded.'}</p>
              <div className="sa-task-meta">
                <span><Icon>business</Icon>{task.department}</span>
                <span><Icon>schedule</Icon>Due {displayDateTime(task.dueDate)}</span>
                <span><Icon>badge</Icon>{task.assignedEmployee || 'Unassigned'}</span>
                <span><Icon>sync_alt</Icon>{task.shiftName}</span>
                <span><Icon>verified</Icon>{task.proofStatus || 'No proof submitted'}</span>
                <span><Icon>fact_check</Icon>{task.requiresProof ? 'Proof required' : 'Proof optional'}</span>
                {task.skill && <span><Icon>psychology</Icon>{task.skill}</span>}
              </div>
              <div className="sa-task-actions">
                <small>Work item #{task.id}</small>
                {['ASSIGNED', 'IN_PROGRESS'].includes(task.status) && <>
                  <ActionButton
                    disabled={working || (task.requiresProof && task.proofStatus !== 'VERIFIED')}
                    onClick={() => handleTaskComplete(task)}
                  >Complete Task</ActionButton>
                  {task.requiresProof && task.proofStatus !== 'VERIFIED' && (
                    <label className="sa-button secondary">
                      Upload Proof
                      <input
                        type="file"
                        accept="image/*"
                        aria-label={`Upload proof for ${task.name}`}
                        disabled={working}
                        onChange={(event) => handleProofUpload(task, event)}
                        hidden
                      />
                    </label>
                  )}
                </>}
              </div>
              {task.proofStatus && <p className="sa-proof-result" aria-live="polite">
                Proof: {task.proofStatus}
                {task.proofConfidence != null && ` · ${Math.round(task.proofConfidence * 100)}% confidence`}
                {task.proofRationale && ` · ${task.proofRationale}`}
              </p>}
              {proofUploadStatus[task.id] && <p className="sa-proof-result" role="status">{proofUploadStatus[task.id]}</p>}
              {task.requiresProof && task.proofStatus !== 'VERIFIED' && ['ASSIGNED', 'IN_PROGRESS'].includes(task.status)
                && <small>Upload proof to enable task completion. WhatsApp is optional.</small>}
            </article>
          ))}
          {!filteredTasks.length && <div className="sa-empty">No live work items found.</div>}
        </div>
      </section>
    </>
  )

  const renderTemplates = () => (
    <>
      <div className="sa-page-heading">
        <div><h2>Task templates</h2><p>Templates are the existing task-master records; supported fields come from the backend schema.</p></div>
        <ActionButton onClick={() => { setEditingTemplate(null); setTemplateFormOpen((value) => !value) }}><Icon>add</Icon>Add template</ActionButton>
      </div>
      {templateFormOpen && <form className="sa-panel sa-report-form" onSubmit={handleTemplateSubmit}>
        <div className="sa-form-grid">
          <Field label="Task name"><input name="task_name" defaultValue={editingTemplate?.task_name || ''} required maxLength="100" /></Field>
          <Field label="Department"><select name="department_id" defaultValue={editingTemplate?.department_id || ''}><option value="">No department</option>{snapshot.departments.map((department) => <option key={department.department_id} value={department.department_id}>{department.department_name}</option>)}</select></Field>
          <Field label="Priority"><select name="priority_category" defaultValue={editingTemplate?.priority_category || 'MEDIUM'}>{['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'].map((priority) => <option key={priority}>{priority}</option>)}</select></Field>
          <Field label="Task type"><select name="task_type" defaultValue={editingTemplate?.task_type || 'RECURRING'}><option value="RECURRING">Recurring</option><option value="EVENT_TEMPLATE">Event template</option></select></Field>
          <Field label="Required role"><input name="required_role" defaultValue={editingTemplate?.required_role || ''} maxLength="100" /></Field>
          <Field label="Required skill"><input name="required_skill" defaultValue={editingTemplate?.required_skill || ''} maxLength="255" /></Field>
          <Field label="Estimated minutes"><input type="number" name="estimated_time" min="1" max="1440" defaultValue={editingTemplate?.estimated_time || ''} /></Field>
          <Field label="Suggested start time"><input type="time" name="suggested_start_time" defaultValue={editingTemplate?.suggested_start_time?.slice(0, 5) || ''} /></Field>
          <Field label="Due time"><input type="time" name="due_time" defaultValue={editingTemplate?.due_time?.slice(0, 5) || ''} /></Field>
          <Field label="Requires verified proof"><input name="requires_proof" type="checkbox" defaultChecked={editingTemplate?.requires_proof || false} /></Field>
          <Field label="Description" className="full"><textarea name="description" defaultValue={editingTemplate?.description || ''} /></Field>
        </div>
        <div className="sa-report-submit"><span>Scheduled templates are generated for an active rostered shift after check-in.</span><div><ActionButton type="submit" disabled={working}>{editingTemplate ? 'Save changes' : 'Create template'}</ActionButton><ActionButton secondary onClick={() => { setTemplateFormOpen(false); setEditingTemplate(null) }}>Cancel</ActionButton></div></div>
      </form>}
      <section className="sa-panel"><div className="sa-panel-heading"><div><h3>Database task templates <span className="sa-count">{snapshot.taskTemplates.length}</span></h3></div></div>
        <div className="sa-table-wrap"><table className="sa-table"><thead><tr>{['Name', 'Department', 'Required role', 'Required skill', 'Priority', 'Duration', 'Suggested start', 'Due time', 'Proof', 'Status', 'Actions'].map((heading) => <th key={heading}>{heading}</th>)}</tr></thead>
          <tbody>{snapshot.taskTemplates.map((template) => (
            <tr key={template.task_id}>
              <td><strong>{template.task_name}</strong><small>{template.description || ''}</small></td>
              <td>{snapshot.departments.find((department) => department.department_id === template.department_id)?.department_name || '—'}</td>
              <td>{template.required_role || '—'}</td><td>{template.required_skill || '—'}</td>
              <td><StatusPill value={template.priority_category} /></td>
              <td>{template.estimated_time ? `${template.estimated_time} min` : '—'}</td>
              <td>{template.suggested_start_time?.slice(0, 5) || '—'}</td>
              <td>{template.due_time?.slice(0, 5) || '—'}</td>
              <td>{template.requires_proof ? 'Required' : 'Optional'}</td><td><StatusPill value={template.task_state} /></td>
              <td><div className="sa-table-actions">
                <button className="sa-link-button" onClick={() => { setEditingTemplate(template); setTemplateFormOpen(true) }}>Edit</button>
                <button className="sa-link-button" disabled={working} onClick={() => perform(() => updateTaskTemplate(template.task_id, { task_state: template.task_state === 'ACTIVE' ? 'INACTIVE' : 'ACTIVE' }), 'Template status updated.')}>{template.task_state === 'ACTIVE' ? 'Deactivate' : 'Activate'}</button>
                <button className="sa-link-button danger-text" disabled={working} onClick={() => window.confirm(`Delete "${template.task_name}"?`) && perform(() => deleteTaskTemplate(template.task_id), 'Template deleted.')}>Delete</button>
              </div></td>
            </tr>
          ))}</tbody>
        </table></div>
        {!snapshot.taskTemplates.length && <div className="sa-empty">No task templates found.</div>}
      </section>
    </>
  )

  const renderReports = () => (
    <>
      <div className="sa-page-heading"><div><h2>Shift reports</h2><p>Submit a new report or review the preserved imported historical reports. Reports do not update live attendance or workload.</p></div></div>
      <form className="sa-report-form" onSubmit={handleReportSubmit}>
        <section className="sa-panel sa-form-section">
          <div className="sa-form-section-title"><span>01</span><div><h3>New shift report</h3><p>Operational reporting only. Do not include treatment decisions.</p></div></div>
          <div className="sa-form-grid">
            <Field label="Nurse name"><input name="nurse_name" required maxLength="255" /></Field>
            <Field label="Shift date"><input type="date" name="shift_date" defaultValue={localDateString()} required /></Field>
            <Field label="Shift"><input name="shift_name" required maxLength="100" /></Field>
            <Field label="Ward / area"><input name="ward_area" required maxLength="255" /></Field>
            <Field label="Patients under care"><input name="patients" type="number" min="0" /></Field>
            {[
              ['New admission?', 'admission'],
              ['Discharge?', 'discharge'],
              ['Critical patient?', 'critical'],
              ['Patient shifted to ICU / higher center?', 'shifted'],
            ].map(([label, name]) => <Field label={label} key={name}><select name={name}><option>No</option><option>Yes</option></select></Field>)}
            <Field label="Transfer bed / patient details"><input name="bed_details" /></Field>
            <Field label="Emergency during shift?"><select name="emergency"><option>No</option><option>Yes</option></select></Field>
            <Field label="Emergency type"><input name="emergency_type" /></Field>
            <Field label="All medicines on time?"><select name="medication"><option>Yes</option><option>No</option></select></Field>
            <Field label="Medication delay reason"><input name="delay_reason" /></Field>
            <Field label="IV / catheter / dressing issue?"><select name="clinical_issue"><option>No</option><option>Yes</option></select></Field>
            <Field label="Clinical issue details"><input name="issue_details" /></Field>
            <Field label="Procedures done"><input name="procedures" /></Field>
            <Field label="Infection-control issue?"><select name="infection"><option>No</option><option>Yes</option></select></Field>
            <Field label="Biomedical-waste issue?"><select name="biomedical"><option>No</option><option>Yes</option></select></Field>
            <Field label="Equipment malfunction?"><select name="equipment"><option>No</option><option>Yes</option></select></Field>
            <Field label="Equipment name"><input name="equipment_name" /></Field>
            <Field label="Proper handover given?"><select name="handover"><option>Yes</option><option>No</option></select></Field>
            <Field label="Consumables running low"><input name="consumables" /></Field>
            <Field label="Staffing status"><input name="staffing" /></Field>
            <Field label="Shift rating"><input name="rating" type="number" min="1" max="5" /></Field>
            <Field label="Pending tasks for next shift" className="full"><textarea name="pending_tasks" /></Field>
            <Field label="Suggestions / concerns" className="full"><textarea name="concerns" /></Field>
          </div>
          <div className="sa-report-submit"><span>Historical source records are retained and never overwritten.</span><ActionButton type="submit" disabled={working}>Submit shift report</ActionButton></div>
        </section>
      </form>
      <section className="sa-panel">
        <div className="sa-panel-heading"><div><h3>Recent shift reports <span className="sa-count">{snapshot.shiftReports.length}</span></h3><p>Historical and newly submitted database records</p></div></div>
        <div className="sa-table-wrap"><table className="sa-table"><thead><tr>{['Shift date', 'Nurse', 'Shift', 'Ward / area', 'Patients', 'Emergency', 'Handover', 'Pending tasks'].map((heading) => <th key={heading}>{heading}</th>)}</tr></thead>
          <tbody>{snapshot.shiftReports.map((record) => (
            <tr key={record.log_id}>
              <td>{record.shift_date}</td><td>{record.nurse_name}</td><td>{record.shift_name}</td><td>{record.ward_area}</td>
              <td>{record.answers?.[SHIFT_LOG_KEYS.patients] ?? '—'}</td>
              <td>{record.answers?.[SHIFT_LOG_KEYS.emergency] ?? '—'}</td>
              <td>{record.answers?.[SHIFT_LOG_KEYS.handover] ?? '—'}</td>
              <td>{record.answers?.[SHIFT_LOG_KEYS.pendingTasks] || '—'}</td>
            </tr>
          ))}</tbody>
        </table></div>
        {!snapshot.shiftReports.length && <div className="sa-empty">No shift reports found.</div>}
      </section>
    </>
  )

  const renderInsights = () => {
    const analytics = snapshot.shiftAnalytics
    const recommendations = snapshot.automationRecommendations || []
    const rules = snapshot.automationRules || []
    const activeTemplates = snapshot.taskTemplates.filter(
      (task) => String(task.task_state || '').toUpperCase() === 'ACTIVE',
    )
    const rulesByRecommendation = new Map(rules.map((rule) => [rule.recommendation_id, rule]))
    return <>
      <div className="sa-page-heading"><div><h2>Historical insights</h2><p>Statistics and learned patterns use submitted shift reports only; they do not represent current operations or clinical guidance.</p></div><ActionButton onClick={handlePatternAnalysis} disabled={working}><Icon>analytics</Icon>Analyze reports</ActionButton></div>
      <section className="sa-panel">
        <div className="sa-panel-heading"><div><h3>Historical report analytics</h3><p>{analytics.total_records} source records · {analytics.data_source}</p></div></div>
        <div className="sa-stats-grid">
          {[
            ['Patients / shift', analytics.average_patients_per_shift ?? '—'],
            ['Emergency occurrences', analytics.emergency_occurrences],
            ['Emergency rate', `${analytics.emergency_rate_percent}%`],
            ['Medication delay rate', `${analytics.medication_delay_rate_percent}%`],
            ['Equipment issue rate', `${analytics.equipment_issue_rate_percent}%`],
            ['Handover issue rate', `${analytics.handover_issue_rate_percent}%`],
          ].map(([label, value]) => <div className="sa-stat sa-stat-blue" key={label}><div className="sa-stat-top"><span>{label}</span></div><strong>{value}</strong></div>)}
        </div>
      </section>
      <div className="sa-two-column">
        <section className="sa-panel"><div className="sa-panel-heading"><div><h3>Records by ward</h3></div></div>
          {analytics.records_by_ward.length ? analytics.records_by_ward.map((row) => <div className="sa-activity-row" key={row.ward_area}><strong>{row.ward_area}</strong><span>{row.records}</span></div>) : <div className="sa-empty">No historical records found.</div>}
        </section>
        <section className="sa-panel"><div className="sa-panel-heading"><div><h3>Records by shift</h3></div></div>
          {analytics.records_by_shift.length ? analytics.records_by_shift.map((row) => <div className="sa-activity-row" key={row.shift_name}><strong>{row.shift_name}</strong><span>{row.records}</span></div>) : <div className="sa-empty">No historical records found.</div>}
        </section>
      </div>
      <section className="sa-panel">
        <div className="sa-panel-heading"><div><h3>Pattern recommendations <span className="sa-count">{recommendations.length}</span></h3><p>Minimum 10 valid observations, 3 occurrences, and 10% recurrence. Confidence is the Wilson 95% lower bound; results are descriptive, not causal.</p></div></div>
        <div className="sa-rule-list">
          {recommendations.map((recommendation) => {
            const rule = rulesByRecommendation.get(recommendation.recommendation_id)
            return <article className="sa-rule-card" key={recommendation.recommendation_id}>
              <div className="sa-rule-title"><h4>{recommendation.pattern_type.replaceAll('_', ' ')}</h4><StatusPill value={recommendation.status} /><StatusPill value={recommendation.risk_level} /></div>
              <p>{recommendation.description}</p>
              <div className="sa-task-meta"><span>{recommendation.occurrences}/{recommendation.observations} reports · {(recommendation.frequency * 100).toFixed(1)}% recurrence</span><span>Confidence lower bound: {(recommendation.confidence * 100).toFixed(1)}%</span><span>{recommendation.ward_area || 'All wards'} · {recommendation.shift_name || 'All shifts'}</span><span>Evidence: {recommendation.supporting_record_ids.length} report IDs</span></div>
              <p className="sa-rule-benefit">{recommendation.expected_benefit} This only creates a supervisor follow-up request from an existing task template; it does not make clinical decisions.</p>
              {recommendation.status === 'PENDING_APPROVAL' && !rule && <form className="sa-rule-form" onSubmit={(event) => handleCreateAutomationRule(event, recommendation)}>
                <Field label="Existing task template"><select name="task_id" required defaultValue=""><option value="" disabled>Select a task</option>{activeTemplates.map((task) => <option key={task.task_id} value={task.task_id}>{task.task_name}</option>)}</select></Field>
                <Field label="Priority"><select name="priority" defaultValue=""><option value="">Use template default</option>{['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'].map((value) => <option key={value}>{value}</option>)}</select></Field>
                <Field label="Due offset"><select name="due_offset" defaultValue="END_OF_DAY">{['ONE_HOUR', 'TWO_HOURS', 'FOUR_HOURS', 'END_OF_DAY'].map((value) => <option key={value}>{value.replaceAll('_', ' ')}</option>)}</select></Field>
                <Field label="Optional expiration"><input name="expires_at" type="datetime-local" /></Field>
                <ActionButton type="submit" disabled={working || !activeTemplates.length}>Create pending rule</ActionButton>
              </form>}
              {rule && <p className="sa-rule-benefit">Rule #{rule.rule_id} is {rule.status.replaceAll('_', ' ').toLowerCase()}.</p>}
              {recommendation.status === 'PENDING_APPROVAL' && !rule && <ActionButton danger secondary disabled={working} onClick={() => perform(() => reviewAutomationRecommendation(recommendation.recommendation_id, 'reject', { notes: 'Rejected from Staff Automation.' }), 'Recommendation rejected.')}>Reject recommendation</ActionButton>}
            </article>
          })}
          {!recommendations.length && <div className="sa-empty">No recommendations yet. Analyze historical reports to discover recurring operational signals.</div>}
        </div>
      </section>
      <section className="sa-panel">
        <div className="sa-panel-heading"><div><h3>Automation rules <span className="sa-count">{rules.length}</span></h3><p>Only explicitly approved rules are active. Execution dispatches a supervisor request through existing agents and the orchestrator.</p></div><ActionButton secondary disabled={working} onClick={handleExpireRules}>Expire due rules</ActionButton></div>
        <div className="sa-rule-list">
          {rules.map((rule) => {
            const effectiveness = ruleEffectiveness[rule.rule_id]
            return <article className="sa-rule-card" key={rule.rule_id}>
              <div className="sa-rule-title"><h4>{rule.rule_name}</h4><StatusPill value={rule.status} /></div>
              <p>{rule.description}</p>
              <div className="sa-task-meta"><span>Signal: {rule.conditions.signal_type.replaceAll('_', ' ')}</span><span>Task template #{rule.action_config.task_id}</span><span>Expires: {displayDateTime(rule.expires_at)}</span></div>
              {rule.status === 'PENDING_APPROVAL' && <form className="sa-rule-form" onSubmit={(event) => handleAutomationRuleEdit(event, rule)}>
                <Field label="Task template"><select name="task_id" defaultValue={rule.action_config.task_id}>{activeTemplates.map((task) => <option key={task.task_id} value={task.task_id}>{task.task_name}</option>)}</select></Field>
                <Field label="Priority"><select name="priority" defaultValue={rule.action_config.priority || ''}><option value="">Use template default</option>{['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'].map((value) => <option key={value}>{value}</option>)}</select></Field>
                <Field label="Due offset"><select name="due_offset" defaultValue={rule.action_config.due_offset}>{['ONE_HOUR', 'TWO_HOURS', 'FOUR_HOURS', 'END_OF_DAY'].map((value) => <option key={value} value={value}>{value.replaceAll('_', ' ')}</option>)}</select></Field>
                <Field label="Optional expiration"><input name="expires_at" type="datetime-local" defaultValue={rule.expires_at ? new Date(rule.expires_at).toISOString().slice(0, 16) : ''} /></Field>
                <ActionButton type="submit" secondary disabled={working}>Save rule edits</ActionButton>
                <ActionButton disabled={working} onClick={() => perform(() => reviewAutomationRule(rule.rule_id, 'approve', {}), 'Rule approved and activated.')}>Approve & activate</ActionButton>
                <ActionButton danger disabled={working} onClick={() => perform(() => reviewAutomationRule(rule.rule_id, 'reject', { notes: 'Rejected from Staff Automation.' }), 'Rule rejected.')}>Reject rule</ActionButton>
              </form>}
              {rule.status === 'ACTIVE' && <ActionButton danger secondary disabled={working} onClick={() => perform(() => reviewAutomationRule(rule.rule_id, 'disable', { notes: 'Disabled from Staff Automation.' }), 'Automation rule disabled.')}>Disable rule</ActionButton>}
              <ActionButton secondary disabled={working} onClick={() => handleRuleEffectiveness(rule.rule_id)}>Load effectiveness</ActionButton>
              {effectiveness && <div className="sa-rule-effectiveness">
                <strong>{effectiveness.succeeded}/{effectiveness.total_executions} dispatches succeeded ({(effectiveness.success_rate * 100).toFixed(1)}%)</strong>
                <span>Failed: {effectiveness.failed} · In progress: {effectiveness.pending} · Existing workflow processed: {effectiveness.request_processing_rate == null ? '—' : `${(effectiveness.request_processing_rate * 100).toFixed(1)}%`}</span>
                {effectiveness.executions.slice(0, 3).map((execution) => <small key={execution.execution_id}>Report #{execution.source_report_id}: {execution.status}{execution.error_message ? ` — ${execution.error_message}` : ''}</small>)}
              </div>}
            </article>
          })}
          {!rules.length && <div className="sa-empty">No learned automation rules have been created.</div>}
        </div>
      </section>
      <section className="sa-panel">
        <div className="sa-panel-heading"><div><h3>Rule lifecycle audit</h3><p>Recent recommendation, edit, approval, activation, rejection, and disable events.</p></div></div>
        {snapshot.automationAudit.slice(0, 10).map((entry) => <div className="sa-activity-row" key={entry.audit_id}><strong>{entry.action.replaceAll('_', ' ')}</strong><span>Rule {entry.rule_id || '—'} · user {entry.actor_id || 'system'} · {displayDateTime(entry.occurred_at)}</span></div>)}
        {!snapshot.automationAudit.length && <div className="sa-empty">No rule lifecycle events recorded yet.</div>}
      </section>
    </>
  }

  const renderEmergency = () => (
    <>
      <div className="sa-page-heading"><div><h2>Emergency workflow</h2><p>Submit supported emergency types to the existing Emergency Response Agent. The backend selects its registered protocol and handles assignments.</p></div><ActionButton onClick={() => setEmergencyOpen((value) => !value)}><Icon>emergency</Icon>Report emergency</ActionButton></div>
      {emergencyOpen && <form className="sa-panel sa-report-form" onSubmit={handleEmergencySubmit}>
        <div className="sa-form-grid">
          <Field label="Emergency type"><select name="emergency_type" required>{['PATIENT_COLLAPSE', 'FIRE', 'ACTIVE_SHOOTER', 'HAZMAT_SPILL', 'INFANT_ABDUCTION', 'BOMB_THREAT', 'COMBATIVE_PERSON', 'MISSING_PATIENT', 'EVACUATION_ALERT', 'MASS_CASUALTY'].map((type) => <option key={type}>{type}</option>)}</select></Field>
          <Field label="Location"><input name="location" required maxLength="255" /></Field>
          <Field label="Reported by"><input value={snapshot.currentUser.email} readOnly /></Field>
        </div>
        <div className="sa-report-submit"><span>Only supported operational emergency types are listed.</span><ActionButton type="submit" disabled={working}>Submit to emergency workflow</ActionButton></div>
      </form>}
      <section className="sa-panel">
        <div className="sa-panel-heading"><div><h3>Recent emergency work items</h3><p>Critical-priority records from the live work queue</p></div></div>
        <div className="sa-task-grid">{tasks.filter((task) => task.priority === 'CRITICAL').map((task) => (
          <article className="sa-task-card critical" key={task.id}><div className="sa-task-card-top"><StatusPill value={task.priority} /><StatusPill value={task.status} /></div><h3>{task.name}</h3><p>{task.description || 'No description recorded.'}</p><div className="sa-task-meta"><span>{task.department}</span><span>{task.assignedEmployee || 'Unassigned'}</span><span>Due {displayDateTime(task.dueDate)}</span></div></article>
        ))}{!tasks.some((task) => task.priority === 'CRITICAL') && <div className="sa-empty">No critical work items found.</div>}</div>
      </section>
    </>
  )

  const renderWorkflow = () => (
    <>
      <div className="sa-page-heading"><div><h2>Workflow traces & approvals</h2><p>These entries are read from backend agent audit logs, orchestrator traces, queued notifications, and pending approvals.</p></div></div>
      <section className="sa-panel">
        <div className="sa-panel-heading"><div><h3>Pending approvals <span className="sa-count">{snapshot.pendingApprovals.length}</span></h3></div></div>
        {snapshot.pendingApprovals.map((approval) => (
          <div className="sa-reassignment-card" key={approval.approval_id}>
            <div className="sa-reassignment-icon"><Icon>approval</Icon></div>
            <div className="sa-reassignment-copy"><div><StatusPill value={approval.status} /><time>{displayDateTime(approval.created_at)}</time></div><h4>{approval.sensitive_action}</h4><p>{approval.rationale || approval.workflow_id}</p></div>
          </div>
        ))}
        {!snapshot.pendingApprovals.length && <div className="sa-empty">No pending approvals.</div>}
      </section>
      <section className="sa-panel">
        <div className="sa-panel-heading"><div><h3>Recent orchestrator traces</h3><p>Actual workflow executions only</p></div></div>
        <div className="sa-table-wrap"><table className="sa-table"><thead><tr>{['Workflow ID', 'Event', 'Status', 'Started', 'Completed'].map((heading) => <th key={heading}>{heading}</th>)}</tr></thead>
          <tbody>{snapshot.traces.map((trace) => <tr key={trace.workflow_id}><td>{trace.workflow_id}</td><td>{trace.event_type || trace.event_name || '—'}</td><td><StatusPill value={trace.execution_status} /></td><td>{displayDateTime(trace.started_at)}</td><td>{displayDateTime(trace.completed_at)}</td></tr>)}</tbody>
        </table></div>
        {!snapshot.traces.length && <div className="sa-empty">No workflow traces found.</div>}
      </section>
      <section className="sa-panel">
        <div className="sa-panel-heading"><div><h3>Agent activity</h3><p>Real backend audit events</p></div></div>
        <div className="sa-activity-list">{snapshot.agentActions.slice(0, 30).map((action) => (
          <div className="sa-activity-row" key={action.agent_action_id}>
            <time>{displayDateTime(action.action_timestamp)}</time><span className="sa-activity-dot automation" />
            <div><strong>{action.action_type || action.agent_name || 'Agent action'}</strong><small>{action.decision_summary || 'No decision details recorded.'}</small></div>
            <StatusPill value={action.execution_status} />
          </div>
        ))}</div>
        {!snapshot.agentActions.length && <div className="sa-empty">No agent actions found.</div>}
      </section>
      <section className="sa-panel">
        <div className="sa-panel-heading"><div><h3>Recent automation events</h3><p>Transactional outbox records, including assignment notifications handled by the Communication Agent.</p></div></div>
        <div className="sa-table-wrap"><table className="sa-table">
          <thead><tr>{['Event', 'Status', 'Attempts', 'Created', 'Processed'].map((heading) => <th key={heading}>{heading}</th>)}</tr></thead>
          <tbody>{snapshot.outboxEvents.map((event) => (
            <tr key={event.event_id}>
              <td>{event.event_type}</td>
              <td><StatusPill value={event.status} /></td>
              <td>{event.attempts}</td>
              <td>{displayDateTime(event.created_at)}</td>
              <td>{displayDateTime(event.processed_at)}</td>
            </tr>
          ))}</tbody>
        </table></div>
        {!snapshot.outboxEvents.length && <div className="sa-empty">No automation events found.</div>}
      </section>
      <section className="sa-panel">
        <div className="sa-panel-heading"><div><h3>Communication channel</h3><p>The Communication Agent records notifications even when live WhatsApp delivery is unavailable.</p></div></div>
        <div className="sa-activity-row">
          <strong>WhatsApp Mode: {snapshot.communicationStatus.delivery_mode === 'DEMO' ? 'Demo / Mock' : 'Live'}</strong>
          <span>{snapshot.communicationStatus.real_whatsapp_configured
            ? 'WhatsApp credentials are configured.'
            : 'Real WhatsApp is not configured; no message is represented as delivered.'}</span>
        </div>
        {snapshot.communicationStatus.notifications.map((notification, index) => (
          <div className="sa-activity-row" key={`${notification.work_id || 'notice'}-${notification.timestamp || index}`}>
            <strong>{notification.status === 'MOCKED' ? 'Simulated notification recorded' : `Notification ${notification.status.toLowerCase()}`}</strong>
            <span>{notification.work_id ? `Work item #${notification.work_id} · ` : ''}{displayDateTime(notification.timestamp)}</span>
          </div>
        ))}
        {!snapshot.communicationStatus.notifications.length && <div className="sa-empty">No notification messages have been recorded yet.</div>}
      </section>
    </>
  )

  const rendered = {
    overview: renderOverview,
    attendance: renderAttendance,
    monthlyAttendance: renderMonthlyAttendance,
    holidayCount: renderHolidayCount,
    tasks: renderTasks,
    workload: renderWorkload,
    templates: renderTemplates,
    reports: renderReports,
    insights: renderInsights,
    emergency: renderEmergency,
    workflow: renderWorkflow,
  }[tab]

  return (
    <main className="staff-automation-page">
      <header className="sa-workspace-header">
        <div><div className="sa-breadcrumb">Operations <Icon>chevron_right</Icon> Staff Automation</div><h1>Staff Automation</h1></div>
      </header>
      <nav className="sa-tabs" aria-label="Staff Automation sections">
        {pageTabs.map((item) => <button key={item.id} className={tab === item.id ? 'active' : ''} onClick={() => setTab(item.id)}><Icon>{item.icon}</Icon>{item.label}</button>)}
      </nav>
      {actionError && <div className="sa-info-banner" role="alert"><Icon>error</Icon><span>{actionError}</span><button className="sa-link-button" onClick={() => setActionError('')}>Dismiss</button></div>}
      {toast && <div className="sa-info-banner" role="status"><Icon>info</Icon><span>{toast}</span></div>}
      <div className="sa-content">{(tab === 'monthlyAttendance' ? null : renderLoadingOrError()) || rendered()}</div>
    </main>
  )
}
