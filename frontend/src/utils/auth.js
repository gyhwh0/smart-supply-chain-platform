const TOKEN_KEY = 'procurement_token'
const USER_KEY = 'procurement_user'

export const getToken = () => localStorage.getItem(TOKEN_KEY)
export const getUser = () => {
  try { return JSON.parse(localStorage.getItem(USER_KEY) || 'null') } catch { return null }
}
export const setSession = (token, user) => {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(USER_KEY, JSON.stringify(user))
  window.dispatchEvent(new CustomEvent('auth-user-updated', { detail: user }))
}
export const updateUser = (user) => {
  localStorage.setItem(USER_KEY, JSON.stringify(user))
  window.dispatchEvent(new CustomEvent('auth-user-updated', { detail: user }))
}
export const logout = () => {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
  window.dispatchEvent(new CustomEvent('auth-user-updated', { detail: null }))
}

export const hasPermission = (permission) => {
  const user = getUser()
  return user?.permissions?.includes(permission) ?? false
}
