<template>
  <div>
    <div class="page-header"><div><h2>仓库管理</h2><p>进货自动入库、分拣自动备货、装车自动出库，领料和临时调整可人工登记</p></div><div class="actions"><el-button v-for="type in createTypes" :key="type.value" :type="type.button" @click="openCreate(type.value)">新增{{type.label}}</el-button></div></div>
    <el-alert type="info" :closable="false" show-icon title="这里是业务库存台账，与上传 Excel 的“智能库存查询”相互独立；联动单据自动记账，避免重复计算。"/>
    <div class="metrics"><el-card><span>台账商品</span><b>{{summary.product_count}}</b></el-card><el-card><span>可用库存合计</span><b>{{number(summary.available_total)}}</b></el-card><el-card><span>备货占用商品</span><b class="warning">{{summary.reserved_count}}</b></el-card><el-card><span>负可用库存</span><b class="danger">{{summary.negative_count}}</b></el-card></div>

    <el-card class="panel stock-panel"><div class="section-title"><div><b>实时库存结余</b><span>现存 = 入库 - 出库 - 领料；可用 = 现存 - 备货占用</span></div><el-input v-model="stockKeyword" clearable placeholder="搜索商品或分类" style="width:260px"/></div>
      <el-table :data="filteredStock" max-height="360" stripe><el-table-column prop="category" label="分类" width="120"/><el-table-column prop="product_name" label="商品" min-width="180"/><el-table-column label="现存" width="130"><template #default="s"><b>{{number(s.row.on_hand)}} {{s.row.unit_name}}</b></template></el-table-column><el-table-column label="备货占用" width="130"><template #default="s"><span class="warning">{{number(s.row.reserved)}} {{s.row.unit_name}}</span></template></el-table-column><el-table-column label="可用" width="150"><template #default="s"><b :class="{danger:s.row.available<0,ok:s.row.available>=0}">{{number(s.row.available)}} {{s.row.unit_name}}</b></template></el-table-column><el-table-column label="累计入库" width="120"><template #default="s">{{number(s.row.total_inbound)}}</template></el-table-column><el-table-column label="累计出库" width="120"><template #default="s">{{number(s.row.total_outbound)}}</template></el-table-column><el-table-column label="累计领料" width="120"><template #default="s">{{number(s.row.total_material)}}</template></el-table-column></el-table>
    </el-card>

    <el-card class="panel"><el-tabs v-model="activeType" @tab-change="loadDocuments"><el-tab-pane v-for="tab in tabs" :key="tab.value" :label="tab.label" :name="tab.value"/></el-tabs>
      <div class="filters"><el-date-picker v-model="dateRange" type="daterange" value-format="YYYY-MM-DD" range-separator="至" :clearable="false" @change="loadDocuments"/><el-input v-model="keyword" clearable placeholder="单号、来源、对象或商品" @keyup.enter="loadDocuments"/><el-button type="primary" @click="loadDocuments">查询</el-button><el-button @click="resetFilters">重置今天</el-button></div>
      <el-table :data="documents" row-key="id"><el-table-column type="expand"><template #default="s"><el-table :data="s.row.items" size="small" border><el-table-column prop="product_name" label="商品"/><el-table-column prop="category" label="分类"/><el-table-column label="数量"><template #default="c">{{number(c.row.quantity)}} {{c.row.unit_name}}</template></el-table-column><el-table-column prop="batch_no" label="批次"/><el-table-column prop="remark" label="备注"/></el-table></template></el-table-column><el-table-column prop="document_no" label="仓库单号" min-width="190"/><el-table-column label="类型" width="100"><template #default="s"><el-tag :type="typeMeta(s.row.document_type).tag">{{typeMeta(s.row.document_type).label}}</el-tag></template></el-table-column><el-table-column prop="business_date" label="业务日期" width="120"/><el-table-column prop="warehouse" label="仓库" width="120"/><el-table-column prop="target_name" label="供应商/客户/部门" min-width="150"/><el-table-column label="来源" min-width="180"><template #default="s">{{sourceLabel(s.row)}}<el-tag v-if="s.row.status==='released'" size="small" type="info">已转出库</el-tag></template></el-table-column><el-table-column prop="creator_name" label="制单人" width="110"/><el-table-column label="操作" width="90"><template #default="s"><el-button v-if="s.row.source_type==='manual'" link type="danger" @click="remove(s.row)">删除</el-button><span v-else class="muted">联动单据</span></template></el-table-column></el-table>
    </el-card>

    <el-dialog v-model="visible" :title="`新增${typeMeta(form.document_type).label}`" width="920px" top="5vh"><el-form label-width="100px"><el-row :gutter="14"><el-col :span="8"><el-form-item label="业务日期" required><el-date-picker v-model="form.business_date" value-format="YYYY-MM-DD" style="width:100%"/></el-form-item></el-col><el-col :span="8"><el-form-item label="仓库" required><el-input v-model="form.warehouse"/></el-form-item></el-col><el-col :span="8"><el-form-item :label="targetLabel"><el-input v-model="form.target_name" :placeholder="targetPlaceholder"/></el-form-item></el-col></el-row><el-form-item label="说明"><el-input v-model="form.notes" placeholder="领用用途、出库原因或其他说明"/></el-form-item></el-form>
      <div class="line-head"><b>商品明细</b><el-button type="primary" plain @click="addLine">添加一行</el-button></div><el-table :data="form.items" border max-height="360"><el-table-column label="商品" min-width="230"><template #default="s"><el-select v-model="s.row.product_id" filterable style="width:100%" @change="productChanged(s.row)"><el-option v-for="p in options.products" :key="p.id" :label="`${p.category} · ${p.name}`" :value="p.id"/></el-select></template></el-table-column><el-table-column label="单位" width="150"><template #default="s"><el-select v-model="s.row.unit_id"><el-option v-for="u in unitsOf(s.row)" :key="u.id" :label="u.name" :value="u.id"/></el-select></template></el-table-column><el-table-column label="数量" width="150"><template #default="s"><el-input-number v-model="s.row.quantity" :min="0.01" :precision="2" style="width:125px"/></template></el-table-column><el-table-column label="批次" width="140"><template #default="s"><el-input v-model="s.row.batch_no"/></template></el-table-column><el-table-column label="备注" min-width="160"><template #default="s"><el-input v-model="s.row.remark"/></template></el-table-column><el-table-column width="65"><template #default="s"><el-button link type="danger" @click="form.items.splice(s.$index,1)">移除</el-button></template></el-table-column></el-table>
      <template #footer><el-button @click="visible=false">取消</el-button><el-button type="primary" :loading="saving" @click="save">保存并记账</el-button></template></el-dialog>
  </div>
