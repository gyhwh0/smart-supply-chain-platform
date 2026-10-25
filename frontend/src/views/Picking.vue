<template>
  <div>
    <div class="page-header">
      <div><h2>扫码分拣看板</h2><p>按客户生成任务，标签扫码确认分拣与装车，实时查看未完成商品</p></div>
      <div class="actions"><el-button @click="router.push('/label-printing')">打印分拣标签</el-button><el-button type="primary" @click="openGenerate">生成分拣任务</el-button></div>
    </div>

    <el-row :gutter="14" class="metrics">
      <el-col v-for="item in metrics" :key="item.label" :span="6"><el-card shadow="never"><span>{{item.label}}</span><strong>{{item.value}}</strong></el-card></el-col>
    </el-row>

    <el-card class="panel filters">
      <el-date-picker v-model="filters.delivery_date" value-format="YYYY-MM-DD" clearable placeholder="配送日期" />
      <el-select v-model="filters.status" clearable placeholder="任务状态"><el-option v-for="(label,key) in statusLabels" :key="key" :label="label" :value="key"/></el-select>
      <el-input v-model="keyword" clearable placeholder="搜索客户、单号、人员" style="width:260px" />
      <el-button type="primary" @click="loadTasks">查询</el-button><el-button @click="clearFilters">清空</el-button>
    </el-card>

    <el-empty v-if="!filteredTasks.length" description="暂无分拣任务，请先从已确认销售单生成" />
    <div v-else class="task-list">
      <el-card v-for="task in filteredTasks" :key="task.id" class="panel task-card" shadow="never">
        <div class="task-head">
          <div><div class="customer"><b>{{task.customer_name}}</b><el-tag size="small" effect="plain">{{task.customer_code||'无编号'}}</el-tag><el-tag :type="statusType(task.status)">{{statusLabels[task.status]||task.status}}</el-tag></div><p>{{task.sales_order_no}} · 配送 {{task.delivery_date||'未设置'}}</p></div>
          <div class="task-actions"><el-button link type="primary" @click="router.push(`/label-printing?order=${task.sales_order_id}&picking=1`)">打印二维码标签</el-button></div>
        </div>
        <div class="staff"><span>分拣员：<b>{{task.sorter_name}}</b></span><span>配送员：<b>{{task.delivery_name}}</b></span><span>分拣 {{task.picked_count}}/{{task.total_count}}</span><span>装车 {{task.loaded_count}}/{{task.total_count}}</span></div>
        <el-progress :percentage="task.total_count?Math.round(task.picked_count/task.total_count*100):0" :stroke-width="10" />
        <el-table :data="task.items" size="small" class="items">
          <el-table-column prop="product_name" label="商品" min-width="180"/><el-table-column label="数量" width="120"><template #default="s">{{number(s.row.quantity)}} {{s.row.unit_name}}</template></el-table-column>
          <el-table-column label="分拣状态" width="130"><template #default="s"><el-tag :type="s.row.picked_at?'success':'info'">{{s.row.picked_at?'已分拣':'待分拣'}}</el-tag></template></el-table-column>
          <el-table-column label="装车状态" width="130"><template #default="s"><el-tag :type="s.row.loaded_at?'success':'info'">{{s.row.loaded_at?'已装车':'待装车'}}</el-tag></template></el-table-column>
          <el-table-column label="异常" min-width="150"><template #default="s"><span :class="{danger:s.row.exception_note}">{{s.row.exception_note||'—'}}</span></template></el-table-column>
        </el-table>
      </el-card>
    </div>

    <el-dialog v-model="generateVisible" title="从销售单生成分拣任务" width="90%" style="max-width:1100px" top="5vh">
      <el-alert title="任务会自动带入客户已分配的分拣员、配送员和全部商品。生成后到“标签打印”打印二维码。" type="info" :closable="false" />
      <div class="generate-filters">
        <div class="quick-date"><span>快捷日期</span><el-radio-group v-model="quickRange" @change="applyQuickRange"><el-radio-button value="today">今天</el-radio-button><el-radio-button value="tomorrow">明天</el-radio-button><el-radio-button value="week">未来7天</el-radio-button><el-radio-button value="all">全部</el-radio-button></el-radio-group></div>
        <el-date-picker v-model="generateFilters.dateRange" type="daterange" value-format="YYYY-MM-DD" range-separator="至" start-placeholder="开始配送日期" end-placeholder="结束配送日期" unlink-panels @change="quickRange='custom'" />
        <el-input v-model="generateFilters.keyword" clearable placeholder="搜索销售单、客户名称或编号" />
        <el-select v-model="generateFilters.sorter" clearable placeholder="全部分拣员"><el-option v-for="name in sorterOptions" :key="name" :label="name" :value="name"/></el-select>
        <el-select v-model="generateFilters.delivery" clearable placeholder="全部配送员"><el-option v-for="name in deliveryOptions" :key="name" :label="name" :value="name"/></el-select>
        <el-select v-model="generateFilters.assignment" placeholder="人员分配情况"><el-option label="全部分配情况" value="all"/><el-option label="人员已配齐" value="ready"/><el-option label="存在未分配" value="missing"/></el-select>
        <el-select v-model="generateFilters.generated" placeholder="生成状态"><el-option label="仅待生成" value="pending"/><el-option label="全部销售单" value="all"/><el-option label="仅已生成" value="generated"/></el-select>
      </div>
      <div class="generate-result"><span>当前筛选出 <b>{{filteredOrders.length}}</b> 张销售单，其中 {{selectableOrderCount}} 张可生成</span><div><el-button size="small" :disabled="!selectableOrderCount" @click="selectFilteredOrders">选择当前结果</el-button><el-button size="small" @click="orderTable?.clearSelection()">取消选择</el-button></div></div>
      <el-table v-if="filteredOrders.length" ref="orderTable" :data="filteredOrders" max-height="460" @selection-change="selectedOrders=$event">
        <el-table-column type="selection" width="48" :selectable="row=>!row.generated"/><el-table-column prop="order_no" label="销售单" width="180"/><el-table-column label="客户" min-width="180"><template #default="s">{{s.row.customer_code||'无编号'}} · {{s.row.customer_name}}</template></el-table-column><el-table-column prop="delivery_date" label="配送日期" width="115"/><el-table-column label="分拣员" min-width="105" prop="sorter_name"/><el-table-column label="配送员" min-width="105" prop="delivery_name"/><el-table-column prop="item_count" label="商品数" width="80"/><el-table-column label="状态" width="95"><template #default="s"><el-tag :type="s.row.generated?'info':'success'">{{s.row.generated?'已生成':'待生成'}}</el-tag></template></el-table-column>
      </el-table>
      <el-empty v-if="!filteredOrders.length" description="当前条件下没有销售单，请调整日期或筛选条件" :image-size="80" />
      <template #footer><el-button @click="generateVisible=false">取消</el-button><el-button type="primary" :disabled="!selectedOrders.length" :loading="saving" @click="generate">生成 {{selectedOrders.length}} 个任务</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed,nextTick,onMounted,reactive,ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { generatePickingTasks,getPickingOptions,getPickingTasks } from '@/api'
