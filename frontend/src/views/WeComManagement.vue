<template>
  <div>
    <div class="page-header"><div><h2>企业微信订单助手</h2><p>管理微信客户绑定、AI订单草稿和消息处理状态</p></div><el-button type="primary" :loading="loading" @click="loadAll">刷新数据</el-button></div>

    <el-alert v-if="!status.configured" type="warning" :closable="false" show-icon title="企业微信参数尚未配置完整">
      <template #default>请在服务器 .env 中配置 WECOM_CORP_ID、WECOM_KF_SECRET、WECOM_CALLBACK_TOKEN 和 WECOM_ENCODING_AES_KEY，然后重启后端。回调地址：<b>{{ callbackUrl }}</b></template>
    </el-alert>
    <div class="metrics">
      <el-card><span>接入状态</span><b :class="status.configured?'ok':'warning'">{{ status.configured?'已配置':'待配置' }}</b></el-card>
      <el-card><span>客户绑定</span><b>{{ status.binding_count || 0 }}</b></el-card>
      <el-card><span>待处理消息</span><b class="warning">{{ status.pending_message_count || 0 }}</b></el-card>
      <el-card><span>待确认订单</span><b class="warning">{{ status.pending_draft_count || 0 }}</b></el-card>
    </div>

    <el-card class="panel">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="订单草稿" name="drafts">
          <el-table :data="drafts" stripe>
            <el-table-column type="expand"><template #default="s"><div class="draft-detail"><p><b>客户原话：</b>{{ s.row.raw_message }}</p><el-table :data="s.row.items" size="small" border><el-table-column prop="requested_name" label="客户说法"/><el-table-column prop="product_name" label="匹配商品"/><el-table-column prop="quantity" label="数量" width="90"/><el-table-column prop="unit_name" label="单位" width="90"/><el-table-column label="单价" width="110"><template #default="c">{{ c.row.unit_price==null?'待确认':`¥${money(c.row.unit_price)}` }}</template></el-table-column><el-table-column label="识别" width="100"><template #default="c"><el-tag :type="c.row.matched?'success':'warning'">{{c.row.matched?'已匹配':'待处理'}}</el-tag></template></el-table-column><el-table-column label="待处理原因" min-width="190"><template #default="c"><span v-if="c.row.matched" class="ok">可生成销售单</span><span v-else class="warning">{{itemIssue(c.row)}}</span></template></el-table-column></el-table></div></template></el-table-column>
            <el-table-column prop="customer_name" label="客户" min-width="150"/><el-table-column prop="assignee_name" label="订单员" width="120"/><el-table-column prop="delivery_date" label="配送日期" width="120"/><el-table-column label="识别可信度" width="120"><template #default="s">{{Math.round(s.row.confidence*100)}}%</template></el-table-column><el-table-column label="状态" width="145"><template #default="s"><el-tag :type="draftStatus(s.row.status).type">{{draftStatus(s.row.status).label}}</el-tag></template></el-table-column><el-table-column prop="created_at" label="接收时间" min-width="170"><template #default="s">{{time(s.row.created_at)}}</template></el-table-column><el-table-column label="操作" width="160" fixed="right"><template #default="s"><el-button v-if="s.row.status!=='confirmed'" link type="primary" :disabled="s.row.items.some(i=>!i.matched)" @click="confirmDraft(s.row)">确认生成销售单</el-button><el-button v-else link type="success" @click="$router.push('/sales-orders')">查看销售单</el-button></template></el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane :label="`微信消息${pendingMessageCount ? `（待处理 ${pendingMessageCount}）` : ''}`" name="messages">
          <div class="toolbar"><el-switch v-model="onlyPendingMessages" active-text="仅看未解决"/><span>处理完成后将从顶部提醒中自动移除</span></div>
          <el-table :data="visibleMessages" stripe><el-table-column prop="customer_name" label="客户" width="160"/><el-table-column prop="content" label="消息内容" min-width="300" show-overflow-tooltip/><el-table-column prop="intent" label="识别意图" width="120"/><el-table-column label="处理状态" width="140"><template #default="s"><el-tag :type="['failed','needs_review','needs_binding'].includes(s.row.status)?'warning':'success'">{{messageStatus(s.row.status)}}</el-tag></template></el-table-column><el-table-column prop="external_userid" label="微信客户ID" min-width="180"/><el-table-column label="消息时间" min-width="170"><template #default="s">{{time(s.row.occurred_at)}}</template></el-table-column><el-table-column label="操作" width="110" fixed="right"><template #default="s"><el-button v-if="['failed','needs_review','needs_binding'].includes(s.row.status)" link type="primary" @click="resolveMessage(s.row)">标记已处理</el-button><span v-else class="muted">—</span></template></el-table-column></el-table>
        </el-tab-pane>

        <el-tab-pane label="客户绑定" name="bindings">
          <div class="toolbar"><el-button type="primary" @click="bindingVisible=true">新增绑定</el-button><span>一个企业客户可以绑定多个微信联系人</span></div>
          <el-table :data="bindings"><el-table-column prop="customer_code" label="客户编号" width="120"/><el-table-column prop="customer_name" label="客户名称" min-width="140"/><el-table-column prop="display_name" label="微信称呼" min-width="130"><template #default="s"><b>{{s.row.display_name}}</b><small v-if="s.row.wechat_name&&s.row.wechat_name!==s.row.display_name" class="profile-name">微信昵称：{{s.row.wechat_name}}</small></template></el-table-column><el-table-column prop="external_userid" label="企业微信客户ID" min-width="210"/><el-table-column prop="open_kfid" label="微信客服账号ID" min-width="190"/><el-table-column label="验证状态" width="100"><template #default="s"><el-tag :type="s.row.verified?'success':'warning'">{{s.row.verified?'已验证':'待验证'}}</el-tag></template></el-table-column><el-table-column label="最近联系" min-width="165"><template #default="s">{{time(s.row.last_seen_at)}}</template></el-table-column><el-table-column label="操作" width="90"><template #default="s"><el-button link type="danger" @click="removeBinding(s.row)">解除</el-button></template></el-table-column></el-table>
        </el-tab-pane>

        <el-tab-pane label="接入测试" name="test">
          <el-alert type="info" :closable="false" title="这里用于企业微信正式接通前验证客户识别、订单解析和投诉分流，不会向真实微信发送消息。"/>
          <el-form label-width="120px" class="test-form"><el-form-item label="选择已绑定客户"><el-select v-model="test.external_userid" filterable style="width:420px"><el-option v-for="item in bindings" :key="item.id" :label="`${item.customer_name} · ${item.external_userid}`" :value="item.external_userid"/></el-select></el-form-item><el-form-item label="模拟客户消息"><el-input v-model="test.content" type="textarea" :rows="5" placeholder="例如：明天送土豆20斤，五花肉10斤"/></el-form-item><el-form-item><el-button type="primary" @click="runTest">发送模拟消息</el-button></el-form-item></el-form>
          <el-card v-if="testResult" shadow="never" class="test-result"><pre>{{testResult}}</pre></el-card>
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <el-dialog v-model="bindingVisible" title="绑定微信客户" width="560px"><el-form label-width="125px"><el-form-item label="系统客户" required><el-select v-model="binding.customer_id" filterable style="width:100%"><el-option v-for="item in options.customers" :key="item.id" :label="`${item.customer_code||'无编号'} · ${item.name}`" :value="item.id"/></el-select></el-form-item><el-form-item label="微信客户ID" required><el-input v-model="binding.external_userid" placeholder="external_userid"/></el-form-item><el-form-item label="微信客服账号ID"><el-input v-model="binding.open_kfid" placeholder="open_kfid，测试可填 test-kf"/></el-form-item><el-form-item label="客户称呼"><el-input v-model="binding.wechat_remark" placeholder="自动读取微信资料，也可填写王姐等称呼"/><small class="profile-help">优先使用该称呼；未填写时自动使用微信昵称、客户联系人或客户名称。</small></el-form-item><el-form-item label="已人工核验"><el-switch v-model="binding.verified"/></el-form-item></el-form><template #footer><el-button @click="bindingVisible=false">取消</el-button><el-button type="primary" @click="saveBinding">保存绑定</el-button></template></el-dialog>
  </div>
