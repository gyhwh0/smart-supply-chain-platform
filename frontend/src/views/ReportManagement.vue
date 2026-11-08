<template>
  <div class="report-page">
    <div class="page-header">
      <div><h2>报表管理</h2><p>从录单、核单、采购、仓储到分拣履约的统一经营分析中心</p></div>
      <el-button type="success" :loading="exporting" @click="download"><el-icon><Download /></el-icon>导出当前报表</el-button>
    </div>

    <el-card class="report-shell" shadow="never">
      <aside class="report-nav">
        <template v-for="group in groups" :key="group.name">
          <div class="group-title">{{ group.name }}</div>
          <button v-for="item in group.items" :key="item.key" :class="{ active: reportKey === item.key }" @click="selectReport(item.key)">
            <span>{{ item.name }}</span><small>{{ item.description }}</small>
          </button>
        </template>
      </aside>

      <main class="report-content">
        <div class="report-title"><div><h3>{{ report?.title || current?.name }}</h3><p>{{ report?.description || current?.description }}</p></div><el-tag type="info">默认当天</el-tag></div>
        <div class="filters">
          <el-date-picker v-model="dateRange" type="daterange" value-format="YYYY-MM-DD" range-separator="至" start-placeholder="开始日期" end-placeholder="结束日期" :clearable="false" />
          <el-select v-if="supports('customer_id')" v-model="filters.customer_id" placeholder="全部客户" clearable filterable><el-option v-for="item in catalog.customers" :key="item.id" :label="item.name" :value="item.id" /></el-select>
          <el-select v-if="supports('supplier_id')" v-model="filters.supplier_id" placeholder="全部供应商" clearable filterable><el-option v-for="item in catalog.suppliers" :key="item.id" :label="item.name" :value="item.id" /></el-select>
          <el-select v-if="supports('creator_id')" v-model="filters.creator_id" placeholder="全部订单员/制单人" clearable filterable><el-option v-for="item in catalog.creators" :key="item.id" :label="item.name" :value="item.id" /></el-select>
          <el-select v-if="supports('assignee_id')" v-model="filters.assignee_id" placeholder="全部投诉处理人" clearable filterable><el-option v-for="item in catalog.creators" :key="item.id" :label="item.name" :value="item.id" /></el-select>
          <el-select v-if="supports('sorter_id')" v-model="filters.sorter_id" placeholder="全部分拣员" clearable filterable><el-option v-for="item in catalog.sorters" :key="item.id" :label="item.name" :value="item.id" /></el-select>
          <el-select v-if="supports('product_id')" v-model="filters.product_id" placeholder="全部商品" clearable filterable><el-option v-for="item in catalog.products" :key="item.id" :label="item.name" :value="item.id" /></el-select>
          <el-select v-if="supports('category')" v-model="filters.category" placeholder="全部分类" clearable><el-option v-for="item in catalog.categories" :key="item" :label="item" :value="item" /></el-select>
          <el-select v-if="supports('severity')" v-model="filters.severity" placeholder="全部投诉等级" clearable><el-option v-for="item in catalog.complaint_severities" :key="item.value" :label="item.name" :value="item.value" /></el-select>
          <el-select v-if="supports('complaint_category')" v-model="filters.complaint_category" placeholder="全部投诉分类" clearable><el-option v-for="item in catalog.complaint_categories" :key="item" :label="item" :value="item" /></el-select>
          <el-select v-if="supports('status')" v-model="filters.status" :placeholder="reportKey === 'complaints' ? '全部处理状态' : '全部单据状态'" clearable><el-option v-for="item in statusOptions" :key="item.value" :label="item.name" :value="item.value" /></el-select>
          <el-input v-if="supports('keyword')" v-model="filters.keyword" :placeholder="reportKey === 'complaints' ? '投诉编号、客户、内容关键词' : '单号、客户、商品关键词'" clearable @keyup.enter="load" />
          <el-button type="primary" @click="search">查询</el-button><el-button @click="reset">重置</el-button>
        </div>

        <div class="metrics" v-loading="loading">
          <div v-for="item in report?.metrics || []" :key="item.key" class="metric">
            <span>{{ item.label }}<el-tooltip v-if="item.help" :content="item.help"><el-icon><QuestionFilled /></el-icon></el-tooltip></span>
            <strong>{{ metricValue(item) }}</strong>
          </div>
        </div>

        <div v-if="reportKey === 'dashboard' && report?.sections" class="dashboard-sections">
          <section><h4>客户销售 TOP 5</h4><div v-for="(item,index) in report.sections.top_customers" :key="item.name" class="rank"><i>{{ index + 1 }}</i><span>{{ item.name }}</span><b>{{ money(item.amount) }}</b></div><el-empty v-if="!report.sections.top_customers.length" :image-size="48" description="当天暂无验收销售数据" /></section>
          <section><h4>商品销售 TOP 5</h4><div v-for="(item,index) in report.sections.top_products" :key="item.name" class="rank"><i>{{ index + 1 }}</i><span>{{ item.name }}</span><b>{{ money(item.amount) }}</b></div><el-empty v-if="!report.sections.top_products.length" :image-size="48" description="当天暂无验收销售数据" /></section>
          <section><h4>分拣工作量 TOP 5</h4><div v-for="(item,index) in report.sections.sorters" :key="item.sorter_name" class="rank"><i>{{ index + 1 }}</i><span>{{ item.sorter_name }}</span><b>{{ item.item_count }} 行</b></div><el-empty v-if="!report.sections.sorters.length" :image-size="48" description="当天暂无分拣任务" /></section>
        </div>

        <el-alert v-for="note in report?.notes || []" :key="note" :title="note" type="info" :closable="false" show-icon class="note" />
        <el-table :data="report?.rows || []" border stripe v-loading="loading" height="520" empty-text="当前筛选范围内暂无数据">
          <el-table-column v-for="column in report?.columns || []" :key="column.key" :prop="column.key" :label="column.label" :min-width="column.width">
            <template #default="scope">
              <el-tag v-if="column.type === 'status'" effect="plain" :type="tagType(scope.row[column.key])">{{ display(scope.row[column.key], column.type) }}</el-tag>
              <span v-else :class="{ amount: column.type === 'money' }">{{ display(scope.row[column.key], column.type) }}</span>
            </template>
          </el-table-column>
        </el-table>
        <div class="pagination"><span>共 {{ report?.total_rows || 0 }} 条</span><el-pagination v-model:current-page="page" v-model:page-size="pageSize" :page-sizes="[20,50,100,200]" layout="sizes, prev, pager, next" :total="report?.total_rows || 0" @change="load" /></div>
      </main>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { downloadManagementReport, getManagementReport, getReportCatalog } from '@/api'

