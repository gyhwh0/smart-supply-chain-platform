<template>
  <div>
    <div class="page-header">
      <div><h2>销售单</h2><p>面向订单员的快捷录单台，确认后可按最低报价一键拆分采购</p></div>
      <el-button type="primary" size="large" @click="openCreate"><el-icon><Plus /></el-icon> 快捷录单</el-button>
    </div>

    <div class="metric-grid">
      <el-card><small>销售单</small><strong>{{ rows.length }}</strong></el-card>
      <el-card><small>待确认</small><strong>{{ rows.filter(item => item.status === 'draft').length }}</strong></el-card>
      <el-card><small>已转采购</small><strong>{{ rows.filter(item => item.purchases.length).length }}</strong></el-card>
      <el-card><small>销售总额</small><strong>¥{{ money(rows.reduce((sum, item) => sum + item.total_amount, 0)) }}</strong></el-card>
    </div>

    <el-card class="panel">
      <div class="toolbar">
        <el-date-picker v-model="dateRange" type="daterange" value-format="YYYY-MM-DD" range-separator="至" start-placeholder="开始单据日期" end-placeholder="结束单据日期" :clearable="false" @change="load" />
        <el-input v-model="keyword" clearable placeholder="搜索单号、客户、商品" style="width:300px"><template #prefix><el-icon><Search /></el-icon></template></el-input>
        <el-radio-group v-model="statusFilter"><el-radio-button value="all">全部</el-radio-button><el-radio-button value="draft">待确认</el-radio-button><el-radio-button value="confirmed">已确认</el-radio-button></el-radio-group>
        <el-button @click="resetDate">今天</el-button>
      </div>
      <el-table :data="filteredRows" row-key="id">
        <el-table-column type="expand">
          <template #default="scope">
            <div class="detail-box">
              <el-table :data="scope.row.items" size="small">
                <el-table-column label="商品" min-width="190"><template #default="cell"><span>{{cell.row.product_name}}</span><el-tag v-if="cell.row.is_addition" type="warning" size="small" class="addition-tag">加单 +{{cell.row.addition_quantity}} {{cell.row.unit_name}}</el-tag></template></el-table-column>
                <el-table-column prop="category" label="分类" width="110" />
                <el-table-column prop="specification" label="规格" min-width="110"><template #default="cell">{{ cell.row.specification || '—' }}</template></el-table-column>
                <el-table-column label="数量" width="120"><template #default="cell">{{ cell.row.quantity }} {{ cell.row.unit_name }}</template></el-table-column>
                <el-table-column label="单价" width="110"><template #default="cell">¥{{ money(cell.row.unit_price) }}</template></el-table-column>
                <el-table-column label="金额" width="120"><template #default="cell"><b>¥{{ money(cell.row.amount) }}</b></template></el-table-column>
                <el-table-column prop="remark" label="备注" min-width="150"><template #default="cell">{{ cell.row.remark || '—' }}</template></el-table-column>
              </el-table>
              <div v-if="scope.row.purchases.length" class="purchase-links">
                <span>已生成采购：</span><el-tag v-for="item in scope.row.purchases" :key="item.id" type="success">{{ item.supplier_name }} · {{ item.order_no }}</el-tag>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="order_no" label="销售单号" min-width="185" />
        <el-table-column prop="customer_name" label="客户" min-width="140" />
        <el-table-column prop="order_date" label="单据日期" width="115" />
        <el-table-column prop="delivery_date" label="要求交期" width="115"><template #default="scope">{{ scope.row.delivery_date || '未指定' }}</template></el-table-column>
        <el-table-column label="商品" width="130"><template #default="scope"><span>{{ scope.row.items.length }} 项</span><el-tag v-if="scope.row.has_additions" type="warning" size="small" class="addition-tag">含 {{scope.row.addition_item_count}} 项加单</el-tag></template></el-table-column>
        <el-table-column label="销售金额" width="130"><template #default="scope"><b class="amount">¥{{ money(scope.row.total_amount) }}</b></template></el-table-column>
        <el-table-column label="状态" width="110"><template #default="scope"><el-tag :type="scope.row.status === 'confirmed' ? 'success' : 'warning'">{{ scope.row.status === 'confirmed' ? '已确认' : '待确认' }}</el-tag></template></el-table-column>
        <el-table-column label="采购进度" width="120"><template #default="scope"><el-tag v-if="scope.row.purchases.length" type="success" effect="plain">{{ scope.row.purchases.length }} 张采购单</el-tag><span v-else class="muted">未生成</span></template></el-table-column>
        <el-table-column label="操作" width="540" fixed="right">
          <template #default="scope">
            <el-button link type="primary" @click="printOrder(scope.row)">打印</el-button>
            <el-button link type="primary" @click="openEdit(scope.row)">编辑</el-button>
            <el-button v-if="scope.row.status === 'draft'" link type="success" @click="confirm(scope.row)">确认</el-button>
            <el-button link type="danger" @click="remove(scope.row)">删除</el-button>
            <el-button v-if="scope.row.status === 'confirmed' && canPurchase" link type="primary" @click="openProcurement(scope.row)">分配供应商并转采购</el-button>
            <el-button v-if="scope.row.status === 'confirmed' && canPurchase" link type="success" @click="router.push({path:'/smart-split',query:{source:'sales',id:scope.row.id}})">智能拆单</el-button>
            <el-button v-if="scope.row.status === 'confirmed'" link type="warning" @click="openAcceptance(scope.row)">配送验收</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="visible" :title="form.id ? '编辑销售单' : '快捷录入销售单'" width="94%" top="3vh" destroy-on-close>
      <el-alert title="快捷录单：选择商品后自动带出默认单位和参考价；同一客户、同一配送日期的后续加单会自动合并到原销售单，并同步已生成的分拣配送任务。" type="info" show-icon :closable="false" />
      <el-form label-position="top" class="order-form">
        <el-row :gutter="16">
          <el-col :span="7"><el-form-item label="客户" required><el-select v-model="form.customer_id" filterable placeholder="输入名称搜索客户" style="width:100%"><el-option v-for="item in options.customers" :key="item.id" :label="item.name" :value="item.id"><span>{{ item.name }}</span><small class="option-note">{{ item.contact_name || '' }} {{ item.phone || '' }}</small></el-option></el-select></el-form-item></el-col>
          <el-col :span="5"><el-form-item label="单据日期" required><el-date-picker v-model="form.order_date" value-format="YYYY-MM-DD" style="width:100%" /></el-form-item></el-col>
          <el-col :span="5"><el-form-item label="要求交期"><el-date-picker v-model="form.delivery_date" value-format="YYYY-MM-DD" clearable style="width:100%" /></el-form-item></el-col>
          <el-col :span="7"><el-form-item label="标题"><el-input v-model="form.title" /></el-form-item></el-col>
        </el-row>
        <div class="line-heading"><div><b>商品明细</b><small>支持按商品名、通用别名、客户专属名称、编码或分类搜索</small></div><div class="quick-actions"><el-select v-model="batchProductIds" multiple filterable collapse-tags collapse-tags-tooltip placeholder="批量搜索并选择商品" style="width:320px"><el-option v-for="item in options.products.filter(p => !filledProductIds.includes(p.id))" :key="item.id" :label="productSearchLabel(item)" :value="item.id" /></el-select><el-button type="primary" plain :disabled="!batchProductIds.length" @click="addBatchProducts">批量加入</el-button><el-button @click="copyLast" :disabled="!filledItems.length">复制上一行</el-button></div></div>
        <el-table :data="form.items" border class="entry-table" :row-class-name="({ row }) => !row.product_id ? 'quick-empty-row' : ''">
          <el-table-column type="index" label="#" width="48" />
          <el-table-column label="商品" min-width="240"><template #default="scope"><el-select v-model="scope.row.product_id" filterable placeholder="名称/别名/编码/分类" style="width:100%" @change="selectProduct(scope.row)"><el-option v-for="item in availableProducts(scope.row)" :key="item.id" :label="productSearchLabel(item)" :value="item.id"><span>{{ customerProductName(item) }}</span><small class="option-note"><template v-if="customerProductName(item)!==item.name">系统名 {{item.name}} · </template>{{ item.sku || '无编码' }} · {{ item.category }}</small></el-option></el-select></template></el-table-column>
          <el-table-column label="规格" min-width="130"><template #default="scope"><el-input v-model="scope.row.specification" placeholder="如 500ml/瓶" /></template></el-table-column>
          <el-table-column label="单位" width="150"><template #default="scope"><el-select v-model="scope.row.unit_id" style="width:100%" @change="changeSalesUnit(scope.row)"><el-option v-for="unit in productOf(scope.row)?.units || []" :key="unit.id" :label="`${unit.name} · ¥${money(unitSalesPrice(productOf(scope.row),unit))}`" :value="unit.id" /></el-select></template></el-table-column>
          <el-table-column label="数量" width="135"><template #default="scope"><el-input-number v-model="scope.row.quantity" :min="0.0001" :precision="2" controls-position="right" style="width:100%" /></template></el-table-column>
          <el-table-column label="销售单价" width="145"><template #default="scope"><el-input-number v-model="scope.row.unit_price" :min="0" :precision="2" controls-position="right" style="width:100%" /></template></el-table-column>
          <el-table-column label="小计" width="115"><template #default="scope"><b>¥{{ money(scope.row.quantity * scope.row.unit_price) }}</b></template></el-table-column>
          <el-table-column label="备注" min-width="150"><template #default="scope"><el-input v-model="scope.row.remark" placeholder="客户要求等" /></template></el-table-column>
          <el-table-column width="62"><template #default="scope"><el-button v-if="scope.row.product_id" link type="danger" @click="removeLine(scope.$index)"><el-icon><Delete /></el-icon></el-button></template></el-table-column>
        </el-table>
        <div class="form-bottom"><el-input v-model="form.notes" type="textarea" :rows="2" placeholder="整单备注、配送要求、开票信息等" /><div class="grand-total"><span>共 {{ filledItems.length }} 项</span><b>合计 ¥{{ money(formTotal) }}</b></div></div>
      </el-form>
      <template #footer><el-button @click="visible = false">取消</el-button><el-button type="primary" size="large" :loading="saving" @click="save">保存销售单</el-button></template>
    </el-dialog>

    <el-dialog v-model="acceptanceVisible" :title="`配送验收 · ${acceptance.order_no || ''}`" width="88%" top="5vh">
      <el-alert title="配送员完成装车扫码后会自动带入实配数量；客户实收与实配不一致时，请填写少送、正常损耗、退货等差异原因。" type="warning" show-icon :closable="false" />
      <div class="acceptance-head"><b>{{acceptance.customer_name}}</b><span>业务日期 {{acceptance.business_date}}</span></div>
      <el-table :data="acceptance.items" border max-height="520">
        <el-table-column prop="product_name" label="商品" min-width="160" />
        <el-table-column label="预定数量" width="130"><template #default="s">{{s.row.ordered_quantity}} {{s.row.unit_name}}</template></el-table-column>
        <el-table-column label="实际配送" width="170"><template #default="s"><el-input-number v-model="s.row.delivered_quantity" :min="0" :precision="4" controls-position="right" /></template></el-table-column>
        <el-table-column label="客户验收" width="170"><template #default="s"><el-input-number v-model="s.row.accepted_quantity" :min="0" :precision="4" controls-position="right" /></template></el-table-column>
        <el-table-column label="验收金额" width="130"><template #default="s">¥{{money((s.row.accepted_quantity || 0) * s.row.unit_price)}}</template></el-table-column>
        <el-table-column label="差异原因" min-width="220"><template #default="s"><el-input v-model="s.row.variance_reason" :placeholder="acceptanceDifference(s.row) ? '必填：少送/损耗/退货等' : '数量一致可不填'" /></template></el-table-column>
      </el-table>
      <div class="acceptance-total">客户验收金额：<b>¥{{money(acceptanceTotal)}}</b></div>
      <template #footer><el-button @click="acceptanceVisible=false">取消</el-button><el-button type="primary" :loading="acceptanceSaving" @click="saveAcceptance">确认并保存验收</el-button></template>
    </el-dialog>

    <el-dialog v-model="procurementVisible" title="按商品分配供应商并生成采购单" width="94%" top="3vh">
      <el-alert title="已按各供应商的标准单位报价推荐最低价。您可以逐商品改选供应商，也可以按分类批量套用；提交后系统会自动按供应商拆成多张采购单。" type="success" show-icon :closable="false" />
      <div class="allocation-head">
        <div><b>{{ procurementData.order_no }}</b><span>{{ procurementData.customer_name }} · {{ procurementItems.length }} 项商品</span></div>
        <div class="allocation-tools">
          <el-select v-model="allocationCategory" clearable placeholder="全部分类" style="width:150px"><el-option v-for="item in allocationCategories" :key="item" :label="item" :value="item" /></el-select>
          <el-select v-model="batchSupplierId" clearable filterable placeholder="选择供应商批量套用" style="width:220px"><el-option v-for="item in allocationSuppliers" :key="item.id" :label="item.name" :value="item.id" /></el-select>
          <el-button :disabled="!batchSupplierId" @click="applySupplierBatch">应用到当前分类</el-button>
          <el-button type="primary" plain @click="useRecommended">一键采用推荐最低价</el-button>
        </div>
      </div>
      <el-table :data="visibleProcurementItems" border max-height="560">
        <el-table-column prop="category" label="分类" width="110" />
        <el-table-column prop="product_name" label="商品" min-width="170" />
        <el-table-column label="销售需求" width="130"><template #default="scope">{{ scope.row.sales_quantity }} {{ scope.row.sales_unit_name }}</template></el-table-column>
        <el-table-column label="供应商" min-width="260">
          <template #default="scope">
            <el-tag v-if="scope.row.already_procured" type="info">已生成采购单</el-tag>
            <el-select v-else v-model="scope.row.supplier_id" filterable placeholder="选择供货商" style="width:100%">
              <el-option v-for="item in scope.row.supplier_options" :key="item.supplier_id" :label="item.supplier_name" :value="item.supplier_id"><span>{{ item.supplier_name }}</span><small class="option-note">折基准价 ¥{{ money(item.base_unit_price) }}<em v-if="item.is_recommended"> · 推荐</em></small></el-option>
            </el-select>
            <el-tag v-if="!scope.row.already_procured && !scope.row.supplier_options.length" type="danger">暂无供应商报价</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="采购单位/数量" min-width="175"><template #default="scope"><span v-if="selectedSupplierOption(scope.row)">{{ selectedSupplierOption(scope.row).purchase_quantity }} {{ selectedSupplierOption(scope.row).unit_name }}</span><span v-else>—</span></template></el-table-column>
        <el-table-column label="采购价" width="130"><template #default="scope"><span v-if="selectedSupplierOption(scope.row)">¥{{ money(selectedSupplierOption(scope.row).unit_price) }}</span><span v-else>—</span></template></el-table-column>
        <el-table-column label="价格判断" width="120"><template #default="scope"><el-tag v-if="selectedSupplierOption(scope.row)?.is_recommended" type="success">全局最低价</el-tag><el-tag v-else-if="scope.row.supplier_id" type="warning">人工指定</el-tag><span v-else>—</span></template></el-table-column>
      </el-table>
      <div class="allocation-summary"><span>待采购 {{ pendingProcurementItems.length }} 项</span><span>已选择 {{ selectedProcurementCount }} 项</span><b>预计拆分为 {{ selectedSupplierCount }} 张供应商采购单</b></div>
      <template #footer><el-button @click="procurementVisible = false">取消</el-button><el-button type="primary" size="large" :loading="generating" @click="submitProcurement">确认分配并生成采购单</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { confirmSalesOrder, createSalesOrder, deleteSalesOrder, generatePurchasesFromSales, getFinanceOrderDetail, getSalesOrderOptions, getSalesOrders, getSalesProcurementOptions, saveFinanceSettlement, updateSalesOrder } from '@/api'
