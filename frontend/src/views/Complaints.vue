<template>
  <div>
    <div class="page-header">
      <div>
        <h2>投诉专栏</h2>
        <p>集中处理微信自动识别和人工登记的客户投诉，食品安全问题优先升级</p>
      </div>
      <div class="header-actions"><el-button type="primary" @click="openCreate">新增投诉</el-button><el-button @click="load">刷新</el-button></div>
    </div>
    <el-alert
      v-if="urgentRows.length"
      class="urgent-alert"
      type="error"
      :closable="false"
      show-icon
      :title="`有 ${urgentRows.length} 条食品安全紧急投诉待处理`"
      description="P0 投诉应立即联系客户，核实就医情况、涉事批次并保留证据。"
    />
    <div class="metrics">
      <el-card
        ><span>区间投诉</span><b>{{ summary.complaint_count }}</b></el-card
      ><el-card
        ><span>同期销售单</span><b>{{ summary.order_count }}</b></el-card
      ><el-card
        ><span>投诉率</span><b :class="{ danger: summary.complaint_rate >= 5 }">{{ Number(summary.complaint_rate || 0).toFixed(2) }}%</b></el-card
      ><el-card
        ><span>待处理</span
        ><b class="warning">{{
          rows.filter((r) => ["new", "processing"].includes(r.status)).length
        }}</b></el-card
      ><el-card
        ><span>已经超时</span
        ><b class="danger">{{
          rows.filter((r) => r.overdue).length
        }}</b></el-card
      ><el-card
        ><span>食品安全 P0</span
        ><b class="danger">{{
          rows.filter((r) => r.severity === "P0" && r.status !== "closed")
            .length
        }}</b></el-card
      >
    </div>
    <el-card class="panel"
      ><div class="toolbar">
        <el-date-picker v-model="dateRange" type="daterange" value-format="YYYY-MM-DD" range-separator="至" start-placeholder="开始日期" end-placeholder="结束日期" :clearable="false" @change="load" />
        <el-select
          v-model="filters.status"
          clearable
          placeholder="全部状态"
          @change="load"
          ><el-option
            v-for="item in statuses"
            :key="item.value"
            :label="item.label"
            :value="item.value" /></el-select
        ><el-select
          v-model="filters.severity"
          clearable
          placeholder="全部等级"
          @change="load"
          ><el-option label="P0 紧急" value="P0" /><el-option
            label="P1 重要"
            value="P1" /><el-option label="P2 普通" value="P2"
        /></el-select><el-button @click="resetFilters">重置今天</el-button>
      </div>
      <el-table
        :data="rows"
        stripe
        :row-class-name="
          ({ row }) =>
            row.severity === 'P0' &&
            !['resolved', 'closed'].includes(row.status)
              ? 'urgent-row'
              : row.overdue
                ? 'overdue-row'
                : ''
        "
        ><el-table-column
          prop="complaint_no"
          label="投诉编号"
          min-width="190"
        /><el-table-column
          prop="customer_name"
          label="客户"
          width="150"
        /><el-table-column label="等级" width="100"
          ><template #default="s"
            ><el-tag
              :type="
                s.row.severity === 'P0'
                  ? 'danger'
                  : s.row.severity === 'P1'
                    ? 'warning'
                    : 'info'
              "
              >{{
                s.row.severity === "P0" ? "P0 紧急" : s.row.severity
              }}</el-tag
            ></template
          ></el-table-column
        ><el-table-column
          prop="category"
          label="分类"
          width="120"
        /><el-table-column
          prop="content"
          label="投诉内容"
          min-width="280"
          show-overflow-tooltip
        /><el-table-column
          prop="assignee_name"
          label="处理人"
          width="120"
        /><el-table-column label="处理时限" min-width="170"
          ><template #default="s"
            ><span :class="{ danger: s.row.overdue }">{{
              time(s.row.due_at)
            }}</span></template
          ></el-table-column
        ><el-table-column label="状态" width="120"
          ><template #default="s"
            ><el-tag>{{ statusLabel(s.row.status) }}</el-tag></template
          ></el-table-column
        ><el-table-column label="操作" width="100"
          ><template #default="s"
            ><el-button link type="primary" @click="open(s.row)"
              >处理</el-button
            ></template
          ></el-table-column
        ></el-table
      >
    </el-card>
    <el-dialog
      v-model="visible"
      :title="creating ? '新增投诉' : `处理投诉 · ${form.complaint_no}`"
      width="650px"
      ><el-descriptions v-if="!creating" :column="2" border
        ><el-descriptions-item label="客户">{{
          form.customer_name
        }}</el-descriptions-item
        ><el-descriptions-item label="分类"
          >{{ form.category }} / {{ form.severity }}</el-descriptions-item
        ><el-descriptions-item label="原始内容" :span="2">{{
          form.content
        }}</el-descriptions-item></el-descriptions
      ><el-form label-width="95px" style="margin-top: 18px"
        ><template v-if="creating"><el-form-item label="投诉客户" required><el-select v-model="form.customer_id" filterable style="width:100%"><el-option v-for="item in options.customers" :key="item.id" :label="`${item.customer_code || '无编号'} · ${item.name}`" :value="item.id"/></el-select></el-form-item><el-form-item label="投诉分类" required><el-select v-model="form.category" style="width:100%"><el-option v-for="item in categories" :key="item" :label="item" :value="item"/></el-select></el-form-item><el-form-item label="投诉等级" required><el-radio-group v-model="form.severity"><el-radio-button value="P0">P0 紧急</el-radio-button><el-radio-button value="P1">P1 重要</el-radio-button><el-radio-button value="P2">P2 普通</el-radio-button></el-radio-group></el-form-item><el-form-item label="投诉内容" required><el-input v-model="form.content" type="textarea" :rows="5" placeholder="请填写客户反馈的问题、涉及商品和发生情况"/></el-form-item></template
        ><el-form-item label="处理人"
          ><el-select v-model="form.assigned_to" clearable style="width: 100%"
            ><el-option
              v-for="item in options.clerks"
              :key="item.id"
              :label="item.name"
              :value="item.id" /></el-select></el-form-item
        ><el-form-item v-if="!creating" label="处理状态"
          ><el-select v-model="form.status" style="width: 100%"
            ><el-option
              v-for="item in statuses"
              :key="item.value"
              :label="item.label"
              :value="item.value" /></el-select></el-form-item
        ><el-form-item v-if="!creating" label="处理结果"
          ><el-input
            v-model="form.resolution"
            type="textarea"
            :rows="5" /></el-form-item></el-form
      ><template #footer
        ><el-button @click="visible = false">取消</el-button
        ><el-button type="primary" @click="save"
          >{{ creating ? '确认新增' : '保存处理结果' }}</el-button
        ></template
      ></el-dialog
    >
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import { createComplaint, getComplaints, getComplaintSummary, getWeComOptions, updateComplaint } from "@/api";
const today = () => new Date().toLocaleDateString("sv-SE");
const rows = ref([]),
  visible = ref(false),
  creating = ref(false),
  dateRange = ref([today(), today()]),
  options = reactive({ customers: [], clerks: [] }),
  summary = reactive({ complaint_count: 0, order_count: 0, complaint_rate: 0 }),
  filters = reactive({ status: null, severity: null }),
  form = reactive({});