const today = () => new Date().toLocaleDateString('en-CA')
const catalog = reactive({ reports: [], customers: [], suppliers: [], products: [], creators: [], sorters: [], categories: [], statuses: [], complaint_statuses: [], complaint_severities: [], complaint_categories: [] })
const reportKey = ref('dashboard'), report = ref(null), loading = ref(false), exporting = ref(false)
const dateRange = ref([today(), today()]), page = ref(1), pageSize = ref(50)
const filters = reactive({ customer_id: null, supplier_id: null, creator_id: null, assignee_id: null, sorter_id: null, product_id: null, category: null, severity: null, complaint_category: null, status: null, keyword: '' })
const filterSupport = {
  dashboard: ['customer_id','supplier_id','creator_id','sorter_id','product_id','category','keyword'], reconciliation: ['customer_id','supplier_id','creator_id','product_id','category','status','keyword'],
  order_clerk: ['customer_id','creator_id','product_id','category','status','keyword'], sorter: ['sorter_id'], sales_orders: ['customer_id','supplier_id','creator_id','product_id','category','status','keyword'],
  complaints: ['customer_id','assignee_id','severity','complaint_category','status','keyword'],
  profit_detail: ['customer_id','supplier_id','creator_id','product_id','category','status','keyword'], supplier_profit: ['customer_id','supplier_id','creator_id','product_id','category','status','keyword'],
  purchase_orders: ['supplier_id','creator_id','product_id','category','status','keyword'], inventory_flow: ['product_id','category'], customer_profit: ['customer_id','supplier_id','creator_id','product_id','category','status','keyword'],
  product_profit: ['customer_id','supplier_id','creator_id','product_id','category','status','keyword'], adjustments: ['customer_id','creator_id','product_id','category','status','keyword'],
}
const supports = key => filterSupport[reportKey.value]?.includes(key)
const groups = computed(() => ['运营管理', '经营报表'].map(name => ({ name, items: catalog.reports.filter(item => item.group === name) })))
const current = computed(() => catalog.reports.find(item => item.key === reportKey.value))
const statusOptions = computed(() => reportKey.value === 'complaints' ? catalog.complaint_statuses : catalog.statuses)
const params = () => ({ date_from: dateRange.value[0], date_to: dateRange.value[1], page: page.value, page_size: pageSize.value, ...Object.fromEntries(Object.entries(filters).filter(([key, value]) => supports(key) && value !== null && value !== '')) })
const load = async () => { loading.value = true; try { report.value = await getManagementReport(reportKey.value, params()) } finally { loading.value = false } }
const search = () => { page.value = 1; load() }
const selectReport = key => { reportKey.value = key; page.value = 1; load() }
const reset = () => { Object.assign(filters, { customer_id: null, supplier_id: null, creator_id: null, assignee_id: null, sorter_id: null, product_id: null, category: null, severity: null, complaint_category: null, status: null, keyword: '' }); dateRange.value = [today(), today()]; search() }
const money = value => `¥${Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
const metricValue = item => item.type === 'money' ? money(item.value) : item.type === 'percent' ? `${Number(item.value || 0).toFixed(2)}%` : Number(item.value || 0).toLocaleString('zh-CN')
const display = (value, type) => { if (value === null || value === undefined || value === '') return '—'; if (type === 'money') return money(value); if (type === 'percent') return `${Number(value).toFixed(2)}%`; if (type === 'number') return Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 4 }); if (type === 'datetime') return new Date(value).toLocaleString('zh-CN', { hour12: false }); return value }
const tagType = value => String(value).includes('P0') || String(value).includes('超时') ? 'danger' : String(value).includes('待') || String(value).includes('差异') || String(value).includes('未') || String(value).includes('新投诉') ? 'warning' : String(value).includes('完成') || String(value).includes('解决') || String(value).includes('关闭') || String(value).includes('确认') || String(value).includes('核清') || String(value).includes('验收') ? 'success' : 'info'
const download = async () => { exporting.value = true; try { const blob = await downloadManagementReport(reportKey.value, params()); const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = `${report.value?.title || '经营报表'}_${dateRange.value[0]}_${dateRange.value[1]}.xlsx`; link.click(); URL.revokeObjectURL(url); ElMessage.success('Excel 已生成') } finally { exporting.value = false } }
onMounted(async () => { Object.assign(catalog, await getReportCatalog()); await load() })
</script>

<style scoped>
.report-page{min-width:0}.report-shell :deep(.el-card__body){padding:0;display:grid;grid-template-columns:250px minmax(0,1fr);min-height:760px}.report-nav{padding:18px 12px;background:#f6f8fb;border-right:1px solid #e5eaf1;overflow:auto}.group-title{padding:9px 10px 6px;color:#8792a5;font-size:12px;font-weight:700;letter-spacing:1px}.report-nav button{width:100%;border:0;background:transparent;text-align:left;border-radius:8px;padding:10px 12px;margin:2px 0;cursor:pointer;color:#26334a}.report-nav button span,.report-nav button small{display:block}.report-nav button span{font-weight:650}.report-nav button small{color:#8b96a8;margin-top:4px;line-height:16px}.report-nav button:hover,.report-nav button.active{background:#e7f0ff;color:#2266be}.report-nav button.active{box-shadow:inset 3px 0 #347bd1}.report-content{padding:20px;min-width:0}.report-title{display:flex;align-items:flex-start;justify-content:space-between}.report-title h3{font-size:21px;margin:0}.report-title p{color:#8190a5;margin:7px 0 16px}.filters{display:grid;grid-template-columns:2fr repeat(6,minmax(130px,1fr)) 1.5fr auto auto;gap:9px;padding:14px;background:#f8fafc;border:1px solid #e7ebf1;border-radius:10px}.filters>*{width:100%}.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:12px;margin:16px 0}.metric{border:1px solid #e7ecf3;border-radius:10px;padding:14px 16px;background:linear-gradient(145deg,#fff,#f8fbff)}.metric span{display:flex;align-items:center;gap:4px;color:#7c889b;font-size:13px}.metric strong{display:block;font-size:23px;margin-top:7px;color:#20304a}.dashboard-sections{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:16px}.dashboard-sections section{border:1px solid #e6ebf2;border-radius:10px;padding:13px}.dashboard-sections h4{margin:0 0 10px}.rank{display:flex;align-items:center;gap:9px;padding:7px 0;border-bottom:1px dashed #edf0f4}.rank:last-child{border:0}.rank i{width:22px;height:22px;background:#eef4fc;color:#3476c5;border-radius:6px;display:grid;place-items:center;font-style:normal;font-weight:700}.rank span{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.rank b{color:#2b69b0}.note{margin:0 0 10px}.amount{font-weight:650;color:#e05d2a}.pagination{display:flex;justify-content:space-between;align-items:center;margin-top:14px;color:#8490a1}@media(max-width:1500px){.filters{grid-template-columns:repeat(4,minmax(150px,1fr))}.report-shell :deep(.el-card__body){grid-template-columns:220px minmax(0,1fr)}}@media(max-width:950px){.report-shell :deep(.el-card__body){display:block}.report-nav{display:flex;gap:6px;overflow:auto}.report-nav .group-title{display:none}.report-nav button{min-width:160px}.filters{grid-template-columns:1fr 1fr}.dashboard-sections{grid-template-columns:1fr}}
</style>