const router=useRouter(),tasks=ref([]),orders=ref([]),selectedOrders=ref([]),generateVisible=ref(false),saving=ref(false),keyword=ref(''),orderTable=ref(null),quickRange=ref('today')
const filters=reactive({delivery_date:null,status:null})
const generateFilters=reactive({dateRange:[],keyword:'',sorter:null,delivery:null,assignment:'all',generated:'pending'})
const statusLabels={pending:'待开始',picking:'分拣中',picked:'已分拣',delivering:'装车中',completed:'已完成'}
const formatDate=date=>{const year=date.getFullYear(),month=String(date.getMonth()+1).padStart(2,'0'),day=String(date.getDate()).padStart(2,'0');return `${year}-${month}-${day}`}
const dateAfter=days=>{const result=new Date();result.setDate(result.getDate()+days);return formatDate(result)}
const applyQuickRange=value=>{if(value==='today')generateFilters.dateRange=[dateAfter(0),dateAfter(0)];else if(value==='tomorrow')generateFilters.dateRange=[dateAfter(1),dateAfter(1)];else if(value==='week')generateFilters.dateRange=[dateAfter(0),dateAfter(6)];else generateFilters.dateRange=[]}
const sorterOptions=computed(()=>[...new Set(orders.value.map(row=>row.sorter_name).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'zh-CN')))
const deliveryOptions=computed(()=>[...new Set(orders.value.map(row=>row.delivery_name).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'zh-CN')))
const filteredOrders=computed(()=>{const key=generateFilters.keyword.trim().toLowerCase(),[start,end]=generateFilters.dateRange||[];return orders.value.filter(row=>{
  if(start&&(!row.delivery_date||row.delivery_date<start||row.delivery_date>end))return false
  if(key&&!`${row.order_no} ${row.customer_name} ${row.customer_code||''}`.toLowerCase().includes(key))return false
  if(generateFilters.sorter&&row.sorter_name!==generateFilters.sorter)return false
  if(generateFilters.delivery&&row.delivery_name!==generateFilters.delivery)return false
  const missing=row.sorter_name?.includes('未分配')||row.delivery_name?.includes('未分配')
  if(generateFilters.assignment==='ready'&&missing)return false
  if(generateFilters.assignment==='missing'&&!missing)return false
  if(generateFilters.generated==='pending'&&row.generated)return false
  if(generateFilters.generated==='generated'&&!row.generated)return false
  return true
})})
const selectableOrderCount=computed(()=>filteredOrders.value.filter(row=>!row.generated).length)
const filteredTasks=computed(()=>{const key=keyword.value.trim().toLowerCase();return tasks.value.filter(row=>!key||`${row.customer_name} ${row.customer_code||''} ${row.sales_order_no} ${row.sorter_name} ${row.delivery_name}`.toLowerCase().includes(key))})
const metrics=computed(()=>[{label:'客户任务',value:tasks.value.length},{label:'待分拣商品',value:tasks.value.reduce((n,t)=>n+t.total_count-t.picked_count,0)},{label:'已分拣商品',value:tasks.value.reduce((n,t)=>n+t.picked_count,0)},{label:'已完成客户',value:tasks.value.filter(t=>t.status==='completed').length}])
const number=v=>Number(v).toLocaleString('zh-CN',{maximumFractionDigits:4})
const statusType=s=>s==='completed'?'success':s==='picking'||s==='delivering'?'warning':s==='picked'?'primary':'info'
const loadTasks=async()=>tasks.value=await getPickingTasks(Object.fromEntries(Object.entries(filters).filter(([,v])=>v)))
const load=async()=>{[orders.value]=await Promise.all([getPickingOptions(),loadTasks()])}
const clearFilters=()=>{filters.delivery_date=null;filters.status=null;keyword.value='';loadTasks()}
const openGenerate=async()=>{orders.value=await getPickingOptions();Object.assign(generateFilters,{dateRange:[],keyword:'',sorter:null,delivery:null,assignment:'all',generated:'pending'});quickRange.value='today';applyQuickRange('today');selectedOrders.value=[];generateVisible.value=true;await nextTick();orderTable.value?.clearSelection()}
const selectFilteredOrders=()=>{orderTable.value?.clearSelection();filteredOrders.value.filter(row=>!row.generated).forEach(row=>orderTable.value?.toggleRowSelection(row,true))}
const generate=async()=>{saving.value=true;try{const result=await generatePickingTasks({sales_order_ids:selectedOrders.value.map(row=>row.id)});ElMessage.success(result.message);generateVisible.value=false;selectedOrders.value=[];await load()}finally{saving.value=false}}
onMounted(load)
</script>

