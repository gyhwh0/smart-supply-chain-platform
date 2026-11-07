<template>
  <div>
    <div class="page-header"><div><h2>删除审核</h2><p>所有删除操作先进入审核，批准前原数据和业务联动均保持不变</p></div></div>
    <el-card class="panel">
      <div class="toolbar"><el-radio-group v-model="status" @change="load"><el-radio-button value="pending">待审核</el-radio-button><el-radio-button value="approved">已批准</el-radio-button><el-radio-button value="rejected">已驳回</el-radio-button><el-radio-button value="all">全部</el-radio-button></el-radio-group><el-button @click="load">刷新</el-button></div>
      <el-alert v-if="status==='pending'" title="批准后才会执行删除；存在历史单据的数据仍会按业务规则安全禁用，不能破坏历史凭证。" type="warning" :closable="false" show-icon class="notice"/>
      <el-table :data="rows" empty-text="暂无删除申请">
        <el-table-column prop="entity_type_name" label="模块" width="145"/>
        <el-table-column prop="entity_label" label="申请删除对象" min-width="220"/>
        <el-table-column prop="requester_name" label="申请人" width="120"/>
        <el-table-column label="申请时间" width="175"><template #default="scope">{{timeText(scope.row.created_at)}}</template></el-table-column>
        <el-table-column label="状态" width="100"><template #default="scope"><el-tag :type="statusType(scope.row.status)">{{statusText(scope.row.status)}}</el-tag></template></el-table-column>
        <el-table-column prop="reviewer_name" label="审核人" width="110"/>
        <el-table-column prop="execution_result" label="处理结果" min-width="220" show-overflow-tooltip/>
        <el-table-column v-if="status==='pending'" label="操作" width="150" fixed="right"><template #default="scope"><el-button link type="danger" @click="approve(scope.row)">批准删除</el-button><el-button link @click="reject(scope.row)">驳回</el-button></template></el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { approveDeletionRequest, getDeletionRequests, rejectDeletionRequest } from '@/api'

const rows=ref([]);const status=ref('pending')
const load=async()=>{rows.value=await getDeletionRequests(status.value==='all'?{}:{status:status.value})}
const timeText=value=>value?new Date(value).toLocaleString('zh-CN',{hour12:false}):'—'
const statusText=value=>({pending:'待审核',approved:'已批准',rejected:'已驳回'}[value]||value)
const statusType=value=>({pending:'warning',approved:'success',rejected:'info'}[value]||'info')
const approve=async row=>{await ElMessageBox.confirm(`批准删除“${row.entity_label}”后将立即执行且不可撤销，是否继续？`,'批准删除',{type:'warning',confirmButtonText:'批准并执行',cancelButtonText:'取消'});const result=await approveDeletionRequest(row.id,null);ElMessage.success(result.message);load()}
const reject=async row=>{const {value}=await ElMessageBox.prompt(`请输入驳回“${row.entity_label}”的原因`,'驳回删除申请',{inputPlaceholder:'例如：该数据仍在使用',inputValidator:value=>Boolean(value.trim())||'请填写驳回原因'});const result=await rejectDeletionRequest(row.id,value);ElMessage.success(result.message);load()}
onMounted(load)
</script>

<style scoped>.toolbar{display:flex;justify-content:space-between;gap:12px;margin-bottom:14px}.notice{margin-bottom:14px}@media(max-width:700px){.toolbar{align-items:flex-start;flex-direction:column}}</style>
