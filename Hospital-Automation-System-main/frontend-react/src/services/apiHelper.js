/**
 * Central authenticated fetch wrapper.
 *
 * Reads the JWT from localStorage and appends the Authorization header.
 * Sets Content-Type to application/json only when a body is present
 * and the body is not FormData (file uploads need the browser to
 * calculate the multipart boundary automatically).
 */
export async function authFetch(url, options = {}) {
  const token = localStorage.getItem('access_token')
  const headers = { ...options.headers }
  const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')
  const requestUrl = /^https?:\/\//i.test(url)
    ? url
    : `${apiBaseUrl}${url.startsWith('/') ? url : `/${url}`}`

  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }

  if (options.body && !(options.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json'
  }

  const response = await fetch(requestUrl, { ...options, headers })

  // Auto-logout on expired/invalid token (skip public auth endpoints)
  if (response.status === 401
      && !url.includes('/auth/login')
      && !url.includes('/auth/signup')) {
    localStorage.removeItem('access_token')
    localStorage.removeItem('user_role')
    localStorage.removeItem('user_email')
    window.dispatchEvent(new Event('authChange'))
    window.location.href = '/auth'
  }

  return response
}
