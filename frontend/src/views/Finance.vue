<template>
  <div>
    <div class="page-header">
      <div><h2>财务管理</h2><p>按配送业务日期核对预定、实配、验收、开票与毛利；销售额以客户验收数量为准</p></div>
      <el-button type="primary" :loading="loading" @click="load"><el-icon><Refresh /></el-icon> 刷新数据</el-button>
    </div>

    <el-card class="panel filters">
      <el-date-picker v-model="dateRange" type="daterange" value-format="YYYY-MM-DD" range-separator="至" start-placeholder="开始日期" end-placeholder="结束日期" :clearable="false" />
      <el-select v-model="filters.customer_id" filterable clearable placeholder="全部客户" style="width:190px"><el-option v-for="item in options.customers" :key="item.id" :label="item.name" :value="item.id" /></el-select>
      <el-select v-model="filters.category" clearable placeholder="全部商品分类" style="width:170px"><el-option v-for="item in options.categories" :key="item" :label="item" :value="item" /></el-select>
      <el-button type="primary" @click="load">查询汇总</el-button>
      <el-button @click="reset">今天</el-button>
    </el-card>

    <el-alert class="rule-tip" type="info" :closable="false" show-icon title="统计口径：预定金额=确认销售单；配送金额=配送员装车确认或人工实配；验收/销售金额=客户实际验收；毛利=验收金额－对应采购成本。成本缺失的商品不计入毛利。" />

    <div class="metric-grid" v-loading="loading">
      <el-card v-for="item in metricCards" :key="item.key" :class="item.className"><small>{{ item.label }}</small><strong>{{ item.money ? `¥${money(metrics[item.key])}` : integer(metrics[item.key]) }}</strong><span>{{ item.help }}</span></el-card>
    </div>

    <div v-if="metrics.pending_acceptance_count || metrics.missing_cost_items || metrics.variance_order_count" class="attention-grid">
      <el-alert v-if="metrics.pending_acceptance_count" type="warning" :closable="false" show-icon :title="`${metrics.pending_acceptance_count} 张销售单尚未完成验收，暂不计入销售额`" />
      <el-alert v-if="metrics.missing_cost_items" type="error" :closable="false" show-icon :title="`${metrics.missing_cost_items} 项已验收商品缺少成本，毛利暂未计入`" />
      <el-alert v-if="metrics.variance_order_count" type="info" :closable="false" show-icon :title="`${metrics.variance_order_count} 张销售单存在实配与验收差异`" />
    </div>

    <el-row :gutter="16" class="ranking-row">
      <el-col :span="15">
        <el-card class="panel ranking-card">
          <template #header><div class="card-title"><div><b>销售商品排行</b><small>按验收销售金额排序，可同时核对数量与毛利</small></div><el-radio-group v-model="rankMode" size="small"><el-radio-button value="amount">金额</el-radio-button><el-radio-button value="gross_profit">毛利</el-radio-button><el-radio-button value="base_quantity">数量</el-radio-button></el-radio-group></div></template>
          <el-table :data="sortedProducts" max-height="390" empty-text="所选时间暂无已验收商品">
            <el-table-column type="index" label="排名" width="65" />
            <el-table-column prop="product_name" label="商品" min-width="150" />
            <el-table-column prop="category" label="分类" width="105" />
            <el-table-column label="验收数量（折算）" width="145"><template #default="s">{{ number(s.row.base_quantity) }}</template></el-table-column>
            <el-table-column label="销售金额" width="130"><template #default="s"><b class="money">¥{{ money(s.row.amount) }}</b></template></el-table-column>
            <el-table-column label="毛利" width="125"><template #default="s"><span :class="s.row.missing_cost ? 'warn' : 'profit'">{{ s.row.missing_cost ? '成本待补' : `¥${money(s.row.gross_profit)}` }}</span></template></el-table-column>
          </el-table>
        </el-card>
      </el-col>
      <el-col :span="9">
        <el-card class="panel ranking-card">
          <template #header><div class="card-title"><div><b>客户销售排行</b><small>按实际验收销售金额排序</small></div></div></template>
          <el-table :data="data.customer_ranking" max-height="390" empty-text="暂无客户销售数据">
            <el-table-column type="index" width="55" />
            <el-table-column prop="customer_name" label="客户" min-width="125" />
            <el-table-column prop="order_count" label="订单" width="65" />
            <el-table-column label="销售金额" width="120"><template #default="s">¥{{ money(s.row.amount) }}</template></el-table-column>
            <el-table-column label="毛利" width="110"><template #default="s">¥{{ money(s.row.gross_profit) }}</template></el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>

    <el-card class="panel">
      <template #header><div class="card-title"><div><b>销售单验收与财务核对</b><small>点击核对可登记少送、损耗、客户实收、成本和开票金额</small></div></div></template>
      <el-table :data="data.orders" row-key="id" v-loading="loading">
        <el-table-column type="expand"><template #default="s"><el-table :data="s.row.items" size="small"><el-table-column prop="product_name" label="商品" min-width="140" /><el-table-column label="预定" width="105"><template #default="i">{{number(i.row.ordered_quantity)}} {{i.row.unit_name}}</template></el-table-column><el-table-column label="实配" width="105"><template #default="i">{{i.row.delivered_quantity == null ? '待配送' : `${number(i.row.delivered_quantity)} ${i.row.unit_name}`}}</template></el-table-column><el-table-column label="验收" width="105"><template #default="i">{{i.row.accepted_quantity == null ? '待验收' : `${number(i.row.accepted_quantity)} ${i.row.unit_name}`}}</template></el-table-column><el-table-column prop="variance_reason" label="差异原因" min-width="140"><template #default="i">{{i.row.variance_reason || '—'}}</template></el-table-column><el-table-column label="成本来源" width="130"><template #default="i">{{i.row.cost_source}}</template></el-table-column></el-table></template></el-table-column>
        <el-table-column prop="order_no" label="销售单号" min-width="185" />
        <el-table-column prop="business_date" label="业务日期" width="115" />
        <el-table-column prop="customer_name" label="客户" min-width="130" />
        <el-table-column label="预定金额" width="115"><template #default="s">¥{{money(s.row.ordered_amount)}}</template></el-table-column>
        <el-table-column label="配送金额" width="115"><template #default="s">¥{{money(s.row.delivered_amount)}}</template></el-table-column>
        <el-table-column label="验收金额" width="115"><template #default="s"><b class="money">¥{{money(s.row.accepted_amount)}}</b></template></el-table-column>
        <el-table-column label="毛利" width="110"><template #default="s">¥{{money(s.row.gross_profit)}}</template></el-table-column>
        <el-table-column label="验收状态" width="105"><template #default="s"><el-tag :type="acceptanceType(s.row.acceptance_status)">{{acceptanceLabel(s.row.acceptance_status)}}</el-tag></template></el-table-column>
        <el-table-column label="开票" width="115"><template #default="s"><span v-if="s.row.invoice_amount">¥{{money(s.row.invoice_amount)}}</span><span v-else class="muted">未开票</span></template></el-table-column>
        <el-table-column label="操作" width="100" fixed="right"><template #default="s"><el-button link type="primary" @click="openSettlement(s.row)">核对</el-button></template></el-table-column>
      </el-table>
    </el-card>

    <el-card v-if="data.daily.length > 1" class="panel daily-card">
      <template #header><div class="card-title"><div><b>每日经营汇总</b><small>用于跨日期查询时查看每日变化</small></div></div></template>
      <el-table :data="data.daily"><el-table-column prop="date" label="日期" /><el-table-column prop="order_count" label="订单数" /><el-table-column label="预定金额"><template #default="s">¥{{money(s.row.ordered_amount)}}</template></el-table-column><el-table-column label="配送金额"><template #default="s">¥{{money(s.row.delivered_amount)}}</template></el-table-column><el-table-column label="销售金额"><template #default="s">¥{{money(s.row.accepted_amount)}}</template></el-table-column><el-table-column label="开票金额"><template #default="s">¥{{money(s.row.invoice_amount)}}</template></el-table-column><el-table-column label="毛利"><template #default="s">¥{{money(s.row.gross_profit)}}</template></el-table-column></el-table>
    </el-card>

    <el-dialog v-model="settlementVisible" :title="`配送验收与财务核对 · ${settlement.order_no || ''}`" width="92%" top="4vh">
      <el-alert title="实配数量来自配送装车扫码，也可以人工修正；实配与验收不一致时必须写明少送、正常损耗、退货等原因。" type="warning" :closable="false" show-icon />
      <div class="settlement-meta"><b>{{settlement.customer_name}}</b><span>业务日期 {{settlement.business_date}}</span><span>预定金额 ¥{{money(settlement.ordered_amount)}}</span></div>
      <el-table :data="settlement.items" border max-height="500">
        <el-table-column prop="product_name" label="商品" min-width="150" />
        <el-table-column label="预定数量" width="120"><template #default="s">{{number(s.row.ordered_quantity)}} {{s.row.unit_name}}</template></el-table-column>
        <el-table-column label="实配数量" width="155"><template #default="s"><el-input-number v-model="s.row.delivered_quantity" :min="0" :precision="4" controls-position="right" /></template></el-table-column>
        <el-table-column label="客户验收数量" width="165"><template #default="s"><el-input-number v-model="s.row.accepted_quantity" :min="0" :precision="4" controls-position="right" /></template></el-table-column>
        <el-table-column label="差异" width="95"><template #default="s"><span :class="difference(s.row) ? 'warn' : 'muted'">{{s.row.accepted_quantity == null ? '待验收' : number(difference(s.row))}}</span></template></el-table-column>
        <el-table-column label="差异原因" min-width="180"><template #default="s"><el-input v-model="s.row.variance_reason" :placeholder="difference(s.row) ? '必填：少送/损耗/退货等' : '无差异可不填'" /></template></el-table-column>
        <el-table-column label="成本单价" width="155"><template #default="s"><el-input-number v-model="s.row.cost_unit_price" :min="0" :precision="4" controls-position="right" /><small class="cost-source">{{s.row.cost_source}}</small></template></el-table-column>
        <el-table-column label="验收金额" width="120"><template #default="s">¥{{money((s.row.accepted_quantity || 0) * s.row.unit_price)}}</template></el-table-column>
      </el-table>
      <div class="invoice-box"><el-form label-position="top"><el-row :gutter="16"><el-col :span="8"><el-form-item label="累计开票金额"><el-input-number v-model="settlement.invoice_amount" :min="0" :precision="2" controls-position="right" style="width:100%" /></el-form-item></el-col><el-col :span="8"><el-form-item label="开票日期"><el-date-picker v-model="settlement.invoice_date" value-format="YYYY-MM-DD" clearable style="width:100%" /></el-form-item></el-col><el-col :span="8"><div class="accepted-total"><small>本单验收金额</small><b>¥{{money(settlementAcceptedAmount)}}</b></div></el-col></el-row></el-form></div>
      <template #footer><el-button @click="settlementVisible=false">取消</el-button><el-button type="primary" :loading="saving" @click="saveSettlement">保存核对结果</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getFinanceDashboard, getFinanceOptions, getFinanceOrderDetail, saveFinanceSettlement } from '@/api'

