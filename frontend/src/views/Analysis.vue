<template>
  <div>
    <div class="page-header">
      <div><h2>智能比价分析</h2><p>按基础单位统一价格口径，快速定位最低价、价差和供应商优势品类</p></div>
      <el-button :loading="loading" @click="load"><el-icon><Refresh /></el-icon>刷新报价</el-button>
    </div>

    <el-row :gutter="14" class="metrics">
      <el-col :span="6"><el-card class="panel metric"><span>参与比价商品</span><strong>{{ data.products.length }}</strong></el-card></el-col>
      <el-col :span="6"><el-card class="panel metric"><span>报价供应商</span><strong>{{ supplierOptions.length }}</strong></el-card></el-col>
      <el-col :span="6"><el-card class="panel metric"><span>有效报价</span><strong>{{ allRows.length }}</strong></el-card></el-col>
      <el-col :span="6"><el-card class="panel metric"><span>选择最低价可节省</span><strong class="saving">¥ {{ totalSaving.toFixed(2) }}</strong></el-card></el-col>
    </el-row>

    <el-card class="panel ai-card">
      <div class="ai-title"><div><el-icon><MagicStick /></el-icon><strong>AI 采购顾问</strong><span>可以按你的关注点生成采购建议</span></div><el-button type="primary" :loading="aiLoading" @click="runAI">生成分析</el-button></div>
      <div class="prompt-row"><el-input v-model="question" placeholder="例如：重点分析饮料品类，兼顾最低价和供应商集中风险" @keyup.enter="runAI" /><el-dropdown @command="question = $event"><el-button>常用问题<el-icon><ArrowDown /></el-icon></el-button><template #dropdown><el-dropdown-menu><el-dropdown-item command="分析每个供应商的优势品类、关键价差，并给出采购建议。">综合采购建议</el-dropdown-item><el-dropdown-item command="找出价差最大的商品，说明潜在节省金额和优先谈价对象。">重点关注价差</el-dropdown-item><el-dropdown-item command="在价格优势之外，分析供应商集中风险并给出分散采购建议。">供应风险建议</el-dropdown-item></el-dropdown-menu></template></el-dropdown></div>
      <div v-if="aiText" class="ai-content" v-html="marked.parse(aiText)"></div>
    </el-card>

    <div v-if="data.supplier_advantages.length" class="section-title">供应商优势概览</div>
    <el-row :gutter="14" class="advantage-grid">
      <el-col v-for="item in data.supplier_advantages" :key="item.supplier_name" :span="8">
        <el-card class="panel advantage"><div class="supplier-icon">{{ item.supplier_name.slice(0, 1) }}</div><div><strong>{{ item.supplier_name }}</strong><p>最低价优势品类</p><el-tag v-for="categoryItem in item.categories" :key="categoryItem.category" type="success" effect="plain">{{ categoryItem.category }} · {{ categoryItem.winning_products }} 个</el-tag></div></el-card>
      </el-col>
    </el-row>

    <el-card class="panel comparison-card">
      <div class="comparison-head"><div><strong>报价明细</strong><span>筛选结果 {{ filteredRows.length }} 条</span></div><el-button :disabled="!filteredRows.length" @click="downloadCsv"><el-icon><Download /></el-icon>导出筛选结果</el-button></div>
      <div class="filters">
        <el-input v-model="keyword" clearable placeholder="搜索商品名称" prefix-icon="Search" />
        <el-select v-model="category" clearable placeholder="全部品类"><el-option v-for="item in categoryOptions" :key="item" :label="item" :value="item" /></el-select>
        <el-select v-model="supplier" clearable placeholder="全部供应商"><el-option v-for="item in supplierOptions" :key="item" :label="item" :value="item" /></el-select>
        <el-select v-model="sortBy" placeholder="排序方式"><el-option label="商品默认顺序" value="default" /><el-option label="基础单价从低到高" value="price" /><el-option label="价差比例从高到低" value="gap" /></el-select>
        <el-switch v-model="onlyLowest" active-text="只看最低价" />
      </div>
      <el-table :data="filteredRows" stripe :row-class-name="({ row }) => row.isLowest ? 'lowest-row' : ''" max-height="620">
        <el-table-column prop="product_name" label="商品" min-width="150" fixed />
        <el-table-column prop="category" label="品类" min-width="110" />
        <el-table-column prop="supplier_name" label="供应商" min-width="150" />
        <el-table-column label="供应商报价" min-width="150"><template #default="scope">¥ {{ formatPrice(scope.row.quoted_price) }} / {{ scope.row.unit_name }}</template></el-table-column>
        <el-table-column label="基础单位价" min-width="130" sortable prop="base_unit_price"><template #default="scope"><strong class="base-price">¥ {{ formatPrice(scope.row.base_unit_price) }}</strong></template></el-table-column>
        <el-table-column label="比最低价高" min-width="150"><template #default="scope"><span v-if="scope.row.isLowest" class="best">—</span><span v-else class="gap">+ ¥ {{ formatPrice(scope.row.gap) }}（{{ scope.row.gapPercent.toFixed(1) }}%）</span></template></el-table-column>
        <el-table-column label="推荐" width="110" fixed="right"><template #default="scope"><el-tag v-if="scope.row.isLowest" type="success" effect="dark">最低价</el-tag><el-tag v-else type="info" effect="plain">对比价</el-tag></template></el-table-column>
      </el-table>
      <el-empty v-if="!filteredRows.length" description="暂无符合筛选条件的有效报价" />
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { marked } from 'marked'
import { getAIAnalysis, getAnalysis } from '@/api'

