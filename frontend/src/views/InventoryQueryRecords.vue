<template>
  <div>
    <div class="page-header">
      <div><h2>查询记录管理</h2><p>隐藏管理入口：查看库存搜索和智能比价 AI 提问</p></div>
      <el-button @click="router.push(activeTab === 'inventory' ? '/inventory' : '/analysis')">返回对应业务页面</el-button>
    </div>
    <el-tabs v-model="activeTab" class="record-tabs" @tab-change="load">
      <el-tab-pane label="库存查询记录" name="inventory" />
      <el-tab-pane label="AI 比价提问记录" name="ai" />
    </el-tabs>

    <template v-if="activeTab === 'inventory'">
      <el-row :gutter="14" class="metrics">
        <el-col :span="8"><el-card class="panel metric"><span>筛选结果</span><strong>{{ records.length }}</strong></el-card></el-col>
        <el-col :span="8"><el-card class="panel metric"><span>旧系统记录</span><strong>{{ records.filter(r => r.source === 'legacy').length }}</strong></el-card></el-col>
        <el-col :span="8"><el-card class="panel metric"><span>新系统记录</span><strong>{{ records.filter(r => r.source === 'new').length }}</strong></el-card></el-col>
      </el-row>
      <el-card class="panel">
        <div class="toolbar">
          <el-input v-model="keyword" clearable placeholder="搜索内容、关键词、账号或查询类型" style="width:380px" @keyup.enter="load" />
          <el-select v-model="source" style="width:170px" @change="load"><el-option label="全部记录" value="all" /><el-option label="新系统记录" value="new" /><el-option label="旧系统记录" value="legacy" /></el-select>
          <el-button type="primary" @click="load">筛选</el-button><el-button @click="reset">重置</el-button><span class="hint">最多显示最近 1000 条</span>
        </div>
        <el-table :data="paged" v-loading="loading" stripe>
          <el-table-column label="查询时间" width="180"><template #default="s">{{ formatTime(s.row.created_at) }}</template></el-table-column>
          <el-table-column label="来源" width="105"><template #default="s"><el-tag :type="s.row.source === 'new' ? 'success' : 'info'">{{ s.row.source === 'new' ? '新系统' : '旧系统' }}</el-tag></template></el-table-column>
          <el-table-column label="查询人员" width="155"><template #default="s"><div>{{ s.row.user_name || '未知' }}</div><small>{{ s.row.username || '-' }}</small></template></el-table-column>
          <el-table-column prop="question" label="搜索内容" min-width="240" show-overflow-tooltip /><el-table-column prop="query_type" label="查询类型" width="120" /><el-table-column prop="keyword" label="识别关键词" min-width="150" show-overflow-tooltip /><el-table-column prop="result_count" label="结果数" width="90" align="center" />
        </el-table>
        <div class="pagination"><el-pagination v-model:current-page="page" :page-size="pageSize" :total="records.length" layout="total, prev, pager, next" /></div>
      </el-card>
    </template>

    <template v-else>
      <el-row :gutter="14" class="metrics">
        <el-col :span="8"><el-card class="panel metric"><span>AI 提问总数</span><strong>{{ aiRecords.length }}</strong></el-card></el-col>
        <el-col :span="8"><el-card class="panel metric"><span>调用成功</span><strong class="success">{{ aiRecords.filter(r => r.status === 'success').length }}</strong></el-card></el-col>
        <el-col :span="8"><el-card class="panel metric"><span>失败或拒绝</span><strong class="danger">{{ aiRecords.filter(r => ['failed','rejected'].includes(r.status)).length }}</strong></el-card></el-col>
      </el-row>
      <el-card class="panel">
        <div class="toolbar">
          <el-input v-model="keyword" clearable placeholder="搜索 AI 问题、账号、姓名或模型" style="width:380px" @keyup.enter="load" />
          <el-select v-model="aiStatus" style="width:150px" @change="load"><el-option label="全部状态" value="all" /><el-option label="成功" value="success" /><el-option label="失败" value="failed" /><el-option label="无报价拒绝" value="rejected" /><el-option label="本地结果" value="fallback" /></el-select>
          <el-button type="primary" @click="load">筛选</el-button><el-button @click="reset">重置</el-button><span class="hint">从本功能上线后开始记录</span>
        </div>
        <el-table :data="aiPaged" v-loading="loading" stripe>
          <el-table-column label="提问时间" width="180"><template #default="s">{{ formatTime(s.row.created_at) }}</template></el-table-column>
          <el-table-column label="提问人员" width="170"><template #default="s"><div>{{ s.row.user_name || '未知' }}</div><small>{{ s.row.username || '-' }}</small></template></el-table-column>
          <el-table-column prop="question" label="向 AI 提出的问题" min-width="400" show-overflow-tooltip />
          <el-table-column prop="model_name" label="调用模型" width="170" />
          <el-table-column label="状态" width="105"><template #default="s"><el-tag :type="statusType(s.row.status)">{{ statusLabel(s.row.status) }}</el-tag></template></el-table-column>
        </el-table>
        <div class="pagination"><el-pagination v-model:current-page="page" :page-size="pageSize" :total="aiRecords.length" layout="total, prev, pager, next" /></div>
      </el-card>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getAIAnalysisQueryRecords, getInventoryQueryRecords } from '@/api'
const router=useRouter(),activeTab=ref('inventory'),records=ref([]),aiRecords=ref([]),keyword=ref(''),source=ref('all'),aiStatus=ref('all'),page=ref(1),loading=ref(false),pageSize=20
const paged=computed(()=>records.value.slice((page.value-1)*pageSize,page.value*pageSize));const aiPaged=computed(()=>aiRecords.value.slice((page.value-1)*pageSize,page.value*pageSize))
const formatTime=value=>value?new Date(value).toLocaleString('zh-CN',{hour12:false}):'-';const statusLabel=value=>({success:'成功',failed:'失败',rejected:'无报价',fallback:'本地结果',pending:'处理中'}[value]||value);const statusType=value=>value==='success'?'success':value==='pending'?'warning':['failed','rejected'].includes(value)?'danger':'info'
const load=async()=>{loading.value=true;try{if(activeTab.value==='inventory'){const result=await getInventoryQueryRecords({admin:'yes',keyword:keyword.value,source:source.value});records.value=result.records}else{const result=await getAIAnalysisQueryRecords({admin:'yes',keyword:keyword.value,status:aiStatus.value});aiRecords.value=result.records}page.value=1}catch(error){ElMessage.error(error?.response?.data?.detail||'查询记录加载失败')}finally{loading.value=false}}
const reset=()=>{keyword.value='';source.value='all';aiStatus.value='all';load()};onMounted(load)
</script>

<style scoped>
.record-tabs{margin-bottom:16px}.metrics{margin-bottom:16px}.metric :deep(.el-card__body){display:flex;justify-content:space-between;align-items:center}.metric span{color:#8490a3}.metric strong{font-size:28px;color:#347bd2}.metric strong.success{color:#24946b}.metric strong.danger{color:#d95c5c}.toolbar{display:flex;align-items:center;gap:10px;margin-bottom:16px}.hint{margin-left:auto;color:#8b93a5;font-size:13px}.pagination{display:flex;justify-content:flex-end;margin-top:18px}small{color:#8b93a5}
</style>
