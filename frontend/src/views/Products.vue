<template>
  <div>
    <div class="page-header">
      <div><h2>{{ isSupplier ? '已分配商品' : '商品管理' }}</h2><p>商品关联统一分类，并支持基础单位、箱、件等多单位换算</p></div>
      <div v-if="!isSupplier" class="header-actions"><el-button @click="downloadTemplate">下载Excel模板</el-button><el-upload :show-file-list="false" :http-request="uploadExcel" accept=".xlsx"><el-button type="success" plain>一键导入商品</el-button></el-upload><el-button type="danger" plain :disabled="!selected.length" @click="batchRemove">批量删除（{{ selected.length }}）</el-button><el-button type="primary" @click="openCreate"><el-icon><Plus /></el-icon>新增商品</el-button></div>
    </div>
    <el-card class="panel">
      <div class="product-toolbar">
        <el-input v-model="keyword" clearable size="large" placeholder="搜索商品名称、SKU、通用别名或客户专属名称" class="product-search">
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-select v-model="categoryFilter" clearable placeholder="全部分类" size="large" class="filter-select">
          <el-option v-for="item in categories" :key="item.id" :label="item.name" :value="item.id" />
        </el-select>
        <el-select v-model="statusFilter" placeholder="全部状态" size="large" class="status-select">
          <el-option label="全部状态" value="all"/><el-option label="仅启用" value="active"/><el-option label="仅停用" value="inactive"/>
        </el-select>
        <el-button v-if="hasFilters" size="large" @click="clearFilters">清除筛选</el-button>
        <span class="result-count">找到 {{filteredRows.length}} 个商品</span>
      </div>
      <el-table :data="filteredRows" @selection-change="selected = $event" empty-text="没有找到符合条件的商品">
        <el-table-column v-if="!isSupplier" type="selection" width="46" />
        <el-table-column label="图片" width="76"><template #default="scope"><el-image v-if="scope.row.image_url" :src="scope.row.image_url" fit="cover" class="product-thumb" :preview-src-list="[scope.row.image_url]" preview-teleported/><div v-else class="product-placeholder">暂无</div></template></el-table-column>
        <el-table-column prop="name" label="商品名称" min-width="150" />
        <el-table-column label="别名" min-width="170"><template #default="scope"><el-tag v-for="alias in scope.row.aliases" :key="alias" type="info" class="unit-tag">{{alias}}</el-tag><span v-if="!scope.row.aliases.length" class="muted">—</span></template></el-table-column>
        <el-table-column prop="category" label="品类" min-width="120" />
        <el-table-column prop="sku" label="SKU" min-width="110" />
        <el-table-column label="参考价" width="120"><template #default="scope"><span class="price">{{ scope.row.reference_price == null ? '—' : `¥ ${scope.row.reference_price}` }}</span></template></el-table-column>
        <el-table-column label="单位与价格" min-width="310"><template #default="scope"><div v-for="unit in scope.row.units" :key="unit.id" class="unit-price-line"><el-tag :type="unit.is_base ? 'success' : 'info'">{{ unit.name }}{{ unit.is_base ? '（基础）' : ` × ${unit.conversion_rate}` }}</el-tag><span>售 {{priceText(effectiveSalesPrice(scope.row,unit))}}</span><span>参考进价 {{priceText(unit.reference_purchase_price)}}</span></div></template></el-table-column>
        <el-table-column label="保管要求" min-width="190"><template #default="scope"><div>{{scope.row.shelf_life_days ? `保质期 ${scope.row.shelf_life_days} 天` : '保质期未设置'}}</div><small class="muted">{{temperatureText(scope.row)}} · 损耗 {{scope.row.loss_rate??0}}%</small></template></el-table-column>
        <el-table-column label="质检报告" width="110"><template #default="scope"><el-button v-if="scope.row.quality_report_url" link type="primary" @click="downloadReport(scope.row)">查看报告</el-button><span v-else class="muted">未上传</span></template></el-table-column>
        <el-table-column v-if="!isSupplier" label="已绑定供应商" min-width="210"><template #default="scope"><el-tag v-for="id in scope.row.supplier_ids" :key="id" type="info" class="unit-tag">{{ supplierName(id) }}</el-tag><span v-if="!scope.row.supplier_ids.length" class="muted">暂未绑定</span></template></el-table-column>
        <el-table-column label="状态" min-width="190"><template #default="scope"><el-tag :type="scope.row.active ? 'success' : 'info'">{{ scope.row.active ? '启用' : '停用' }}</el-tag><el-tag v-if="scope.row.mini_visible" type="primary" class="mini-tag">{{scope.row.mini_all_customers?'小程序·全部客户':`小程序·${scope.row.mini_customer_ids.length}个客户`}}</el-tag><el-tag v-else type="info" class="mini-tag">小程序下架</el-tag></template></el-table-column>
        <el-table-column v-if="!isSupplier" label="操作" width="250" fixed="right">
          <template #default="scope">
            <el-button link type="primary" @click="openEdit(scope.row)">编辑商品</el-button>
            <el-button link :type="scope.row.active ? 'warning' : 'success'" @click="toggle(scope.row)">{{ scope.row.active ? '禁用' : '启用' }}</el-button>
            <el-button link type="danger" @click="remove(scope.row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="visible" :title="form.id ? '编辑商品' : '新增商品'" width="900px">
      <el-form label-width="95px">
        <el-form-item label="商品名称" required><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="商品分类" required>
          <el-select v-model="form.category_id" filterable placeholder="请选择分类" style="width:100%">
            <el-option v-for="item in selectableCategories" :key="item.id" :label="item.name" :value="item.id" :disabled="!item.active" />
          </el-select>
        </el-form-item>
        <el-form-item label="SKU"><el-input v-model="form.sku" /></el-form-item>
        <el-form-item label="兼容参考价"><el-input-number v-model="form.reference_price" :min="0" :precision="2" controls-position="right" /><span class="field-tip">旧数据兼容；实际开单优先使用下方各单位销售价</span></el-form-item>
        <el-form-item label="通用别名"><el-select v-model="form.aliases" multiple filterable allow-create default-first-option placeholder="输入别名后按回车，如 马铃薯、洋芋" style="width:100%"/><div class="binding-help">采购、销售录单和微信下单均可通过这些别名识别该商品。</div></el-form-item>
        <el-divider>质量与储存信息</el-divider>
        <el-row :gutter="14"><el-col :span="8"><el-form-item label="保质期（天）"><el-input-number v-model="form.shelf_life_days" :min="1" style="width:100%"/></el-form-item></el-col><el-col :span="8"><el-form-item label="最低温度（℃）"><el-input-number v-model="form.storage_temperature_min" :precision="1" style="width:100%"/></el-form-item></el-col><el-col :span="8"><el-form-item label="最高温度（℃）"><el-input-number v-model="form.storage_temperature_max" :precision="1" style="width:100%"/></el-form-item></el-col></el-row>
        <el-row :gutter="14"><el-col :span="8"><el-form-item label="标准损耗率（%）"><el-input-number v-model="form.loss_rate" :min="0" :max="100" :precision="2" style="width:100%"/></el-form-item></el-col><el-col :span="16"><el-form-item label="储存说明"><el-input v-model="form.storage_notes" placeholder="如：冷藏避光、开封后24小时内使用"/></el-form-item></el-col></el-row>
        <el-form-item v-if="form.id" label="质检报告"><el-upload :show-file-list="false" :http-request="uploadReport" accept=".pdf,.jpg,.jpeg,.png,.webp"><el-button type="primary" plain>{{form.quality_report_name?'重新上传':'上传质检报告'}}</el-button></el-upload><span v-if="form.quality_report_name" class="report-name">{{form.quality_report_name}}</span><div class="binding-help">支持 PDF、JPG、PNG、WEBP，最大10MB。</div></el-form-item>
        <el-form-item v-if="form.id" label="商品图片"><el-upload :show-file-list="false" :http-request="uploadImage" accept=".jpg,.jpeg,.png,.webp"><el-button type="primary" plain>{{form.image_name?'更换图片':'上传商品图片'}}</el-button></el-upload><el-image v-if="form.image_url" :src="form.image_url" fit="cover" class="form-product-image"/><span v-if="form.image_name" class="report-name">{{form.image_name}}</span><div class="binding-help">用于小程序商品列表，支持 JPG、PNG、WEBP，最大5MB。</div></el-form-item>
        <el-divider>客户专属商品名称</el-divider>
        <div class="binding-help alias-help">例如：系统商品“土豆”为客户 k500h 设置“马铃薯”，该客户的微信识别和销售单均显示“马铃薯”。</div>
        <div v-for="(row,index) in form.customer_aliases" :key="index" class="customer-alias-row"><el-select v-model="row.customer_id" filterable placeholder="选择客户"><el-option v-for="customer in customers" :key="customer.id" :label="`${customer.customer_code||'无编号'} · ${customer.name}`" :value="customer.id"/></el-select><el-input v-model="row.alias" placeholder="该客户的专属名称"/><el-button link type="danger" @click="form.customer_aliases.splice(index,1)">删除</el-button></div>
        <el-button link type="primary" @click="form.customer_aliases.push({customer_id:null,alias:''})">+ 添加客户专属名称</el-button>
        <el-form-item label="说明"><el-input v-model="form.description" type="textarea" /></el-form-item>
        <el-form-item label="绑定供应商">
          <el-select v-model="form.supplier_ids" multiple filterable collapse-tags collapse-tags-tooltip placeholder="可选择多个供应商，保存后自动分配商品" style="width:100%">
            <el-option v-for="supplier in activeSuppliers" :key="supplier.id" :value="supplier.id" :label="supplierOptionLabel(supplier)" :class="{ 'assigned-option': originalSupplierIds.includes(supplier.id) }" />
          </el-select>
          <div class="binding-help">保存后会自动生成商品分配；标注“已分配”的供应商表示此前已经绑定。</div>
        </el-form-item>
        <el-form-item label="小程序上架"><el-switch v-model="form.mini_visible" active-text="上架" inactive-text="下架" /><span class="field-tip">下架后只影响商家小程序，后台历史单据不受影响。</span></el-form-item>
        <template v-if="form.mini_visible">
          <el-form-item label="可见范围"><el-radio-group v-model="form.mini_all_customers"><el-radio-button :value="true">全部客户</el-radio-button><el-radio-button :value="false">指定客户</el-radio-button></el-radio-group></el-form-item>
          <el-form-item v-if="!form.mini_all_customers" label="分配客户"><el-select v-model="form.mini_customer_ids" multiple filterable collapse-tags collapse-tags-tooltip placeholder="选择能在小程序看到该商品的客户" style="width:100%"><el-option v-for="customer in customers.filter(item=>item.active)" :key="customer.id" :value="customer.id" :label="`${customer.customer_code||'无编号'} · ${customer.name}`"/></el-select><div class="binding-help">未分配给任何客户时，该商品不会在小程序显示。</div></el-form-item>
        </template>
        <el-form-item v-if="form.id" label="状态"><el-switch v-model="form.active" active-text="启用" inactive-text="停用" /></el-form-item>
        <el-divider>多单位与价格管理</el-divider>
        <el-alert title="先确定最小常用单位为基础单位。换算率表示“1个当前单位包含多少个基础单位”，例如基础单位是瓶，1箱=12瓶，则箱的换算率填12。" type="info" :closable="false" show-icon class="unit-guide" />
        <div class="unit-row unit-row-head"><span>单位名称</span><span>换算率</span><span>销售价</span><span>参考进价</span><span>类型</span><span></span></div>
        <div v-for="(unit, index) in form.units" :key="unit.id||`new-${index}`" class="unit-row" :class="{'base-unit-row':unit.is_base}">
          <el-input v-model="unit.name" :disabled="Boolean(form.id&&unit.id)" placeholder="单位，如 瓶/箱" />
          <el-input-number v-model="unit.conversion_rate" :disabled="Boolean(form.id&&unit.id)||unit.is_base" :min="0.0001" :precision="4" controls-position="right" />
          <el-input-number v-model="unit.sales_price" :min="0" :precision="2" placeholder="销售价" controls-position="right" />
          <el-input-number v-model="unit.reference_purchase_price" :min="0" :precision="2" placeholder="参考进价" controls-position="right" />
          <el-checkbox v-model="unit.is_base" :disabled="Boolean(form.id)" @change="setBase(index)">{{unit.is_base?'基础单位':'设为基础'}}</el-checkbox>
          <el-button v-if="!unit.id&&form.units.length>1" link type="danger" @click="form.units.splice(index, 1)">删除</el-button>
          <div class="unit-meaning">{{unitMeaning(unit)}}</div>
        </div>
        <el-button link type="primary" @click="addUnitRow">+ 添加销售/采购单位</el-button>
        <div v-if="form.id" class="unit-history-tip">已有单位可能已被历史订单和报价引用，因此单位名称、换算率及基础单位不可直接改动；价格可随时修改，也可以继续添加新单位。</div>
      </el-form>
      <template #footer><el-button @click="visible = false">取消</el-button><el-button type="primary" @click="save">保存</el-button></template>
    </el-dialog>

  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { addProductUnit, batchDeleteProducts, createProduct, deleteProduct, downloadProductImportTemplate, downloadProductQualityReport, getAssignments, getCategories, getCustomers, getProducts, getSuppliers, importProducts, updateProduct, updateProductUnitPrices, uploadProductImage, uploadProductQualityReport } from '@/api'
