<template>
  <div>
    <div class="page-header">
      <div><h2>供应商管理</h2><p>维护供应商档案、报价账号及合作状态</p></div>
      <div class="header-actions"><el-button type="danger" plain :disabled="!selected.length" @click="batchRemove">批量删除（{{ selected.length }}）</el-button><el-button type="primary" @click="openCreate"><el-icon><Plus /></el-icon>新增供应商</el-button></div>
    </div>
    <el-card class="panel">
      <el-table :data="rows" @selection-change="selected = $event">
        <el-table-column type="selection" width="46" />
        <el-table-column prop="name" label="供应商" min-width="170" />
        <el-table-column prop="contact_name" label="联系人" min-width="110" />
        <el-table-column prop="phone" label="电话" min-width="130" />
        <el-table-column prop="email" label="邮箱" min-width="180" show-overflow-tooltip />
        <el-table-column label="状态" width="90"><template #default="scope"><el-tag :type="scope.row.active ? 'success' : 'info'">{{ scope.row.active ? '合作中' : '已停用' }}</el-tag></template></el-table-column>
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="scope">
            <el-button link type="primary" @click="openEdit(scope.row)">编辑</el-button>
            <el-button link :type="scope.row.active ? 'warning' : 'success'" @click="toggle(scope.row)">{{ scope.row.active ? '禁用' : '启用' }}</el-button>
            <el-button link type="danger" @click="remove(scope.row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
    <el-dialog v-model="visible" :title="form.id ? '编辑供应商' : '新增供应商'" width="580px">
      <el-form label-width="105px">
        <el-form-item label="供应商名称" required><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="联系人"><el-input v-model="form.contact_name" /></el-form-item>
        <el-form-item label="联系电话"><el-input v-model="form.phone" /></el-form-item>
        <el-form-item label="邮箱"><el-input v-model="form.email" /></el-form-item>
        <el-form-item label="地址"><el-input v-model="form.address" /></el-form-item>
        <template v-if="!form.id">
          <el-divider>供应商登录账号（可选）</el-divider>
          <el-form-item label="登录账号"><el-input v-model="form.login_username" autocomplete="off" /></el-form-item>
          <el-form-item label="登录密码"><el-input v-model="form.login_password" type="password" show-password autocomplete="new-password" /></el-form-item>
        </template>
        <el-form-item v-else label="合作状态"><el-switch v-model="form.active" active-text="启用" inactive-text="停用" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="visible = false">取消</el-button><el-button type="primary" @click="save">保存</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { batchDeleteSuppliers, createSupplier, deleteSupplier, getSuppliers, updateSupplier } from '@/api'

const rows = ref([])
const selected = ref([])
const visible = ref(false)
const blank = () => ({ id: null, name: '', contact_name: '', phone: '', email: '', address: '', login_username: '', login_password: '', active: true })
const form = reactive(blank())
const load = async () => { rows.value = await getSuppliers() }
const openCreate = () => { Object.assign(form, blank()); visible.value = true }
const openEdit = (row) => { Object.assign(form, blank(), row); visible.value = true }
const payload = () => ({ name: form.name.trim(), contact_name: form.contact_name || null, phone: form.phone || null, email: form.email || null, address: form.address || null, active: form.active })
const save = async () => {
  if (!form.name.trim()) return ElMessage.warning('请输入供应商名称')
  if (!form.id && form.login_username && !form.login_password) return ElMessage.warning('设置登录账号后请填写密码')
  if (form.id) await updateSupplier(form.id, payload())
  else await createSupplier({ ...payload(), login_username: form.login_username || null, login_password: form.login_password || null })
  ElMessage.success('保存成功')
  visible.value = false
  await load()
}
const toggle = async (row) => {
  await updateSupplier(row.id, { ...row, active: !row.active })
  ElMessage.success(row.active ? '供应商已禁用' : '供应商已启用')
  await load()
}
const remove = async (row) => {
  await ElMessageBox.confirm(`确认删除“${row.name}”吗？若已有分配或报价，将改为安全禁用并保留历史数据。`, '删除供应商', { type: 'warning' })
  const result = await deleteSupplier(row.id)
  ElMessage.success(result.message)
  await load()
}
const batchRemove = async () => {
  await ElMessageBox.confirm(`确认批量处理选中的 ${selected.value.length} 家供应商吗？有历史数据时将安全禁用。`, '批量删除', { type: 'warning' })
  const result = await batchDeleteSuppliers(selected.value.map(item => item.id))
  ElMessage.success(result.message)
  await load()
}
onMounted(load)
</script>

<style scoped>.header-actions { display:flex; gap:10px; }</style>
