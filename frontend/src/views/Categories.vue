<template>
  <div>
    <div class="page-header">
      <div><h2>分类管理</h2><p>统一维护商品分类，新增商品时直接选择，批量分配时也可按分类操作</p></div>
      <div class="header-actions"><el-button type="danger" plain :disabled="!selected.length" @click="batchRemove">批量删除（{{ selected.length }}）</el-button><el-button type="primary" @click="openCreate"><el-icon><Plus /></el-icon>新增分类</el-button></div>
    </div>
    <el-card class="panel">
      <el-table :data="rows" @selection-change="selected = $event">
        <el-table-column type="selection" width="46" />
        <el-table-column prop="name" label="分类名称" min-width="180" />
        <el-table-column prop="description" label="说明" min-width="280" show-overflow-tooltip />
        <el-table-column label="状态" width="100">
          <template #default="scope"><el-tag :type="scope.row.active ? 'success' : 'info'">{{ scope.row.active ? '启用' : '停用' }}</el-tag></template>
        </el-table-column>
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="scope">
            <el-button link type="primary" @click="openEdit(scope.row)">编辑</el-button>
            <el-button link :type="scope.row.active ? 'warning' : 'success'" @click="toggle(scope.row)">{{ scope.row.active ? '禁用' : '启用' }}</el-button>
            <el-button link type="danger" @click="remove(scope.row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
    <el-dialog v-model="visible" :title="form.id ? '编辑分类' : '新增分类'" width="520px">
      <el-form label-width="90px">
        <el-form-item label="分类名称" required><el-input v-model="form.name" maxlength="100" show-word-limit /></el-form-item>
        <el-form-item label="分类说明"><el-input v-model="form.description" type="textarea" :rows="3" maxlength="255" show-word-limit /></el-form-item>
        <el-form-item v-if="form.id" label="状态"><el-switch v-model="form.active" active-text="启用" inactive-text="停用" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="visible = false">取消</el-button><el-button type="primary" @click="save">保存</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { batchDeleteCategories, createCategory, deleteCategory, getCategories, updateCategory } from '@/api'

const rows = ref([])
const selected = ref([])
const visible = ref(false)
const blank = () => ({ id: null, name: '', description: '', active: true })
const form = reactive(blank())
const load = async () => { rows.value = await getCategories() }
const openCreate = () => { Object.assign(form, blank()); visible.value = true }
const openEdit = (row) => { Object.assign(form, blank(), row); visible.value = true }
const save = async () => {
  if (!form.name.trim()) return ElMessage.warning('请输入分类名称')
  if (form.id) await updateCategory(form.id, form)
  else await createCategory(form)
  ElMessage.success('保存成功')
  visible.value = false
  await load()
}
const toggle = async (row) => {
  await updateCategory(row.id, { name: row.name, description: row.description, active: !row.active })
  ElMessage.success(row.active ? '分类已禁用' : '分类已启用')
  await load()
}
const remove = async (row) => {
  await ElMessageBox.confirm(`确认删除“${row.name}”吗？若已有商品，系统会改为安全禁用。`, '删除分类', { type: 'warning' })
  const result = await deleteCategory(row.id)
  ElMessage.success(result.message)
  await load()
}
const batchRemove = async () => {
  await ElMessageBox.confirm(`确认批量处理选中的 ${selected.value.length} 个分类吗？有关联商品时将安全禁用。`, '批量删除', { type: 'warning' })
  const result = await batchDeleteCategories(selected.value.map(item => item.id))
  ElMessage.success(result.message)
  await load()
}
onMounted(load)
</script>

<style scoped>.header-actions { display:flex; gap:10px; }</style>
