import './KpiCard.css'

export default function KpiCard({ icon, label, value, subtitle, subtitleIcon, variant = 'default' }) {
  const isEmergency = variant === 'emergency'

  return (
    <div className={`kpi-card glass-card ${isEmergency ? 'kpi-emergency emergency-pulse' : ''}`}>
      <div className="kpi-header">
        <span
          className={`material-symbols-outlined kpi-icon ${isEmergency ? 'kpi-icon-error' : 'kpi-icon-primary'}`}
        >
          {icon}
        </span>
        <span className={`kpi-label ${isEmergency ? 'kpi-label-error' : ''}`}>{label}</span>
      </div>
      <div className="kpi-body">
        <h3 className={`kpi-value ${isEmergency ? 'kpi-value-error' : ''}`}>{value}</h3>
        <div className={`kpi-subtitle ${isEmergency ? 'kpi-subtitle-error' : ''}`}>
          {subtitleIcon === 'trending_up' && (
            <span className="material-symbols-outlined kpi-subtitle-icon">trending_up</span>
          )}
          {subtitleIcon === 'dot' && <span className={`kpi-dot ${isEmergency ? 'kpi-dot-error' : 'kpi-dot-secondary'}`} />}
          {subtitleIcon === 'ping' && <span className="kpi-dot kpi-dot-error kpi-dot-ping" />}
          <span>{subtitle}</span>
        </div>
      </div>
    </div>
  )
}
