<template>
  <div>
    <div class="page-header">
      <div><h2>销售汇总</h2><p>先选择统计时间查看客户销售看板，再按需要生成不同格式的成品汇总</p></div>
    </div>

    <el-card class="time-card">
      <div class="time-title"><div><b>统计时间</b><p>不选择时间时统计全部销售数据；选择时间后只查看对应区间</p></div><el-tag type="success" size="large">{{ periodLabel }}</el-tag></div>
      <div class="time-actions">
        <el-date-picker v-model="dateRange" type="daterange" format="YYYY年MM月DD日" value-format="YYYY-MM-DD" range-separator="至" start-placeholder="开始日期（可选）" end-placeholder="结束日期（可选）" :shortcuts="dateShortcuts" clearable size="large" style="width:420px" @change="loadCustomerBoard" />
        <el-button type="primary" size="large" :loading="loading" @click="loadCustomerBoard">查询客户销售看板</el-button>
        <el-button size="large" @click="reset">恢复全部时间</el-button>
      </div>
    </el-card>
      <div class="metric-grid">
        <el-card><small>有销售客户</small><strong>{{ overview.customer_count }}</strong></el-card>
        <el-card><small>销售单数</small><strong>{{ overview.order_count }}</strong></el-card>
        <el-card class="total-card"><small>统计时间内销售额</small><strong>¥{{ money(overview.total_amount) }}</strong></el-card>
      </div>

      <el-card class="panel customer-panel">
        <div class="section-head"><div><h3>客户销售看板</h3><p>按销售金额降序；点击客户查看所选时间内的销售单和商品明细</p></div><el-input v-model="customerKeyword" clearable placeholder="搜索客户、联系人、制单人" style="width:300px" @keyup.enter="searchCustomer" @clear="searchCustomer"><template #prefix><el-icon><Search /></el-icon></template><template #append><el-button @click="searchCustomer">搜索</el-button></template></el-input></div>
        <el-table :data="overview.rows" stripe @row-click="openCustomer" class="click-table" empty-text="所选时间内暂无已确认销售单">
          <el-table-column type="index" label="排名" width="68" />
          <el-table-column prop="customer_name" label="客户" min-width="180"><template #default="scope"><div class="customer-name"><b>{{ scope.row.customer_name }}</b><small>{{ scope.row.contact_name || '无联系人' }} · {{ scope.row.phone || '无电话' }}</small></div></template></el-table-column>
          <el-table-column label="销售金额" width="155" sortable prop="sales_amount"><template #default="scope"><b class="amount">¥{{ money(scope.row.sales_amount) }}</b></template></el-table-column>
          <el-table-column prop="order_count" label="单量" width="90" />
          <el-table-column prop="item_count" label="商品行" width="90" />
          <el-table-column label="下单时间" min-width="190"><template #default="scope">{{ scope.row.first_order_date }}<span v-if="scope.row.first_order_date !== scope.row.last_order_date"> 至 {{ scope.row.last_order_date }}</span></template></el-table-column>
          <el-table-column label="最近制单时间" min-width="175"><template #default="scope">{{ formatTime(scope.row.last_created_at) }}</template></el-table-column>
          <el-table-column prop="creator_names" label="制单人/订单员" min-width="150" />
          <el-table-column prop="sorter_name" label="分拣员" width="115" />
          <el-table-column prop="delivery_name" label="配送员" width="115" />
          <el-table-column label="操作" width="95" fixed="right"><template #default><el-button link type="primary">查看明细 →</el-button></template></el-table-column>
        </el-table>
        <el-pagination v-if="overview.customer_count > pageSize" v-model:current-page="customerPage" :page-size="pageSize" :total="overview.customer_count" layout="total, prev, pager, next, jumper" class="pagination" @current-change="loadOverview" />
      </el-card>

      <div class="summary-title"><div><h3>选择汇总成品</h3><p>点击一种汇总方式，在弹出的成品页中设置过滤、查看分类预览并下载 Excel</p></div></div>
      <div class="report-types">
        <el-card v-for="item in reportTypes" :key="item.value" shadow="hover" class="report-card" @click="openReport(item)">
          <div class="report-icon" :style="{background:item.bg,color:item.color}"><el-icon><component :is="item.icon" /></el-icon></div>
          <div><h3>{{ item.label }}</h3><p>{{ item.description }}</p><span>{{ item.hint }}</span></div><el-icon class="arrow"><ArrowRight /></el-icon>
        </el-card>
      </div>

    <el-dialog v-model="reportVisible" :title="`${activeReport.label} · 成品汇总页`" width="95%" top="2vh" destroy-on-close>
      <div class="report-period"><el-icon><Calendar /></el-icon><b>统计时间：{{ periodLabel }}</b><span>{{ dateRange?.length ? '所有过滤和导出均限定在此时间内' : '当前汇总全部时间的销售数据' }}</span></div>
      <el-card class="dialog-filter" shadow="never">
        <div class="filter-heading"><b>汇总过滤条件</b><span>可多条件组合过滤，修改后点击“重新生成”</span></div>
        <el-form inline>
          <el-form-item label="汇总分类"><el-select v-model="reportFilters.dimension" style="width:165px"><el-option v-for="item in dimensions" :key="item.value" :label="item.label" :value="item.value" /></el-select></el-form-item>
          <el-form-item label="客户"><el-select v-model="reportFilters.customer_id" clearable filterable placeholder="全部客户" style="width:160px"><el-option v-for="item in options.customers" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item>
          <el-form-item label="供应商"><el-select v-model="reportFilters.supplier_id" clearable filterable placeholder="全部供应商" style="width:170px"><el-option v-for="item in options.suppliers" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item>
          <el-form-item label="商品分类"><el-select v-model="reportFilters.category" clearable filterable placeholder="全部分类" style="width:150px"><el-option v-for="item in options.categories" :key="item" :label="item" :value="item" /></el-select></el-form-item>
          <el-form-item label="分拣员"><el-select v-model="reportFilters.sorter_id" clearable filterable placeholder="全部分拣员" style="width:145px"><el-option v-for="item in options.sorters" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item>
          <el-form-item label="配送员"><el-select v-model="reportFilters.delivery_id" clearable filterable placeholder="全部配送员" style="width:145px"><el-option v-for="item in options.deliveries" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item>
          <el-form-item label="订单员"><el-select v-model="reportFilters.creator_id" clearable filterable placeholder="全部订单员" style="width:145px"><el-option v-for="item in options.creators" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item>
          <el-form-item><el-button type="primary" :loading="reportLoading" @click="loadReport">重新生成</el-button><el-button @click="clearReportFilters">清空过滤</el-button></el-form-item>
        </el-form>
      </el-card>

      <div class="report-metrics"><div><span>销售单数</span><b>{{ reportSummary.order_count }}</b></div><div><span>汇总项目</span><b>{{ reportSummary.group_count }}</b></div><div><span>销售总额</span><b class="amount">¥{{ money(reportSummary.total_amount) }}</b></div></div>

      <div class="classification-preview">
        <div class="classification-block"><div class="classification-title"><b>供应商分类预览</b><span>前 6 项，商品按行预览</span></div><div class="mini-list supplier-mini"><div v-for="item in supplierPreview.rows.slice(0,6)" :key="item.name"><div><span>{{ item.name }}</span><small v-for="product in item.product_details.slice(0,3)" :key="product.name">{{ product.name }}　{{ product.quantity_display }}</small><small v-if="!item.product_details.length">暂无对应商品</small></div><b>¥{{ compactMoney(item.sales_amount) }}</b></div><el-empty v-if="!supplierPreview.rows.length" description="暂无供应商采购关联" :image-size="45" /></div></div>
        <div class="classification-block"><div class="classification-title"><b>商品分类预览</b><span>前 6 项</span></div><div class="mini-list"><div v-for="item in categoryPreview.rows.slice(0,6)" :key="item.name"><span>{{ item.name }}</span><b>¥{{ compactMoney(item.sales_amount) }}</b></div><el-empty v-if="!categoryPreview.rows.length" description="暂无商品分类数据" :image-size="45" /></div></div>
      </div>

      <div class="finished-report">
        <div class="finished-title"><div><h3>{{ activeReport.label }}</h3><p>{{ dimensionLabel }} · {{ periodLabel }}</p></div><el-button type="success" size="large" :disabled="!reportSummary.rows.length" @click="downloadReport"><el-icon><Download /></el-icon> 下载 Excel 成品</el-button></div>
        <div v-if="reportFilters.dimension==='supplier'" class="supplier-purchase-report">
          <section v-for="(supplier,index) in pagedReportRows" :key="supplier.name" class="supplier-order-block">
            <h4>（{{supplier.name}}）采购单　日期：{{reportDateLabel}}　共{{reportSummary.rows.length}}页　第{{(reportPage-1)*reportPageSize+index+1}}页</h4>
            <table><thead><tr><th>菜名</th><th>总数量</th><th>订单总数</th></tr></thead><tbody><tr v-for="product in supplier.product_details" :key="product.name"><td>{{product.name}}</td><td>{{product.quantity_display}}</td><td>{{product.order_breakdown||'暂无客户订购明细'}}</td></tr><tr v-if="!supplier.product_details.length"><td colspan="3" class="empty-row">暂无对应商品明细</td></tr></tbody></table>
          </section>
        </div>
        <div v-else-if="activeReport.value === 'horizontal'" class="horizontal-report"><div v-for="item in reportSummary.rows" :key="item.name"><span>{{ item.name }}</span><b>¥{{ money(item.sales_amount) }}</b><small>{{ item.order_count }} 单<br>{{ item.quantity_display || '无数量' }}</small></div></div>
        <el-table v-else :data="pagedReportRows" border stripe max-height="470">
          <el-table-column type="index" label="序号" width="65" />
          <el-table-column prop="name" :label="dimensionLabel" min-width="220"><template #default="scope"><b>{{ scope.row.name }}</b></template></el-table-column>
          <el-table-column v-if="activeReport.value !== 'quantity'" prop="order_count" label="销售单数" width="120" />
          <el-table-column prop="quantity_display" label="销售数量" min-width="220" />
          <el-table-column v-if="activeReport.value !== 'quantity'" prop="item_count" label="明细行数" width="120" />
          <el-table-column prop="sales_amount" label="销售金额" width="180"><template #default="scope"><b class="amount">¥{{ money(scope.row.sales_amount) }}</b></template></el-table-column>
          <el-table-column label="销售占比" width="180"><template #default="scope"><el-progress :percentage="reportSummary.total_amount ? Number((scope.row.sales_amount / reportSummary.total_amount * 100).toFixed(1)) : 0" /></template></el-table-column>
        </el-table>
        <el-pagination v-if="(reportFilters.dimension==='supplier' || activeReport.value !== 'horizontal') && reportSummary.rows.length > reportPageSize" v-model:current-page="reportPage" :page-size="reportPageSize" :total="reportSummary.rows.length" layout="total, prev, pager, next" class="pagination" />
      </div>
      <template #footer><el-button @click="reportVisible=false">关闭</el-button><el-button type="success" :disabled="!reportSummary.rows.length" @click="downloadReport">下载 Excel</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { downloadSalesSummary, getSalesOverview, getSalesSummary, getSalesSummaryOptions } from '@/api'

