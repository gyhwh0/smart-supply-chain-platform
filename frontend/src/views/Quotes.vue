<template>
  <div>
    <div class="page-header">
      <div><h2>我的报价</h2><p>填写各计价单位价格，可单独保存，也可一键保存页面内全部报价</p></div>
      <el-button type="primary" size="large" :loading="savingAll" :disabled="!filledItems.length" @click="submitAll"><el-icon><Select /></el-icon>一键保存全部（{{ filledItems.length }}）</el-button>
    </div>

    <el-row :gutter="14" class="metrics">
      <el-col :span="6"><el-card class="panel metric"><span>已分配商品</span><strong>{{ rows.length }}</strong></el-card></el-col>
      <el-col :span="6"><el-card class="panel metric"><span>待报价单位</span><strong class="warning">{{ pendingUnitCount }}</strong></el-card></el-col>
      <el-col :span="6"><el-card class="panel metric"><span>已报价单位</span><strong class="success">{{ quotedUnitCount }}</strong></el-card></el-col>
      <el-col :span="6"><el-card class="panel metric"><span>未保存修改</span><strong :class="dirtyCount ? 'danger' : ''">{{ dirtyCount }}</strong></el-card></el-col>
    </el-row>

    <el-card class="panel filters">
      <el-input v-model="keyword" clearable placeholder="搜索商品名称或 SKU" prefix-icon="Search" />
      <el-select v-model="category" clearable placeholder="全部品类"><el-option v-for="item in categories" :key="item" :label="item" :value="item" /></el-select>
      <el-select v-model="status" placeholder="全部状态"><el-option label="全部状态" value="all" /><el-option label="待报价" value="pending" /><el-option label="已报价" value="quoted" /><el-option label="有未保存修改" value="dirty" /></el-select>
    </el-card>

    <el-row :gutter="18" class="quote-grid">
      <el-col v-for="row in filteredRows" :key="row.id" :span="12">
        <el-card class="panel quote-card">
          <div class="quote-head">
            <div><span>{{ row.product.category }}</span><h3>{{ row.product.name }}</h3><small>{{ row.product.sku || '无 SKU' }}</small></div>
            <el-tag :type="rowStatus(row).type">{{ rowStatus(row).text }}</el-tag>
          </div>
          <div v-for="unit in row.product.units" :key="unit.id" class="quote-line" :class="{ dirty: isDirty(row.id, unit.id) }">
            <div class="unit"><strong>{{ unit.name }}</strong><small>{{ unit.is_base ? '基础单位' : `1 ${unit.name} = ${unit.conversion_rate} 基础单位` }}</small></div>
            <div class="price-input"><span>¥</span><el-input-number v-model="drafts[key(row.id, unit.id)]" :min="0.01" :precision="2" controls-position="right" placeholder="输入价格" /></div>
            <el-tag v-if="isDirty(row.id, unit.id)" type="warning" effect="plain">未保存</el-tag><el-tag v-else-if="original[key(row.id, unit.id)]" type="success" effect="plain">已保存</el-tag><el-tag v-else type="info" effect="plain">待填写</el-tag>
            <el-button type="primary" plain :loading="savingKeys.has(key(row.id, unit.id))" @click="submit(row, unit)">保存</el-button>
          </div>
        </el-card>
      </el-col>
    </el-row>
    <el-empty v-if="!filteredRows.length" description="没有符合筛选条件的报价任务" />
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getAssignments, saveQuote, saveQuotesBatch } from '@/api'

