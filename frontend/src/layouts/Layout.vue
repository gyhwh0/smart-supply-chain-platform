<template>
  <el-container class="shell">
    <el-aside width="238px" class="sidebar">
      <div class="brand">
        <div class="brand-mark">嘉</div>
        <div><strong>智能管理平台</strong><small>供应链智能管理</small></div>
      </div>
      <el-menu router :default-active="route.path" class="nav">
        <el-menu-item index="/dashboard"
          ><el-icon><DataBoard /></el-icon><span>工作台</span></el-menu-item
        >
        <el-sub-menu v-if="hasProcurementMenu" index="procurement">
          <template #title
            ><el-icon><ShoppingCart /></el-icon
            ><span>{{
              user?.role === "supplier" ? "报价管理" : "采购比价管理"
            }}</span></template
          >
          <el-menu-item v-if="can('supplier_management')" index="/suppliers"
            >供应商管理</el-menu-item
          >
          <el-menu-item v-if="can('category_management')" index="/categories"
            >分类管理</el-menu-item
          >
          <el-menu-item v-if="can('product_management')" index="/products">{{
            user?.role === "supplier" ? "已分配商品" : "商品管理"
          }}</el-menu-item>
          <el-menu-item v-if="can('assignment_management')" index="/assignments"
            >商品分配</el-menu-item
          >
          <el-menu-item v-if="can('quote_management')" index="/quotes"
            >我的报价</el-menu-item
          >
          <el-menu-item v-if="can('analysis')" index="/analysis"
            >智能比价</el-menu-item
          >
          <el-menu-item v-if="can('order_management')" index="/orders"
            >采购下单</el-menu-item
          >
          <el-menu-item v-if="can('smart_split_management')" index="/smart-split"
            >智能拆单</el-menu-item
          >
          <el-menu-item v-if="can('supplier_order_view')" index="/supplier-orders"
            >采购订单</el-menu-item
          >
        </el-sub-menu>
        <el-sub-menu
          v-if="can('sales_order_management') || can('sales_summary') || can('wecom_management') || can('complaint_management')"
          index="sales"
        >
          <template #title
            ><el-icon><Sell /></el-icon><span>销售管理</span></template
          >
          <el-menu-item v-if="can('sales_order_management')" index="/sales-orders"
            >销售单</el-menu-item
          >
          <el-menu-item v-if="can('sales_summary')" index="/sales-summary"
            >销售汇总</el-menu-item
          >
          <el-menu-item v-if="can('wecom_management')" index="/wecom-management"
            >企业微信订单助手</el-menu-item
          >
          <el-menu-item v-if="can('complaint_management')" index="/complaints"
            ><span class="menu-label"><span>投诉专栏</span><el-badge v-if="attention.urgent_complaints" :value="attention.urgent_complaints" type="danger" class="menu-badge" /></span></el-menu-item
          >
        </el-sub-menu>
        <el-sub-menu
          v-if="can('staff_management') || can('customer_management')"
          index="delivery"
        >
          <template #title
            ><el-icon><Van /></el-icon><span>分拣配送管理</span></template
          >
          <el-menu-item v-if="can('staff_management')" index="/staff"
            >分拣配送人员</el-menu-item
          >
          <el-menu-item v-if="can('customer_management')" index="/customers"
            >客户管理</el-menu-item
          >
        </el-sub-menu>
        <el-menu-item v-if="can('inventory')" index="/inventory"
          ><el-icon><Files /></el-icon><span>库存查询</span></el-menu-item
        >
        <el-sub-menu v-if="can('warehouse_management') || can('inbound_management') || can('label_printing') || can('picking_management') || can('picking_monitor')" index="warehouse-business">
          <template #title><el-icon><Box /></el-icon><span>仓库管理</span></template>
          <el-menu-item v-if="can('warehouse_management')" index="/warehouse">库存台账</el-menu-item>
          <el-menu-item v-if="can('warehouse_management')" index="/inventory-counts">库存盘点</el-menu-item>
          <el-menu-item v-if="can('inbound_management')" index="/inbound">进货与退货</el-menu-item>
          <el-menu-item v-if="can('label_printing')" index="/label-printing">标签打印</el-menu-item>
          <el-menu-item v-if="can('picking_management')" index="/picking">扫码分拣</el-menu-item>
          <el-menu-item v-if="can('picking_monitor')" index="/picking-monitor">分拣配送监控</el-menu-item>
        </el-sub-menu>
        <el-menu-item v-if="can('finance_management')" index="/finance">
          <el-icon><Wallet /></el-icon><span>财务管理</span>
        </el-menu-item>
        <el-menu-item v-if="can('report_management')" index="/reports">
          <el-icon><TrendCharts /></el-icon><span>报表管理</span>
        </el-menu-item>
        <el-menu-item v-if="can('account_management')" index="/accounts"
          ><el-icon><UserFilled /></el-icon><span>账号管理</span></el-menu-item
        >
        <el-menu-item v-if="can('deletion_approval') && user?.role === 'admin'" index="/deletion-approvals">
          <el-icon><CircleCheck /></el-icon><span>删除审核</span>
        </el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="topbar">
        <div>
          <span class="role-pill">{{ roleLabel }}</span>
        </div>
        <el-dropdown @command="handleCommand">
          <div class="account">
            <el-avatar :size="34">{{ user?.name?.slice(0, 1) }}</el-avatar
            ><span>{{ user?.name }}</span
            ><el-icon><ArrowDown /></el-icon>
          </div>
          <template #dropdown
            ><el-dropdown-menu
              ><el-dropdown-item command="logout"
                >退出登录</el-dropdown-item
              ></el-dropdown-menu
            ></template
          >
        </el-dropdown>
      </el-header>
      <div v-if="attention.urgent_complaints" class="attention attention-danger" @click="router.push('/complaints')">
        <strong>紧急食品安全投诉</strong>
        <span>有 {{ attention.urgent_complaints }} 条 P0 投诉待处理<span v-if="attention.latest_complaint">：{{ attention.latest_complaint.content }}</span></span>
        <b>立即处理 →</b>
      </div>
      <div v-if="attention.review_items" class="attention attention-warning" @click="router.push({ path: '/wecom-management', query: { tab: attention.review_drafts ? 'drafts' : 'messages' } })">
        <strong>微信消息需人工处理</strong>
        <span>仍有 <template v-if="attention.review_drafts">{{ attention.review_drafts }} 条订单草稿</template><template v-if="attention.review_drafts && attention.review_messages">、</template><template v-if="attention.review_messages">{{ attention.review_messages }} 条微信消息</template>尚未解决</span>
        <b>立即查看 →</b>
      </div>
      <el-main class="content"><router-view /></el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { getMe, getWeComAttention } from "@/api";
