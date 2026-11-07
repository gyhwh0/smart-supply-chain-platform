const { apiBase } = require('./config')

App({
  globalData: { apiBase, token: '', profile: null },
  onLaunch() { this.login() },
  login() {
    if (this._loginPromise) return this._loginPromise
    this._loginPromise = new Promise((resolve, reject) => {
      wx.login({
        success: ({ code }) => {
          if (!code) return reject(new Error('未取得微信登录凭证'))
          wx.request({
            url: `${apiBase}/api/mini/login`, method: 'POST', data: { code },
            success: ({ statusCode, data }) => {
              if (statusCode >= 400) return reject(new Error(data.detail || '登录失败'))
              this.globalData.token = data.token
              this.globalData.profile = data
              wx.setStorageSync('mini_token', data.token)
              resolve(data)
            },
            fail: reject
          })
        }, fail: reject
      })
    })
    this._loginPromise.then(
      () => { this._loginPromise = null },
      () => { this._loginPromise = null }
    )
    return this._loginPromise
  }
})