import { getUser } from '@/utils/auth'

const isSupplier = computed(() => getUser()?.role === 'supplier')
const rows = ref([])
const categories = ref([])
const suppliers = ref([])
const customers = ref([])
const selected = ref([])
const keyword = ref('')
const categoryFilter = ref(null)
const statusFilter = ref('all')
const originalSupplierIds = ref([])
const visible = ref(false)
const blank = () => ({ id: null, name: '', category: '', category_id: null, sku: '', reference_price: null, aliases: [], customer_aliases: [], shelf_life_days: null, storage_temperature_min: null, storage_temperature_max: null, loss_rate: 0, storage_notes: '', quality_report_name: null, image_name: null, image_url: null, mini_visible: true, mini_all_customers: false, mini_customer_ids: [], description: '', active: true, supplier_ids: [], units: [{ name: '件', conversion_rate: 1, is_base: true, sales_price: null, reference_purchase_price: null }] })
const form = reactive(blank())
const selectableCategories = computed(() => categories.value.filter(item => item.active || item.id === form.category_id))
const activeSuppliers = computed(() => suppliers.value.filter(item => item.active || form.supplier_ids.includes(item.id)))
const hasFilters = computed(() => Boolean(keyword.value.trim() || categoryFilter.value || statusFilter.value !== 'all'))
const filteredRows = computed(() => {
  const query = keyword.value.trim().toLowerCase()
  return rows.value.filter(row => {
    if (categoryFilter.value && row.category_id !== categoryFilter.value) return false
    if (statusFilter.value === 'active' && !row.active) return false
    if (statusFilter.value === 'inactive' && row.active) return false
    if (!query) return true
    const searchable = [
      row.name, row.sku, row.category, row.description,
      ...(row.aliases || []),
      ...(row.customer_aliases || []).map(item => item.alias),
      ...(row.units || []).map(item => item.name),
    ].filter(Boolean).join(' ').toLowerCase()
    return searchable.includes(query)
  })
})
const clearFilters = () => { keyword.value=''; categoryFilter.value=null; statusFilter.value='all' }
const saveBlob=(blob,name)=>{const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();URL.revokeObjectURL(url)}
const downloadTemplate=async()=>saveBlob(await downloadProductImportTemplate(),'商品批量导入模板.xlsx')
const uploadExcel=async({file})=>{const result=await importProducts(file);ElMessage.success(result.message);await load()}

