const { apiBase } = require('../config')

async function request(path, options = {}) {
  const app = getApp()
  let token = app.globalData.token || wx.getStorageSync('mini_token')
  if (!token && path !== '/api/mini/login') {
    const login = await app.login()
    token = login.token
  }
  return new Promise((resolve, reject) => {
    wx.request({
      url: `${apiBase}${path}`,
      method: options.method || 'GET', data: options.data,
      header: token ? { Authorization: `Bearer ${token}` } : {},
      success: ({ statusCode, data }) => {
        if (statusCode === 401) wx.removeStorageSync('mini_token')
        if (statusCode >= 400) return reject(new Error(data.detail || '请求失败'))
        resolve(data)
      }, fail: reject
    })
  })
}

module.exports = request