import { getUser, logout, updateUser } from "@/utils/auth";

const route = useRoute();
const router = useRouter();
const user = ref(getUser());
const attention = ref({ urgent_complaints: 0, review_items: 0, review_drafts: 0, review_messages: 0, latest_complaint: null });
let attentionTimer;
const can = (permission) => user.value?.permissions?.includes(permission);
const hasProcurementMenu = computed(() =>
  [
    "supplier_management",
    "category_management",
    "product_management",
    "assignment_management",
    "quote_management",
    "analysis",
    "order_management",
    "smart_split_management",
    "supplier_order_view",
  ].some(can),
);
const roleLabel = computed(
  () =>
    ({
      supplier: "供应商",
      admin: "管理员",
      warehouse: "仓管员",
      purchaser: "采购员",
      order_clerk: "订单员",
    })[user.value?.role] || "用户",
);
const handleCommand = () => {
  logout();
  router.push("/login");
};
const syncUser = async () => {
  const latest = await getMe();
  user.value = latest;
  updateUser(latest);
};
const loadAttention = async () => {
  if (!can("wecom_management")) return;
  try {
    attention.value = await getWeComAttention();
  } catch (_) {
    // 权限变化或短暂网络错误不影响主页面使用。
  }
};
const handleUserUpdate = (event) => {
  user.value = event.detail;
};
const handleVisibility = () => {
  if (!document.hidden) {
    syncUser();
    loadAttention();
  }
};
const handleAttentionUpdate = () => loadAttention();
watch(
  () => route.fullPath,
  () => {
    syncUser();
    loadAttention();
  },
);
onMounted(() => {
  window.addEventListener("auth-user-updated", handleUserUpdate);
  window.addEventListener("focus", syncUser);
  document.addEventListener("visibilitychange", handleVisibility);
  window.addEventListener("attention-updated", handleAttentionUpdate);
  syncUser();
  loadAttention();
  attentionTimer = window.setInterval(loadAttention, 30000);
});
onBeforeUnmount(() => {
  window.removeEventListener("auth-user-updated", handleUserUpdate);
  window.removeEventListener("focus", syncUser);
  document.removeEventListener("visibilitychange", handleVisibility);
  window.removeEventListener("attention-updated", handleAttentionUpdate);
  window.clearInterval(attentionTimer);
});
</script>

<style scoped>
.shell {
  min-height: 100vh;
}
.sidebar {
  background: #101a2d;
  color: white;
  padding: 0 12px;
}
.brand {
  height: 78px;
  display: flex;
  gap: 12px;
  align-items: center;
  padding: 0 10px;
}
.brand-mark {
  width: 38px;
  height: 38px;
  display: grid;
  place-items: center;
  border-radius: 11px;
  background: linear-gradient(135deg, #4a8dff, #62d3b4);
  font-weight: 800;
}
.brand strong,
.brand small {
  display: block;
}
.brand strong {
  font-size: 18px;
}
.brand small {
  color: #8290a8;
  margin-top: 3px;
}
.nav {
  border: 0;
  background: transparent;
}
.nav :deep(.el-menu-item),
.nav :deep(.el-sub-menu__title) {
  color: #aeb8cb;
  border-radius: 9px;
  margin: 5px 0;
}
.nav :deep(.el-menu-item:hover),
.nav :deep(.el-sub-menu__title:hover),
.nav :deep(.is-active) {
  background: #203453;
  color: #fff;
}
.nav :deep(.el-menu) {
  background: transparent;
}
.nav :deep(.el-sub-menu .el-menu-item) {
  min-width: auto;
  padding-left: 52px !important;
}
.topbar {
  height: 66px;
  background: white;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid #e9edf4;
  padding: 0 28px;
}
.account {
  display: flex;
  align-items: center;
  gap: 9px;
  cursor: pointer;
}
.role-pill {
  background: #edf5ff;
  color: #3274d9;
  padding: 6px 12px;
  border-radius: 20px;
  font-size: 13px;
}
.content {
  padding: 28px;
}
.menu-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
}
.menu-badge {
  margin-right: 4px;
}
.attention {
  min-height: 46px;
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 8px 28px;
  cursor: pointer;
  border-bottom: 1px solid;
}
.attention span {
  flex: 1;
}
.attention-danger {
  color: #a51d1d;
  background: #fff0f0;
  border-color: #f3b5b5;
  animation: urgent-pulse 1.8s ease-in-out infinite;
}
.attention-warning {
  color: #8a5100;
  background: #fff8e6;
  border-color: #f1cf82;
}
@keyframes urgent-pulse {
  0%, 100% { background: #fff0f0; }
  50% { background: #ffdede; }
}
</style>
