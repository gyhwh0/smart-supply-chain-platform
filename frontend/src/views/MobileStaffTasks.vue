<template>
  <main class="mobile-page">
    <header class="topbar">
      <div class="brand"><span>嘉</span><div><b>我的作业任务</b><small>分拣与配送移动工作台</small></div></div>
      <el-button circle :loading="loading" aria-label="刷新任务" @click="load"><el-icon><Refresh /></el-icon></el-button>
    </header>

    <el-result v-if="error" icon="error" title="入口无法使用" :sub-title="error">
      <template #extra><p class="help">请联系管理员在“业务人员管理”中重新生成手机入口。</p></template>
    </el-result>

    <section v-else-if="entry && !authenticated" class="login-card">
      <div class="login-icon">{{entry.staff_type==='sorter'?'分拣':'配送'}}</div>
      <h1>{{entry.name}}，请验证身份</h1>
      <p>{{entry.staff_type==='sorter'?'分拣员':'配送员'}}专属入口 · 验证后7天内免登录</p>
      <el-alert v-if="!entry.pin_configured" title="管理员尚未设置工作密码，请联系管理员后再试。" type="warning" :closable="false" show-icon />
      <el-input v-model="pin" type="password" show-password maxlength="6" inputmode="numeric" placeholder="请输入6位工作密码" size="large" @keyup.enter="login" />
      <el-button type="primary" size="large" :disabled="!entry.pin_configured||!/^\d{6}$/.test(pin)" :loading="loggingIn" @click="login">进入我的任务</el-button>
      <small>连续输错5次将锁定15分钟，请勿将密码告诉他人。</small>
    </section>

    <template v-else-if="data.staff">
      <section class="welcome">
        <div><small>{{ dateText }}</small><h1>{{ data.staff.name }}，辛苦了</h1><p>{{ roleText }} · 页面每 30 秒自动更新</p></div>
        <div class="role-badge">{{ data.staff.staff_type === 'sorter' ? '分拣' : '配送' }}</div>
      </section>

      <nav class="scope-tabs">
        <button v-for="item in scopes" :key="item.value" :class="{active:scope===item.value}" @click="changeScope(item.value)">{{item.label}}</button>
      </nav>

      <section class="summary">
        <div><b>{{data.task_count}}</b><span>客户任务</span></div>
        <div><b>{{data.completed_items}} / {{data.total_items}}</b><span>{{data.staff.staff_type==='sorter'?'已分拣':'已装车'}}</span></div>
        <div><b>{{ progress }}%</b><span>完成进度</span></div>
      </section>

      <el-alert
        title="推荐用微信扫一扫扫描商品标签完成确认；标签破损或无法扫码时，再使用商品旁的“手工确认”。"
        type="info"
        :closable="false"
        show-icon
        class="scan-tip"
      />

      <el-empty v-if="!data.tasks.length" :description="emptyText">
        <el-button type="primary" plain @click="load">刷新任务</el-button>
      </el-empty>

      <section v-for="task in data.tasks" :key="task.id" class="task-card">
        <div class="task-head">
          <div><small>{{task.delivery_date}} 配送</small><h2>{{task.customer_name}}</h2><p>{{task.customer_code||'无客户编号'}} · {{task.sales_order_no}}</p></div>
          <el-tag :type="statusType(task.status)" effect="light">{{statusLabels[task.status]||task.status}}</el-tag>
        </div>
        <div class="task-meta">
          <span>{{data.staff.staff_type==='sorter'?'配送员':'分拣员'}}</span>
          <b>{{data.staff.staff_type==='sorter'?task.delivery_name:task.sorter_name}}</b>
          <span>任务号</span><b>{{task.task_no}}</b>
        </div>
        <div class="task-progress">
          <span>完成 {{taskDone(task)}} / {{task.total_count}}</span>
          <el-progress :percentage="taskPercent(task)" :show-text="false" :stroke-width="9" />
        </div>

        <div class="items">
          <article v-for="item in task.items" :key="item.id">
            <div class="item-state" :class="stateClass(item)">{{stateMark(item)}}</div>
            <div class="item-info"><b>{{item.product_name}}</b><span>{{number(item.quantity)}} {{item.unit_name}}</span><em v-if="item.exception_note">异常：{{item.exception_note}}</em></div>
            <div class="item-action">
              <span>{{stateText(item)}}</span>
              <el-button v-if="canConfirm(item)" link type="primary" :loading="savingId===item.id" @click="manualConfirm(item)">手工确认</el-button>
              <el-button link type="danger" :disabled="savingId===item.id" @click="openException(item)">报异常</el-button>
            </div>
          </article>
        </div>
      </section>
    </template>

    <div v-else class="loading"><el-icon class="is-loading" size="34"><Loading /></el-icon><p>正在读取你的任务…</p></div>

    <el-dialog v-model="exceptionVisible" title="报告商品异常" width="92%" class="exception-dialog">
      <p class="exception-product">{{exceptionItem?.product_name}}</p>
      <el-input v-model="exceptionNote" type="textarea" :rows="4" placeholder="例如：少2斤、包装破损、暂时缺货" maxlength="255" show-word-limit />
      <template #footer><el-button @click="exceptionVisible=false">取消</el-button><el-button type="danger" :disabled="!exceptionNote.trim()" :loading="savingId===exceptionItem?.id" @click="submitException">提交异常</el-button></template>
    </el-dialog>
  </main>
