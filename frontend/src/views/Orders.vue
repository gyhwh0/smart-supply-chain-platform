<template>
  <div>
    <div class="page-header"><div><h2>采购下单</h2><p>接收仓库备货需求，基于供应商报价生成并下达采购单</p></div><div><el-button type="primary" plain @click="router.push('/smart-split')">智能拆单</el-button><el-badge :value="pendingRequisitionCount" :hidden="!pendingRequisitionCount"><el-button type="warning" plain @click="requisitionVisible=true">备货采购需求</el-button></el-badge><el-button type="success" plain @click="openSales"><el-icon><DocumentCopy/></el-icon>引用销售单</el-button><el-button type="primary" @click="openCreate"><el-icon><Plus/></el-icon>新增采购订单</el-button></div></div>
    <el-card class="panel">
      <div class="toolbar"><el-input v-model="keyword" clearable prefix-icon="Search" placeholder="搜索订单号、供应商或标题" style="width:340px"/><el-select v-model="statusFilter" clearable placeholder="全部状态" style="width:150px"><el-option label="草稿" value="draft"/><el-option label="已确认" value="confirmed"/></el-select></div>
      <el-table :data="filteredOrders"><el-table-column type="expand"><template #default="s"><div class="saved-items"><div class="saved-title"><b>采购单已保存商品</b><span>这些商品已在采购单中，无需重新加入</span></div><el-table :data="s.row.items" size="small"><el-table-column prop="product_name" label="商品" min-width="160"/><el-table-column prop="category" label="分类" width="110"/><el-table-column label="采购数量" width="135"><template #default="cell">{{cell.row.quantity}} {{cell.row.unit_name}}</template></el-table-column><el-table-column label="采购单价" width="120"><template #default="cell">¥ {{money(cell.row.unit_price)}}</template></el-table-column><el-table-column label="金额" width="130"><template #default="cell"><b>¥ {{money(cell.row.amount)}}</b></template></el-table-column><el-table-column label="价格" width="120"><template #default="cell"><el-tag v-if="cell.row.is_best_price" type="success">最优价</el-tag><el-tag v-else type="info">普通报价</el-tag></template></el-table-column><el-table-column prop="remark" label="来源/备注" min-width="200"/></el-table></div></template></el-table-column><el-table-column prop="order_no" label="订单编号" min-width="190"/><el-table-column prop="title" label="报表标题" min-width="150"/><el-table-column prop="supplier_name" label="供应商" min-width="150"/><el-table-column label="已带入商品" min-width="220"><template #default="s"><div class="item-preview"><b>{{s.row.items.length}} 项</b><span>{{s.row.items.slice(0,2).map(item=>item.product_name).join('、')}}<template v-if="s.row.items.length>2"> 等</template></span></div></template></el-table-column><el-table-column label="订单金额" min-width="130"><template #default="s"><strong class="price">¥ {{money(s.row.total_amount)}}</strong></template></el-table-column><el-table-column prop="expected_date" label="期望到货" width="120"/><el-table-column label="状态" width="100"><template #default="s"><el-tag :type="s.row.status==='confirmed'?'success':'warning'">{{s.row.status==='confirmed'?'已下达':'草稿'}}</el-tag></template></el-table-column><el-table-column label="操作" width="410" fixed="right"><template #default="s"><el-button link type="primary" @click="openEdit(s.row)">查看/编辑明细</el-button><el-button v-if="s.row.status==='draft'" link type="success" @click="confirm(s.row)">确认并下达供应商</el-button><el-button v-if="s.row.status==='draft'" link type="danger" @click="remove(s.row)">删除</el-button><template v-else><el-button link @click="download(s.row,'png')">下载图片</el-button><el-button link @click="download(s.row,'xlsx')">下载表格</el-button></template></template></el-table-column></el-table>
    </el-card>

    <el-dialog :key="dialogKey" v-model="visible" v-loading="dialogLoading" :title="form.id?'编辑采购订单及报表':'新增采购订单'" width="1080px" top="3vh" destroy-on-close @closed="resetOrderDialog">
      <el-steps :active="form.supplier_id ? (lines.length ? 2 : 1) : 0" simple><el-step title="选择供应商"/><el-step title="批量选择商品"/><el-step title="编辑订单报表"/></el-steps>
      <div class="order-basic">
        <el-form label-width="90px"><el-row :gutter="14"><el-col :span="10"><el-form-item label="供应商" required><el-select v-model="form.supplier_id" filterable :disabled="!!form.id" placeholder="请先选择供应商" style="width:100%" @change="loadOptions"><el-option v-for="s in activeSuppliers" :key="s.id" :label="s.name" :value="s.id"/></el-select></el-form-item></el-col><el-col :span="8"><el-form-item label="报表标题"><el-input v-model="form.title"/></el-form-item></el-col><el-col :span="6"><el-form-item label="期望到货"><el-date-picker v-model="form.expected_date" type="date" value-format="YYYY-MM-DD" style="width:100%"/></el-form-item></el-col></el-row></el-form>
      </div>

      <template v-if="form.supplier_id">
        <div v-if="!form.id || showChooser" class="chooser">
          <div class="section-head"><div><strong>选择商品</strong><span>价格来自该供应商最新报价，绿色标签表示该供应商为当前最优价</span></div><el-button type="primary" plain :disabled="!filteredProducts.length" @click="addFiltered">添加当前筛选全部（{{filteredProducts.length}}）</el-button></div>
          <div class="product-filters"><el-input v-model="productKeyword" clearable placeholder="搜索商品名称、别名或 SKU"/><el-select v-model="categoryFilter" clearable placeholder="全部分类"><el-option v-for="c in categoryOptions" :key="c" :label="c" :value="c"/></el-select><el-radio-group v-model="priceFilter"><el-radio-button value="all">全部报价</el-radio-button><el-radio-button value="best">只看最优价</el-radio-button></el-radio-group></div>
          <div class="product-list"><div v-for="product in filteredProducts" :key="product.product_id" class="product-card" :class="{selected:hasLine(product.product_id)}"><div><strong>{{product.name}}</strong><small>{{product.category}} · {{product.sku||'无 SKU'}}<template v-if="product.aliases?.length"> · 别名：{{product.aliases.join('、')}}</template></small></div><div class="quote-info"><span>最低可订价 <b>¥ {{money(product.quote_units[0].price)}}</b> / {{product.quote_units[0].unit_name}}</span><el-tag v-if="product.has_best_price" type="success" effect="dark">该供应商为最优价</el-tag><el-tag v-else type="info">非最优价</el-tag></div><el-button v-if="!hasLine(product.product_id)" type="primary" link @click="addProduct(product)">加入订单</el-button><el-button v-else type="success" link disabled>已加入</el-button></div><el-empty v-if="!filteredProducts.length" description="该供应商暂无符合条件的有效报价" :image-size="60"/></div>
        </div>

        <div class="section-head selected-head"><div><strong>{{form.id?'已保存的采购商品':'订单明细与报表内容'}}</strong><span>{{form.id?'销售单商品已自动带入，可直接确认或调整数量价格':'数量、采购价和备注均可自定义修改'}}</span></div><div class="selected-actions"><el-button v-if="form.id" plain @click="showChooser=!showChooser">{{showChooser?'收起选品区':'添加其他商品'}}</el-button><strong class="total">合计：¥ {{money(total)}}</strong></div></div>
        <el-table :data="lines" max-height="310" border><el-table-column prop="product_name" label="商品" min-width="140"/><el-table-column prop="category" label="分类" width="100"/><el-table-column label="采购单位" min-width="130"><template #default="s"><el-select v-model="s.row.unit_id" @change="changeUnit(s.row)"><el-option v-for="u in s.row.quote_units" :key="u.unit_id" :label="`${u.unit_name} · ¥${money(u.price)}`" :value="u.unit_id"/></el-select></template></el-table-column><el-table-column label="数量" width="125"><template #default="s"><el-input-number v-model="s.row.quantity" :min="0.01" :precision="2" controls-position="right" style="width:105px"/></template></el-table-column><el-table-column label="采购单价" width="145"><template #default="s"><el-input-number v-model="s.row.unit_price" :min="0.01" :precision="2" controls-position="right" style="width:125px"/></template></el-table-column><el-table-column label="价格优势" width="130"><template #default="s"><el-tag v-if="selectedQuote(s.row)?.is_best_price" type="success">供应商最优价</el-tag><el-tag v-else type="info">普通报价</el-tag></template></el-table-column><el-table-column label="金额" width="110"><template #default="s">¥ {{money(s.row.quantity*s.row.unit_price)}}</template></el-table-column><el-table-column label="行备注" min-width="150"><template #default="s"><el-input v-model="s.row.remark" placeholder="可选"/></template></el-table-column><el-table-column width="60"><template #default="s"><el-button link type="danger" @click="lines.splice(s.$index,1)">移除</el-button></template></el-table-column></el-table>
        <el-form label-width="90px" class="report-fields"><el-form-item label="订单备注"><el-input v-model="form.notes" type="textarea" :rows="2" placeholder="付款、交付、验收等说明"/></el-form-item><el-form-item label="报表页脚"><el-input v-model="form.report_footer" placeholder="例如：请按订单明细备货并及时反馈交期"/></el-form-item></el-form>
      </template>
      <template #footer><el-button @click="visible=false">取消</el-button><el-button type="primary" :disabled="!lines.length" @click="save">{{form.id?'保存修改':'保存为草稿'}}</el-button></template>
    </el-dialog>
    <el-dialog v-model="salesVisible" title="引用销售单自动生成采购" width="900px">
      <el-alert title="系统会逐项比较供应商报价，自动选择标准单位价格最低的供应商，并按供应商拆分采购单。无报价商品会保留，补充报价后可再次生成。" type="success" show-icon :closable="false"/>
      <el-table :data="salesOrders" style="margin-top:16px" max-height="520">
        <el-table-column prop="order_no" label="销售单号" min-width="185"/>
        <el-table-column prop="customer_name" label="客户" min-width="130"/>
        <el-table-column prop="order_date" label="日期" width="110"/>
        <el-table-column label="商品/金额" min-width="145"><template #default="s">{{s.row.items.length}} 项 · ¥{{money(s.row.total_amount)}}</template></el-table-column>
        <el-table-column label="已生成" width="100"><template #default="s"><el-tag v-if="s.row.purchases.length" type="success">{{s.row.purchases.length}} 张</el-tag><span v-else>未生成</span></template></el-table-column>
        <el-table-column label="操作" width="135"><template #default="s"><el-button type="primary" link @click="allocateFromSales(s.row)">逐商品分配</el-button></template></el-table-column>
      </el-table>
    </el-dialog>
    <el-dialog v-model="requisitionVisible" title="仓库备货采购需求" width="1050px" top="5vh"><el-alert type="info" :closable="false" title="系统按库存结余自动计算缺口；点击生成后按当前最优报价拆分为供应商采购草稿，再到采购列表确认下达。"/><el-table :data="requisitions" row-key="id" style="margin-top:14px" max-height="560"><el-table-column type="expand"><template #default="s"><el-table :data="s.row.items" size="small" border><el-table-column prop="product_name" label="缺货商品"/><el-table-column prop="category" label="分类"/><el-table-column label="需求数量"><template #default="c">{{c.row.quantity}} {{c.row.unit_name}}</template></el-table-column><el-table-column label="已生成采购"><template #default="c">{{c.row.ordered_quantity}} {{c.row.unit_name}}</template></el-table-column><el-table-column label="待采购"><template #default="c"><b class="price">{{c.row.remaining_quantity}} {{c.row.unit_name}}</b></template></el-table-column></el-table></template></el-table-column><el-table-column prop="requisition_no" label="需求单号" min-width="190"/><el-table-column prop="warehouse_document_no" label="备货单" min-width="170"/><el-table-column prop="target_name" label="备货对象" min-width="130"/><el-table-column prop="needed_date" label="需求日期" width="115"/><el-table-column label="状态" width="110"><template #default="s"><el-tag :type="requisitionStatus(s.row.status).type">{{requisitionStatus(s.row.status).label}}</el-tag></template></el-table-column><el-table-column label="采购单" min-width="180"><template #default="s"><div v-if="s.row.purchase_orders.length"><el-tag v-for="o in s.row.purchase_orders" :key="o.id" size="small">{{o.supplier_name}} · {{o.order_no}}</el-tag></div><span v-else class="muted">尚未生成</span></template></el-table-column><el-table-column label="操作" width="140"><template #default="s"><el-button v-if="s.row.status==='pending'" link type="primary" @click="generateRequisition(s.row)">按最优价生成采购</el-button><span v-else class="muted">{{s.row.status==='ordered'?'已生成':'库存充足'}}</span></template></el-table-column></el-table></el-dialog>
  </div>
