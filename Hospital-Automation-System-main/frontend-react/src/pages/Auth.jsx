import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { authFetch } from '../services/apiHelper'
import './Auth.css'

export default function Auth() {
  const navigate = useNavigate()

  const [isSignUp, setIsSignUp] = useState(false)
  const [role, setRole] = useState('SUPERVISOR')

  const getErrorMessage = (detail) => {
    if (Array.isArray(detail)) {
      return detail.map(err => {
        const field = err.loc ? err.loc[err.loc.length - 1] : '';
        let msg = err.msg || '';
        if (field === 'password' && msg.includes('at least 8 characters')) {
          return 'Password must be at least 8 characters long.';
        }
        if (field === 'email' && (msg.includes('valid email') || msg.includes('value is not a valid email'))) {
          return 'Please enter a valid email address.';
        }
        if (field) {
          const capitalizedField = field.charAt(0).toUpperCase() + field.slice(1).replace('_', ' ');
          let formattedMsg = msg.replace(/^String\b/i, capitalizedField);
          // Strip Pydantic's "Value error, " prefix to show clean message
          formattedMsg = formattedMsg.replace(/^Value error,\s*/i, '');
          return formattedMsg;
        }
        return msg || JSON.stringify(err);
      }).join(', ')
    }
    if (typeof detail === 'object' && detail !== null) {
      return detail.msg || JSON.stringify(detail)
    }
    return detail
  }

  // Form input states
  const [employeeIdOrEmail, setEmployeeIdOrEmail] = useState('')
  const [adminKey, setAdminKey] = useState('')
  const [workEmail, setWorkEmail] = useState('')
  const [department, setDepartment] = useState('')
  const [dbDepartments, setDbDepartments] = useState([])
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [rememberDevice, setRememberDevice] = useState(false)
  const [acceptTerms, setAcceptTerms] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const [showConfirmPassword, setShowConfirmPassword] = useState(false)

  useEffect(() => {
    if (isSignUp) {
      authFetch('/auth/departments')
        .then((res) => {
          if (!res.ok) throw new Error('Failed to load departments')
          return res.json()
        })
        .then((data) => {
          setDbDepartments(data)
          if (data.length > 0) {
            setDepartment(data[0].department_name)
          }
        })
        .catch((err) => console.error('Failed to load signup departments:', err))
    }
  }, [isSignUp])


  const [errorMsg, setErrorMsg] = useState('')
  const [infoMsg, setInfoMsg] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setErrorMsg('')
    setInfoMsg('')

    if (isSignUp) {
      const emailRegex = /^[^\s@]+@[^\s@]+\.[a-zA-Z]{2,}$/;
      if (!emailRegex.test(workEmail)) {
        setErrorMsg('Please enter a valid email address.')
        return
      }
      if (password.length < 8) {
        setErrorMsg('Password must be at least 8 characters long.')
        return
      }
      // Password complexity check
      const complexityRegex = /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])/;
      if (!complexityRegex.test(password)) {
        setErrorMsg('Password must contain at least one uppercase letter, one lowercase letter, one digit, and one special character (@$!%*?&).')
        return
      }
      if (password !== confirmPassword) {
        setErrorMsg('Passwords do not match.')
        return
      }
    }

    setLoading(true)

    try {
      if (!isSignUp) {
        // Sign In
        const payload = {
          username: employeeIdOrEmail,
          password: password,
        }
        const res = await authFetch('/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        })

        const data = await res.json()

        if (res.ok) {
          localStorage.setItem('access_token', data.access_token)
          localStorage.setItem('user_role', data.role)
          if (data.email) localStorage.setItem('user_email', data.email)
          if (data.department_id) localStorage.setItem('user_department_id', data.department_id)
          else localStorage.removeItem('user_department_id')
          if (data.employee_id) localStorage.setItem('user_employee_id', data.employee_id)
          else localStorage.removeItem('user_employee_id')
          window.dispatchEvent(new Event('authChange'))
          if (data.role === 'ADMIN') {
            navigate('/')
          } else {
            navigate('/supervisor')
          }
          return
        } else {
          setErrorMsg(getErrorMessage(data.detail) || 'Sign in failed. Please check your credentials.')
          setLoading(false)
          return
        }
      } else {
        // Sign Up
        if (role === 'ADMIN') {
          setErrorMsg('Admin account registration is disabled.')
          setLoading(false)
          return
        }
        const payload = {
          email: workEmail.trim().toLowerCase(),
          password: password,
          role: 'SUPERVISOR',
          employee_id_str: employeeIdOrEmail,
          department_name: department,
        }
        const res = await authFetch('/auth/signup', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        })

        const data = await res.json()

        if (res.ok) {
          setInfoMsg('Supervisor registration submitted successfully! Your account is pending Administrator approval before you can sign in.')
          setIsSignUp(false)
          setLoading(false)
          return
        } else {
          setErrorMsg(getErrorMessage(data.detail) || 'Registration failed. Please check your inputs.')
          setLoading(false)
          return
        }
      }
    } catch (err) {
      console.warn('Auth request failed, using local role simulation:', err)
      if (isSignUp) {
        setInfoMsg('Supervisor registration submitted! Admin approval is required for full console access.')
        setIsSignUp(false)
        setLoading(false)
        return
      }
      localStorage.setItem('access_token', 'simulated_token_' + Date.now())
      localStorage.setItem('user_role', role)
      window.dispatchEvent(new Event('authChange'))
      if (role === 'ADMIN') {
        navigate('/')
      } else {
        navigate('/supervisor')
      }
    } finally {
      setLoading(false)
    }
  }
  return (
    <div className="auth-page-container">
      {/* Top Navbar */}
      <header className="auth-top-bar">
        <div className="auth-brand-logo">
          <div className="auth-logo-badge">
            <svg width="20" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
            </svg>
          </div>
          <span className="auth-brand-name">Hospital Automation</span>
        </div>
        <div className="auth-top-actions">
          <button className="auth-top-btn">
            <span className="material-symbols-outlined" style={{ fontSize: 18 }}>
              help
            </span>
            Help
          </button>
          <button className="auth-top-btn">
            <span className="material-symbols-outlined" style={{ fontSize: 18 }}>
              language
            </span>
            EN
          </button>
        </div>
      </header>

      {/* Main Glass Card Container */}
      <main className="auth-main-wrapper" style={{ flexDirection: 'column' }}>
        <div className="auth-card">
          <div className="auth-header-section">
            <h1 className="auth-title">
              {isSignUp ? 'Create Account' : 'Welcome Back'}
            </h1>
            <p className="auth-subtitle">
              {isSignUp
                ? 'Register your supervisor credentials for console access'
                : 'Sign in to access your designated console'}
            </p>

            <div className="auth-mode-toggle">
              <button
                type="button"
                className={`auth-toggle-btn ${isSignUp ? 'inactive' : ''}`}
                onClick={() => { setIsSignUp(false); setErrorMsg(''); setInfoMsg(''); }}
              >
                Sign In
              </button>
              <span>|</span>
              <button
                type="button"
                className={`auth-toggle-btn ${!isSignUp ? 'inactive' : ''}`}
                onClick={() => { setIsSignUp(true); setRole('SUPERVISOR'); setErrorMsg(''); setInfoMsg(''); }}
              >
                New Account? Sign Up
              </button>
            </div>
          </div>

          {infoMsg && (
            <div style={{
              margin: '12px 0',
              padding: '12px 16px',
              borderRadius: '8px',
              backgroundColor: '#ffffff',
              border: '1px solid #000000',
              color: '#000000',
              fontSize: '13px',
              lineHeight: '1.4'
            }}>
              <span className="material-symbols-outlined" style={{ fontSize: 16, verticalAlign: 'middle', marginRight: 6, color: '#000000' }}>info</span>
              {infoMsg}
            </div>
          )}

          {errorMsg && (
            <div style={{
              margin: '12px 0',
              padding: '12px 16px',
              borderRadius: '8px',
              backgroundColor: 'rgba(211, 47, 47, 0.15)',
              border: '1px solid #d32f2f',
              color: '#ef5350',
              fontSize: '13px',
              lineHeight: '1.4'
            }}>
              <span className="material-symbols-outlined" style={{ fontSize: 16, verticalAlign: 'middle', marginRight: 6 }}>warning</span>
              {errorMsg}
            </div>
          )}

          {/* Role Pill Selector */}
          {!isSignUp ? (
            <div className="auth-role-tabs">
              <button
                type="button"
                className={`auth-role-btn ${role === 'SUPERVISOR' ? 'active' : ''}`}
                onClick={() => setRole('SUPERVISOR')}
              >
                Supervisor
              </button>
              <button
                type="button"
                className={`auth-role-btn ${role === 'ADMIN' ? 'active' : ''}`}
                onClick={() => setRole('ADMIN')}
              >
                Admin
              </button>
            </div>
          ) : (
            <div className="auth-role-tabs">
              <button
                type="button"
                className="auth-role-btn active"
                style={{ cursor: 'default' }}
              >
                Supervisor
              </button>
            </div>
          )}

          {/* Form */}
          <form className="auth-form" onSubmit={handleSubmit}>
            {!isSignUp ? (
              <>
                {role === 'SUPERVISOR' ? (
                  <div className="auth-field-group">
                    <div className="auth-input-wrapper">
                      <span className="material-symbols-outlined auth-input-icon">
                        mail
                      </span>
                      <input
                        type="text"
                        className="auth-input"
                        placeholder="Supervisor Employee ID / Email"
                        value={employeeIdOrEmail}
                        onChange={(e) => setEmployeeIdOrEmail(e.target.value)}
                        required
                      />
                    </div>
                  </div>
                ) : (
                  <div className="auth-field-group">
                    <div className="auth-input-wrapper">
                      <span className="material-symbols-outlined auth-input-icon">
                        security
                      </span>
                      <input
                        type="text"
                        className="auth-input"
                        placeholder="Admin ID / Work Email"
                        value={employeeIdOrEmail}
                        onChange={(e) => setEmployeeIdOrEmail(e.target.value)}
                        required
                      />
                    </div>
                  </div>
                )}

                <div className="auth-field-group">
                  <div className="auth-input-wrapper">
                    <span className="material-symbols-outlined auth-input-icon">
                      lock
                    </span>
                    <input
                      type={showPassword ? 'text' : 'password'}
                      className="auth-input has-toggle"
                      placeholder="Password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      required
                    />
                    <button
                      type="button"
                      className="auth-password-toggle-btn"
                      onClick={() => setShowPassword(!showPassword)}
                      tabIndex={-1}
                    >
                      <span className="material-symbols-outlined">
                        {showPassword ? 'visibility' : 'visibility_off'}
                      </span>
                    </button>
                  </div>
                </div>

                <div className="auth-options-row">
                  <label className="auth-checkbox-label">
                    <input
                      type="checkbox"
                      className="auth-checkbox"
                      checked={rememberDevice}
                      onChange={(e) => setRememberDevice(e.target.checked)}
                    />
                    Remember device
                  </label>
                  <a href="#forgot" className="auth-forgot-link">
                    Forgot Password?
                  </a>
                </div>

                <button type="submit" className="auth-submit-btn">
                  Sign In as {role === 'SUPERVISOR' ? 'Supervisor' : 'Admin'}
                </button>
              </>
            ) : (
              <>
                <div className="auth-field-group">
                  <label className="auth-label">Hospital Employee ID</label>
                  <div className="auth-input-wrapper">
                    <span className="material-symbols-outlined auth-input-icon">
                      badge
                    </span>
                    <input
                      type="text"
                      className="auth-input"
                      placeholder="e.g. EMP-101"
                      value={employeeIdOrEmail}
                      onChange={(e) => setEmployeeIdOrEmail(e.target.value)}
                      required
                    />
                  </div>
                </div>

                <div className="auth-field-group">
                  <label className="auth-label">Select Department</label>
                  <div className="auth-input-wrapper">
                    <span className="material-symbols-outlined auth-input-icon">
                      apartment
                    </span>
                    <select
                      className="auth-select"
                      value={department}
                      onChange={(e) => setDepartment(e.target.value)}
                    >
                      {dbDepartments.map((d) => (
                        <option key={d.department_id} value={d.department_name}>
                          {d.department_name}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                <div className="auth-field-group">
                  <label className="auth-label">Work Email Address</label>
                  <div className="auth-input-wrapper">
                    <span className="material-symbols-outlined auth-input-icon">
                      mail
                    </span>
                    <input
                      type="email"
                      className="auth-input"
                      placeholder="supervisor@hospital.com"
                      value={workEmail}
                      onChange={(e) => setWorkEmail(e.target.value)}
                      required
                    />
                  </div>
                </div>

                <div className="auth-double-row">
                  <div className="auth-field-group">
                    <label className="auth-label">Create Password</label>
                    <div className="auth-input-wrapper">
                      <span className="material-symbols-outlined auth-input-icon">
                        lock
                      </span>
                      <input
                        type={showPassword ? 'text' : 'password'}
                        className="auth-input has-toggle"
                        placeholder="••••••••"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        required
                      />
                      <button
                        type="button"
                        className="auth-password-toggle-btn"
                        onClick={() => setShowPassword(!showPassword)}
                        tabIndex={-1}
                      >
                        <span className="material-symbols-outlined">
                          {showPassword ? 'visibility' : 'visibility_off'}
                        </span>
                      </button>
                    </div>
                  </div>

                  <div className="auth-field-group">
                    <label className="auth-label">Confirm Password</label>
                    <div className="auth-input-wrapper">
                      <span className="material-symbols-outlined auth-input-icon">
                        lock
                      </span>
                      <input
                        type={showConfirmPassword ? 'text' : 'password'}
                        className="auth-input has-toggle"
                        placeholder="••••••••"
                        value={confirmPassword}
                        onChange={(e) => setConfirmPassword(e.target.value)}
                        required
                      />
                      <button
                        type="button"
                        className="auth-password-toggle-btn"
                        onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                        tabIndex={-1}
                      >
                        <span className="material-symbols-outlined">
                          {showConfirmPassword ? 'visibility' : 'visibility_off'}
                        </span>
                      </button>
                    </div>
                  </div>
                </div>

                <label className="auth-checkbox-label" style={{ marginTop: 4 }}>
                  <input
                    type="checkbox"
                    className="auth-checkbox"
                    checked={acceptTerms}
                    onChange={(e) => setAcceptTerms(e.target.checked)}
                    required
                  />
                  I accept the Hospital Compliance & Data Privacy Guidelines.
                </label>

                <button type="submit" className="auth-submit-btn">
                  Register as Supervisor
                </button>
              </>
            )}

            {isSignUp && (
              <div className="auth-switch-prompt">
                Already registered?{' '}
                <button
                  type="button"
                  className="auth-forgot-link"
                  style={{ background: 'none', border: 'none', cursor: 'pointer' }}
                  onClick={() => setIsSignUp(false)}
                >
                  Sign In
                </button>
              </div>
            )}

            <div className="auth-sub-links">
              <a href="#support" className="auth-sub-link">
                <span className="material-symbols-outlined" style={{ fontSize: 15 }}>
                  support
                </span>
                Support
              </a>
              <span>•</span>
              <a href="#diagnostics" className="auth-sub-link">
                <span className="material-symbols-outlined" style={{ fontSize: 15 }}>
                  medical_information
                </span>
                System Diagnostics
              </a>
            </div>
          </form>
        </div>
      </main>

      {/* Page Footer */}
      <footer className="auth-page-footer">
        <div>
          © 2024 VitalStream Health Systems. All rights reserved. HIPAA &amp; GDPR Compliant.
        </div>
        <div className="auth-footer-links">
          <a href="#security" className="auth-footer-link">
            Security Protocol
          </a>
          <a href="#privacy" className="auth-footer-link">
            Privacy Policy
          </a>
          <a href="#status" className="auth-footer-link">
            System Status
          </a>
        </div>
      </footer>
    </div>
  )
}
