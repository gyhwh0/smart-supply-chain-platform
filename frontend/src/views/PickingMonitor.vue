<template>
  <div class="monitor-page">
    <div class="page-header">
      <div><h2>分拣配送监控看板</h2><p>集中查看人员工作量、客户任务进度、单品确认节奏和异常情况</p></div>
      <div class="header-actions"><span class="refresh-time">更新于 {{lastRefresh||'—'}}</span><el-switch v-model="autoRefresh" active-text="自动刷新"/><el-button :loading="loading" @click="load"><el-icon><Refresh /></el-icon>刷新</el-button><el-button @click="toggleFullscreen">全屏看板</el-button></div>
    </div>

    <el-card class="filter-card" shadow="never">
      <div class="quick-row"><span>统计日期</span><el-radio-group v-model="quickDate" @change="applyQuickDate"><el-radio-button value="today">今天</el-radio-button><el-radio-button value="tomorrow">明天</el-radio-button><el-radio-button value="week">近7天</el-radio-button><el-radio-button value="custom">自定义</el-radio-button></el-radio-group></div>
      <div class="filters">
        <el-date-picker v-model="dateRange" type="daterange" value-format="YYYY-MM-DD" range-separator="至" start-placeholder="开始日期" end-placeholder="结束日期" :clearable="false" @change="dateChanged" />
        <el-select v-model="roleFilter" placeholder="全部岗位"><el-option label="全部岗位" value="all"/><el-option label="分拣员" value="sorter"/><el-option label="配送员" value="delivery"/></el-select>
        <el-select v-model="staffFilter" clearable filterable placeholder="全部人员"><el-option v-for="row in roleStaff" :key="row.staff_id" :label="`${row.staff_name}（${roleLabel(row.staff_type)}）`" :value="row.staff_id"/></el-select>
        <el-select v-model="statusFilter" placeholder="全部进度"><el-option label="全部进度" value="all"/><el-option label="待开始" value="pending"/><el-option label="进行中" value="working"/><el-option label="已完成" value="completed"/><el-option label="存在异常" value="exception"/></el-select>
        <el-input v-model="keyword" clearable placeholder="搜索客户、销售单、商品" />
      </div>
    </el-card>

    <section class="overview">
      <div class="metric blue"><span>客户任务</span><b>{{overview.task_count}}</b><small>完成 {{overview.completed_task_count}}</small></div>
      <div class="metric orange"><span>待分拣商品</span><b>{{Math.max(0,overview.total_items-overview.picked_items)}}</b><small>已分拣 {{overview.picked_items}} / {{overview.total_items}}</small></div>
      <div class="metric green"><span>待装车商品</span><b>{{Math.max(0,overview.total_items-overview.loaded_items)}}</b><small>已装车 {{overview.loaded_items}} / {{overview.total_items}}</small></div>
      <div class="metric purple"><span>今日已作业人员</span><b>{{overview.working_staff_count}}</b><small>共 {{data.staff.length}} 名在岗人员</small></div>
      <div class="metric red"><span>异常商品</span><b>{{overview.exception_count}}</b><small>{{overview.exception_count?'需要及时处理':'当前无异常'}}</small></div>
    </section>

    <el-alert title="耗时说明：客户完成耗时从该客户第一件商品确认至最后一件确认；单品用时显示与上一件商品的确认间隔。首件商品显示确认时间，不把任务生成后的等待时间算作实际分拣用时。" type="info" :closable="false" show-icon class="explain"/>

    <section class="section-block">
      <div class="section-title"><div><h3>人员工作量</h3><p>点击人员卡片可只看该人员负责的客户任务</p></div><span>{{filteredStaff.length}} 人</span></div>
      <el-empty v-if="!filteredStaff.length" description="当前日期没有符合条件的人员数据" />
      <div v-else class="staff-grid">
        <article v-for="row in filteredStaff" :key="row.staff_id" class="staff-card" :class="{selected:staffFilter===row.staff_id,idle:!row.task_count}" @click="staffFilter=staffFilter===row.staff_id?null:row.staff_id">
          <header><div class="avatar" :class="row.staff_type">{{row.staff_name.slice(0,1)}}</div><div><h4>{{row.staff_name}}</h4><span>{{roleLabel(row.staff_type)}} · {{row.customer_count}} 个客户</span></div><el-tag :type="row.pending_items?'warning':'success'">{{row.pending_items?`待处理 ${row.pending_items}`:'已完成'}}</el-tag></header>
          <div class="work-numbers"><div><b>{{row.completed_items}}/{{row.total_items}}</b><span>商品进度</span></div><div><b>{{row.completed_task_count}}/{{row.task_count}}</b><span>客户完成</span></div><div><b>{{duration(row.average_customer_seconds)}}</b><span>平均每客户</span></div></div>
          <el-progress :percentage="row.progress" :stroke-width="10" :color="row.staff_type==='sorter'?'#3978e9':'#17a673'" />
          <div class="content-line"><span>负责客户</span><p>{{unique(row.customers).join('、')||'暂无任务'}}</p></div>
          <div v-if="row.pending_products.length" class="content-line"><span>待处理商品</span><p>{{row.pending_products.join('、')}}</p></div>
          <footer><span v-if="row.exception_count" class="danger">{{row.exception_count}} 项异常</span><span v-else>无异常</span><span>最后操作 {{timeOnly(row.last_action_at)}}</span></footer>
        </article>
      </div>
    </section>

    <section class="section-block">
      <div class="section-title"><div><h3>客户任务与单品时间</h3><p>展开客户可查看每件商品的确认时间和相邻操作间隔</p></div><span>{{filteredTasks.length}} 个客户任务</span></div>
      <el-table :data="filteredTasks" row-key="id" stripe empty-text="当前筛选条件下没有任务">
        <el-table-column type="expand">
          <template #default="scope">
            <div class="task-detail">
              <div class="timeline-summary"><span>任务生成：<b>{{dateTime(scope.row.created_at)}}</b></span><span>开始分拣：<b>{{dateTime(scope.row.picking_started_at)}}</b></span><span>分拣完成：<b>{{dateTime(scope.row.picking_finished_at)}}</b></span><span>装车完成：<b>{{dateTime(scope.row.loading_finished_at)}}</b></span></div>
              <el-table :data="scope.row.items" size="small" border>
                <el-table-column prop="product_name" label="商品" min-width="180"/><el-table-column label="数量" width="110"><template #default="s">{{number(s.row.quantity)}} {{s.row.unit_name}}</template></el-table-column>
                <el-table-column label="分拣确认" min-width="160"><template #default="s"><div>{{dateTime(s.row.picked_at)}}</div><small v-if="s.row.picked_at" class="interval">{{s.row.picked_interval_seconds==null?'首件确认':`距上一件 ${duration(s.row.picked_interval_seconds)}`}}</small></template></el-table-column>
                <el-table-column label="装车确认" min-width="160"><template #default="s"><div>{{dateTime(s.row.loaded_at)}}</div><small v-if="s.row.loaded_at" class="interval">{{s.row.loaded_interval_seconds==null?'首件确认':`距上一件 ${duration(s.row.loaded_interval_seconds)}`}}</small></template></el-table-column>
                <el-table-column label="异常" min-width="140"><template #default="s"><span :class="{danger:s.row.exception_note}">{{s.row.exception_note||'—'}}</span></template></el-table-column>
              </el-table>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="客户" min-width="180"><template #default="s"><b>{{s.row.customer_name}}</b><div class="subtext">{{s.row.customer_code||'无编号'}} · {{s.row.sales_order_no}}</div></template></el-table-column>
        <el-table-column prop="delivery_date" label="配送日期" width="110"/>
        <el-table-column label="分拣员 / 配送员" min-width="170"><template #default="s">{{s.row.sorter_name}}<span class="slash">/</span>{{s.row.delivery_name}}</template></el-table-column>
        <el-table-column label="分拣进度" width="140"><template #default="s"><span>{{s.row.picked_count}} / {{s.row.total_count}}</span><el-progress :percentage="percent(s.row.picked_count,s.row.total_count)" :show-text="false" :stroke-width="6"/></template></el-table-column>
        <el-table-column label="装车进度" width="140"><template #default="s"><span>{{s.row.loaded_count}} / {{s.row.total_count}}</span><el-progress :percentage="percent(s.row.loaded_count,s.row.total_count)" :show-text="false" :stroke-width="6" color="#17a673"/></template></el-table-column>
        <el-table-column label="客户耗时" min-width="155"><template #default="s"><div>分拣 {{duration(s.row.picking_duration_seconds)}}</div><div>装车 {{duration(s.row.loading_duration_seconds)}}</div></template></el-table-column>
        <el-table-column label="状态" width="95"><template #default="s"><el-tag :type="statusType(s.row.status)">{{statusLabels[s.row.status]||s.row.status}}</el-tag><div v-if="s.row.exception_count" class="exception-text">{{s.row.exception_count}}项异常</div></template></el-table-column>
      </el-table>
    </section>
  </div>