const rows = ref([])
const drafts = reactive({})
const original = reactive({})
const keyword = ref('')
const category = ref('')
const status = ref('all')
const savingAll = ref(false)
const savingKeys = reactive(new Set())
const key = (assignmentId, unitId) => `${assignmentId}-${unitId}`
const categories = computed(() => [...new Set(rows.value.map(row => row.product.category))].sort())
const allUnits = computed(() => rows.value.flatMap(row => row.product.units.map(unit => ({ row, unit, key: key(row.id, unit.id) }))))
const quotedUnitCount = computed(() => allUnits.value.filter(item => original[item.key] != null).length)
const pendingUnitCount = computed(() => allUnits.value.length - quotedUnitCount.value)
const isDirty = (assignmentId, unitId) => {
  const id = key(assignmentId, unitId)
  const value = drafts[id]
  return value != null && Number(value) > 0 && Number(value) !== Number(original[id])
}
const dirtyCount = computed(() => allUnits.value.filter(item => isDirty(item.row.id, item.unit.id)).length)
const filledItems = computed(() => allUnits.value.filter(item => Number(drafts[item.key]) > 0))
const rowStatus = row => {
  if (row.product.units.some(unit => isDirty(row.id, unit.id))) return { text: '有未保存修改', type: 'warning' }
  const count = row.product.units.filter(unit => original[key(row.id, unit.id)] != null).length
  if (!count) return { text: '待报价', type: 'info' }
  if (count === row.product.units.length) return { text: '已全部报价', type: 'success' }
  return { text: `已报价 ${count}/${row.product.units.length}`, type: 'warning' }
}
const filteredRows = computed(() => rows.value.filter(row => {
  const term = keyword.value.trim().toLowerCase()
  const matchesKeyword = !term || row.product.name.toLowerCase().includes(term) || (row.product.sku || '').toLowerCase().includes(term)
  const matchesCategory = !category.value || row.product.category === category.value
  const state = rowStatus(row).text
  const savedCount = row.product.units.filter(unit => original[key(row.id, unit.id)] != null).length
  const matchesStatus = status.value === 'all' || (status.value === 'pending' && savedCount < row.product.units.length) || (status.value === 'quoted' && savedCount > 0) || (status.value === 'dirty' && state.includes('未保存'))
  return matchesKeyword && matchesCategory && matchesStatus
}))
const load = async () => {
  rows.value = await getAssignments()
  for (const item of allUnits.value) {
    const quote = item.row.quotes.find(current => current.unit_id === item.unit.id)
    original[item.key] = quote?.price ?? null
    drafts[item.key] = quote?.price ?? null
  }
}
const submit = async (row, unit) => {
  const id = key(row.id, unit.id)
  const price = drafts[id]
  if (!price) return ElMessage.warning('请输入有效报价')
  savingKeys.add(id)
  try {
    await saveQuote(row.id, { unit_id: unit.id, price, currency: 'CNY' })
    original[id] = Number(price)
    ElMessage.success(`${row.product.name} / ${unit.name} 报价已保存`)
  } finally { savingKeys.delete(id) }
}
const submitAll = async () => {
  if (!filledItems.value.length) return ElMessage.warning('请至少填写一条报价')
  savingAll.value = true
  try {
    const payload = filledItems.value.map(item => ({ assignment_id: item.row.id, unit_id: item.unit.id, price: drafts[item.key], currency: 'CNY' }))
    const result = await saveQuotesBatch(payload)
    for (const item of filledItems.value) original[item.key] = Number(drafts[item.key])
    ElMessage.success(result.message)
  } finally { savingAll.value = false }
}
onMounted(load)
</script>

<style scoped>
.metrics { margin-bottom: 16px; }.metric :deep(.el-card__body){display:flex;align-items:center;justify-content:space-between}.metric span{color:#8490a3}.metric strong{font-size:28px}.warning{color:#d98a2f}.success{color:#24946b}.danger{color:#df5747}
.filters{margin-bottom:18px}.filters :deep(.el-card__body){display:grid;grid-template-columns:1fr 220px 190px;gap:12px}.quote-grid>.el-col{margin-bottom:18px}.quote-card{height:100%}.quote-head{display:flex;justify-content:space-between;align-items:flex-start;border-bottom:1px solid #eef1f6;padding-bottom:14px}.quote-head span{font-size:12px;color:#4383d8}.quote-head h3{margin:5px 0 2px;font-size:19px}.quote-head small,.unit small{display:block;color:#929bad;margin-top:4px}.quote-line{display:grid;grid-template-columns:minmax(120px,1fr) 180px 78px 66px;gap:10px;align-items:center;padding:13px 8px;border-bottom:1px dashed #edf0f4}.quote-line:last-child{border-bottom:0}.quote-line.dirty{background:#fff9ed;border-radius:8px}.price-input{display:flex;align-items:center;gap:6px;color:#65728a}.price-input .el-input-number{width:155px}
</style>
