<template>
  <div class="login-page">
    <div class="intro"><div class="logo">嘉</div><h1>让每一次采购<br />都有数据依据</h1><p>供应商协同报价 · 多单位智能换算 · AI 价格洞察</p></div>
    <el-card class="login-card">
      <h2>欢迎登录</h2><p class="muted">进入嘉采供应链管理平台</p>
      <el-form :model="form" @keyup.enter="submit">
        <el-form-item><el-input v-model="form.username" size="large" placeholder="账号" prefix-icon="User" /></el-form-item>
        <el-form-item><el-input v-model="form.password" type="password" show-password size="large" placeholder="密码" prefix-icon="Lock" /></el-form-item>
        <el-button type="primary" size="large" :loading="loading" style="width:100%" @click="submit">登录系统</el-button>
      </el-form>
      <div class="demo">演示采购员：buyer / buyer123</div>
    </el-card>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { loginApi } from '@/api'
import { setSession } from '@/utils/auth'
const router = useRouter(); const loading = ref(false)
const form = reactive({ username: 'buyer', password: 'buyer123' })
const submit = async () => { loading.value = true; try { const res = await loginApi(form); setSession(res.token,res.user); ElMessage.success('登录成功'); router.push('/') } finally { loading.value=false } }
</script>

<style scoped>
.login-page{min-height:100vh;display:grid;grid-template-columns:1.2fr 1fr;background:linear-gradient(135deg,#11213d 0%,#173861 55%,#f4f7fb 55%)}.intro{color:white;align-self:center;padding-left:13vw}.logo{width:56px;height:56px;display:grid;place-items:center;background:#55c6a9;border-radius:16px;font-size:26px;font-weight:800}.intro h1{font-size:46px;line-height:1.25;margin:24px 0 16px}.intro p{color:#aec1d9;font-size:17px}.login-card{width:430px;align-self:center;justify-self:center;padding:28px;border:0;border-radius:18px}.login-card h2{font-size:28px;margin:0 0 8px}.login-card .el-form{margin-top:32px}.demo{margin-top:20px;text-align:center;color:#8b93a5;font-size:13px}
</style>