</template>

<script setup>
import { computed,onBeforeUnmount,onMounted,reactive,ref,watch } from 'vue'
import { getPickingMonitor } from '@/api'

const loading=ref(false),autoRefresh=ref(true),lastRefresh=ref(''),quickDate=ref('today'),roleFilter=ref('all'),staffFilter=ref(null),statusFilter=ref('all'),keyword=ref('')
const data=reactive({overview:{task_count:0,completed_task_count:0,total_items:0,picked_items:0,loaded_items:0,exception_count:0,working_staff_count:0},staff:[],tasks:[]})
const overview=computed(()=>data.overview)
const formatDate=date=>{const y=date.getFullYear(),m=String(date.getMonth()+1).padStart(2,'0'),d=String(date.getDate()).padStart(2,'0');return `${y}-${m}-${d}`}
const offsetDate=days=>{const value=new Date();value.setDate(value.getDate()+days);return formatDate(value)}
const dateRange=ref([offsetDate(0),offsetDate(0)])
const statusLabels={pending:'待开始',picking:'分拣中',picked:'已分拣',delivering:'装车中',completed:'已完成'}
const roleLabel=role=>role==='sorter'?'分拣员':'配送员'
const unique=values=>[...new Set(values)]
const number=value=>Number(value).toLocaleString('zh-CN',{maximumFractionDigits:4})
const percent=(done,total)=>total?Math.round(done/total*100):0
const duration=seconds=>{if(seconds==null)return '—';if(seconds<60)return `${seconds}秒`;if(seconds<3600)return `${Math.floor(seconds/60)}分${seconds%60?`${seconds%60}秒`:''}`;const h=Math.floor(seconds/3600),m=Math.floor(seconds%3600/60);return `${h}小时${m?`${m}分`:''}`}
const parseTime=value=>value?new Date(value):null
const dateTime=value=>{const date=parseTime(value);return date&&!Number.isNaN(date)?date.toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}):'—'}
const timeOnly=value=>{const date=parseTime(value);return date&&!Number.isNaN(date)?date.toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}):'—'}
const statusType=status=>status==='completed'?'success':status==='picking'||status==='delivering'?'warning':status==='picked'?'primary':'info'
const roleStaff=computed(()=>data.staff.filter(row=>roleFilter.value==='all'||row.staff_type===roleFilter.value))
const filteredStaff=computed(()=>roleStaff.value.filter(row=>!staffFilter.value||row.staff_id===staffFilter.value).sort((a,b)=>b.pending_items-a.pending_items||b.total_items-a.total_items))
const filteredTasks=computed(()=>{const key=keyword.value.trim().toLowerCase();return data.tasks.filter(row=>{
  if(staffFilter.value&&row.sorter_id!==staffFilter.value&&row.delivery_id!==staffFilter.value)return false
  if(roleFilter.value==='sorter'&&staffFilter.value&&row.sorter_id!==staffFilter.value)return false
  if(roleFilter.value==='delivery'&&staffFilter.value&&row.delivery_id!==staffFilter.value)return false
  if(statusFilter.value==='pending'&&row.status!=='pending')return false
  if(statusFilter.value==='working'&&!['picking','picked','delivering'].includes(row.status))return false
  if(statusFilter.value==='completed'&&row.status!=='completed')return false
  if(statusFilter.value==='exception'&&!row.exception_count)return false
  if(key&&!`${row.customer_name} ${row.customer_code||''} ${row.sales_order_no} ${row.items.map(item=>item.product_name).join(' ')}`.toLowerCase().includes(key))return false
  return true
})})
const load=async()=>{loading.value=true;try{const result=await getPickingMonitor({date_from:dateRange.value[0],date_to:dateRange.value[1]});Object.assign(data,result);lastRefresh.value=new Date().toLocaleTimeString('zh-CN',{hour12:false})}finally{loading.value=false}}
const applyQuickDate=value=>{if(value==='today')dateRange.value=[offsetDate(0),offsetDate(0)];else if(value==='tomorrow')dateRange.value=[offsetDate(1),offsetDate(1)];else if(value==='week')dateRange.value=[offsetDate(-6),offsetDate(0)];else return;load()}
const dateChanged=()=>{quickDate.value='custom';load()}
const toggleFullscreen=()=>document.fullscreenElement?document.exitFullscreen():document.documentElement.requestFullscreen()
watch(roleFilter,()=>{if(staffFilter.value&&!roleStaff.value.some(row=>row.staff_id===staffFilter.value))staffFilter.value=null})
let timer
onMounted(()=>{load();timer=window.setInterval(()=>{if(autoRefresh.value&&!document.hidden&&!loading.value)load()},30000)})
onBeforeUnmount(()=>window.clearInterval(timer))
</script>