</template>

<script setup>
import { computed,onMounted,reactive,ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage,ElMessageBox } from 'element-plus'
import { confirmWeComOrderDraft,deleteWeComBinding,getWeComBindings,getWeComMessages,getWeComOptions,getWeComOrderDrafts,getWeComStatus,resolveWeComMessage,saveWeComBinding,simulateWeComMessage } from '@/api'
const route=useRoute()
const loading=ref(false),activeTab=ref(['drafts','messages','bindings','test'].includes(route.query.tab)?route.query.tab:'drafts'),bindingVisible=ref(false),testResult=ref('')
const onlyPendingMessages=ref(true)
const status=reactive({}),options=reactive({customers:[],clerks:[]}),drafts=ref([]),messages=ref([]),bindings=ref([])
const binding=reactive({customer_id:null,external_userid:'',open_kfid:'',wechat_remark:'',verified:true}),test=reactive({external_userid:'',content:'明天送土豆20斤，五花肉10斤',open_kfid:'test-kf'})
const callbackUrl=computed(()=>`${window.location.origin}/api/wecom/callback`)
const money=v=>Number(v||0).toFixed(2),time=v=>v?new Date(v).toLocaleString('zh-CN',{hour12:false}):'—'
const draftStatus=v=>({needs_review:{label:'需订单员处理',type:'warning'},awaiting_confirmation:{label:'等待客户确认',type:'primary'},confirmed:{label:'已生成销售单',type:'success'}}[v]||{label:v,type:'info'})
const messageStatus=v=>({needs_binding:'客户待绑定',needs_review:'待人工处理',failed:'自动识别失败',resolved:'已处理',processed:'已完成',awaiting_confirmation:'等待客户确认',confirmed:'已生成销售单'}[v]||v)
const itemIssue=item=>!item.product_name?'商品尚未匹配':!item.unit_name?'商品已匹配，但客户所需单位尚未配置':item.unit_price==null?'商品未填写参考价格':'需要人工核对'
const pendingStatuses=['failed','needs_review','needs_binding']
const pendingMessageCount=computed(()=>messages.value.filter(item=>pendingStatuses.includes(item.status)).length)
const visibleMessages=computed(()=>onlyPendingMessages.value?messages.value.filter(item=>pendingStatuses.includes(item.status)):messages.value)
const loadAll=async()=>{loading.value=true;try{const [a,b,c,d,e]=await Promise.all([getWeComStatus(),getWeComOptions(),getWeComBindings(),getWeComMessages(),getWeComOrderDrafts()]);Object.assign(status,a);Object.assign(options,b);bindings.value=c;messages.value=d;drafts.value=e}finally{loading.value=false}}
const saveBinding=async()=>{if(!binding.customer_id||!binding.external_userid.trim())return ElMessage.warning('请选择客户并填写微信客户ID');await saveWeComBinding({...binding,wechat_remark:binding.wechat_remark.trim()||null,open_kfid:binding.open_kfid.trim()||'test-kf'});ElMessage.success('绑定已保存');bindingVisible.value=false;Object.assign(binding,{customer_id:null,external_userid:'',open_kfid:'',wechat_remark:'',verified:true});await loadAll()}
const removeBinding=async row=>{await ElMessageBox.confirm(`确认解除 ${row.customer_name} 的微信绑定吗？`,'解除绑定',{type:'warning'});await deleteWeComBinding(row.id);ElMessage.success('已解除绑定');await loadAll()}
const refreshAttention=()=>window.dispatchEvent(new CustomEvent('attention-updated'))
const confirmDraft=async row=>{const result=await confirmWeComOrderDraft(row.id);ElMessage.success(`${result.message}：${result.order_no}`);await loadAll();refreshAttention()}
const resolveMessage=async row=>{await resolveWeComMessage(row.id);ElMessage.success('该消息已标记为处理完成');await loadAll();refreshAttention()}
const runTest=async()=>{if(!test.external_userid||!test.content.trim())return ElMessage.warning('请选择绑定客户并输入消息');const row=bindings.value.find(i=>i.external_userid===test.external_userid);const result=await simulateWeComMessage({...test,open_kfid:row?.open_kfid||'test-kf'});testResult.value=JSON.stringify(result,null,2);await loadAll()}
onMounted(loadAll)
</script>

<style scoped>
.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:16px 0}.metrics span,.metrics b{display:block}.metrics span{color:#7e8999}.metrics b{font-size:25px;margin-top:7px}.ok{color:#24946b}.warning{color:#db7b2b}.toolbar{display:flex;align-items:center;gap:14px;margin-bottom:14px}.toolbar span{color:#8490a3}.draft-detail{padding:12px 40px 18px;background:#f7f9fc}.test-form{max-width:700px;margin-top:22px}.test-result{margin-top:14px;background:#f7f9fc}.test-result pre{white-space:pre-wrap;margin:0}.profile-name{display:block;color:#8b96a8;font-weight:normal}.profile-help{display:block;color:#8b96a8;margin-top:5px}
</style>
