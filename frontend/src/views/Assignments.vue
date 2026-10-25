<template>
  <div>
    <div class="page-header">
      <div><h2>商品分配</h2><p>可按整个品类快速分配，也可搜索并精确勾选商品</p></div>
      <el-button type="primary" @click="openDialog"><el-icon><Connection /></el-icon>批量分配</el-button>
    </div>
    <el-card class="panel">
      <el-table :data="rows">
        <el-table-column prop="product.name" label="商品" min-width="150" />
        <el-table-column prop="product.category" label="品类" min-width="120" />
        <el-table-column prop="supplier.name" label="供应商" min-width="160" />
        <el-table-column label="可报价单位" min-width="180"><template #default="scope"><el-tag v-for="unit in scope.row.product.units" :key="unit.id" class="small-tag">{{ unit.name }}</el-tag></template></el-table-column>
        <el-table-column label="报价状态" width="130"><template #default="scope"><el-tag :type="scope.row.quotes.length ? 'success' : 'warning'">{{ scope.row.quotes.length ? `已报价 ${scope.row.quotes.length} 项` : '待报价' }}</el-tag></template></el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="visible" title="批量分配商品" width="880px" top="5vh">
      <el-alert title="同一商品和供应商重复分配时不会产生重复数据，只会恢复原有分配。" type="info" :closable="false" show-icon />
      <div class="section-title">第一步：选择商品范围</div>
      <el-radio-group v-model="mode" class="mode-switch">
        <el-radio-button value="category">按品类批量分配</el-radio-button>
        <el-radio-button value="product">按商品精确分配</el-radio-button>
      </el-radio-group>

      <div v-if="mode === 'category'" class="choice-panel category-grid">
        <el-checkbox v-for="category in activeCategories" :key="category.id" v-model="form.category_ids" :value="category.id" border>
          <span>{{ category.name }}</span><small>{{ productCount(category.id) }} 个启用商品</small>
        </el-checkbox>
      </div>
      <div v-else class="choice-panel">
        <div class="filter-row">
          <el-input v-model="keyword" clearable placeholder="搜索商品名称或 SKU" style="width:260px" />
          <el-select v-model="filterCategory" clearable placeholder="全部品类" style="width:180px"><el-option v-for="category in activeCategories" :key="category.id" :label="category.name" :value="category.id" /></el-select>
          <el-button @click="selectFiltered">选择当前筛选结果</el-button>
          <el-button @click="form.product_ids = []">清空</el-button>
        </div>
        <el-checkbox-group v-model="form.product_ids" class="product-grid">
          <el-checkbox v-for="product in filteredProducts" :key="product.id" :value="product.id" border :disabled="productAlreadyAssigned(product.id)" :class="{ 'already-assigned': productAlreadyAssigned(product.id) }">
            <span>{{ product.name }}</span><small>{{ product.category }} · {{ product.sku || '无 SKU' }}{{ productAlreadyAssigned(product.id) ? ' · 已向所选供应商分配' : '' }}</small>
          </el-checkbox>
        </el-checkbox-group>
        <el-empty v-if="!filteredProducts.length" description="没有符合条件的启用商品" :image-size="70" />
      </div>

      <div class="section-title">第二步：选择接收报价任务的供应商</div>
      <div class="choice-panel">
        <el-input v-model="supplierKeyword" clearable placeholder="搜索供应商" style="width:280px;margin-bottom:12px" />
        <el-checkbox-group v-model="form.supplier_ids" class="supplier-grid">
          <el-checkbox v-for="supplier in filteredSuppliers" :key="supplier.id" :value="supplier.id" border :disabled="supplierFullyAssigned(supplier.id)" :class="{ 'already-assigned': supplierAlreadyCount(supplier.id) > 0 }">
            <span>{{ supplier.name }}</span><small v-if="supplierAlreadyCount(supplier.id)">已分配 {{ supplierAlreadyCount(supplier.id) }}/{{ selectedProductCount }} 个商品{{ supplierFullyAssigned(supplier.id) ? ' · 无需重复选择' : '' }}</small><small v-else>{{ supplier.contact_name || '暂无联系人' }} · {{ supplier.phone || '暂无电话' }}</small>
          </el-checkbox>
        </el-checkbox-group>
      </div>

      <div class="assignment-summary">
        将 <strong>{{ selectedProductCount }}</strong> 个商品分配给 <strong>{{ form.supplier_ids.length }}</strong> 家供应商，预计形成 <strong>{{ selectedProductCount * form.supplier_ids.length }}</strong> 条分配关系
      </div>
      <template #footer><el-button @click="visible = false">取消</el-button><el-button type="primary" @click="save">确认分配</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { createAssignments, getAssignments, getCategories, getProducts, getSuppliers } from '@/api'