const categories = ["食品安全", "质量问题", "少送漏送", "配送问题", "价格问题", "服务问题", "其他"];
const urgentRows = computed(() =>
  rows.value.filter(
    (r) => r.severity === "P0" && !["resolved", "closed"].includes(r.status),
  ),
);
const statuses = [
  { value: "new", label: "新投诉" },
  { value: "processing", label: "处理中" },
  { value: "waiting_customer", label: "等待客户" },
  { value: "resolved", label: "已解决" },
  { value: "closed", label: "已关闭" },
];
const statusLabel = (v) => statuses.find((i) => i.value === v)?.label || v,
  time = (v) =>
    v ? new Date(v).toLocaleString("zh-CN", { hour12: false }) : "—";
const load = async () => {
  const dateParams = { date_from: dateRange.value?.[0], date_to: dateRange.value?.[1] };
  const [complaints, metrics] = await Promise.all([
    getComplaints({ ...dateParams, status: filters.status || undefined, severity: filters.severity || undefined }),
    getComplaintSummary(dateParams),
  ]);
  rows.value = complaints;
  Object.assign(summary, metrics);
};
const resetFilters = async () => { dateRange.value = [today(), today()]; filters.status = null; filters.severity = null; await load(); };
const openCreate = () => {
  creating.value = true;
  Object.keys(form).forEach(key => delete form[key]);
  Object.assign(form, { customer_id: null, assigned_to: null, category: "其他", severity: "P2", content: "" });
  visible.value = true;
};
const open = (row) => {
  creating.value = false;
  Object.assign(form, row);
  visible.value = true;
};
const save = async () => {
  if (creating.value) {
    if (!form.customer_id) return ElMessage.warning("请选择投诉客户");
    if (!form.content?.trim()) return ElMessage.warning("请填写投诉内容");
    await createComplaint({ customer_id: form.customer_id, assigned_to: form.assigned_to, category: form.category, severity: form.severity, content: form.content.trim() });
    ElMessage.success("投诉已登记");
  } else {
  await updateComplaint(form.id, {
    status: form.status,
    assigned_to: form.assigned_to,
    resolution: form.resolution || null,
  });
  ElMessage.success("投诉处理信息已保存");
  }
  visible.value = false;
  await load();
  window.dispatchEvent(new CustomEvent("attention-updated"));
};
onMounted(async () => {
  Object.assign(options, await getWeComOptions());
  await load();
});
</script>

<style scoped>
.urgent-alert {
  margin-bottom: 16px;
}
.metrics {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 14px;
  margin-bottom: 16px;
}
.metrics span,
.metrics b {
  display: block;
}
.metrics span {
  color: #7e8999;
}
.metrics b {
  font-size: 25px;
  margin-top: 7px;
}
.warning {
  color: #db7b2b;
}
.danger {
  color: #d9534f;
  font-weight: 600;
}
.toolbar {
  display: flex;
  gap: 12px;
  margin-bottom: 14px;
}
.header-actions { display:flex; gap:10px; }
@media (max-width: 1200px) { .metrics { grid-template-columns: repeat(3, 1fr); } }
.panel :deep(.overdue-row td) {
  background: #fff2f1 !important;
}
.panel :deep(.urgent-row td) {
  background: #ffe4e4 !important;
}
.panel :deep(.urgent-row:hover td) {
  background: #ffd5d5 !important;
}
</style>