import { getUser } from '@/utils/auth'

const rows = ref([])
const route = useRoute()
const router = useRouter()
const options = reactive({ customers: [], products: [] })
const visible = ref(false)
const saving = ref(false)
const keyword = ref('')
const statusFilter = ref('all')
const batchProductIds = ref([])
const procurementVisible = ref(false)
const generating = ref(false)
const procurementData = reactive({ order_no: '', customer_name: '' })
const procurementItems = ref([])
const acceptanceVisible = ref(false)
const acceptanceSaving = ref(false)
const acceptance = reactive({ id: null, order_no: '', customer_name: '', business_date: '', invoice_amount: 0, invoice_date: null, items: [] })
const allocationCategory = ref('')
const batchSupplierId = ref(null)
const today = () => new Date().toLocaleDateString('sv-SE')
const dateRange = ref([today(), today()])
const newLine = () => ({ product_id: null, unit_id: null, specification: '', quantity: 1, unit_price: 0, remark: '' })
const blank = () => ({ id: null, customer_id: null, order_date: today(), delivery_date: null, title: '销售订单', notes: '', items: [newLine()] })
const form = reactive(blank())
const canPurchase = computed(() => getUser()?.permissions?.includes('order_management'))
const filledItems = computed(() => form.items.filter(item => item.product_id))
const filledProductIds = computed(() => filledItems.value.map(item => item.product_id))
const formTotal = computed(() => filledItems.value.reduce((sum, item) => sum + Number(item.quantity || 0) * Number(item.unit_price || 0), 0))
const acceptanceTotal = computed(() => acceptance.items.reduce((sum, item) => sum + Number(item.accepted_quantity || 0) * Number(item.unit_price || 0), 0))
const allocationCategories = computed(() => [...new Set(procurementItems.value.map(item => item.category))].sort())
const visibleProcurementItems = computed(() => procurementItems.value.filter(item => !allocationCategory.value || item.category === allocationCategory.value))
const allocationSuppliers = computed(() => {
  const suppliers = new Map()
  visibleProcurementItems.value.forEach(row => row.supplier_options.forEach(item => suppliers.set(item.supplier_id, { id: item.supplier_id, name: item.supplier_name })))
  return [...suppliers.values()].sort((a, b) => a.name.localeCompare(b.name, 'zh-CN'))
})
const pendingProcurementItems = computed(() => procurementItems.value.filter(item => !item.already_procured))
const selectedProcurementCount = computed(() => pendingProcurementItems.value.filter(item => item.supplier_id).length)
const selectedSupplierCount = computed(() => new Set(pendingProcurementItems.value.map(item => item.supplier_id).filter(Boolean)).size)
const filteredRows = computed(() => rows.value.filter(row => {
  if (statusFilter.value !== 'all' && row.status !== statusFilter.value) return false
  const text = `${row.order_no} ${row.customer_name} ${row.title} ${row.items.map(item => item.product_name).join(' ')}`.toLowerCase()
  return text.includes(keyword.value.trim().toLowerCase())
}))
const money = value => Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const load = async () => { const [orderRows, optionRows] = await Promise.all([getSalesOrders({ date_from: dateRange.value?.[0], date_to: dateRange.value?.[1] }), getSalesOrderOptions()]); rows.value = orderRows; Object.assign(options, optionRows) }
const resetDate = async () => { dateRange.value = [today(), today()]; await load() }
const productOf = line => options.products.find(item => item.id === line.product_id)
const customerAlias = product => product?.customer_aliases?.find(item => Number(item.customer_id) === Number(form.customer_id))?.alias
const customerProductName = product => customerAlias(product) || product?.name || ''
const productSearchLabel = product => [...new Set([customerProductName(product), product.name, ...(product.aliases || []), product.sku, product.category].filter(Boolean))].join(' · ')
const unitSalesPrice = (product,unit) => unit?.sales_price ?? (product?.reference_price == null ? 0 : Number(product.reference_price) * Number(unit?.conversion_rate || 1))
const changeSalesUnit = line => { const product=productOf(line); const unit=product?.units.find(item=>item.id===line.unit_id); line.unit_price=unitSalesPrice(product,unit) }
const availableProducts = line => options.products.filter(item => item.id === line.product_id || !form.items.some(other => other !== line && other.product_id === item.id))
const ensureEmptyLine = () => { if (!form.items.length || form.items.at(-1).product_id) form.items.push(newLine()) }
const selectProduct = line => { const product = productOf(line); if (!product) return; const unit=product.units.find(item => item.is_base) || product.units[0]; line.unit_id = unit?.id || null; line.unit_price = unitSalesPrice(product,unit); ensureEmptyLine() }
const addLine = () => ensureEmptyLine()
const removeLine = index => { form.items.splice(index, 1); ensureEmptyLine() }
const copyLast = () => { const source = filledItems.value.at(-1); if (!source) return; const empty = form.items.at(-1); Object.assign(empty, { ...source, product_id: null, unit_id: null, specification: '', remark: '' }) }
const addBatchProducts = () => { batchProductIds.value.forEach(id => { const line = newLine(); line.product_id = id; form.items.splice(Math.max(form.items.length - 1, 0), 0, line); selectProduct(line) }); batchProductIds.value = []; ensureEmptyLine(); ElMessage.success('已批量加入商品，可继续连续录入') }
const openCreate = () => { Object.assign(form, blank()); batchProductIds.value = []; visible.value = true }
const openEdit = row => { Object.assign(form, { id: row.id, customer_id: row.customer_id, order_date: row.order_date, delivery_date: row.delivery_date, title: row.title, notes: row.notes || '', items: [...row.items.map(item => ({ product_id: item.product_id, unit_id: item.unit_id, specification: item.specification || '', quantity: item.quantity, unit_price: item.unit_price, remark: item.remark || '' })), newLine()] }); batchProductIds.value = []; visible.value = true }
const payload = () => ({ customer_id: form.customer_id, order_date: form.order_date, delivery_date: form.delivery_date || null, title: form.title.trim() || '销售订单', notes: form.notes.trim() || null, items: filledItems.value.map(item => ({ ...item, specification: item.specification?.trim() || null, remark: item.remark?.trim() || null })) })
const notifyBusinessUpdate = detail => window.dispatchEvent(new CustomEvent('business-data-updated', { detail }))
const save = async () => {
  if (!form.customer_id || !form.order_date) return ElMessage.warning('请选择客户和单据日期')
  if (!filledItems.value.length || filledItems.value.some(item => !item.unit_id || Number(item.quantity) <= 0)) return ElMessage.warning('请完整填写商品、单位和数量')
  saving.value = true
  try { const result = form.id ? await updateSalesOrder(form.id, payload()) : await createSalesOrder(payload()); ElMessage.success(result.message || '销售单保存成功'); visible.value = false; await load(); notifyBusinessUpdate({ module: 'sales-orders', action: form.id ? 'update' : 'create' }) } finally { saving.value = false }
}
const escapeHtml = value => String(value ?? '').replace(/[&<>'"]/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' })[char])
const printOrder = row => {
  const printWindow = window.open('', '_blank', 'width=980,height=760')
  if (!printWindow) return ElMessage.warning('浏览器拦截了打印窗口，请允许弹窗后重试')
  const itemRows = row.items.map((item, index) => `<tr><td>${index + 1}</td><td>${escapeHtml(item.product_name)}</td><td>${escapeHtml(item.specification || '—')}</td><td>${escapeHtml(item.quantity)} ${escapeHtml(item.unit_name)}</td><td>¥${money(item.unit_price)}</td><td>¥${money(item.amount)}</td><td>${escapeHtml(item.remark || '')}</td></tr>`).join('')
  printWindow.document.write(`<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>${escapeHtml(row.order_no)} 销售单</title><style>
    @page{size:A4;margin:12mm}*{box-sizing:border-box}body{font-family:"Microsoft YaHei","PingFang SC",sans-serif;color:#111;margin:0;font-size:13px}h1{text-align:center;font-size:24px;letter-spacing:8px;margin:4px 0 20px}.meta{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px 24px;margin-bottom:14px}.meta b{font-weight:600}table{width:100%;border-collapse:collapse}th,td{border:1px solid #222;padding:8px 6px;text-align:center}th{background:#f2f2f2}.total{text-align:right;font-size:16px;font-weight:700;margin-top:12px}.signatures{display:grid;grid-template-columns:repeat(3,1fr);gap:50px;margin-top:44px}.footer{text-align:center;color:#666;font-size:11px;margin-top:30px}@media print{.no-print{display:none}}
  </style></head><body><h1>销售单</h1><div class="meta"><span><b>销售单号：</b>${escapeHtml(row.order_no)}</span><span><b>客户：</b>${escapeHtml(row.customer_name)}</span><span><b>状态：</b>${row.status === 'confirmed' ? '已确认' : '待确认'}</span><span><b>单据日期：</b>${escapeHtml(row.order_date)}</span><span><b>配送日期：</b>${escapeHtml(row.delivery_date || '未指定')}</span><span><b>制单人：</b>${escapeHtml(row.creator_name)}</span></div><table><thead><tr><th style="width:45px">序号</th><th>商品</th><th>规格</th><th>数量</th><th>单价</th><th>金额</th><th>备注</th></tr></thead><tbody>${itemRows}</tbody></table><div class="total">合计：¥${money(row.total_amount)}</div><div class="signatures"><span>制单：____________</span><span>复核：____________</span><span>客户签收：____________</span></div><div class="footer">打印时间：${new Date().toLocaleString('zh-CN')}</div><script>window.onload=()=>setTimeout(()=>window.print(),150)<\/script></body></html>`)
  printWindow.document.close()
}
const acceptanceDifference = item => Number(item.delivered_quantity || 0) - Number(item.accepted_quantity || 0)
const openAcceptance = async row => {
  const detail = await getFinanceOrderDetail(row.id)
  detail.items = detail.items.map(item => ({ ...item, delivered_quantity: item.delivered_quantity ?? item.ordered_quantity, accepted_quantity: item.accepted_quantity ?? item.delivered_quantity ?? item.ordered_quantity, variance_reason: item.variance_reason || '' }))
  Object.assign(acceptance, detail)
  acceptanceVisible.value = true
}
const saveAcceptance = async () => {
  for (const item of acceptance.items) {
    if (item.delivered_quantity == null || item.accepted_quantity == null) return ElMessage.warning(`${item.product_name}请填写配送和验收数量`)
    if (acceptanceDifference(item) && !item.variance_reason?.trim()) return ElMessage.warning(`${item.product_name}存在数量差异，请填写原因`)
  }
  acceptanceSaving.value = true
  try {
    const result = await saveFinanceSettlement(acceptance.id, { invoice_amount: acceptance.invoice_amount || 0, invoice_date: acceptance.invoice_date || null, items: acceptance.items.map(item => ({ sales_order_item_id: item.id, delivered_quantity: item.delivered_quantity, accepted_quantity: item.accepted_quantity, variance_reason: item.variance_reason?.trim() || null, cost_unit_price: item.cost_unit_price })) })
    ElMessage.success(result.message)
    acceptanceVisible.value = false
    await load()
  } finally { acceptanceSaving.value = false }
}
const confirm = async row => { await ElMessageBox.confirm(`确认销售单 ${row.order_no}？确认后不可再修改。`, '确认销售单', { type: 'warning' }); await confirmSalesOrder(row.id); ElMessage.success('销售单已确认'); await load() }
const remove = async row => { await ElMessageBox.confirm(`确认提交销售单 ${row.order_no} 的删除申请吗？管理员审核前单据不会删除。`, '提交删除申请', { type: 'warning' }); const result = await deleteSalesOrder(row.id); ElMessage.success(result.message); await load() }
const selectedSupplierOption = row => row.supplier_options.find(item => item.supplier_id === row.supplier_id)
const useRecommended = () => procurementItems.value.forEach(item => { if (!item.already_procured) item.supplier_id = item.recommended_supplier_id })
const applySupplierBatch = () => {
  let applied = 0
  visibleProcurementItems.value.forEach(item => { if (!item.already_procured && item.supplier_options.some(option => option.supplier_id === batchSupplierId.value)) { item.supplier_id = batchSupplierId.value; applied += 1 } })
  ElMessage.success(`已为当前范围内 ${applied} 个可供商品套用该供应商`)
}
const openProcurement = async row => {
  const data = await getSalesProcurementOptions(row.id)
  Object.assign(procurementData, data)
  procurementItems.value = data.items.map(item => ({ ...item, supplier_id: item.already_procured ? null : item.recommended_supplier_id }))
  allocationCategory.value = ''; batchSupplierId.value = null; procurementVisible.value = true
}
const submitProcurement = async () => {
  const selectable = pendingProcurementItems.value.filter(item => item.supplier_options.length)
  if (!selectable.length) return ElMessage.warning('当前没有可采购的商品，请先维护供应商报价')
  if (selectable.some(item => !item.supplier_id)) return ElMessage.warning('请为每个有报价的商品选择供应商')
  generating.value = true
  try {
    const result = await generatePurchasesFromSales(procurementData.sales_order_id, { automatic: false, allocations: selectable.map(item => ({ product_id: item.product_id, supplier_id: item.supplier_id })) })
    ElMessage.success(result.message)
    if (result.unquoted_products.length) ElMessage.warning(`暂无报价、未生成采购：${result.unquoted_products.join('、')}`)
    procurementVisible.value = false
    await load()
  } finally { generating.value = false }
}
onMounted(async () => {
  await load()
  if (route.query.allocate) {
    let row = rows.value.find(item => item.id === Number(route.query.allocate))
    if (!row) {
      const allRows = await getSalesOrders()
      row = allRows.find(item => item.id === Number(route.query.allocate))
      if (row) { dateRange.value = [row.order_date, row.order_date]; rows.value = allRows.filter(item => item.order_date === row.order_date) }
    }
    if (row) await openProcurement(row)
    await router.replace('/sales-orders')
  }
})
</script>

