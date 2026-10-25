import { useState, useEffect, useCallback } from 'react'
import { authFetch } from '../services/apiHelper'
import './AgentManagement.css'

const AGENT_ICONS = {
  'TASK_MANAGEMENT_AGENT': 'assignment',
  'ASSIGNMENT_AGENT': 'person_add',
  'WORKFORCE_AGENT': 'groups',
  'EMERGENCY_RESPONSE_AGENT': 'emergency',
  'EVENT_AGENT': 'bolt',
  'ORCHESTRATOR_AGENT': 'hub',
  'TASK_VERIFICATION_AGENT': 'fact_check',
  'COMMUNICATION_AGENT': 'chat',
}

function getAgentIcon(name) {
  return AGENT_ICONS[name] || 'smart_toy'
}

function timeAgo(isoStr) {
  if (!isoStr) return 'Never'
  const diff = Date.now() - new Date(isoStr).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'Just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  return `${days}d ago`
}

export default function AgentManagement() {
  const [agents, setAgents] = useState([])
  const [capabilities, setCapabilities] = useState([])
  const [eventMap, setEventMap] = useState({})
  const [selectedAgent, setSelectedAgent] = useState(null)
  const [agentStats, setAgentStats] = useState(null)
  const [agentActions, setAgentActions] = useState([])
  const [agentCaps, setAgentCaps] = useState([])
  const [loading, setLoading] = useState(true)
  const [statsLoading, setStatsLoading] = useState(false)
  const [activeTab, setActiveTab] = useState('capabilities')
  const [expandedCap, setExpandedCap] = useState(null)
  const [landingPanel, setLandingPanel] = useState(null)

  useEffect(() => {
    async function loadInitialData() {
      try {
        const [agentsRes, capsRes, eventsRes] = await Promise.all([
          authFetch('/agents/'),
          authFetch('/capabilities/'),
          authFetch('/capabilities/events'),
        ])
        const agentsData = await agentsRes.json()
        const capsData = await capsRes.json()
        const eventsData = await eventsRes.json()
        setAgents(agentsData)
        setCapabilities(capsData)
        setEventMap(eventsData)
      } catch (err) {
        console.error('Failed to load agent data:', err)
      } finally {
        setLoading(false)
      }
    }
    loadInitialData()
  }, [])

  const selectAgent = useCallback(async (agent) => {
    setSelectedAgent(agent)
    setActiveTab('capabilities')
    setExpandedCap(null)
    setStatsLoading(true)

    const agentNameUpper = agent.agent_name.toUpperCase().replace(/ /g, '_')
    const filtered = capabilities.filter(c => c.agent_name === agentNameUpper)
    setAgentCaps(filtered)

    try {
      const [statsRes, actionsRes] = await Promise.all([
        authFetch(`/agents/${agent.agent_id}/stats`),
        authFetch(`/agents/${agent.agent_id}/actions?limit=50`),
      ])
      if (statsRes.ok) setAgentStats(await statsRes.json())
      if (actionsRes.ok) setAgentActions(await actionsRes.json())
    } catch (err) {
      console.error('Failed to load agent details:', err)
    } finally {
      setStatsLoading(false)
    }
  }, [capabilities])

  if (loading) {
    return (
      <div className="agent-container">
        <div className="loading-center">
          <span className="material-symbols-outlined">progress_activity</span>
          Loading agents...
        </div>
      </div>
    )
  }

  const allEvents = Object.keys(eventMap)
  const uniqueAgentNames = [...new Set(capabilities.map(c => c.agent_name))]

  return (
    <div className="agent-container">
      <aside className="agent-sidebar">
        <div className="agent-sidebar-header">
          <h2>
            <span className="material-symbols-outlined">smart_toy</span>
            Agents
          </h2>
          <p>{agents.length} registered agents</p>
        </div>
        <div className="agent-list custom-scrollbar">
          {agents.map(agent => (
            <div
              key={agent.agent_id}
              className={`agent-card${selectedAgent?.agent_id === agent.agent_id ? ' active' : ''}`}
              onClick={() => selectAgent(agent)}
            >
              <div className="agent-card-icon">
                <span className="material-symbols-outlined">
                  {getAgentIcon(agent.agent_name.toUpperCase().replace(/ /g, '_'))}
                </span>
              </div>
              <div className="agent-card-info">
                <div className="agent-card-name">{agent.agent_name}</div>
                <div className="agent-card-category">{agent.agent_category}</div>
              </div>
            </div>
          ))}
        </div>
      </aside>

      <main className="agent-main custom-scrollbar">
        {!selectedAgent ? (
          <div className="agent-landing">
            <div className="landing-hero">
              <span className="material-symbols-outlined landing-hero-icon">smart_toy</span>
              <h2>Agent Management</h2>
              <p>Select an agent from the sidebar, or explore the system-wide views below.</p>
            </div>

            <div className="landing-buttons">
              <button
                className={`landing-toggle-btn${landingPanel === 'matrix' ? ' active' : ''}`}
                onClick={() => setLandingPanel(landingPanel === 'matrix' ? null : 'matrix')}
              >
                <span className="material-symbols-outlined">grid_view</span>
                <div className="landing-toggle-text">
                  <span className="landing-toggle-title">Event Coverage Matrix</span>
                  <span className="landing-toggle-sub">See which agents handle which events</span>
                </div>
                <span className="material-symbols-outlined landing-toggle-arrow">
                  {landingPanel === 'matrix' ? 'expand_less' : 'expand_more'}
                </span>
              </button>
              <button
                className={`landing-toggle-btn${landingPanel === 'flow' ? ' active' : ''}`}
                onClick={() => setLandingPanel(landingPanel === 'flow' ? null : 'flow')}
              >
                <span className="material-symbols-outlined">account_tree</span>
                <div className="landing-toggle-text">
                  <span className="landing-toggle-title">Dependency Flow</span>
                  <span className="landing-toggle-sub">Capability execution order per event</span>
                </div>
                <span className="material-symbols-outlined landing-toggle-arrow">
                  {landingPanel === 'flow' ? 'expand_less' : 'expand_more'}
                </span>
              </button>
            </div>

            {landingPanel === 'matrix' && (
              <section className="agent-section landing-panel">
                <div className="agent-section-title">
                  <span className="material-symbols-outlined">grid_view</span>
                  Event Coverage Matrix
                </div>
                <div className="coverage-matrix">
                  <table className="coverage-table">
                    <thead>
                      <tr>
                        <th>Event</th>
                        {uniqueAgentNames.map(name => (
                          <th key={name} title={name}>{name.replace(/_/g, ' ').split(' ').map(w => w[0]).join('')}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {allEvents.map(event => (
                        <tr key={event}>
                          <td>{event}</td>
                          {uniqueAgentNames.map(name => (
                            <td key={name}>
                              {eventMap[event]?.includes(name) ? (
                                <span className="coverage-check">
                                  <span className="material-symbols-outlined">check</span>
                                </span>
                              ) : (
                                <span className="coverage-empty">—</span>
                              )}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            )}

            {landingPanel === 'flow' && (
              <section className="agent-section landing-panel">
                <div className="agent-section-title">
                  <span className="material-symbols-outlined">account_tree</span>
                  Dependency Flow — All Events
                </div>
                <div className="dep-flow">
                  {allEvents.map(event => {
                    const eventCaps = capabilities
                      .filter(c => c.handles_events.includes(event))
                      .sort((a, b) => a.priority - b.priority)
                    if (eventCaps.length === 0) return null
                    return (
                      <div key={event} className="dep-flow-event-group">
                        <div className="dep-flow-event-label">
                          <span className="material-symbols-outlined">bolt</span>
                          {event}
                        </div>
                        <div className="dep-flow-steps">
                          {eventCaps.map((cap, idx) => (
                            <div key={cap.name} className="dep-flow-step">
                              <div className="dep-flow-node">{idx + 1}</div>
                              <div className="dep-flow-info">
                                <div className="dep-flow-cap-name">{cap.name}</div>
                                <div className="dep-flow-agent-name">{cap.agent_name} — priority {cap.priority}</div>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </section>
            )}
          </div>
        ) : (
          <>
            <div className="agent-page-heading">
              <div>
                <h2>
                  <span className="material-symbols-outlined">
                    {getAgentIcon(selectedAgent.agent_name.toUpperCase().replace(/ /g, '_'))}
                  </span>
                  {selectedAgent.agent_name}
                </h2>
                <p>{selectedAgent.description || selectedAgent.agent_category}</p>
              </div>
            </div>

            {statsLoading ? (
              <div className="loading-center">
                <span className="material-symbols-outlined">progress_activity</span>
                Loading details...
              </div>
            ) : (
              <>
                {agentStats && (
                  <section className="agent-section">
                    <div className="agent-section-title">
                      <span className="material-symbols-outlined">monitoring</span>
                      Performance Metrics
                    </div>
                    <div className="stats-grid">
                      <div className="stat-card">
                        <span className="stat-label">Total Executions</span>
                        <span className="stat-value primary">{agentStats.total_executions}</span>
                      </div>
                      <div className="stat-card">
                        <span className="stat-label">Success</span>
                        <span className="stat-value success">{agentStats.success_count}</span>
                        <div className="success-gauge">
                          <div className="success-gauge-fill" style={{ width: `${agentStats.success_rate}%` }} />
                        </div>
                        <span className="stat-sub">{agentStats.success_rate}% success rate</span>
                      </div>
                      <div className="stat-card">
                        <span className="stat-label">Failed</span>
                        <span className="stat-value failed">{agentStats.failed_count}</span>
                      </div>
                      <div className="stat-card">
                        <span className="stat-label">Avg Exec Time</span>
                        <span className="stat-value">{agentStats.avg_execution_time_ms != null ? `${agentStats.avg_execution_time_ms}ms` : '—'}</span>
                      </div>
                      <div className="stat-card">
                        <span className="stat-label">Last Active</span>
                        <span className="stat-value" style={{ fontSize: 16 }}>{timeAgo(agentStats.last_active)}</span>
                      </div>
                      <div className="stat-card">
                        <span className="stat-label">Pending</span>
                        <span className="stat-value">{agentStats.pending_count}</span>
                      </div>
                    </div>
                  </section>
                )}

                <div className="tab-bar">
                  <button className={`tab-btn${activeTab === 'capabilities' ? ' active' : ''}`} onClick={() => setActiveTab('capabilities')}>
                    <span className="material-symbols-outlined">extension</span>
                    Capabilities ({agentCaps.length})
                  </button>
                  <button className={`tab-btn${activeTab === 'actions' ? ' active' : ''}`} onClick={() => setActiveTab('actions')}>
                    <span className="material-symbols-outlined">history</span>
                    Action History ({agentActions.length})
                  </button>
                  <button className={`tab-btn${activeTab === 'flow' ? ' active' : ''}`} onClick={() => setActiveTab('flow')}>
                    <span className="material-symbols-outlined">account_tree</span>
                    Dependency Flow
                  </button>
                </div>

                {activeTab === 'capabilities' && (
                  <section className="agent-section">
                    <div className="agent-section-title">
                      <span className="material-symbols-outlined">extension</span>
                      Registered Capabilities
                    </div>
                    {agentCaps.length === 0 ? (
                      <div className="loading-center" style={{ padding: 20 }}>
                        <span className="material-symbols-outlined" style={{ animation: 'none' }}>info</span>
                        No capabilities registered for this agent.
                      </div>
                    ) : (
                      <div className="cap-list">
                        {agentCaps.map(cap => {
                          const isExpanded = expandedCap === cap.name
                          return (
                            <div
                              key={cap.name}
                              className={`cap-item${isExpanded ? ' expanded' : ''}`}
                              onClick={() => setExpandedCap(isExpanded ? null : cap.name)}
                            >
                              <div className="cap-item-header">
                                <div>
                                  <div className="cap-item-name">{cap.name}</div>
                                  <div className="cap-item-desc">{cap.description}</div>
                                </div>
                                <div className="cap-item-meta">
                                  <span className="cap-priority">P{cap.priority}</span>
                                  {cap.continue_on_failure && <span className="chip chip-flag">resilient</span>}
                                </div>
                              </div>
                              {isExpanded && (
                                <div className="cap-detail">
                                  <div className="cap-detail-row">
                                    <span className="cap-detail-label">Events</span>
                                    <div className="cap-detail-value">
                                      {cap.handles_events.map(e => (
                                        <span key={e} className="chip chip-event">{e}</span>
                                      ))}
                                    </div>
                                  </div>
                                  <div className="cap-detail-row">
                                    <span className="cap-detail-label">Requires</span>
                                    <div className="cap-detail-value">
                                      {cap.requires.length > 0 ? cap.requires.map(r => (
                                        <span key={r} className="chip chip-input">{r}</span>
                                      )) : <span style={{ fontSize: 11, color: 'var(--outline)' }}>None</span>}
                                    </div>
                                  </div>
                                  <div className="cap-detail-row">
                                    <span className="cap-detail-label">Produces</span>
                                    <div className="cap-detail-value">
                                      {cap.produces.length > 0 ? cap.produces.map(p => (
                                        <span key={p} className="chip chip-output">{p}</span>
                                      )) : <span style={{ fontSize: 11, color: 'var(--outline)' }}>None</span>}
                                    </div>
                                  </div>
                                </div>
                              )}
                            </div>
                          )
                        })}
                      </div>
                    )}
                  </section>
                )}

                {activeTab === 'actions' && (
                  <section className="agent-section">
                    <div className="agent-section-title">
                      <span className="material-symbols-outlined">history</span>
                      Recent Actions
                    </div>
                    {agentActions.length === 0 ? (
                      <div className="loading-center" style={{ padding: 20 }}>
                        <span className="material-symbols-outlined" style={{ animation: 'none' }}>info</span>
                        No action history found for this agent.
                      </div>
                    ) : (
                      <div className="action-table-wrap custom-scrollbar">
                        <table className="action-table">
                          <thead>
                            <tr>
                              <th>ID</th>
                              <th>Action Type</th>
                              <th>Status</th>
                              <th>Decision Summary</th>
                              <th>Engine</th>
                              <th>Time</th>
                              <th>Timestamp</th>
                            </tr>
                          </thead>
                          <tbody>
                            {agentActions.map(action => (
                              <tr key={action.agent_action_id}>
                                <td>{action.agent_action_id}</td>
                                <td>{action.action_type || '—'}</td>
                                <td>
                                  <span className={`action-status ${(action.execution_status || '').toLowerCase()}`}>
                                    {action.execution_status || '—'}
                                  </span>
                                </td>
                                <td title={action.decision_summary || ''}>{action.decision_summary || '—'}</td>
                                <td>{action.reasoning_engine || '—'}</td>
                                <td className="exec-time">{action.execution_time_ms != null ? `${action.execution_time_ms}ms` : '—'}</td>
                                <td>{action.action_timestamp ? new Date(action.action_timestamp).toLocaleString() : '—'}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </section>
                )}

                {activeTab === 'flow' && (
                  <section className="agent-section">
                    <div className="agent-section-title">
                      <span className="material-symbols-outlined">account_tree</span>
                      Dependency Flow
                    </div>
                    <div className="dep-flow">
                      {(() => {
                        const agentNameUpper = selectedAgent.agent_name.toUpperCase().replace(/ /g, '_')
                        const relevantEvents = [...new Set(agentCaps.flatMap(c => c.handles_events))]
                        if (relevantEvents.length === 0) {
                          return (
                            <div className="loading-center" style={{ padding: 20 }}>
                              <span className="material-symbols-outlined" style={{ animation: 'none' }}>info</span>
                              No event flows found for this agent.
                            </div>
                          )
                        }
                        return relevantEvents.map(event => {
                          const eventCaps = capabilities
                            .filter(c => c.handles_events.includes(event))
                            .sort((a, b) => a.priority - b.priority)
                          return (
                            <div key={event} className="dep-flow-event-group">
                              <div className="dep-flow-event-label">
                                <span className="material-symbols-outlined">bolt</span>
                                {event}
                              </div>
                              <div className="dep-flow-steps">
                                {eventCaps.map((cap, idx) => (
                                  <div
                                    key={cap.name}
                                    className="dep-flow-step"
                                    style={cap.agent_name === agentNameUpper ? { background: 'var(--primary-fixed)', borderRadius: 6 } : {}}
                                  >
                                    <div className="dep-flow-node">{idx + 1}</div>
                                    <div className="dep-flow-info">
                                      <div className="dep-flow-cap-name">
                                        {cap.name}
                                        {cap.agent_name === agentNameUpper && ' ◀'}
                                      </div>
                                      <div className="dep-flow-agent-name">{cap.agent_name} — priority {cap.priority}</div>
                                    </div>
                                  </div>
                                ))}
                              </div>
                            </div>
                          )
                        })
                      })()}
                    </div>
                  </section>
                )}
              </>
            )}
          </>
        )}
      </main>
    </div>
  )
}