const load = async () => {
  ;[categories.value, suppliers.value, customers.value] = await Promise.all([getCategories(), getSuppliers(), isSupplier.value ? Promise.resolve([]) : getCustomers()])
  if (isSupplier.value) {
    const assignments = await getAssignments()
    rows.value = [...new Map(assignments.map(item => [item.product.id, item.product])).values()]
  } else rows.value = await getProducts()
}
const openCreate = () => {
  Object.assign(form, blank())
  originalSupplierIds.value = []
  form.category_id = categories.value.find(item => item.active)?.id ?? null
  visible.value = true
}
const openEdit = (row) => { Object.assign(form, blank(), row, { supplier_ids: [...row.supplier_ids], mini_customer_ids:[...(row.mini_customer_ids||[])], aliases:[...row.aliases], customer_aliases:row.customer_aliases.map(item=>({...item})), units:row.units.map(unit=>({...unit})) }); originalSupplierIds.value = [...row.supplier_ids]; visible.value = true }
const setBase = (index) => { if (form.units[index].is_base) form.units.forEach((unit, current) => { unit.is_base = current === index }) }
const addUnitRow = () => form.units.push({ id:null, name:'', conversion_rate:1, is_base:false, sales_price:null, reference_purchase_price:null })
const unitMeaning = unit => { const base=form.units.find(item=>item.is_base)?.name||'基础单位'; return unit.is_base?`计价基础：1 ${unit.name||base}`:`1 ${unit.name||'当前单位'} = ${Number(unit.conversion_rate||1).toLocaleString('zh-CN',{maximumFractionDigits:4})} ${base}` }
const productPayload = () => ({ name: form.name.trim(), category: form.category, category_id: form.category_id, sku: form.sku?.trim() || null, reference_price: form.reference_price, aliases:form.aliases.map(v=>v.trim()).filter(Boolean), customer_aliases:form.customer_aliases.filter(v=>v.customer_id&&v.alias.trim()).map(v=>({customer_id:v.customer_id,alias:v.alias.trim()})), shelf_life_days:form.shelf_life_days, storage_temperature_min:form.storage_temperature_min, storage_temperature_max:form.storage_temperature_max, loss_rate:form.loss_rate, storage_notes:form.storage_notes?.trim()||null, description: form.description || null, active: form.active, mini_visible: form.mini_visible, mini_all_customers: form.mini_all_customers, mini_customer_ids:form.mini_all_customers?[]:form.mini_customer_ids, supplier_ids: form.supplier_ids })
const temperatureText=row=>row.storage_temperature_min==null&&row.storage_temperature_max==null?'温度未设置':`${row.storage_temperature_min??'—'}～${row.storage_temperature_max??'—'}℃`
const effectiveSalesPrice=(product,unit)=>unit.sales_price??(product.reference_price==null?null:Number(product.reference_price)*Number(unit.conversion_rate||1))
const priceText=value=>value==null?'未设置':`¥${Number(value).toFixed(2)}`
const uploadReport=async({file})=>{await uploadProductQualityReport(form.id,file);ElMessage.success('质检报告上传成功');await load();const updated=rows.value.find(item=>item.id===form.id);if(updated)Object.assign(form,{quality_report_name:updated.quality_report_name,quality_report_url:updated.quality_report_url})}
const uploadImage=async({file})=>{await uploadProductImage(form.id,file);ElMessage.success('商品图片上传成功');await load();const updated=rows.value.find(item=>item.id===form.id);if(updated)Object.assign(form,{image_name:updated.image_name,image_url:`${updated.image_url}?v=${Date.now()}`})}
const downloadReport=async row=>{const blob=await downloadProductQualityReport(row.id);const url=URL.createObjectURL(blob);const link=document.createElement('a');link.href=url;link.download=row.quality_report_name||`${row.name}-质检报告`;link.click();URL.revokeObjectURL(url)}
const save = async () => {
  if (!form.name.trim()) return ElMessage.warning('请输入商品名称')
  if (!form.category_id) return ElMessage.warning('请选择商品分类')
  if (form.units.some(unit => !unit.name.trim())) return ElMessage.warning('请填写所有单位名称')
  const unitNames=form.units.map(unit=>unit.name.trim().toLowerCase())
  if (new Set(unitNames).size!==unitNames.length) return ElMessage.warning('同一个商品不能有重复单位名称')
  if (!form.id) {
    if (form.units.filter(unit => unit.is_base).length !== 1) return ElMessage.warning('必须且只能设置一个基础单位')
    await createProduct({ ...productPayload(), units: form.units })
  } else {
    await updateProduct(form.id, productPayload())
    const existing=form.units.filter(unit=>unit.id)
    if(existing.length)await updateProductUnitPrices(form.id,{units:existing.map(unit=>({unit_id:unit.id,sales_price:unit.sales_price,reference_purchase_price:unit.reference_purchase_price}))})
    for(const unit of form.units.filter(unit=>!unit.id))await addProductUnit(form.id,{name:unit.name.trim(),conversion_rate:unit.conversion_rate,is_base:false,sales_price:unit.sales_price,reference_purchase_price:unit.reference_purchase_price})
  }
  ElMessage.success('保存成功')
  visible.value = false
  await load()
}
const toggle = async (row) => {
  await updateProduct(row.id, { ...row, active: !row.active })
  ElMessage.success(row.active ? '商品已禁用' : '商品已启用')
  await load()
}
const remove = async (row) => {
  await ElMessageBox.confirm(`确认提交商品“${row.name}”的删除申请吗？管理员审核前不会删除。`, '提交删除申请', { type: 'warning' })
  const result = await deleteProduct(row.id)
  ElMessage.success(result.message)
  await load()
}
const supplierName = id => suppliers.value.find(item => item.id === id)?.name || `供应商 #${id}`
const supplierOptionLabel = supplier => `${supplier.name}${originalSupplierIds.value.includes(supplier.id) ? '（已分配）' : ''}`
const batchRemove = async () => {
  await ElMessageBox.confirm(`确认提交选中的 ${selected.value.length} 个商品的删除申请吗？`, '批量提交删除申请', { type: 'warning' })
  const result = await batchDeleteProducts(selected.value.map(item => item.id))
  ElMessage.success(result.message)
  await load()
}
onMounted(load)
</script>