const rows = ref([])
const products = ref([])
const suppliers = ref([])
const categories = ref([])
const visible = ref(false)
const mode = ref('category')
const keyword = ref('')
const supplierKeyword = ref('')
const filterCategory = ref(null)
const form = reactive({ product_ids: [], category_ids: [], supplier_ids: [] })
const activeProducts = computed(() => products.value.filter(item => item.active))
const activeSuppliers = computed(() => suppliers.value.filter(item => item.active))
const activeCategories = computed(() => categories.value.filter(item => item.active))
const filteredProducts = computed(() => activeProducts.value.filter(item => {
  const matchesCategory = !filterCategory.value || item.category_id === filterCategory.value
  const term = keyword.value.trim().toLowerCase()
  const matchesKeyword = !term || item.name.toLowerCase().includes(term) || (item.sku || '').toLowerCase().includes(term)
  return matchesCategory && matchesKeyword
}))
const filteredSuppliers = computed(() => {
  const term = supplierKeyword.value.trim().toLowerCase()
  return activeSuppliers.value.filter(item => !term || item.name.toLowerCase().includes(term))
})
const categoryProductIds = computed(() => new Set(activeProducts.value.filter(item => form.category_ids.includes(item.category_id)).map(item => item.id)))
const selectedProductCount = computed(() => mode.value === 'category' ? categoryProductIds.value.size : form.product_ids.length)
const scopeProductIds = computed(() => mode.value === 'category' ? [...categoryProductIds.value] : form.product_ids)
const assignedPairs = computed(() => new Set(rows.value.map(item => `${item.product.id}:${item.supplier.id}`)))
const productCount = (categoryId) => activeProducts.value.filter(item => item.category_id === categoryId).length
const supplierAlreadyCount = supplierId => scopeProductIds.value.filter(productId => assignedPairs.value.has(`${productId}:${supplierId}`)).length
const supplierFullyAssigned = supplierId => selectedProductCount.value > 0 && supplierAlreadyCount(supplierId) === selectedProductCount.value
const productAlreadyAssigned = productId => form.supplier_ids.length > 0 && form.supplier_ids.every(supplierId => assignedPairs.value.has(`${productId}:${supplierId}`))
const selectFiltered = () => { form.product_ids = [...new Set([...form.product_ids, ...filteredProducts.value.map(item => item.id)])] }
const load = async () => { [rows.value, products.value, suppliers.value, categories.value] = await Promise.all([getAssignments(), getProducts(), getSuppliers(), getCategories()]) }
const openDialog = () => {
  Object.assign(form, { product_ids: [], category_ids: [], supplier_ids: [] })
  mode.value = 'category'
  keyword.value = ''
  supplierKeyword.value = ''
  filterCategory.value = null
  visible.value = true
}
const save = async () => {
  if (!selectedProductCount.value) return ElMessage.warning('请至少选择一个有启用商品的品类或商品')
  if (!form.supplier_ids.length) return ElMessage.warning('请至少选择一家供应商')
  const result = await createAssignments({ product_ids: mode.value === 'product' ? form.product_ids : [], category_ids: mode.value === 'category' ? form.category_ids : [], supplier_ids: form.supplier_ids })
  ElMessage.success(`${result.message}，新增 ${result.created} 条`)
  visible.value = false
  await load()
}
onMounted(load)
</script>

<style scoped>
.small-tag { margin-right: 5px; }
.section-title { margin: 20px 0 10px; font-weight: 700; color: #23324b; }
.mode-switch { margin-bottom: 12px; }
.choice-panel { padding: 16px; border: 1px solid #e5eaf1; border-radius: 10px; background: #fafcff; max-height: 285px; overflow: auto; }
.filter-row { display: flex; gap: 10px; margin-bottom: 14px; }
.category-grid, .product-grid, .supplier-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
.choice-panel :deep(.el-checkbox) { width: 100%; height: auto; min-height: 52px; margin: 0; padding: 10px 12px; align-items: flex-start; }
.choice-panel :deep(.el-checkbox__label) { min-width: 0; display: flex; flex-direction: column; line-height: 20px; }
.choice-panel small { color: #8793a6; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.assignment-summary { margin-top: 16px; padding: 13px 16px; background: #eef6ff; color: #52647e; border-radius: 8px; }
.assignment-summary strong { color: #2475e8; font-size: 17px; }
.choice-panel :deep(.already-assigned) { background: #f0f2f5; color: #a3aab5; border-color: #e2e5e9; }
</style>
