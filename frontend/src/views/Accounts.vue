<template>
  <div>
    <div class="page-header">
      <div><h2>账号与权限管理</h2><p>统一创建管理员、采购员、订单员、仓管员和供应商账号，并按模块分配权限</p></div>
      <div class="header-actions"><el-button type="danger" plain :disabled="!selected.length" @click="batchRemove">批量删除（{{ selected.length }}）</el-button><el-button type="primary" @click="openCreate"><el-icon><Plus /></el-icon>新增账号</el-button></div>
    </div>
    <el-card class="panel">
      <el-table :data="rows" @selection-change="selected = $event">
        <el-table-column type="selection" width="46" :selectable="row => row.id !== currentUser?.id" />
        <el-table-column prop="username" label="登录账号" min-width="140" />
        <el-table-column prop="name" label="姓名/名称" min-width="140" />
        <el-table-column label="角色" width="110"><template #default="scope"><el-tag>{{ roleLabel(scope.row.role) }}</el-tag></template></el-table-column>
        <el-table-column label="关联供应商" min-width="160"><template #default="scope">{{ supplierName(scope.row.supplier_id) }}</template></el-table-column>
        <el-table-column label="权限" min-width="260"><template #default="scope"><el-tag v-for="item in scope.row.permissions" :key="item" type="info" class="permission-tag">{{ permissionLabel(item) }}</el-tag><span v-if="!scope.row.permissions.length" class="muted">未分配</span></template></el-table-column>
        <el-table-column label="状态" width="90"><template #default="scope"><el-tag :type="scope.row.active ? 'success' : 'info'">{{ scope.row.active ? '启用' : '停用' }}</el-tag></template></el-table-column>
        <el-table-column label="操作" width="205" fixed="right"><template #default="scope"><el-button link type="primary" @click="openEdit(scope.row)">编辑</el-button><el-button v-if="scope.row.id !== currentUser?.id" link :type="scope.row.active ? 'warning' : 'success'" @click="toggle(scope.row)">{{ scope.row.active ? '禁用' : '启用' }}</el-button><el-button v-if="scope.row.id !== currentUser?.id" link type="danger" @click="remove(scope.row)">删除</el-button></template></el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="visible" :title="form.id ? '编辑账号' : '新增账号'" width="680px">
      <el-form label-width="105px">
        <el-row :gutter="16">
          <el-col :span="12"><el-form-item label="登录账号" required><el-input v-model="form.username" autocomplete="off" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="姓名/名称" required><el-input v-model="form.name" /></el-form-item></el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12"><el-form-item label="账号角色" required><el-select v-model="form.role" style="width:100%" @change="changeRole"><el-option v-for="item in roles" :key="item.value" :label="item.label" :value="item.value" /></el-select></el-form-item></el-col>
          <el-col :span="12"><el-form-item :label="form.id ? '重置密码' : '登录密码'" :required="!form.id"><el-input v-model="form.password" type="password" show-password autocomplete="new-password" :placeholder="form.id ? '留空表示不修改' : '至少 6 位'" /></el-form-item></el-col>
        </el-row>
        <el-form-item v-if="form.role === 'supplier'" label="关联供应商" required><el-select v-model="form.supplier_id" filterable placeholder="请选择已有供应商" style="width:100%"><el-option v-for="item in activeSuppliers" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item>
        <el-form-item label="账号状态"><el-switch v-model="form.active" active-text="启用" inactive-text="停用" :disabled="form.id === currentUser?.id" /></el-form-item>
        <el-divider>功能权限</el-divider>
        <el-checkbox-group v-model="form.permissions" class="permission-grid">
          <el-checkbox v-for="item in permissionOptions" :key="item.value" :value="item.value" border><span>{{ item.label }}</span><small>{{ item.description }}</small></el-checkbox>
        </el-checkbox-group>
      </el-form>
      <template #footer><el-button @click="visible = false">取消</el-button><el-button type="primary" @click="save">保存账号</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { batchDeleteAccounts, createAccount, deleteAccount, getAccounts, getSuppliers, updateAccount } from '@/api'
import { getUser, updateUser } from '@/utils/auth'