<style scoped>
.unit-tag { margin-right: 6px; margin-bottom: 4px; }
.customer-alias-row{display:grid;grid-template-columns:1fr 1fr 60px;gap:10px;margin:10px 0}.alias-help{margin-bottom:10px}.report-name{margin-left:12px;color:#657389}
.unit-help { margin: -6px 0 12px 95px; color: #8492a6; font-size: 13px; }
.unit-row { display: grid; grid-template-columns: 1fr 125px 135px 135px 95px 55px; gap: 10px; margin-bottom: 10px; align-items: center; }
.unit-row-head{color:#7c8799;font-size:12px;margin-bottom:5px}.unit-guide{margin-bottom:14px}.base-unit-row{background:#f1faf7;border-radius:10px;padding:10px}.unit-meaning{grid-column:1/-1;color:#64758a;font-size:12px;padding-left:4px}.unit-history-tip{margin-top:10px;padding:10px 12px;border-radius:8px;background:#fff8e8;color:#93651e;font-size:12px;line-height:1.6}.unit-price-line{display:flex;align-items:center;gap:8px;margin:4px 0;font-size:12px;color:#657389}.field-tip{margin-left:12px;color:#8a96a8;font-size:12px}.unit-price-table{margin-top:14px}.new-unit-row{display:grid;grid-template-columns:1fr 140px 150px 150px;gap:10px}
.header-actions { display: flex; gap: 10px; }
.product-toolbar{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:16px}.product-search{width:min(440px,100%)}.filter-select{width:170px}.status-select{width:130px}.result-count{margin-left:auto;color:#7d8999;font-size:13px;white-space:nowrap}
.muted, .binding-help { color: #9099a8; font-size: 13px; }
.product-thumb{width:48px;height:48px;border-radius:8px}.product-placeholder{width:48px;height:48px;border-radius:8px;background:#f2f4f7;color:#a4adba;font-size:11px;display:flex;align-items:center;justify-content:center}.form-product-image{width:76px;height:76px;border-radius:10px;margin-left:12px;vertical-align:middle}.mini-tag{margin-left:4px}.report-name{max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.binding-help { margin-top: 6px; }
:global(.el-select-dropdown__item.assigned-option) { color: #a0a8b5; background: #f3f5f8; }
@media (max-width:760px){.product-search,.filter-select,.status-select{width:100%}.result-count{margin-left:0}.unit-row{grid-template-columns:1fr 1fr}.unit-row-head{display:none}.unit-meaning{grid-column:1/-1}}
</style>