</template>

<script setup>
import { computed,onBeforeUnmount,onMounted,reactive,ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage,ElMessageBox } from 'element-plus'
import { confirmPublicStaffTaskItem,getPublicStaffEntry,getPublicStaffTasks,loginPublicStaff } from '@/api'
import { clearStaffSession,getStaffToken,setStaffSession } from '@/utils/staffAuth'

const route=useRoute()
const token=computed(()=>String(route.query.token||''))
const data=reactive({staff:null,task_count:0,total_items:0,completed_items:0,tasks:[]})
const loading=ref(false),error=ref(''),scope=ref('today'),savingId=ref(null),entry=ref(null),authenticated=ref(false),pin=ref(''),loggingIn=ref(false)
const exceptionVisible=ref(false),exceptionItem=ref(null),exceptionNote=ref('')
const scopes=[{label:'今天',value:'today'},{label:'明天',value:'tomorrow'},{label:'全部未完成',value:'unfinished'}]
const statusLabels={pending:'待开始',picking:'分拣中',picked:'已分拣',delivering:'装车中',completed:'已完成'}
const dateText=new Intl.DateTimeFormat('zh-CN',{month:'long',day:'numeric',weekday:'long'}).format(new Date())
const roleText=computed(()=>data.staff?.staff_type==='sorter'?'分拣员':'配送员')
const progress=computed(()=>data.total_items?Math.round(data.completed_items/data.total_items*100):0)
const emptyText=computed(()=>scope.value==='today'?'今天暂时没有分配给你的任务':scope.value==='tomorrow'?'明天暂时没有分配给你的任务':'太棒了，当前没有未完成任务')
const number=v=>Number(v).toLocaleString('zh-CN',{maximumFractionDigits:4})
const statusType=s=>s==='completed'?'success':s==='picking'||s==='delivering'?'warning':s==='picked'?'primary':'info'
const isSorter=()=>data.staff?.staff_type==='sorter'
const taskDone=task=>isSorter()?task.picked_count:task.loaded_count
const taskPercent=task=>task.total_count?Math.round(taskDone(task)/task.total_count*100):0
const isDone=item=>isSorter()?Boolean(item.picked_at):Boolean(item.loaded_at)
const stateClass=item=>item.loaded_at?'done':item.picked_at?'picked':''
const stateMark=item=>item.loaded_at?'✓':item.picked_at?'拣':'待'
const stateText=item=>item.loaded_at?'已装车':item.picked_at?'已分拣':'待分拣'
const canConfirm=item=>!isDone(item)&&(isSorter()||Boolean(item.picked_at))

const load=async()=>{
  if(!getStaffToken()){authenticated.value=false;return}
  loading.value=true
  try{Object.assign(data,await getPublicStaffTasks(getStaffToken(),{scope:scope.value}));authenticated.value=true;error.value=''}
  catch(e){if(e?.response?.status===401){clearStaffSession();localStorage.removeItem('jiacai_staff_entry');authenticated.value=false}else error.value=e?.response?.data?.detail||'任务读取失败，请稍后重试'}
  finally{loading.value=false}
}
const initialize=async()=>{if(!token.value){error.value='链接中缺少人员通行信息';return}try{entry.value=await getPublicStaffEntry(token.value);if(localStorage.getItem('jiacai_staff_entry')===token.value&&getStaffToken())await load()}catch(e){error.value=e?.response?.data?.detail||'入口已失效，请联系管理员重新获取'}}
const login=async()=>{if(!/^\d{6}$/.test(pin.value))return ElMessage.warning('请输入6位数字工作密码');loggingIn.value=true;try{const result=await loginPublicStaff(token.value,pin.value);setStaffSession(result.staff_token,result.staff);localStorage.setItem('jiacai_staff_entry',token.value);authenticated.value=true;pin.value='';await load()}finally{loggingIn.value=false}}
const changeScope=value=>{scope.value=value;load()}
const manualConfirm=async item=>{
  const action=isSorter()?'分拣':'装车'
  await ElMessageBox.confirm(`确认“${item.product_name}”已经完成${action}吗？手工确认仅用于无法扫码的情况。`,`确认已${action}`,{type:'warning',confirmButtonText:'确认完成'})
  savingId.value=item.id
  try{await confirmPublicStaffTaskItem(getStaffToken(),item.id,{stage:isSorter()?'picked':'loaded',note:null});ElMessage.success(`${action}确认成功`);await load()}
  finally{savingId.value=null}
}
const openException=item=>{exceptionItem.value=item;exceptionNote.value='';exceptionVisible.value=true}
const submitException=async()=>{
  savingId.value=exceptionItem.value.id
  try{await confirmPublicStaffTaskItem(getStaffToken(),exceptionItem.value.id,{stage:'exception',note:exceptionNote.value});exceptionVisible.value=false;ElMessage.success('异常已记录，管理端可立即看到');await load()}
  finally{savingId.value=null}
}
let timer
onMounted(()=>{initialize();timer=window.setInterval(()=>{if(authenticated.value&&document.visibilityState==='visible'&&!loading.value)load()},10000)})
onBeforeUnmount(()=>window.clearInterval(timer))
</script>