<style scoped>
.monitor-page{--blue:#3978e9;--green:#17a673;--orange:#ea8b2d;--red:#df4b55}.header-actions{display:flex;align-items:center;gap:10px}.refresh-time{font-size:12px;color:#8190a4}.filter-card{margin-bottom:14px}.quick-row{display:flex;align-items:center;gap:14px;margin-bottom:12px}.quick-row>span{font-size:13px;color:#66758a}.filters{display:grid;grid-template-columns:1.35fr repeat(4,1fr);gap:10px}.filters>*{width:100%}.overview{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:14px}.metric{background:#fff;border-radius:12px;padding:15px 17px;border-left:4px solid var(--blue);box-shadow:0 2px 12px #263b5510}.metric span,.metric b,.metric small{display:block}.metric span{color:#728197;font-size:13px}.metric b{font-size:28px;margin:7px 0;color:#20344f}.metric small{color:#8b97a7}.metric.orange{border-color:var(--orange)}.metric.green{border-color:var(--green)}.metric.purple{border-color:#8a5bd6}.metric.red{border-color:var(--red)}.explain{margin-bottom:14px}.section-block{background:#fff;border-radius:12px;padding:17px;margin-bottom:14px;box-shadow:0 2px 12px #263b550b}.section-title{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:14px}.section-title h3{margin:0;font-size:18px}.section-title p{margin:5px 0 0;color:#8491a3;font-size:13px}.section-title>span{color:#718096;font-size:13px}.staff-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.staff-card{border:1px solid #e7ebf1;border-radius:12px;padding:14px;cursor:pointer;transition:.2s}.staff-card:hover,.staff-card.selected{border-color:#3978e9;box-shadow:0 3px 14px #3978e91c}.staff-card.idle{opacity:.68}.staff-card header{display:flex;align-items:center;gap:9px}.staff-card header>div:nth-child(2){flex:1}.staff-card h4{margin:0 0 4px;font-size:16px}.staff-card header span{font-size:12px;color:#7f8c9f}.avatar{width:38px;height:38px;border-radius:10px;background:#e9f0ff;color:#3978e9;display:grid;place-items:center;font-weight:800}.avatar.delivery{background:#e2f7ef;color:#168c65}.work-numbers{display:grid;grid-template-columns:repeat(3,1fr);margin:14px 0}.work-numbers div{text-align:center;border-right:1px solid #edf0f4}.work-numbers div:last-child{border:0}.work-numbers b,.work-numbers span{display:block}.work-numbers b{font-size:16px}.work-numbers span{font-size:11px;color:#8a96a6;margin-top:3px}.content-line{display:grid;grid-template-columns:65px 1fr;gap:6px;margin-top:10px;font-size:12px}.content-line span{color:#8a96a6}.content-line p{margin:0;color:#536277;line-height:1.5}.staff-card footer{display:flex;justify-content:space-between;border-top:1px dashed #e5e9ef;margin-top:11px;padding-top:9px;font-size:11px;color:#8793a3}.danger,.exception-text{color:#df4b55!important}.task-detail{padding:12px 24px}.timeline-summary{display:flex;gap:22px;flex-wrap:wrap;background:#f5f8fb;padding:10px 12px;border-radius:8px;margin-bottom:10px;font-size:12px;color:#718096}.timeline-summary b{color:#33445b}.subtext{font-size:12px;color:#8995a6;margin-top:4px}.slash{color:#c0c6cf;margin:0 7px}.interval{color:#3978e9}.exception-text{font-size:11px;margin-top:4px}
@media(max-width:1200px){.overview{grid-template-columns:repeat(3,1fr)}.staff-grid{grid-template-columns:repeat(2,1fr)}.filters{grid-template-columns:repeat(3,1fr)}}
@media(max-width:760px){.header-actions{flex-wrap:wrap}.overview{grid-template-columns:repeat(2,1fr)}.staff-grid,.filters{grid-template-columns:1fr}.quick-row{display:block}.quick-row .el-radio-group{margin-top:8px;display:flex;flex-wrap:wrap}.task-detail{padding:8px 0}}
</style>