</template>

<script setup>
import { computed,onMounted,reactive,ref } from 'vue'
import { ElMessage,ElMessageBox } from 'element-plus'
import { createWarehouseDocument,deleteWarehouseDocument,getWarehouseDocuments,getWarehouseOptions,getWarehouseSummary } from '@/api'
const today=()=>new Date().toLocaleDateString('sv-SE')
const tabs=[{value:'all',label:'全部流水'},{value:'inbound',label:'入库'},{value:'outbound',label:'出库'},{value:'material',label:'领料'},{value:'preparation',label:'备货'}]
const createTypes=[{value:'inbound',label:'入库',button:'success'},{value:'outbound',label:'出库',button:'primary'},{value:'material',label:'领料',button:'warning'},{value:'preparation',label:'备货',button:'info'}]
const meta={inbound:{label:'入库',tag:'success'},outbound:{label:'出库',tag:'primary'},material:{label:'领料',tag:'warning'},preparation:{label:'备货',tag:'info'}}
const typeMeta=type=>meta[type]||{label:type,tag:'info'}
const activeType=ref('all'),dateRange=ref([today(),today()]),keyword=ref(''),stockKeyword=ref(''),documents=ref([]),visible=ref(false),saving=ref(false)
const summary=reactive({rows:[],product_count:0,negative_count:0,reserved_count:0,available_total:0}),options=reactive({products:[]})
const blankLine=()=>({product_id:null,unit_id:null,quantity:1,batch_no:'',remark:''})
const form=reactive({document_type:'inbound',business_date:today(),warehouse:'主仓库',target_name:'',notes:'',items:[blankLine()]})
const number=value=>Number(value||0).toLocaleString('zh-CN',{maximumFractionDigits:4})
const filteredStock=computed(()=>summary.rows.filter(row=>!stockKeyword.value||`${row.product_name}${row.category}`.toLowerCase().includes(stockKeyword.value.toLowerCase())))
const targetLabel=computed(()=>form.document_type==='inbound'?'来源单位':form.document_type==='material'?'领用部门':form.document_type==='preparation'?'备货对象':'接收对象')
const targetPlaceholder=computed(()=>form.document_type==='inbound'?'供应商或其他来源':form.document_type==='material'?'如：加工间、食堂':'客户、门店或部门')
const unitsOf=line=>options.products.find(p=>p.id===line.product_id)?.units||[]
const productChanged=line=>{line.unit_id=unitsOf(line).find(u=>u.is_base)?.id||unitsOf(line)[0]?.id||null}
const sourceLabel=row=>row.source_type==='manual'?'手工登记':`${row.source_no||'关联单据'} · 自动联动`
const loadSummary=async()=>Object.assign(summary,await getWarehouseSummary())
const loadDocuments=async()=>documents.value=await getWarehouseDocuments({document_type:activeType.value==='all'?undefined:activeType.value,date_from:dateRange.value[0],date_to:dateRange.value[1],keyword:keyword.value||undefined})
const load=async()=>{const[o]=await Promise.all([getWarehouseOptions(),loadSummary(),loadDocuments()]);Object.assign(options,o)}
const resetFilters=async()=>{dateRange.value=[today(),today()];keyword.value='';await loadDocuments()}
const openCreate=type=>{Object.assign(form,{document_type:type,business_date:today(),warehouse:'主仓库',target_name:'',notes:'',items:[blankLine()]});visible.value=true}
const addLine=()=>form.items.push(blankLine())
const save=async()=>{const items=form.items.filter(i=>i.product_id);if(!items.length)return ElMessage.warning('请至少添加一个商品');if(items.some(i=>!i.unit_id||i.quantity<=0))return ElMessage.warning('请完整填写商品单位和数量');saving.value=true;try{await createWarehouseDocument({...form,target_name:form.target_name||null,notes:form.notes||null,items});ElMessage.success('仓库单据已保存，库存结余已更新');visible.value=false;await Promise.all([loadSummary(),loadDocuments()])}finally{saving.value=false}}
const remove=async row=>{await ElMessageBox.confirm(`确认提交仓库单据 ${row.document_no} 的删除申请吗？管理员审核前不会删除。`,'提交删除申请',{type:'warning'});const result=await deleteWarehouseDocument(row.id);ElMessage.success(result.message);await loadDocuments()}
onMounted(load)
</script>

<style scoped>
.actions{display:flex;gap:8px}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:16px 0}.metrics span,.metrics b{display:block}.metrics span{color:#7d899a}.metrics b{font-size:25px;margin-top:7px}.panel{margin-bottom:16px}.section-title{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px}.section-title b,.section-title span{display:block}.section-title span{font-size:13px;color:#8490a3;margin-top:4px}.filters{display:flex;gap:10px;margin-bottom:14px}.filters .el-input{width:300px}.line-head{display:flex;justify-content:space-between;align-items:center;margin:12px 0}.warning{color:#dc7b2c}.danger{color:#d9534f}.ok{color:#24946b}.muted{color:#9aa3af;font-size:12px}@media(max-width:1100px){.metrics{grid-template-columns:repeat(2,1fr)}}
</style>