<style scoped>
.mobile-page{min-height:100vh;background:#f1f5f7;padding:14px 12px 38px;color:#1f3046;max-width:720px;margin:auto}.topbar{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px}.brand{display:flex;align-items:center;gap:10px}.brand>span{width:40px;height:40px;border-radius:11px;background:#176c64;color:#fff;display:grid;place-items:center;font-size:22px;font-weight:800}.brand b,.brand small{display:block}.brand small{color:#8490a3;margin-top:2px}.login-card{background:#fff;border-radius:16px;padding:28px 20px;text-align:center;box-shadow:0 4px 20px #22384b10}.login-icon{width:68px;height:68px;border-radius:50%;background:#e4f4f1;color:#176c64;display:grid;place-items:center;margin:auto;font-size:18px;font-weight:800}.login-card h1{margin:16px 0 7px}.login-card p{color:#748195;margin:0 0 18px}.login-card .el-alert{margin-bottom:14px;text-align:left}.login-card>.el-button{width:100%;margin:12px 0}.login-card>small{color:#8995a5}.welcome,.summary,.task-card{background:#fff;border-radius:15px;box-shadow:0 2px 12px #22384b0c}.welcome{padding:18px;display:flex;justify-content:space-between;align-items:center;background:linear-gradient(135deg,#176c64,#23998c);color:#fff}.welcome small{opacity:.82}.welcome h1{font-size:23px;margin:7px 0}.welcome p{margin:0;opacity:.82}.role-badge{border:1px solid #ffffff70;background:#ffffff1e;border-radius:12px;padding:10px;font-weight:800}.scope-tabs{display:grid;grid-template-columns:repeat(3,1fr);gap:7px;background:#fff;padding:6px;border-radius:13px;margin:12px 0}.scope-tabs button{border:0;background:transparent;border-radius:9px;padding:10px 3px;color:#637188;font-size:14px}.scope-tabs button.active{background:#e7f5f2;color:#176c64;font-weight:800}.summary{display:grid;grid-template-columns:repeat(3,1fr);padding:15px 6px;margin-bottom:12px}.summary div{text-align:center;border-right:1px solid #edf0f3}.summary div:last-child{border:0}.summary b,.summary span{display:block}.summary b{font-size:20px;color:#176c64}.summary span{font-size:12px;color:#8290a3;margin-top:5px}.scan-tip{margin-bottom:12px}.task-card{padding:16px;margin-bottom:13px}.task-head{display:flex;justify-content:space-between;align-items:flex-start;gap:8px}.task-head small{color:#176c64;font-weight:700}.task-head h2{font-size:21px;margin:5px 0}.task-head p{margin:0;color:#748195;font-size:13px}.task-meta{display:grid;grid-template-columns:62px 1fr;gap:6px 8px;margin:14px 0;padding:11px;background:#f6f8fa;border-radius:10px;font-size:13px}.task-meta span{color:#8894a5}.task-meta b{text-align:right;overflow-wrap:anywhere}.task-progress{display:grid;grid-template-columns:88px 1fr;align-items:center;gap:8px;color:#607087;font-size:13px;margin-bottom:4px}.items article{display:flex;align-items:center;gap:10px;padding:13px 0;border-top:1px solid #edf0f3}.items article:first-child{margin-top:10px}.item-state{width:34px;height:34px;border-radius:50%;background:#e8edf2;display:grid;place-items:center;font-size:12px;font-weight:800;flex:none}.item-state.picked{background:#fff0d8;color:#b86811}.item-state.done{background:#dff6eb;color:#16855f}.item-info{flex:1;min-width:0}.item-info b,.item-info span,.item-info em{display:block}.item-info b{overflow-wrap:anywhere}.item-info span{color:#667489;margin-top:4px}.item-info em{color:#dc4148;font-size:12px;margin-top:4px}.item-action{text-align:right;flex:none;display:flex;flex-direction:column;align-items:flex-end}.item-action>span{font-size:12px;color:#7b8798;margin-bottom:2px}.item-action .el-button{margin:0;height:25px}.loading{text-align:center;padding-top:28vh;color:#708095}.help{color:#7b8798}.exception-product{font-size:17px;font-weight:700;margin-top:0}
@media (max-width:380px){.task-card{padding:13px}.item-action .el-button{font-size:12px;padding:0 3px}.welcome h1{font-size:20px}}
</style>