const localDate = value => { const d=value||new Date(); const offset=d.getTimezoneOffset()*60000; return new Date(d-offset).toISOString().slice(0,10) }
const dateRange=ref([localDate(),localDate()]),filters=reactive({customer_id:null,category:null}),options=reactive({customers:[],categories:[]})
const loading=ref(false),saving=ref(false),rankMode=ref('amount'),settlementVisible=ref(false)
const emptyData=()=>({metrics:{},orders:[],product_ranking:[],customer_ranking:[],daily:[]})
const data=reactive(emptyData()),settlement=reactive({items:[]})
const metrics=computed(()=>data.metrics||{})
const metricCards=[
  {key:'sales_amount',label:'当日销售金额',help:'按客户实际验收',money:true,className:'primary'},
  {key:'ordered_amount',label:'预定金额',help:'确认销售单原金额',money:true},
  {key:'delivered_amount',label:'配送金额',help:'按实际配送数量',money:true},
  {key:'accepted_amount',label:'验收金额',help:'财务结算依据',money:true},
  {key:'invoice_amount',label:'开票金额',help:'累计已登记开票',money:true},
  {key:'supplement_amount',label:'加补金额',help:'合并加单金额',money:true},
  {key:'gross_profit',label:'销售毛利',help:'验收销售－采购成本',money:true,className:'profit-card'},
  {key:'order_count',label:'订单数',help:'已确认销售单'},
  {key:'customer_count',label:'下单客户数',help:'去重客户'},
  {key:'max_order_amount',label:'单笔最大金额',help:'按预定金额',money:true},
]
const sortedProducts=computed(()=>[...data.product_ranking].sort((a,b)=>Number(b[rankMode.value]||0)-Number(a[rankMode.value]||0)))
const settlementAcceptedAmount=computed(()=>settlement.items.reduce((sum,item)=>sum+Number(item.accepted_quantity||0)*Number(item.unit_price||0),0))
const money=value=>Number(value||0).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2})
const number=value=>Number(value||0).toLocaleString('zh-CN',{maximumFractionDigits:4})
const integer=value=>Number(value||0).toLocaleString('zh-CN')
const acceptanceLabel=value=>({pending:'待验收',partial:'部分验收',accepted:'已验收'})[value]||value
const acceptanceType=value=>value==='accepted'?'success':value==='partial'?'warning':'info'
const difference=item=>Number(item.delivered_quantity||0)-Number(item.accepted_quantity||0)
const params=()=>({date_from:dateRange.value?.[0],date_to:dateRange.value?.[1],customer_id:filters.customer_id||undefined,category:filters.category||undefined})
const load=async()=>{loading.value=true;try{Object.assign(data,await getFinanceDashboard(params()))}finally{loading.value=false}}
const reset=()=>{dateRange.value=[localDate(),localDate()];filters.customer_id=null;filters.category=null;load()}
const openSettlement=async row=>{const detail=await getFinanceOrderDetail(row.id);detail.items=detail.items.map(item=>({...item,delivered_quantity:item.delivered_quantity??item.ordered_quantity,accepted_quantity:item.accepted_quantity??item.delivered_quantity??item.ordered_quantity,variance_reason:item.variance_reason||''}));Object.assign(settlement,detail);settlementVisible.value=true}
const saveSettlement=async()=>{
  for(const item of settlement.items){if(item.accepted_quantity!=null&&item.delivered_quantity==null)return ElMessage.warning(`${item.product_name}请填写实配数量`);if(difference(item)&&!item.variance_reason?.trim())return ElMessage.warning(`${item.product_name}存在数量差异，请填写原因`)}
  if(Number(settlement.invoice_amount||0)>0&&!settlement.invoice_date)return ElMessage.warning('填写开票金额后请选择开票日期')
  saving.value=true
  try{const result=await saveFinanceSettlement(settlement.id,{invoice_amount:settlement.invoice_amount||0,invoice_date:settlement.invoice_date||null,items:settlement.items.map(item=>({sales_order_item_id:item.id,delivered_quantity:item.delivered_quantity,accepted_quantity:item.accepted_quantity,variance_reason:item.variance_reason?.trim()||null,cost_unit_price:item.cost_unit_price}))});ElMessage.success(result.message);settlementVisible.value=false;await load()}finally{saving.value=false}
}
onMounted(async()=>{Object.assign(options,await getFinanceOptions());await load()})
</script>

