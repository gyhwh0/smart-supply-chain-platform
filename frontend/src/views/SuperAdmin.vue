<template>
  <div>
    <div class="page-header"><div><h2>超级管理员入口</h2><p>单独控制“默认管理员”可以看到和操作的模块，保存后刷新页面生效</p></div></div>
    <el-alert title="此页面不受“账号管理”权限影响，仅管理员通过专用链接进入。取消某项权限后，默认管理员刷新页面便不会再自动恢复该权限。" type="warning" :closable="false" show-icon />
    <el-card class="panel permission-card" v-loading="loading">
      <div class="account"><div class="avatar">超</div><div><b>{{account.name||'默认管理员'}}</b><span>system_admin</span></div><el-tag type="danger">权限总控</el-tag></div>
      <div class="toolbar"><el-button @click="selected=options.map(item=>item.value)">全选</el-button><el-button @click="selected=[]">全部取消</el-button><span>已选择 {{selected.length}} / {{options.length}} 项</span></div>
      <el-checkbox-group v-model="selected" class="permissions">
        <el-checkbox v-for="item in options" :key="item.value" :value="item.value" border><b>{{item.label}}</b><small>{{item.description}}</small></el-checkbox>
      </el-checkbox-group>
      <div class="footer"><el-button type="primary" size="large" :loading="saving" @click="save">保存默认管理员权限</el-button></div>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted,reactive,ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getDefaultAdminPermissions,saveDefaultAdminPermissions } from '@/api'
import { setSession,getToken,getUser } from '@/utils/auth'
const loading=ref(false),saving=ref(false),selected=ref([]),account=reactive({})
const definitions={dashboard:['工作台','查看业务总览'],account_management:['账号管理','新增账号和设置角色权限'],supplier_management:['供应商管理','维护供应商档案'],category_management:['分类管理','维护商品分类'],product_management:['商品管理','维护商品和单位价格'],assignment_management:['商品分配','给供应商分配商品'],quote_management:['供应商报价','录入和修改报价'],analysis:['智能比价','AI比价分析'],inventory:['库存查询','查询库存数据'],inventory_update:['库存更新','上传库存表'],order_management:['采购下单','创建采购订单'],staff_management:['人员管理','维护订单员、分拣员和配送员'],customer_management:['客户管理','维护客户及人员分配'],sales_order_management:['销售单','录入和确认销售单'],sales_summary:['销售汇总','汇总和导出报表'],wecom_management:['企业微信','客户消息与订单草稿'],complaint_management:['投诉专栏','处理客户投诉'],inbound_management:['进货管理','进货、退货与明细'],warehouse_management:['仓库管理','入库、出库、领料、备货与库存台账'],label_printing:['标签打印','打印普通商品标签'],picking_management:['扫码分拣','生成任务、打印二维码和扫码确认'],picking_monitor:['分拣配送监控','查看人员工作量、客户耗时和单品操作时间'],finance_management:['财务管理','查看销售、验收、开票和毛利']}
const options=ref([])
const load=async()=>{loading.value=true;try{const data=await getDefaultAdminPermissions();Object.assign(account,data);selected.value=[...data.permissions];options.value=data.available_permissions.map(value=>({value,label:definitions[value]?.[0]||value,description:definitions[value]?.[1]||''}))}finally{loading.value=false}}
const save=async()=>{saving.value=true;try{const result=await saveDefaultAdminPermissions(selected.value);const user=getUser();setSession(getToken(),{...user,permissions:result.permissions});ElMessage.success(result.message)}finally{saving.value=false}}
onMounted(load)
</script>

<style scoped>
.permission-card{margin-top:16px}.account{display:flex;align-items:center;gap:12px;border-bottom:1px solid #edf0f4;padding-bottom:16px}.account .avatar{width:46px;height:46px;border-radius:12px;background:#7a2944;color:white;display:grid;place-items:center;font-size:22px;font-weight:800}.account b,.account span{display:block}.account span{color:#8490a3;margin-top:3px}.account .el-tag{margin-left:auto}.toolbar{display:flex;align-items:center;gap:10px;margin:18px 0}.toolbar span{color:#76849a}.permissions{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:11px}.permissions :deep(.el-checkbox){width:100%;height:auto;min-height:66px;margin:0;padding:12px}.permissions :deep(.el-checkbox__label){display:flex;flex-direction:column}.permissions small{color:#8a96a8;margin-top:4px}.footer{text-align:right;margin-top:20px}@media(max-width:900px){.permissions{grid-template-columns:1fr 1fr}}
</style>
