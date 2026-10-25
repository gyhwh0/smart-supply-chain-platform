import axios from 'axios'
import { ElMessage } from 'element-plus'
import router from '@/router'
import { getToken, logout } from './auth'

const request = axios.create({ baseURL: import.meta.env.VITE_API_BASE_URL || '', timeout: 30000 })

request.interceptors.request.use((config) => {
  const token = getToken()
  if (token && !config.headers.Authorization) config.headers.Authorization = `Bearer ${token}`
  return config
})

request.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const message = error.response?.data?.detail || error.message || '请求失败'
    ElMessage.error(message)
    if (error.response?.status === 401 && !error.config?.headers?.['X-Staff-Mobile']) {
      logout()
      router.push('/login')
    }
    return Promise.reject(error)
  }
)

export default request