<style scoped>
.filters{display:flex;align-items:center;gap:10px;margin-bottom:12px}.rule-tip{margin-bottom:14px}.metric-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px;margin-bottom:16px}.metric-grid small,.metric-grid strong,.metric-grid span{display:block}.metric-grid small{color:#78869a}.metric-grid strong{font-size:23px;margin:8px 0 5px;color:#22344d}.metric-grid span{font-size:12px;color:#98a2b1}.metric-grid .primary{border-top:3px solid #337ecc}.metric-grid .primary strong{color:#266fba}.metric-grid .profit-card{border-top:3px solid #21a179}.metric-grid .profit-card strong{color:#188662}.attention-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:16px}.ranking-row{margin-bottom:16px}.ranking-card{height:470px}.card-title{display:flex;justify-content:space-between;align-items:center}.card-title b,.card-title small{display:block}.card-title small{color:#8a96a7;margin-top:4px}.money{color:#dd6437}.profit{color:#17855e}.warn{color:#d67b19}.muted{color:#9aa3b1}.settlement-meta{display:flex;gap:24px;align-items:center;margin:16px 0;color:#68758a}.settlement-meta b{font-size:18px;color:#263750}.cost-source{display:block;color:#8793a3;margin-top:4px}.invoice-box{background:#f5f8fc;border-radius:10px;padding:14px 16px 0;margin-top:15px}.accepted-total{text-align:right;padding-top:9px}.accepted-total small,.accepted-total b{display:block}.accepted-total b{font-size:23px;color:#d45e32;margin-top:6px}.daily-card{margin-top:16px}@media(max-width:1200px){.metric-grid{grid-template-columns:repeat(3,1fr)}.ranking-row :deep(.el-col){max-width:100%;flex:0 0 100%;margin-bottom:14px}.attention-grid{grid-template-columns:1fr}}@media(max-width:700px){.metric-grid{grid-template-columns:repeat(2,1fr)}.filters{flex-wrap:wrap}}
</style>