</template>
<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { confirmOrder, createOrder, deleteOrder, downloadOrderReport, generateOrdersFromRequisition, getOrderOptions, getOrders, getPurchaseRequisitions, getSalesOrders, getSuppliers, updateOrder } from '@/api'

const router = useRouter()
const orders = ref([]), suppliers = ref([]), salesOrders = ref([]), requisitions = ref([])
const visible = ref(false), salesVisible = ref(false), requisitionVisible = ref(false), showChooser = ref(true), dialogLoading = ref(false)
const dialogKey = ref(0), options = ref({ products: [] }), lines = ref([])
const keyword = ref(''), statusFilter = ref(''), productKeyword = ref(''), categoryFilter = ref(''), priceFilter = ref('all')
let editRequestId = 0
const blank = () => ({ id: null, supplier_id: null, title: '采购订单', expected_date: null, notes: '', report_footer: '请供应商按订单明细备货，并及时反馈交付情况。' })
const form = reactive(blank())
const activeSuppliers = computed(() => suppliers.value.filter(item => item.active || item.id === form.supplier_id))
const categoryOptions = computed(() => [...new Set(options.value.products.map(item => item.category))].sort())
const filteredProducts = computed(() => options.value.products.filter(item => (!productKeyword.value || `${item.name}${(item.aliases || []).join('')}${item.sku || ''}`.toLowerCase().includes(productKeyword.value.toLowerCase())) && (!categoryFilter.value || item.category === categoryFilter.value) && (priceFilter.value === 'all' || item.has_best_price)))
const filteredOrders = computed(() => orders.value.filter(order => (!keyword.value || `${order.order_no}${order.supplier_name}${order.title}${order.items.map(item => item.product_name).join('')}`.toLowerCase().includes(keyword.value.toLowerCase())) && (!statusFilter.value || order.status === statusFilter.value)))
const total = computed(() => lines.value.reduce((sum, line) => sum + Number(line.quantity || 0) * Number(line.unit_price || 0), 0))
const pendingRequisitionCount = computed(() => requisitions.value.filter(row => row.status === 'pending').length)
const money = value => Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 4 })
const load = async () => [orders.value, suppliers.value, requisitions.value] = await Promise.all([getOrders(), getSuppliers(), getPurchaseRequisitions()])
const requisitionStatus=status=>({pending:{label:'待采购',type:'warning'},ordered:{label:'已生成采购',type:'success'},sufficient:{label:'库存充足',type:'info'}}[status]||{label:status,type:'info'})
const hasLine = id => lines.value.some(line => line.product_id === id)
const selectedQuote = line => line.quote_units.find(unit => unit.unit_id === line.unit_id)
const resetOrderDialog = () => {
  editRequestId += 1
  lines.value = []
  options.value = { products: [] }
  Object.assign(form, blank())
  showChooser.value = true
  dialogLoading.value = false
  productKeyword.value = ''; categoryFilter.value = ''; priceFilter.value = 'all'
}
const loadOptions = async id => {
  const requestId = ++editRequestId
  dialogLoading.value = true
  lines.value = []
  try {
    const result = await getOrderOptions(id)
    if (requestId !== editRequestId) return
    options.value = result
  } finally { if (requestId === editRequestId) dialogLoading.value = false }
}
const addProduct = product => {
  if (hasLine(product.product_id)) return
  const quote = product.quote_units[0]
  lines.value.push({ product_id: product.product_id, product_name: product.name, category: product.category, unit_id: quote.unit_id, quantity: 1, unit_price: quote.price, remark: '', quote_units: product.quote_units })
}
const addFiltered = () => { filteredProducts.value.forEach(addProduct); ElMessage.success('已批量加入筛选商品') }
const changeUnit = line => { const quote = selectedQuote(line); if (quote) line.unit_price = quote.price }
const openCreate = () => { resetOrderDialog(); dialogKey.value += 1; visible.value = true }
const openEdit = async order => {
  resetOrderDialog()
  const requestId = ++editRequestId
  dialogKey.value += 1
  Object.assign(form, { id: order.id, supplier_id: order.supplier_id, title: order.title, expected_date: order.expected_date, notes: order.notes || '', report_footer: order.report_footer || '' })
  showChooser.value = false
  visible.value = true
  dialogLoading.value = true
  try {
    const result = await getOrderOptions(order.supplier_id)
    if (requestId !== editRequestId || !visible.value) return
    options.value = result
    lines.value = order.items.map(item => {
      const product = result.products.find(row => row.product_id === item.product_id)
      return { ...item, quote_units: product?.quote_units || [{ unit_id: item.unit_id, unit_name: item.unit_name, price: item.unit_price, is_best_price: item.is_best_price }] }
    })
  } finally { if (requestId === editRequestId) dialogLoading.value = false }
}
const payload = () => ({ supplier_id: form.supplier_id, title: form.title, expected_date: form.expected_date || null, notes: form.notes || null, report_footer: form.report_footer || null, items: lines.value.map(line => ({ product_id: line.product_id, unit_id: line.unit_id, quantity: line.quantity, unit_price: line.unit_price, remark: line.remark || null })) })
const notifyBusinessUpdate = detail => window.dispatchEvent(new CustomEvent('business-data-updated', { detail }))
const save = async () => { if (!form.supplier_id) return ElMessage.warning('请选择供应商'); if (!lines.value.length) return ElMessage.warning('请至少选择一个商品'); form.id ? await updateOrder(form.id, payload()) : await createOrder(payload()); ElMessage.success('订单已保存，关联销售成本与财务毛利已同步'); visible.value = false; await load(); notifyBusinessUpdate({ module: 'purchase-orders', action: 'save' }) }
const confirm = async order => { await ElMessageBox.confirm(`确认订单 ${order.order_no} 吗？确认后即可下载采购报表。`, '确认采购订单', { type: 'success' }); const result = await confirmOrder(order.id); ElMessage.success(result.message); await load() }
const remove = async order => { await ElMessageBox.confirm(`确认提交采购单 ${order.order_no} 的删除申请吗？管理员审核前单据不会删除。`, '提交删除申请', { type: 'warning' }); const result = await deleteOrder(order.id); ElMessage.success(result.message); await load() }
const download = async (order, format) => { const blob = await downloadOrderReport(order.id, format); const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = `${order.order_no}.${format}`; link.click(); URL.revokeObjectURL(url) }
const openSales = async () => { salesOrders.value = await getSalesOrders({ status: 'confirmed' }); salesVisible.value = true }
const allocateFromSales = row => router.push({ path: '/sales-orders', query: { allocate: row.id } })
const generateRequisition=async row=>{const result=await generateOrdersFromRequisition(row.id);if(result.unquoted_products?.length)ElMessage.warning(`以下商品没有供应商有效报价：${result.unquoted_products.join('、')}`);else ElMessage.success(result.message);await load()}
onMounted(load)
</script>
<style scoped>
.order-basic{margin-top:20px}.chooser{border:1px solid #e2e8f0;border-radius:12px;padding:15px;background:#fafcff}.section-head{display:flex;align-items:center;justify-content:space-between}.section-head>div{display:flex;align-items:center;gap:12px}.section-head span{font-size:13px;color:#8490a3}.product-filters{display:grid;grid-template-columns:1fr 180px 240px;gap:10px;margin:14px 0}.product-list{max-height:250px;overflow:auto;display:grid;grid-template-columns:1fr 1fr;gap:9px}.product-card{display:grid;grid-template-columns:1fr 270px 70px;align-items:center;gap:10px;border:1px solid #e4e9f0;border-radius:9px;padding:10px 12px;background:white}.product-card.selected{background:#f0f8f4;border-color:#b9dfcc}.product-card small{display:block;color:#8c96a7;margin-top:4px}.quote-info{display:flex;align-items:center;gap:8px;font-size:13px}.quote-info b{color:#dd653b}.selected-head{margin:19px 0 10px}.selected-actions{display:flex;align-items:center;gap:14px}.total{color:#dd653b;font-size:19px}.report-fields{margin-top:15px}.item-preview b,.item-preview span{display:block}.item-preview span{color:#69768a;font-size:13px;margin-top:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.saved-items{padding:12px 45px 18px;background:#f7f9fc}.saved-title{display:flex;gap:12px;align-items:baseline;margin-bottom:10px}.saved-title span{color:#7f8a9c;font-size:13px}
</style>
