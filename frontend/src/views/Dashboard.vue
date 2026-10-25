<template>
  <div>
    <div class="page-header">
      <div>
        <h2>工作台 优化升级中...</h2>
        <p>欢迎回来，{{ user?.name }}。从这里快速进入各业务模块。</p>
      </div>
    </div>
    <div class="hero">
      <div>
        <span>SUPPLY CHAIN INTELLIGENCE</span>
        <h1>{{ heroTitle }}</h1>
        <p>{{ heroDescription }}</p>
      </div>
      <el-icon><ShoppingCartFull /></el-icon>
    </div>
    <div v-if="procurementCards.length" class="section-title">
      {{ isSupplier ? "供应商工作入口" : "业务管理" }}
    </div>
    <el-row v-if="procurementCards.length" :gutter="18">
      <el-col v-for="item in procurementCards" :key="item.title" :span="6">
        <el-card
          class="panel module-card"
          shadow="hover"
          @click="router.push(item.route)"
        >
          <div class="icon" :style="{ background: item.bg, color: item.color }">
            <el-icon><component :is="item.icon" /></el-icon>
          </div>
          <div class="value">{{ item.value }}</div>
          <strong>{{ item.title }}</strong>
          <p>{{ item.text }}</p>
          <span class="go">进入模块 →</span>
        </el-card>
      </el-col>
    </el-row>
    <div v-if="can('inventory')" class="section-title">库存查询</div>
    <el-card
      v-if="can('inventory')"
      class="panel inventory-entry"
      shadow="hover"
      @click="router.push('/inventory')"
    >
      <div class="inventory-icon">
        <el-icon><Files /></el-icon>
      </div>
      <div>
        <h3>智能库存查询</h3>
        <p>从库存表查询商品、品类、规格与批次，识别临期和已过期商品。</p>
      </div>
      <div class="inventory-stat" v-if="!isSupplier">
        <strong>{{ stats.zero_stock ?? 0 }}</strong
        ><span>零/负库存</span>
      </div>
      <el-button type="primary" plain>进入库存查询</el-button>
    </el-card>
  </div>
</template>
<script setup>
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { getDashboard } from "@/api";
import { getUser } from "@/utils/auth";
const router = useRouter(),
  user = getUser(),
  stats = ref({});