const router = useRouter()
const dateRange = ref([]), loading = ref(false), customerKeyword = ref(''), customerPage = ref(1)
const pageSize = 20
const overview = reactive({ rows: [], customer_count: 0, order_count: 0, total_amount: 0 })
const options = reactive({ customers: [], suppliers: [], categories: [], sorters: [], deliveries: [], creators: [] })
const reportVisible = ref(false), reportLoading = ref(false), reportPage = ref(1), reportPageSize = 20
const activeReport = reactive({ value:'normal', label:'普通汇总', description:'' })
const reportSummary = reactive({ rows:[], order_count:0, group_count:0, total_amount:0 })
const supplierPreview = reactive({ rows:[] }), categoryPreview = reactive({ rows:[] })
const reportFilters = reactive({ dimension:'category', customer_id:null, supplier_id:null, category:null, sorter_id:null, delivery_id:null, creator_id:null })
const dimensions = [{label:'按供应商',value:'supplier'},{label:'按商品分类',value:'category'},{label:'按商品',value:'product'},{label:'按客户',value:'customer'},{label:'按订单员',value:'creator'},{label:'按分拣员',value:'sorter'},{label:'按配送员',value:'delivery'}]
const reportTypes = [
  {value:'horizontal',label:'横排汇总',description:'将各分类结果横向铺开，适合快速对比金额和单量',hint:'默认按供应商',dimension:'supplier',icon:'Grid',bg:'#edf5ff',color:'#347dde'},
  {value:'quantity',label:'数量汇总',description:'突出商品采购/销售数量，适合备货和分拣核对',hint:'默认按商品',dimension:'product',icon:'DataLine',bg:'#eaf8f1',color:'#24946b'},
  {value:'normal',label:'普通汇总',description:'标准表格呈现单量、数量、明细和销售金额',hint:'默认按商品分类',dimension:'category',icon:'Tickets',bg:'#fff4e8',color:'#d87532'},
  {value:'custom',label:'自定义汇总',description:'自由选择维度并组合供应商、品类、人员等条件',hint:'7 种汇总维度',dimension:'supplier',icon:'SetUp',bg:'#f4efff',color:'#8159d9'},
]
const dateShortcuts = [{text:'今天',value:()=>{const d=new Date();return[d,d]}},{text:'近7天',value:()=>{const e=new Date(),s=new Date();s.setDate(s.getDate()-6);return[s,e]}},{text:'本月',value:()=>{const e=new Date(),s=new Date(e.getFullYear(),e.getMonth(),1);return[s,e]}},{text:'上月',value:()=>{const n=new Date(),s=new Date(n.getFullYear(),n.getMonth()-1,1),e=new Date(n.getFullYear(),n.getMonth(),0);return[s,e]}}]
const baseParams = () => ({date_from:dateRange.value?.[0],date_to:dateRange.value?.[1]})
const reportParams = (dimension=reportFilters.dimension) => ({...baseParams(),dimension,customer_id:reportFilters.customer_id||undefined,supplier_id:reportFilters.supplier_id||undefined,category:reportFilters.category||undefined,sorter_id:reportFilters.sorter_id||undefined,delivery_id:reportFilters.delivery_id||undefined,creator_id:reportFilters.creator_id||undefined})
const dimensionLabel = computed(()=>dimensions.find(item=>item.value===reportFilters.dimension)?.label||'汇总对象')
const periodLabel = computed(()=>dateRange.value?.length?`${dateRange.value[0]} 至 ${dateRange.value[1]}`:'全部时间')
const pagedReportRows = computed(()=>reportSummary.rows.slice((reportPage.value-1)*reportPageSize,reportPage.value*reportPageSize))
const reportDateLabel = computed(()=>dateRange.value?.[1]||dateRange.value?.[0]||new Date().toISOString().slice(0,10))
const money = value=>Number(value||0).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2})
const compactMoney = value=>Number(value||0).toLocaleString('zh-CN',{maximumFractionDigits:0})
const formatTime = value=>value?new Date(value).toLocaleString('zh-CN',{hour12:false}):'—'
const loadOverview = async()=>Object.assign(overview,await getSalesOverview({...baseParams(),keyword:customerKeyword.value.trim()||undefined,page:customerPage.value,page_size:pageSize}))
const loadCustomerBoard = async()=>{loading.value=true;customerPage.value=1;try{await loadOverview()}finally{loading.value=false}}
const searchCustomer = async()=>{customerPage.value=1;await loadOverview()}
const reset = async()=>{dateRange.value=[];customerKeyword.value='';await loadCustomerBoard()}
const openCustomer = row=>router.push({path:`/sales-customers/${row.customer_id}`,query:baseParams()})
const openReport = async item=>{Object.assign(activeReport,item);Object.assign(reportFilters,{dimension:item.dimension,customer_id:null,supplier_id:null,category:null,sorter_id:null,delivery_id:null,creator_id:null});reportVisible.value=true;await loadReport()}
const loadReport = async()=>{reportLoading.value=true;reportPage.value=1;try{const [main,suppliers,categories]=await Promise.all([getSalesSummary(reportParams()),getSalesSummary(reportParams('supplier')),getSalesSummary(reportParams('category'))]);Object.assign(reportSummary,main);Object.assign(supplierPreview,suppliers);Object.assign(categoryPreview,categories)}finally{reportLoading.value=false}}
const clearReportFilters = async()=>{const dimension=reportFilters.dimension;Object.assign(reportFilters,{dimension,customer_id:null,supplier_id:null,category:null,sorter_id:null,delivery_id:null,creator_id:null});await loadReport()}
const downloadReport = async()=>{const blob=await downloadSalesSummary({...reportParams(),report_type:activeReport.value});const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=`${activeReport.label}_${dateRange.value?.length?`${dateRange.value[0]}至${dateRange.value[1]}`:'全部时间'}.xlsx`;link.click();URL.revokeObjectURL(url);ElMessage.success('Excel 成品汇总已下载')}
onMounted(async()=>{Object.assign(options,await getSalesSummaryOptions());await loadCustomerBoard()})
</script>

