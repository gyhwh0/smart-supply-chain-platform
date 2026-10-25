<template>
  <main class="mobile">
    <div class="brand"><div class="mark">嘉</div><div><b>扫码分拣</b><small>商品核对与装车确认</small></div></div>
    <el-result v-if="needsLogin" icon="warning" title="请先验证人员身份" sub-title="请先打开管理员发给你的个人任务入口，输入6位工作密码后，再扫描商品标签。"><template #extra><el-button type="primary" @click="$router.back()">返回上一页</el-button></template></el-result>
    <el-result v-else-if="error" icon="error" title="标签无法识别" :sub-title="error" />
    <template v-else-if="task">
      <section class="customer-card"><div><small>当前客户</small><h1>{{task.customer_name}}</h1><p>{{task.customer_code||'无客户编号'}} · 配送 {{task.delivery_date||'未设置'}}</p></div><el-tag :type="statusType(task.status)" size="large">{{statusLabels[task.status]}}</el-tag></section>
      <section class="people"><div><small>分拣员</small><b>{{task.sorter_name}}</b></div><div><small>配送员</small><b>{{task.delivery_name}}</b></div></section>
      <section class="progress"><div><span>已分拣 {{task.picked_count}} / {{task.total_count}}</span><span>已装车 {{task.loaded_count}} / {{task.total_count}}</span></div><el-progress :percentage="task.total_count?Math.round(task.picked_count/task.total_count*100):0" :stroke-width="12" /></section>
      <section v-if="current" class="current">
        <div class="scan-title">本次扫码商品</div><h2>{{current.product_name}}</h2><div class="qty">{{number(current.quantity)}} {{current.unit_name}}</div>
        <el-alert v-if="current.exception_note" :title="`异常：${current.exception_note}`" type="error" :closable="false" />
        <el-button v-if="profile.staff_type==='sorter'&&!current.picked_at" type="primary" size="large" :loading="saving" @click="submit('picked')">确认已分拣</el-button>
        <el-button v-else-if="profile.staff_type==='delivery'&&!current.picked_at" size="large" disabled>等待分拣员确认</el-button>
        <el-button v-else-if="profile.staff_type==='delivery'&&!current.loaded_at" type="success" size="large" :loading="saving" @click="submit('loaded')">确认已装车 / 交接</el-button>
        <el-button v-else type="success" size="large" disabled>{{profile.staff_type==='sorter'?'该商品已完成分拣':'该商品已完成装车'}}</el-button>
        <el-button link type="danger" @click="exceptionVisible=true">数量不符、破损或缺货？报告异常</el-button>
      </section>
      <section class="list"><h3>该客户全部商品</h3><article v-for="item in task.items" :key="item.id" :class="{active:item.is_current}"><div class="state" :class="item.loaded_at?'done':item.picked_at?'picked':''">{{item.loaded_at?'✓':item.picked_at?'拣':'待'}}</div><div class="info"><b>{{item.product_name}}</b><span>{{number(item.quantity)}} {{item.unit_name}}</span><em v-if="item.exception_note">异常：{{item.exception_note}}</em></div><div class="state-text">{{item.loaded_at?'已装车':item.picked_at?'已分拣':'待分拣'}}</div></article></section>
    </template>
    <div v-else class="loading"><el-icon class="is-loading" size="34"><Loading /></el-icon><p>正在读取分拣标签…</p></div>

    <el-dialog v-model="exceptionVisible" title="报告商品异常" width="90%"><el-input v-model="exceptionNote" type="textarea" :rows="4" placeholder="例如：少2斤、包装破损、暂时缺货" maxlength="255" show-word-limit/><template #footer><el-button @click="exceptionVisible=false">取消</el-button><el-button type="danger" :disabled="!exceptionNote.trim()" :loading="saving" @click="submit('exception')">提交异常</el-button></template></el-dialog>
  </main>
</template>

