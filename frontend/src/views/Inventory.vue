<template>
  <div>
    <div class="page-header">
      <div>
        <h2>智能库存查询</h2>
        <p>基于库存数据查询商品、规格、批次、临期与已过期信息</p>
      </div>
      <div>
        <input
          ref="fileInput"
          type="file"
          accept=".xlsx"
          hidden
          @change="handleUpload"
        /><el-button
          v-if="canUpdate"
          :loading="uploading"
          @click="fileInput.click()"
          ><el-icon><Upload /></el-icon>更新库存表</el-button
        >
      </div>
    </div>
    <div class="update-time">
      <el-icon><Clock /></el-icon>库存上次更新时间：{{
        summary.last_update || "加载中…"
      }}<span
        >个别商品库存可能存在一定误差，每日晚上 19:30
        前更新当天库存，暂只支持干货查询。</span
      >
    </div>
    <el-row :gutter="14" class="metrics">
      <el-col :span="5"
        ><el-card class="panel"
          ><span>商品条目</span
          ><strong>{{ summary.total_items ?? 0 }}</strong></el-card
        ></el-col
      >
      <el-col :span="5"
        ><el-card class="panel"
          ><span>库存合计</span
          ><strong>{{ formatNumber(summary.total_stock) }}</strong></el-card
        ></el-col
      >
      <el-col :span="5"
        ><el-card class="panel"
          ><span>零/负库存</span
          ><strong class="danger">{{
            summary.zero_stock ?? 0
          }}</strong></el-card
        ></el-col
      >
      <el-col :span="4"
        ><el-card class="panel"
          ><span>批次数</span
          ><strong>{{ summary.batch_count ?? 0 }}</strong></el-card
        ></el-col
      >
      <el-col :span="5"
        ><el-card class="panel"
          ><span>30天内到期</span
          ><strong class="warning">{{
            summary.expiring_30_days ?? 0
          }}</strong></el-card
        ></el-col
      >
    </el-row>
    <el-card class="panel query-panel">
      <div class="filters">
        <span class="filter-label">按库存品类查询</span>
        <el-select
          v-model="form.categories"
          multiple
          collapse-tags
          clearable
          placeholder="选择一个或多个品类，可直接查询"
          ><el-option
            v-for="c in summary.categories || []"
            :key="c"
            :label="c"
            :value="c" /></el-select
        ><el-checkbox v-model="form.only_available">只看有库存商品</el-checkbox
        ><el-checkbox v-model="form.only_expiring">只看30天内到期</el-checkbox>
      </div>
      <div class="query">
        <el-input
          v-model="form.question"
          size="large"
          clearable
          placeholder="例如：可乐还有多少 / 批次260606送了什么货 / 查一下临期商品 / 有没有已经过期的"
          @keyup.enter="search"
          ><template #prefix
            ><el-icon><Search /></el-icon></template></el-input
        ><el-button
          type="primary"
          size="large"
          :loading="loading"
          @click="search"
          ><el-icon><MagicStick /></el-icon>智能查询</el-button
        >
      </div>
    </el-card>
    <el-card v-if="searched" class="panel result-panel">
      <div class="result-head">
        <div>
          <el-tag>{{ result.query_type }}</el-tag
          ><span
            >检索关键词：<strong>{{ result.keyword || "未识别" }}</strong></span
          ><span v-if="result.days_left"
            >剩余 {{ result.days_left }} 天内到期</span
          ><span>找到 {{ result.count }} 条结果</span>
        </div>
        <el-button v-if="result.rows?.length" @click="downloadCsv"
          ><el-icon><Download /></el-icon>下载 CSV</el-button
        >
      </div>
      <el-alert
        v-if="result.has_zero_stock"
        title="结果中包含零库存或负库存商品，请优先核对。"
        type="warning"
        :closable="false"
        style="margin-bottom: 14px"
      />
      <el-table
        v-if="result.rows?.length"
        :data="result.rows"
        stripe
        max-height="520"
        ><el-table-column
          prop="商品名称"
          label="商品名称"
          fixed
          min-width="150" /><el-table-column
          prop="品类"
          label="品类"
          min-width="100" /><el-table-column
          prop="规格"
          label="规格"
          min-width="120" /><el-table-column
          prop="总数量（最小单位）"
          label="总数量"
          min-width="110" /><el-table-column
          prop="整件数量"
          label="整件数量"
          min-width="100" /><el-table-column
          prop="散装数量"
          label="散装数量"
          min-width="100" /><el-table-column
          prop="入库"
          label="入库" /><el-table-column
          prop="出库"
          label="出库" /><el-table-column
          prop="退货"
          label="退货" /><el-table-column
          prop="批次"
          label="批次"
          min-width="110" /><el-table-column
          prop="生产日期"
          label="生产日期"
          min-width="110" /><el-table-column
          prop="保质期(月)"
          label="保质期(月)"
          min-width="110" /><el-table-column
          prop="到期日"
          label="到期日"
          min-width="110" /><el-table-column
          prop="剩余天数"
          label="剩余天数"
          min-width="100"
          ><template #default="s"
            ><span
              :class="
                Number(s.row['剩余天数']) < 0
                  ? 'danger'
                  : Number(s.row['剩余天数']) <= 30
                    ? 'warning'
                    : ''
              "
              >{{ s.row["剩余天数"] }}</span
            ></template
          ></el-table-column
        ><el-table-column prop="货物状态" label="货物状态" min-width="100"
      /></el-table>
      <el-empty v-else :description="emptyText" />
    </el-card>
  </div>
