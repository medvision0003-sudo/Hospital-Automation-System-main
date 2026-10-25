import './DepartmentCard.css'

export default function DepartmentCard({ name, description, pendingTasks, assignedTasks, availableWorkers, totalStaff }) {
  const hasPending = pendingTasks > 0

  return (
    <div className="dept-card glass-card">
      <div className="dept-header">
        <div>
          <h4 className="dept-name">{name}</h4>
          {description && <p className="dept-floor">{description}</p>}
        </div>
        {hasPending && (
          <span className="dept-tag dept-tag-error">{pendingTasks} Pending</span>
        )}
        {!hasPending && (
          <span className="dept-tag dept-tag-primary">Clear</span>
        )}
      </div>

      <div className="dept-stats">
        <div className="dept-stat">
          <p className="dept-stat-label">Pending</p>
          <p className={`dept-stat-value ${hasPending ? 'dept-stat-highlight' : ''}`}>{pendingTasks}</p>
        </div>
        <div className="dept-stat">
          <p className="dept-stat-label">Assigned</p>
          <p className="dept-stat-value">{assignedTasks}</p>
        </div>
        <div className="dept-stat">
          <p className="dept-stat-label">Staff</p>
          <p className="dept-stat-value">{totalStaff || availableWorkers}</p>
        </div>
      </div>
    </div>
  )
}