<script setup>
import { computed,onMounted,ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { confirmPublicPicking,getPublicPicking } from '@/api'
import { clearStaffSession,getStaffProfile,getStaffToken } from '@/utils/staffAuth'
const route=useRoute(),task=ref(null),error=ref(''),saving=ref(false),exceptionVisible=ref(false),exceptionNote=ref(''),needsLogin=ref(false)
const profile=getStaffProfile()||{}
const code=computed(()=>String(route.query.code||'')),current=computed(()=>task.value?.items.find(item=>item.is_current))
const statusLabels={pending:'待开始',picking:'分拣中',picked:'已分拣',delivering:'装车中',completed:'已完成'}
const statusType=s=>s==='completed'?'success':s==='picking'||s==='delivering'?'warning':s==='picked'?'primary':'info'
const number=v=>Number(v).toLocaleString('zh-CN',{maximumFractionDigits:4})
const load=async()=>{if(!getStaffToken()||!profile.staff_type){needsLogin.value=true;return}if(!code.value){error.value='二维码中缺少分拣码';return}try{task.value=await getPublicPicking(code.value)}catch(e){error.value=e?.response?.data?.detail||'二维码已失效，请联系管理员重新打印'}}
const submit=async stage=>{saving.value=true;try{task.value=await confirmPublicPicking(code.value,{stage,note:stage==='exception'?exceptionNote.value:null},getStaffToken());exceptionVisible.value=false;exceptionNote.value='';ElMessage.success(stage==='picked'?'分拣确认成功':stage==='loaded'?'装车确认成功':'异常已记录')}catch(e){if(e?.response?.status===401){clearStaffSession();needsLogin.value=true}}finally{saving.value=false}}
onMounted(load)
</script>

<style scoped>
.mobile{min-height:100vh;background:#f1f5f7;padding:16px 14px 36px;color:#1f3046;max-width:680px;margin:auto}.brand{display:flex;align-items:center;gap:10px;margin-bottom:14px}.brand .mark{width:38px;height:38px;border-radius:10px;background:#176c64;color:white;display:grid;place-items:center;font-size:21px;font-weight:800}.brand b,.brand small{display:block}.brand small{color:#8490a3;margin-top:2px}.customer-card,.people,.progress,.current,.list{background:white;border-radius:14px;padding:16px;margin-bottom:12px;box-shadow:0 2px 10px #22384b0c}.customer-card{display:flex;justify-content:space-between;align-items:center}.customer-card small,.people small{color:#8490a3}.customer-card h1{font-size:23px;margin:5px 0}.customer-card p{margin:0;color:#68768a}.people{display:grid;grid-template-columns:1fr 1fr;gap:14px}.people div{background:#f5f8fa;border-radius:10px;padding:12px}.people b,.people small{display:block}.people b{margin-top:5px}.progress>div{display:flex;justify-content:space-between;margin-bottom:10px}.current{border:2px solid #1c8f83;text-align:center}.scan-title{color:#1c8f83;font-weight:700}.current h2{font-size:25px;margin:13px 0 6px}.qty{font-size:22px;font-weight:800;color:#e66b28;margin-bottom:15px}.current>.el-button{width:100%;margin:7px 0 0}.list h3{margin:0 0 12px}.list article{display:flex;align-items:center;gap:11px;padding:12px 4px;border-top:1px solid #edf0f4}.list article.active{background:#effaf8;margin:0 -8px;padding:12px;border-radius:8px}.state{width:34px;height:34px;border-radius:50%;background:#e8edf2;display:grid;place-items:center;font-size:12px;font-weight:700;flex:none}.state.picked{background:#fff0d8;color:#b86811}.state.done{background:#dff6eb;color:#16855f}.info{flex:1}.info b,.info span,.info em{display:block}.info span{color:#667489;margin-top:4px}.info em{color:#dc4148;font-size:12px;margin-top:4px}.state-text{font-size:12px;color:#7b8798}.loading{text-align:center;padding-top:28vh;color:#708095}
</style>