<style scoped>
.metric-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin-bottom:18px; }
.metric-grid small,.metric-grid strong { display:block; }.metric-grid small { color:#7c8799; }.metric-grid strong { font-size:25px; margin-top:8px; color:#1c2c44; }
.toolbar { display:flex; align-items:center; flex-wrap:wrap; gap:12px; margin-bottom:16px; }.amount { color:#e06535; }.muted { color:#a0a8b5; }
.detail-box { padding:12px 46px 18px; background:#f7f9fc; }.purchase-links { margin-top:12px; display:flex; align-items:center; flex-wrap:wrap; gap:8px; }
.addition-tag { margin-left:7px; }
.order-form { margin-top:18px; }.line-heading { display:flex; align-items:center; justify-content:space-between; gap:16px; margin:8px 0 10px; }.line-heading small { display:block; color:#8490a3; margin-top:4px; }.quick-actions { display:flex; gap:8px; align-items:center; }.entry-table { width:100%; }.entry-table :deep(.quick-empty-row td) { background:#f3f8ff; }
.option-note { float:right; color:#9099a8; margin-left:24px; }.option-note em { color:#2a9d6f; font-style:normal; }.form-bottom { display:grid; grid-template-columns:1fr auto; align-items:end; gap:24px; margin-top:16px; }.grand-total { min-width:260px; text-align:right; }.grand-total span,.grand-total b { display:block; }.grand-total span { color:#7c8799; }.grand-total b { color:#df6131; font-size:24px; margin-top:5px; }
.allocation-head { display:flex; justify-content:space-between; align-items:center; gap:18px; margin:18px 0 12px; }.allocation-head b,.allocation-head span { display:block; }.allocation-head span { color:#7c8799; margin-top:4px; }.allocation-tools { display:flex; align-items:center; gap:8px; }.allocation-summary { display:flex; justify-content:flex-end; gap:24px; align-items:center; padding:16px 4px 0; color:#68758a; }.allocation-summary b { color:#287cba; font-size:17px; }
.acceptance-head { display:flex; gap:24px; align-items:center; margin:16px 0; color:#758196; }.acceptance-head b { color:#263850; font-size:18px; }.acceptance-total { text-align:right; margin-top:16px; color:#68758a; }.acceptance-total b { color:#dc6438; font-size:22px; margin-left:8px; }
@media (max-width:1000px) { .metric-grid { grid-template-columns:repeat(2,1fr); }.form-bottom { grid-template-columns:1fr; } }
</style>