</template>
<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import { getInventorySummary, queryInventory, uploadInventory } from "@/api";
import { getUser } from "@/utils/auth";
const canUpdate = computed(() =>
    getUser()?.permissions?.includes("inventory_update"),
  ),
  summary = ref({}),
  loading = ref(false),
  uploading = ref(false),
  searched = ref(false),
  fileInput = ref();
const form = reactive({
  question: "",
  categories: [],
  only_available: false,
  only_expiring: false,
});
const result = ref({ rows: [], count: 0 });
const emptyText = computed(() =>
  result.value.query_type === "临期查询"
    ? `当前没有剩余 ${result.value.days_left} 天内到期的商品`
    : result.value.query_type === "过期查询"
      ? "当前没有已过期商品"
      : "没有找到相关结果，可以换商品名、品类、规格或批次再试。",
);
const loadSummary = async () => (summary.value = await getInventorySummary());
const formatNumber = (value) =>
  Number(value || 0).toLocaleString("zh-CN", { maximumFractionDigits: 1 });
const search = async () => {
  if (!form.question.trim() && !form.categories.length)
    return ElMessage.warning("请输入查询内容，或至少选择一个库存品类");
  loading.value = true;
  try {
    result.value = await queryInventory(form);
    searched.value = true;
  } finally {
    loading.value = false;
  }
};
const handleUpload = async (event) => {
  const file = event.target.files?.[0];
  if (!file) return;
  uploading.value = true;
  try {
    summary.value = await uploadInventory(file);
    searched.value = false;
    ElMessage.success("库存表已更新");
  } finally {
    uploading.value = false;
    event.target.value = "";
  }
};
const downloadCsv = () => {
  const rows = result.value.rows;
  if (!rows.length) return;
  const cols = Object.keys(rows[0]);
  const escape = (v) => `"${String(v ?? "").replaceAll('"', '""')}"`;
  const csv =
    "\ufeff" +
    [
      cols.map(escape).join(","),
      ...rows.map((row) => cols.map((c) => escape(row[c])).join(",")),
    ].join("\n");
  const url = URL.createObjectURL(
    new Blob([csv], { type: "text/csv;charset=utf-8" }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = `${result.value.query_type}结果.csv`;
  a.click();
  URL.revokeObjectURL(url);
};
onMounted(loadSummary);
</script>
<style scoped>
.update-time {
  display: flex;
  align-items: center;
  gap: 7px;
  margin: -8px 0 16px;
  color: #627089;
  font-size: 13px;
}
.update-time span {
  margin-left: auto;
  color: #b07c33;
}
.metrics {
  margin-bottom: 16px;
}
.metrics .panel :deep(.el-card__body) {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.metrics span {
  color: #8b93a5;
  font-size: 13px;
}
.metrics strong {
  font-size: 25px;
  color: #26354d;
}
.danger {
  color: #e0523f !important;
  font-weight: 700;
}
.warning {
  color: #dc8a2e !important;
  font-weight: 700;
}
.query-panel {
  margin-bottom: 16px;
}
.filters {
  display: flex;
  align-items: center;
  gap: 22px;
  margin-bottom: 14px;
}
.filters .el-select {
  width: 300px;
}
.query {
  display: grid;
  grid-template-columns: 1fr 130px;
  gap: 12px;
}
.result-panel {
  margin-top: 16px;
}
.result-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.result-head > div {
  display: flex;
  align-items: center;
  gap: 16px;
  color: #68748a;
  font-size: 13px;
}
</style>