<style scoped>
.actions,.filters,.staff,.customer{display:flex;align-items:center;gap:10px}.metrics{margin-bottom:14px}.metrics .el-card span{color:#78869a}.metrics .el-card strong{display:block;font-size:28px;margin-top:8px;color:#203552}.filters{margin-bottom:14px}.task-list{display:grid;gap:14px}.task-head{display:flex;justify-content:space-between;align-items:flex-start}.task-head p{color:#8490a3;margin:7px 0}.customer b{font-size:18px}.staff{background:#f5f8fc;padding:10px 12px;border-radius:8px;margin:8px 0 12px;gap:28px}.items{margin-top:12px}.danger{color:#e5484d;font-weight:600}.generate-filters{display:grid;grid-template-columns:1.5fr 1fr 1fr;gap:10px;margin:14px 0;padding:14px;background:#f6f8fb;border-radius:10px}.generate-filters>*{width:100%}.quick-date{grid-column:1/-1;display:flex;align-items:center;gap:14px}.quick-date>span{color:#66758a;font-size:13px}.generate-result{display:flex;justify-content:space-between;align-items:center;margin:0 0 10px;color:#6d7b8f}.generate-result b{color:#176c64;font-size:17px}@media(max-width:760px){.metrics .el-col{max-width:50%;flex:0 0 50%;margin-bottom:10px}.filters,.staff{flex-wrap:wrap}.task-head{display:block}.generate-filters{grid-template-columns:1fr}.quick-date{display:block}.quick-date .el-radio-group{margin-top:8px;display:flex;flex-wrap:wrap}.generate-result{align-items:flex-start;gap:8px;flex-direction:column}}
</style>