const isSupplier = computed(() => user?.role === "supplier");
const heroTitle = computed(() =>
  isSupplier.value
    ? "及时维护报价，赢得更多合作机会"
    : "采购、比价与库存，一站式协同管理",
);
const heroDescription = computed(() =>
  isSupplier.value
    ? "查看分配商品、更新报价并查询相关库存。"
    : "实时掌握供应商、商品库存、报价等。",
);
const can = (permission) => user?.permissions?.includes(permission);
const procurementCards = computed(() =>
  isSupplier.value
    ? [
        {
          title: "已分配商品",
          text: "查看采购员分配的商品",
          icon: "Box",
          route: "/products",
          value: stats.value.assigned ?? 0,
          bg: "#edf5ff",
          color: "#347dde",
        },
        {
          title: "已报价",
          text: "已完成报价的商品",
          icon: "CircleCheck",
          route: "/quotes",
          value: stats.value.quoted ?? 0,
          bg: "#eaf8f1",
          color: "#24946b",
        },
        {
          title: "待报价",
          text: "需要尽快维护价格",
          icon: "EditPen",
          route: "/quotes",
          value: stats.value.pending ?? 0,
          bg: "#fff4e8",
          color: "#df812c",
        },
      ].filter((item) =>
        can(
          item.route === "/quotes" ? "quote_management" : "product_management",
        ),
      )
    : [
        {
          permission: "supplier_management",
          title: "供应商管理",
          text: "供应资源与报价账号",
          icon: "OfficeBuilding",
          route: "/suppliers",
          value: stats.value.suppliers ?? 0,
          bg: "#edf5ff",
          color: "#347dde",
        },
        {
          permission: "product_management",
          title: "商品管理",
          text: "商品档案、单位与供应商绑定",
          icon: "Box",
          route: "/products",
          value: stats.value.products ?? 0,
          bg: "#eaf8f1",
          color: "#24946b",
        },
        {
          permission: "assignment_management",
          title: "商品分配",
          text: "向供应商发起询价",
          icon: "Connection",
          route: "/assignments",
          value: stats.value.assignments ?? 0,
          bg: "#fff4e8",
          color: "#df812c",
        },
        {
          permission: "analysis",
          title: "智能比价",
          text: "最低价与品类优势",
          icon: "TrendCharts",
          route: "/analysis",
          value: "AI",
          bg: "#f4efff",
          color: "#8159d9",
        },
        {
          permission: "order_management",
          title: "采购下单",
          text: "批量选品与采购报表",
          icon: "DocumentChecked",
          route: "/orders",
          value: "PO",
          bg: "#fff2e8",
          color: "#d87532",
        },
        {
          permission: "sales_order_management",
          title: "销售单",
          text: "客户订单快捷录入与确认",
          icon: "Tickets",
          route: "/sales-orders",
          value: stats.value.sales_orders ?? "SO",
          bg: "#eef8ff",
          color: "#287cba",
        },
        {
          permission: "sales_summary",
          title: "销售汇总",
          text: "多维统计与 Excel 导出",
          icon: "DataAnalysis",
          route: "/sales-summary",
          value: "汇总",
          bg: "#fff0f3",
          color: "#c84b6e",
        },
        {
          permission: "staff_management",
          title: "分拣配送人员",
          text: "分拣员与配送员档案",
          icon: "Van",
          route: "/staff",
          value: "人员",
          bg: "#eaf8f1",
          color: "#24946b",
        },
        {
          permission: "customer_management",
          title: "客户管理",
          text: "客户及服务人员分配",
          icon: "User",
          route: "/customers",
          value: "客户",
          bg: "#edf5ff",
          color: "#347dde",
        },
        {
          permission: "account_management",
          title: "账号管理",
          text: "角色、账号与功能权限",
          icon: "UserFilled",
          route: "/accounts",
          value: "ACL",
          bg: "#f1f4f8",
          color: "#53657c",
        },
        {
          permission: "inbound_management",
          title: "进货与退货",
          text: "到货录入、批次追溯与退货",
          icon: "TakeawayBox",
          route: "/inbound",
          value: "入库",
          bg: "#eef9f4",
          color: "#248c68",
        },
        {
          permission: "label_printing",
          title: "标签打印",
          text: "客户订单标签与自定义打印",
          icon: "Printer",
          route: "/label-printing",
          value: "标签",
          bg: "#fff6e8",
          color: "#cf7b20",
        },
        {
          permission: "picking_management",
          title: "扫码分拣",
          text: "按客户分拣、扫码确认与装车追踪",
          icon: "FullScreen",
          route: "/picking",
          value: "扫码",
          bg: "#eaf8f6",
          color: "#16877c",
        },
      ].filter((item) => can(item.permission)),
);
onMounted(async () => (stats.value = await getDashboard()));
</script>
<style scoped>
.hero {
  background: linear-gradient(120deg, #19345d, #2d6ca5);
  color: #fff;
  border-radius: 18px;
  padding: 34px 42px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  box-shadow: 0 14px 36px rgba(26, 61, 105, 0.2);
}
.hero span {
  font-size: 12px;
  letter-spacing: 2px;
  color: #79dfc4;
}
.hero h1 {
  margin: 10px 0;
  font-size: 29px;
}
.hero p {
  color: #c9d7e8;
}
.hero > .el-icon {
  font-size: 92px;
  color: rgba(255, 255, 255, 0.18);
}
.section-title {
  font-size: 18px;
  font-weight: 700;
  margin: 25px 0 14px;
}
.module-card {
  cursor: pointer;
  height: 210px;
  position: relative;
}
.module-card :deep(.el-card__body) {
  height: 100%;
}
.icon {
  width: 46px;
  height: 46px;
  display: grid;
  place-items: center;
  border-radius: 13px;
  font-size: 22px;
}
.value {
  position: absolute;
  right: 20px;
  top: 22px;
  font-size: 28px;
  font-weight: 800;
  color: #26354d;
}
.module-card strong {
  display: block;
  margin-top: 18px;
  font-size: 17px;
}
.module-card p {
  margin: 7px 0;
  color: #8b93a5;
}
.go {
  position: absolute;
  bottom: 18px;
  color: #3d7fd5;
  font-size: 13px;
}
.inventory-entry {
  cursor: pointer;
}
.inventory-entry :deep(.el-card__body) {
  display: flex;
  align-items: center;
  gap: 18px;
}
.inventory-icon {
  width: 58px;
  height: 58px;
  display: grid;
  place-items: center;
  border-radius: 15px;
  background: #eaf8f1;
  color: #24946b;
  font-size: 28px;
}
.inventory-entry h3 {
  margin: 0 0 7px;
}
.inventory-entry p {
  margin: 0;
  color: #8b93a5;
}
.inventory-entry > div:nth-child(2) {
  flex: 1;
}
.inventory-stat {
  text-align: center;
  padding: 0 26px;
  border-right: 1px solid #edf0f5;
}
.inventory-stat strong,
.inventory-stat span {
  display: block;
}
.inventory-stat strong {
  font-size: 25px;
  color: #e15e41;
}
.inventory-stat span {
  font-size: 12px;
  color: #8b93a5;
  margin-top: 3px;
}
</style>
