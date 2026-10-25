<template>
  <div>
    <div class="page-header">
      <div>
        <h2>投诉专栏</h2>
        <p>集中处理微信自动识别和人工登记的客户投诉，食品安全问题优先升级</p>
      </div>
      <el-button type="primary" @click="load">刷新</el-button>
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
        ><span>全部投诉</span><b>{{ rows.length }}</b></el-card
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
        /></el-select>
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
      :title="`处理投诉 · ${form.complaint_no}`"
      width="650px"
      ><el-descriptions :column="2" border
        ><el-descriptions-item label="客户">{{
          form.customer_name
        }}</el-descriptions-item
        ><el-descriptions-item label="分类"
          >{{ form.category }} / {{ form.severity }}</el-descriptions-item
        ><el-descriptions-item label="原始内容" :span="2">{{
          form.content
        }}</el-descriptions-item></el-descriptions
      ><el-form label-width="95px" style="margin-top: 18px"
        ><el-form-item label="处理人"
          ><el-select v-model="form.assigned_to" clearable style="width: 100%"
            ><el-option
              v-for="item in options.clerks"
              :key="item.id"
              :label="item.name"
              :value="item.id" /></el-select></el-form-item
        ><el-form-item label="处理状态"
          ><el-select v-model="form.status" style="width: 100%"
            ><el-option
              v-for="item in statuses"
              :key="item.value"
              :label="item.label"
              :value="item.value" /></el-select></el-form-item
        ><el-form-item label="处理结果"
          ><el-input
            v-model="form.resolution"
            type="textarea"
            :rows="5" /></el-form-item></el-form
      ><template #footer
        ><el-button @click="visible = false">取消</el-button
        ><el-button type="primary" @click="save"
          >保存处理结果</el-button
        ></template
      ></el-dialog
    >
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import { getComplaints, getWeComOptions, updateComplaint } from "@/api";
const rows = ref([]),
  visible = ref(false),
  options = reactive({ clerks: [] }),
  filters = reactive({ status: null, severity: null }),
  form = reactive({});
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
  rows.value = await getComplaints({
    status: filters.status || undefined,
    severity: filters.severity || undefined,
  });
};
const open = (row) => {
  Object.assign(form, row);
  visible.value = true;
};
const save = async () => {
  await updateComplaint(form.id, {
    status: form.status,
    assigned_to: form.assigned_to,
    resolution: form.resolution || null,
  });
  ElMessage.success("投诉处理信息已保存");
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
  grid-template-columns: repeat(4, 1fr);
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
