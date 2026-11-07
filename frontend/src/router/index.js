import { createRouter, createWebHistory } from 'vue-router'
import { getToken, getUser, setSession } from '@/utils/auth'

const routes = [
  { path: '/login', component: () => import('@/views/Login.vue') },
  { path: '/scan-picking', component: () => import('@/views/MobilePicking.vue'), meta: { public: true } },
  { path: '/mobile-tasks', component: () => import('@/views/MobileStaffTasks.vue'), meta: { public: true } },
  {
    path: '/',
    component: () => import('@/layouts/Layout.vue'),
    children: [
      { path: '', redirect: '/dashboard' },
      { path: 'dashboard', component: () => import('@/views/Dashboard.vue'), meta: { permission: 'dashboard' } },
      { path: 'accounts', component: () => import('@/views/Accounts.vue'), meta: { permission: 'account_management' } },
      { path: 'super-admin', component: () => import('@/views/SuperAdmin.vue'), meta: { superAdmin: true } },
      { path: 'suppliers', component: () => import('@/views/Suppliers.vue'), meta: { permission: 'supplier_management' } },
      { path: 'categories', component: () => import('@/views/Categories.vue'), meta: { permission: 'category_management' } },
      { path: 'products', component: () => import('@/views/Products.vue'), meta: { permission: 'product_management' } },
      { path: 'assignments', component: () => import('@/views/Assignments.vue'), meta: { permission: 'assignment_management' } },
      { path: 'quotes', component: () => import('@/views/Quotes.vue'), meta: { permission: 'quote_management' } },
      { path: 'analysis', component: () => import('@/views/Analysis.vue'), meta: { permission: 'analysis' } },
      { path: 'orders', component: () => import('@/views/Orders.vue'), meta: { permission: 'order_management' } },
      { path: 'sales-orders', component: () => import('@/views/SalesOrders.vue'), meta: { permission: 'sales_order_management' } },
      { path: 'sales-summary', component: () => import('@/views/SalesSummary.vue'), meta: { permission: 'sales_summary' } },
      { path: 'wecom-management', component: () => import('@/views/WeComManagement.vue'), meta: { permission: 'wecom_management' } },
      { path: 'complaints', component: () => import('@/views/Complaints.vue'), meta: { permission: 'complaint_management' } },
      { path: 'sales-customers/:id', component: () => import('@/views/SalesCustomerDetail.vue'), meta: { permission: 'sales_summary' } },
      { path: 'staff', component: () => import('@/views/Staff.vue'), meta: { permission: 'staff_management' } },
      { path: 'customers', component: () => import('@/views/Customers.vue'), meta: { permission: 'customer_management' } },
      { path: 'inventory', component: () => import('@/views/Inventory.vue'), meta: { permission: 'inventory' } },
      { path: 'inbound', component: () => import('@/views/Inbound.vue'), meta: { permission: 'inbound_management' } },
      { path: 'warehouse', component: () => import('@/views/Warehouse.vue'), meta: { permission: 'warehouse_management' } },
      { path: 'label-printing', component: () => import('@/views/LabelPrinting.vue'), meta: { permission: 'label_printing' } },
      { path: 'picking', component: () => import('@/views/Picking.vue'), meta: { permission: 'picking_management' } },
      { path: 'picking-monitor', component: () => import('@/views/PickingMonitor.vue'), meta: { permission: 'picking_monitor' } },
      { path: 'finance', component: () => import('@/views/Finance.vue'), meta: { permission: 'finance_management' } },
      { path: 'inventory-query-records', component: () => import('@/views/InventoryQueryRecords.vue'), meta: { adminOnly: true, hiddenLink: true } }
    ]
  }
]

const router = createRouter({ history: createWebHistory(), routes })
let defaultAdminChecked = false
const tryDefaultAdmin = async () => {
  if (getToken()) return false
  if (defaultAdminChecked) return false
  defaultAdminChecked = true
  try {
    const base = import.meta.env.VITE_API_BASE_URL || ''
    const response = await fetch(`${base}/api/auth/default-admin`, { method: 'POST' })
    if (!response.ok) return false
    const result = await response.json()
    setSession(result.token, result.user)
    return true
  } catch { return false }
}
router.beforeEach(async (to) => {
  if (to.meta.public) return true
  const defaultMode = await tryDefaultAdmin()
  if (to.path === '/login') return (defaultMode || getToken()) ? '/dashboard' : true
  if (!getToken()) return '/login'
  const user = getUser()
  if (to.meta.superAdmin && (to.query.admin !== 'yes' || user?.role !== 'admin')) return '/dashboard'
  if (to.meta.hiddenLink && (to.query.admin !== 'yes' || user?.role !== 'admin')) return '/dashboard'
  if (to.meta.permission && !user?.permissions?.includes(to.meta.permission)) {
    const candidates = [
      ['dashboard', '/dashboard'], ['account_management', '/accounts'], ['supplier_management', '/suppliers'],
      ['category_management', '/categories'], ['product_management', '/products'],
      ['assignment_management', '/assignments'], ['quote_management', '/quotes'],
      ['analysis', '/analysis'], ['inventory', '/inventory'],
      ['order_management', '/orders'], ['staff_management', '/staff'], ['customer_management', '/customers'],
      ['sales_order_management', '/sales-orders'], ['sales_summary', '/sales-summary'],
      ['wecom_management', '/wecom-management'], ['complaint_management', '/complaints'],
      ['inbound_management', '/inbound'], ['label_printing', '/label-printing'],
      ['warehouse_management', '/warehouse'],
      ['picking_management', '/picking'],
      ['picking_monitor', '/picking-monitor'],
      ['finance_management', '/finance'],
    ]
    return candidates.find(([permission]) => user?.permissions?.includes(permission))?.[1] || '/login'
  }
  return true
})

export default router