const currentUser = getUser()
const rows = ref([])
const suppliers = ref([])
const selected = ref([])
const visible = ref(false)
const roles = [{ value: 'admin', label: '管理员' }, { value: 'purchaser', label: '采购员' }, { value: 'order_clerk', label: '订单员' }, { value: 'warehouse', label: '仓管员' }, { value: 'supplier', label: '供应商' }]
const permissionOptions = [
  { value: 'dashboard', label: '工作台', description: '查看业务概览' },
  { value: 'account_management', label: '账号管理', description: '创建账号并设置权限' },
  { value: 'supplier_management', label: '供应商管理', description: '维护供应商档案' },
  { value: 'category_management', label: '分类管理', description: '维护商品分类' },
  { value: 'product_management', label: '商品管理', description: '维护商品与绑定供应商' },
  { value: 'assignment_management', label: '商品分配', description: '向供应商分配商品' },
  { value: 'quote_management', label: '供应商报价', description: '维护已分配商品报价' },
  { value: 'analysis', label: '智能比价', description: '查看报价分析' },
  { value: 'inventory', label: '库存查询', description: '查询库存数据' },
  { value: 'inventory_update', label: '库存更新', description: '上传并替换库存表' },
  { value: 'order_management', label: '采购下单', description: '创建订单与下载报表' },
  { value: 'smart_split_management', label: '智能拆单', description: '配置供应规则并生成多供应商采购单' },
  { value: 'supplier_order_view', label: '供应商采购订单', description: '供应商查看已下达订单' },
  { value: 'staff_management', label: '分拣配送人员', description: '维护分拣员和配送员' },
  { value: 'customer_management', label: '客户管理', description: '客户及人员分配' },
  { value: 'sales_order_management', label: '销售单', description: '快捷录入及确认销售单' },
  { value: 'sales_summary', label: '销售汇总', description: '多维汇总及导出 Excel' },
  { value: 'wecom_management', label: '企业微信订单助手', description: '微信客户绑定、消息及订单草稿' },
  { value: 'complaint_management', label: '投诉专栏', description: '处理客户投诉及食品安全升级' },
  { value: 'inbound_management', label: '进货管理', description: '进货、明细查询及进货退货' },
  { value: 'warehouse_management', label: '仓库管理', description: '入库、出库、领料、备货与库存台账' },
  { value: 'label_printing', label: '标签打印', description: '按客户订单或自定义批量打印标签' },
  { value: 'picking_management', label: '扫码分拣', description: '生成分拣任务、扫码确认和查看进度' },
  { value: 'picking_monitor', label: '分拣配送监控', description: '查看人员工作量、客户耗时和单品操作时间' },
  { value: 'finance_management', label: '财务管理', description: '查看销售、验收、开票和毛利数据' },
  { value: 'report_management', label: '报表管理', description: '查看运营统计、利润和进销存报表' },
  { value: 'deletion_approval', label: '删除审核', description: '仅管理员可批准或驳回删除申请' },
]
const roleDefaults = {
  admin: permissionOptions.filter(item => item.value !== 'finance_management').map(item => item.value),
  purchaser: ['dashboard', 'account_management', 'supplier_management', 'category_management', 'product_management', 'assignment_management', 'analysis', 'inventory', 'inventory_update', 'order_management', 'smart_split_management', 'staff_management', 'customer_management', 'sales_order_management', 'sales_summary', 'wecom_management', 'complaint_management', 'inbound_management', 'warehouse_management', 'label_printing', 'picking_management', 'picking_monitor'],
  order_clerk: ['dashboard', 'sales_order_management', 'sales_summary', 'wecom_management', 'complaint_management', 'label_printing', 'picking_management', 'picking_monitor'],
  warehouse: ['dashboard', 'inventory', 'inventory_update', 'staff_management', 'customer_management', 'inbound_management', 'warehouse_management', 'label_printing', 'picking_management', 'picking_monitor'],
  supplier: ['dashboard', 'product_management', 'quote_management', 'inventory', 'supplier_order_view'],
}
const blank = () => ({ id: null, username: '', password: '', name: '', role: 'purchaser', supplier_id: null, active: true, permissions: [...roleDefaults.purchaser] })
const form = reactive(blank())
const activeSuppliers = computed(() => suppliers.value.filter(item => item.active || item.id === form.supplier_id))
const load = async () => { [rows.value, suppliers.value] = await Promise.all([getAccounts(), getSuppliers()]) }
const roleLabel = role => roles.find(item => item.value === role)?.label || role
const permissionLabel = value => permissionOptions.find(item => item.value === value)?.label || value
const supplierName = id => id ? suppliers.value.find(item => item.id === id)?.name || `供应商 #${id}` : '—'
const changeRole = role => { form.permissions = [...(roleDefaults[role] || [])]; if (role !== 'supplier') form.supplier_id = null }
const openCreate = () => { Object.assign(form, blank()); visible.value = true }
const openEdit = row => { Object.assign(form, blank(), row, { password: '', permissions: [...row.permissions] }); visible.value = true }
const payload = () => ({ username: form.username.trim(), password: form.password || null, name: form.name.trim(), role: form.role, supplier_id: form.role === 'supplier' ? form.supplier_id : null, active: form.active, permissions: form.permissions })
const save = async () => {
  if (!form.username.trim() || !form.name.trim()) return ElMessage.warning('请填写登录账号和姓名')
  if (!form.id && (!form.password || form.password.length < 6)) return ElMessage.warning('登录密码至少 6 位')
  if (form.password && form.password.length < 6) return ElMessage.warning('登录密码至少 6 位')
  if (form.role === 'supplier' && !form.supplier_id) return ElMessage.warning('请选择关联供应商')
  let saved
  if (form.id) saved = await updateAccount(form.id, payload())
  else saved = await createAccount({ ...payload(), password: form.password })
  if (saved.id === currentUser?.id) updateUser(saved)
  ElMessage.success('账号保存成功')
  visible.value = false
  await load()
}
const toggle = async row => { await updateAccount(row.id, { ...row, password: null, active: !row.active }); ElMessage.success(row.active ? '账号已禁用' : '账号已启用'); await load() }
const remove = async row => { await ElMessageBox.confirm(`确认提交账号“${row.username}”的删除申请吗？管理员审核前不会删除。`, '提交删除申请', { type: 'warning' }); const result = await deleteAccount(row.id); ElMessage.success(result.message); await load() }
const batchRemove = async () => { await ElMessageBox.confirm(`确认提交选中的 ${selected.value.length} 个账号的删除申请吗？`, '批量提交删除申请', { type: 'warning' }); const result = await batchDeleteAccounts(selected.value.map(item => item.id)); ElMessage.success(result.message); await load() }
onMounted(load)
</script>

<style scoped>
.header-actions { display: flex; gap: 10px; }
.permission-tag { margin: 2px 5px 2px 0; }
.muted { color: #a0a8b5; }
.permission-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
.permission-grid :deep(.el-checkbox) { width: 100%; height: auto; min-height: 58px; margin: 0; padding: 9px 12px; align-items: flex-start; }
.permission-grid :deep(.el-checkbox__label) { display: flex; flex-direction: column; line-height: 20px; }
.permission-grid small { color: #9099a8; }
</style>