const data = ref({ products: [], supplier_advantages: [] })
const loading = ref(false)
const aiText = ref('')
const aiLoading = ref(false)
const question = ref('分析每个供应商的优势品类、关键价差，并给出采购建议。')
const keyword = ref('')
const category = ref('')
const supplier = ref('')
const sortBy = ref('default')
const onlyLowest = ref(false)
const allRows = computed(() => data.value.products.flatMap((group, groupIndex) => {
  const minimum = Number(group.quotes[0]?.base_unit_price || 0)
  return group.quotes.map((quote, index) => ({ ...quote, groupIndex, isLowest: index === 0, gap: Number(quote.base_unit_price) - minimum, gapPercent: minimum ? (Number(quote.base_unit_price) - minimum) / minimum * 100 : 0 }))
}))
const categoryOptions = computed(() => [...new Set(allRows.value.map(row => row.category))].sort())
const supplierOptions = computed(() => [...new Set(allRows.value.map(row => row.supplier_name))].sort())
const totalSaving = computed(() => data.value.products.reduce((sum, group) => {
  if (group.quotes.length < 2) return sum
  const prices = group.quotes.map(item => Number(item.base_unit_price))
  return sum + Math.max(...prices) - Math.min(...prices)
}, 0))
const filteredRows = computed(() => {
  const term = keyword.value.trim().toLowerCase()
  const result = allRows.value.filter(row => (!term || row.product_name.toLowerCase().includes(term)) && (!category.value || row.category === category.value) && (!supplier.value || row.supplier_name === supplier.value) && (!onlyLowest.value || row.isLowest))
  if (sortBy.value === 'price') return [...result].sort((a, b) => a.base_unit_price - b.base_unit_price)
  if (sortBy.value === 'gap') return [...result].sort((a, b) => b.gapPercent - a.gapPercent)
  return result
})
const formatPrice = value => Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 4 })
const load = async () => { loading.value = true; try { data.value = await getAnalysis() } finally { loading.value = false } }
const runAI = async () => {
  if (!question.value.trim()) return ElMessage.warning('请输入希望 AI 分析的问题')
  if (!data.value.products.length) return ElMessage.warning('暂无有效报价，无法生成分析')
  aiLoading.value = true
  try { const result = await getAIAnalysis({ question: question.value.trim() }); aiText.value = result.content } finally { aiLoading.value = false }
}
const downloadCsv = () => {
  const columns = ['商品', '品类', '供应商', '报价单位', '原始报价', '基础单位价', '比最低价高', '是否最低价']
  const rows = filteredRows.value.map(item => [item.product_name, item.category, item.supplier_name, item.unit_name, item.quoted_price, item.base_unit_price, item.gap, item.isLowest ? '是' : '否'])
  const escape = value => `"${String(value ?? '').replaceAll('"', '""')}"`
  const csv = '\ufeff' + [columns, ...rows].map(row => row.map(escape).join(',')).join('\n')
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
  const link = document.createElement('a'); link.href = url; link.download = '智能比价筛选结果.csv'; link.click(); URL.revokeObjectURL(url)
}
onMounted(load)
</script>

<style scoped>
.metrics{margin-bottom:16px}.metric :deep(.el-card__body){display:flex;justify-content:space-between;align-items:center}.metric span{color:#8490a3}.metric strong{font-size:27px;color:#26354d}.metric .saving{color:#24946b;font-size:22px}
.ai-card{border-left:4px solid #4b89e8!important;margin-bottom:20px}.ai-title{display:flex;justify-content:space-between;align-items:center}.ai-title>div{display:flex;align-items:center;gap:9px}.ai-title .el-icon{font-size:21px;color:#4b89e8}.ai-title span{color:#8b93a5;font-size:13px}.prompt-row{display:grid;grid-template-columns:1fr 110px;gap:10px;margin-top:16px}.ai-content{margin-top:18px;padding:16px 20px;background:#f6f9fe;border-radius:10px;line-height:1.8}.ai-content :deep(p:first-child){margin-top:0}.section-title{font-size:18px;font-weight:700;margin:22px 0 13px}.advantage-grid>.el-col{margin-bottom:14px}.advantage{height:100%}.advantage :deep(.el-card__body){display:flex;gap:13px}.supplier-icon{width:42px;height:42px;flex:none;display:grid;place-items:center;border-radius:12px;background:#eaf4ff;color:#397bd1;font-weight:800}.advantage p{color:#8b93a5;margin:7px 0}.advantage .el-tag{margin:3px 5px 3px 0}.comparison-card{margin-top:8px}.comparison-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:15px}.comparison-head>div{display:flex;gap:12px;align-items:center}.comparison-head strong{font-size:18px}.comparison-head span{color:#8b93a5;font-size:13px}.filters{display:grid;grid-template-columns:1fr 170px 190px 210px 130px;gap:10px;align-items:center;margin-bottom:16px}.base-price{color:#2b5e9f}.best{color:#24946b}.gap{color:#d26f3f}.comparison-card :deep(.lowest-row td){background:#f0faf5!important}
</style>