<style scoped>
.time-card{margin-bottom:18px;border:1px solid #dfe6ef}.time-title,.time-actions,.section-head,.summary-title,.filter-heading,.finished-title,.classification-title{display:flex;align-items:center;justify-content:space-between;gap:16px}.time-title p,.section-head p,.summary-title p,.filter-heading span,.finished-title p,.classification-title span{color:#8490a3;font-size:13px;margin:5px 0 0}.time-actions{justify-content:flex-start;margin-top:16px}
.metric-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:18px}.metric-grid small,.metric-grid strong{display:block}.metric-grid small{color:#7c8799}.metric-grid strong{font-size:28px;margin-top:8px}.total-card strong,.amount{color:#df6131}.customer-panel{margin-bottom:24px}.section-head{margin-bottom:16px}.section-head h3,.summary-title h3,.finished-title h3{margin:0}.click-table :deep(tbody tr){cursor:pointer}.customer-name b,.customer-name small{display:block}.customer-name small{color:#8792a3;margin-top:4px}.pagination{justify-content:flex-end;margin-top:16px}
.summary-title{margin:4px 0 14px}.report-types{display:grid;grid-template-columns:repeat(2,1fr);gap:14px}.report-card{cursor:pointer;position:relative}.report-card :deep(.el-card__body){display:flex;gap:16px;align-items:center;min-height:120px}.report-card h3{margin:0 0 6px}.report-card p{margin:0 0 7px;color:#68758a}.report-card span{font-size:12px;color:#8a95a5}.report-icon{width:52px;height:52px;border-radius:14px;display:grid;place-items:center;font-size:25px;flex:none}.report-card .arrow{position:absolute;right:18px;font-size:20px;color:#9aa5b4}
.report-period{display:flex;align-items:center;gap:10px;padding:11px 15px;background:#eef6ff;color:#2867a7;border-radius:9px;margin-bottom:12px}.report-period span{color:#758399;margin-left:8px}.dialog-filter{margin-bottom:14px}.filter-heading{justify-content:flex-start;margin-bottom:12px}.dialog-filter :deep(.el-form-item){margin-bottom:10px}.report-metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:14px}.report-metrics>div{padding:12px 16px;background:#f7f9fc;border-radius:9px}.report-metrics span,.report-metrics b{display:block}.report-metrics span{color:#7d8899;font-size:13px}.report-metrics b{font-size:21px;margin-top:4px}
.classification-preview{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:14px}.classification-block{border:1px solid #e2e8f0;border-radius:10px;padding:13px}.mini-list{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:10px}.mini-list>div{display:flex;justify-content:space-between;gap:8px;padding:8px;background:#f7f9fc;border-radius:7px;min-width:0}.mini-list span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.mini-list b{color:#287cba;white-space:nowrap}.supplier-mini>div>div{min-width:0}.supplier-mini small{display:block;color:#8792a3;font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-top:3px}.finished-report{border:1px solid #dce4ee;border-radius:12px;padding:16px}.finished-title{margin-bottom:13px}.horizontal-report{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;max-height:470px;overflow:auto}.horizontal-report>div{border:1px solid #e2e8f0;border-radius:9px;padding:13px;background:linear-gradient(145deg,#f8fbff,#fff)}.horizontal-report span,.horizontal-report b,.horizontal-report small{display:block}.horizontal-report b{color:#df6131;font-size:19px;margin:7px 0}.horizontal-report small{color:#7e8999;line-height:1.5}.supplier-purchase-report{max-height:470px;overflow:auto;padding:4px 8px;background:#fff}.supplier-order-block{margin-bottom:24px}.supplier-order-block h4{text-align:center;margin:0;padding:8px 5px;font-size:15px;color:#111}.supplier-order-block table{width:100%;border-collapse:collapse;table-layout:fixed;color:#222}.supplier-order-block th,.supplier-order-block td{border:1px solid #444;padding:6px 8px;vertical-align:middle}.supplier-order-block th{text-align:center;font-weight:500}.supplier-order-block th:nth-child(1),.supplier-order-block td:nth-child(1){width:28%}.supplier-order-block th:nth-child(2),.supplier-order-block td:nth-child(2){width:15%;text-align:center}.supplier-order-block td:nth-child(3){line-height:1.6;word-break:break-all}.supplier-order-block .empty-row{text-align:center!important;color:#8a95a5}
@media(max-width:1100px){.report-types,.classification-preview{grid-template-columns:1fr}.horizontal-report{grid-template-columns:repeat(3,1fr)}}
</style>
