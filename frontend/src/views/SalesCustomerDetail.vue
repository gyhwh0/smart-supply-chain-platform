<template>
  <div>
    <div class="page-header">
      <div class="title-row"><el-button circle @click="router.back()"><el-icon><ArrowLeft /></el-icon></el-button><div><h2>{{ detail.customer?.name || '客户销售明细' }}</h2><p>当前明细沿用销售汇总页面选择的时间与过滤范围</p></div></div>
      <el-button type="primary" plain @click="router.push('/sales-summary')">返回销售汇总</el-button>
    </div>
    <el-card v-if="detail.customer" class="profile-card">
      <div><span>联系人</span><b>{{ detail.customer.contact_name || '未填写' }}</b></div><div><span>电话</span><b>{{ detail.customer.phone || '未填写' }}</b></div><div><span>地址</span><b>{{ detail.customer.address || '未填写' }}</b></div><div><span>分拣员</span><b>{{ detail.customer.sorter_name }}</b></div><div><span>配送员</span><b>{{ detail.customer.delivery_name }}</b></div>
    </el-card>
    <div class="metric-grid"><el-card><small>销售单数</small><strong>{{ detail.order_count }}</strong></el-card><el-card><small>商品明细</small><strong>{{ detail.item_count }}</strong></el-card><el-card><small>销售金额</small><strong class="amount">¥{{ money(detail.total_amount) }}</strong></el-card></div>
    <el-card class="panel">
      <div class="range-tip"><el-icon><Calendar /></el-icon><span>统计范围：{{ route.query.date_from || '不限' }} 至 {{ route.query.date_to || '不限' }}</span><el-tag v-if="route.query.category">分类：{{ route.query.category }}</el-tag></div>
      <el-table :data="detail.orders" row-key="id" empty-text="当前范围没有销售明细">
        <el-table-column type="expand"><template #default="scope"><div class="items-box"><el-table :data="scope.row.items" size="small"><el-table-column prop="product_name" label="商品" min-width="150" /><el-table-column prop="category" label="分类" width="110" /><el-table-column prop="specification" label="规格" width="120"><template #default="cell">{{ cell.row.specification || '—' }}</template></el-table-column><el-table-column label="数量" width="120"><template #default="cell">{{ cell.row.quantity }} {{ cell.row.unit_name }}</template></el-table-column><el-table-column label="销售单价" width="120"><template #default="cell">¥{{ money(cell.row.unit_price) }}</template></el-table-column><el-table-column label="金额" width="125"><template #default="cell"><b>¥{{ money(cell.row.amount) }}</b></template></el-table-column><el-table-column prop="supplier_name" label="采购供应商" min-width="150" /><el-table-column prop="remark" label="备注" min-width="140"><template #default="cell">{{ cell.row.remark || '—' }}</template></el-table-column></el-table></div></template></el-table-column>
        <el-table-column prop="order_no" label="销售单号" min-width="190" />
        <el-table-column prop="order_date" label="下单日期" width="115" />
        <el-table-column label="制单时间" min-width="175"><template #default="scope">{{ formatTime(scope.row.created_at) }}</template></el-table-column>
        <el-table-column prop="creator_name" label="制单人/订单员" min-width="140" />
        <el-table-column prop="delivery_date" label="要求交期" width="115"><template #default="scope">{{ scope.row.delivery_date || '未指定' }}</template></el-table-column>
        <el-table-column label="商品" width="90"><template #default="scope">{{ scope.row.items.length }} 项</template></el-table-column>
        <el-table-column label="销售金额" width="145"><template #default="scope"><b class="amount">¥{{ money(scope.row.total_amount) }}</b></template></el-table-column>
      </el-table>
      <el-pagination v-if="detail.order_count > pageSize" v-model:current-page="page" :page-size="pageSize" :total="detail.order_count" layout="total, prev, pager, next, jumper" class="pagination" @current-change="load" />
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getSalesCustomerDetail } from '@/api'
const route = useRoute(), router = useRouter()
const detail = reactive({ customer: null, orders: [], order_count: 0, item_count: 0, total_amount: 0 })
const page = ref(1), pageSize = 20
const money = value => Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const formatTime = value => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—'
const load = async () => Object.assign(detail, await getSalesCustomerDetail(route.params.id, { ...route.query, page: page.value, page_size: pageSize }))
onMounted(load)
</script>

<style scoped>
.title-row { display:flex; align-items:center; gap:13px; }.title-row h2,.title-row p { margin:0; }.title-row p { margin-top:6px; color:#8490a3; }
.profile-card { margin-bottom:16px; }.profile-card :deep(.el-card__body) { display:grid; grid-template-columns:1fr 1fr 2fr 1fr 1fr; gap:18px; }.profile-card span,.profile-card b { display:block; }.profile-card span { color:#8490a3; font-size:13px; margin-bottom:6px; }
.metric-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:14px; margin-bottom:18px; }.metric-grid small,.metric-grid strong { display:block; }.metric-grid small { color:#7c8799; }.metric-grid strong { font-size:27px; margin-top:8px; }.amount { color:#df6131; }.range-tip { display:flex; align-items:center; gap:9px; margin-bottom:15px; color:#657287; }.items-box { padding:10px 45px 16px; background:#f7f9fc; }
.pagination { justify-content:flex-end; margin-top:16px; }
</style>
