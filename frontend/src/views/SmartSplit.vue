<template>
  <div>
    <div class="page-header">
      <div><h2>智能拆单中心</h2><p>把销售或备货需求按配额、产能、价格或质量拆成多供应商采购单</p></div>
      <el-tag size="large" type="success">后端强校验 · 数量可追溯</el-tag>
    </div>

    <el-tabs v-model="activeTab" class="split-tabs" @tab-change="tabChanged">
      <el-tab-pane label="拆单操作台" name="workbench">
        <el-card class="panel source-card" shadow="never">
          <div class="step-title"><i>1</i><div><b>选择采购需求</b><span>支持已确认销售单和仓库备货采购需求</span></div></div>
          <div class="source-fields">
            <el-radio-group v-model="sourceType" @change="sourceId=null;preview=null"><el-radio-button value="sales">销售订单</el-radio-button><el-radio-button value="requisition">备货需求</el-radio-button></el-radio-group>
            <el-select v-model="sourceId" filterable placeholder="搜索并选择单据" style="min-width:390px" @change="preview=null"><el-option v-for="item in currentSources" :key="item.id" :label="item.name" :value="item.id"><span>{{item.name}}</span><small>{{item.needed_date}} · {{item.item_count}} 项</small></el-option></el-select>
          </div>
          <div class="strategy-grid">
            <button v-for="item in strategyOptions" :key="item.value" :class="{active:strategy===item.value}" @click="strategy=item.value;preview=null">
              <el-icon><component :is="item.icon" /></el-icon><div><b>{{item.name}}</b><span>{{item.description}}</span></div>
            </button>
          </div>
          <div class="preview-action"><el-button type="primary" size="large" :disabled="!sourceId" :loading="previewing" @click="runPreview">智能计算拆分方案</el-button></div>
        </el-card>

        <template v-if="preview">
          <el-card class="panel result-card" shadow="never">
            <div class="result-head"><div class="step-title"><i>2</i><div><b>核对与调整拆单结果</b><span>{{preview.source_no}} · {{preview.name}} · {{preview.strategy_name}}</span></div></div><div><el-tag :type="hasGap?'danger':'success'">{{hasGap?'存在未分配或超分':'全部数量匹配'}}</el-tag></div></div>
            <el-alert title="采购量 = 原始需求 ×（1 + 商品/品类损耗率）－ 已生成采购量。您可修改分配数量，系统会实时显示差额并在提交时再次校验产能。" type="info" :closable="false" show-icon />
            <div v-for="item in preview.items" :key="item.product_id" class="product-split" :class="{invalid:Math.abs(balance(item))>0.0001}">
              <div class="product-head">
                <div><b>{{item.product_name}}</b><el-tag size="small" effect="plain">{{item.category}}</el-tag></div>
                <div class="quantity-chain"><span>原需求 <b>{{num(item.demand_base_quantity)}}</b></span><span>损耗 <b>+{{item.loss_rate}}%</b></span><span>目标 <b>{{num(item.target_base_quantity)}}</b></span><span v-if="item.existing_base_quantity">已采购 <b>{{num(item.existing_base_quantity)}}</b></span><span>本次应拆 <strong>{{num(item.required_base_quantity)}} {{item.base_unit_name}}</strong></span></div>
              </div>
              <el-table :data="item.allocations" border size="small">
                <el-table-column prop="supplier_name" label="供应商" min-width="150" />
                <el-table-column label="供货能力" min-width="180"><template #default="s"><span>本次可供 {{num(s.row.capacity)}} {{item.base_unit_name}}</span><small v-if="s.row.daily_remaining!=null">今日剩余 {{num(s.row.daily_remaining)}}</small></template></el-table-column>
                <el-table-column label="价格/评分" min-width="180"><template #default="s"><b class="price">¥{{money(s.row.base_unit_price)}}/{{item.base_unit_name}}</b><small>{{s.row.price_source==='tier_price'?'已命中阶梯价':'标准报价'}} · 质量 {{s.row.quality_score}}</small></template></el-table-column>
                <el-table-column label="分配比例" min-width="190"><template #default="s"><el-slider v-model="s.row.base_quantity" :min="0" :max="Number(s.row.capacity)" :step="0.0001" :show-tooltip="false" /><small>{{allocationPercent(item,s.row)}}%</small></template></el-table-column>
                <el-table-column label="分配数量" width="190"><template #default="s"><el-input-number v-model="s.row.base_quantity" :min="0" :max="Number(s.row.capacity)" :precision="4" controls-position="right" style="width:135px" /> {{item.base_unit_name}}</template></el-table-column>
                <el-table-column label="预计金额" width="120"><template #default="s">¥{{money(s.row.base_quantity*s.row.base_unit_price)}}</template></el-table-column>
                <el-table-column width="70"><template #default="s"><el-button link type="danger" @click="removeAllocation(item,s.$index)">移除</el-button></template></el-table-column>
              </el-table>
              <div class="split-footer">
                <el-select v-model="item.add_assignment_id" placeholder="增加备选供应商" clearable style="width:220px"><el-option v-for="candidate in availableCandidates(item)" :key="candidate.assignment_id" :label="`${candidate.supplier_name} · ¥${money(candidate.base_unit_price)}`" :value="candidate.assignment_id" /></el-select>
                <el-button :disabled="!item.add_assignment_id" @click="addAllocation(item)">加入供应商</el-button>
                <el-button :disabled="balance(item)<=0 || !item.allocations.length" @click="fillRemaining(item)">一键补齐剩余量</el-button>
                <span class="balance" :class="{ok:Math.abs(balance(item))<=0.0001}">已分配 {{num(allocated(item))}}，{{balance(item)>=0?'剩余':'超分'}} {{num(Math.abs(balance(item)))}} {{item.base_unit_name}}</span>
              </div>
            </div>
            <div class="generate-bar"><el-select v-model="reductionStrategy" style="width:250px"><el-option label="减单按原比例同步扣减" value="proportional"/><el-option label="减单从低优先级/高价供应商倒扣" value="reverse_priority"/></el-select><el-input v-model="notes" placeholder="拆单备注（可选）" style="max-width:360px"/><el-button type="success" size="large" :disabled="hasGap || !hasPurchasable" :loading="generating" @click="generate">生成多供应商采购草稿</el-button></div>
          </el-card>
        </template>
      </el-tab-pane>

      <el-tab-pane label="供应规则配置" name="rules">
        <el-card class="panel" shadow="never">
          <div class="toolbar"><el-input v-model="ruleKeyword" clearable placeholder="搜索商品或供应商" style="width:280px"/><el-select v-model="ruleCategory" clearable placeholder="全部分类" style="width:180px"><el-option v-for="item in config.categories" :key="item.id" :label="item.name" :value="item.name"/></el-select><span class="muted">配额按同一商品所有启用供应商的比例自动归一</span></div>
          <el-table :data="filteredAssignments" border stripe height="560">
            <el-table-column prop="category" label="分类" width="110"/><el-table-column prop="product_name" label="商品" min-width="150"/><el-table-column prop="supplier_name" label="供应商" min-width="145"/>
            <el-table-column label="标准价" width="115"><template #default="s">{{s.row.standard_base_price==null?'未报价':`¥${money(s.row.standard_base_price)}`}}</template></el-table-column>
            <el-table-column label="启用拆单" width="90"><template #default="s"><el-switch v-model="s.row.split_enabled"/></template></el-table-column>
            <el-table-column label="优先级" width="110"><template #default="s"><el-input-number v-model="s.row.priority" :min="1" :max="9999" controls-position="right" style="width:90px"/></template></el-table-column>
            <el-table-column label="日最大供货" width="145"><template #default="s"><el-input-number v-model="s.row.daily_capacity_base" :min="0" :precision="4" controls-position="right" style="width:120px"/></template></el-table-column>
            <el-table-column label="单订单上限" width="145"><template #default="s"><el-input-number v-model="s.row.order_capacity_base" :min="0" :precision="4" controls-position="right" style="width:120px"/></template></el-table-column>
            <el-table-column label="固定配额%" width="130"><template #default="s"><el-input-number v-model="s.row.quota_percent" :min="0" :max="100" :precision="2" controls-position="right" style="width:105px"/></template></el-table-column>
            <el-table-column label="阶梯报价" min-width="150"><template #default="s"><el-button link type="primary" @click="openTier(s.row)">{{s.row.tier_prices.length?`${s.row.tier_prices.length} 档阶梯价`:'设置阶梯价'}}</el-button></template></el-table-column>
            <el-table-column label="操作" width="90" fixed="right"><template #default="s"><el-button link type="primary" :loading="s.row.saving" @click="saveRule(s.row)">保存</el-button></template></el-table-column>
          </el-table>
        </el-card>

        <div class="config-grid">
          <el-card shadow="never"><template #header><b>品类默认采购损耗</b></template><div v-for="item in config.categories" :key="item.id" class="config-row"><span>{{item.name}}</span><el-input-number v-model="item.purchase_loss_rate" :min="0" :max="100" :precision="3" controls-position="right"/><span>%</span><el-button link type="primary" @click="saveCategory(item)">保存</el-button></div></el-card>
          <el-card shadow="never"><template #header><div class="card-head"><b>供应商质量评分</b><el-button link type="primary" @click="weightVisible=true">配置权重</el-button></div></template><div v-for="item in config.suppliers" :key="item.id" class="supplier-score"><b>{{item.name}}</b><span>综合 {{item.quality_score}}</span><el-input-number v-model="item.on_time_rate" :min="0" :max="100" :precision="2"/><el-input-number v-model="item.inspection_pass_rate" :min="0" :max="100" :precision="2"/><el-input-number v-model="item.return_rate" :min="0" :max="100" :precision="2"/><el-button link type="primary" @click="savePerformance(item)">保存</el-button><small>准时率 / 质检合格率 / 退换货率</small></div></el-card>
        </div>
      </el-tab-pane>

      <el-tab-pane label="拆单计划与追溯" name="plans">
        <el-card class="panel" shadow="never"><el-table :data="plans" row-key="id" border><el-table-column type="expand"><template #default="s"><div class="plan-detail" v-for="item in s.row.items" :key="item.product_name"><b>{{item.product_name}}</b><span>需求 {{num(item.demand_base_quantity)}}，损耗 {{item.loss_rate}}%，采购 {{num(item.purchase_base_quantity)}} {{item.base_unit_name}}</span><el-tag v-for="a in item.allocations" :key="a.purchase_order_no" size="small">{{a.supplier_name}} {{num(a.base_quantity)}} · {{a.purchase_order_no}}</el-tag></div></template></el-table-column><el-table-column prop="plan_no" label="拆单计划号" min-width="190"/><el-table-column prop="source_no" label="原始需求号" min-width="190"/><el-table-column prop="strategy_name" label="策略" width="110"/><el-table-column prop="needed_date" label="需求日期" width="115"/><el-table-column prop="supplier_count" label="供应商" width="90"/><el-table-column label="状态" width="100"><template #default="s"><el-tag :type="s.row.status==='cancelled'?'info':'success'">{{s.row.status==='cancelled'?'已撤销':'已生成'}}</el-tag></template></el-table-column><el-table-column prop="creator_name" label="操作人" width="110"/><el-table-column prop="generated_at" label="生成时间" width="170"/><el-table-column label="操作" width="100"><template #default="s"><el-button v-if="s.row.status==='generated'" link type="danger" @click="cancelPlan(s.row)">撤销拆单</el-button></template></el-table-column></el-table></el-card>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="tierVisible" :title="`阶梯报价 · ${tierForm.product_name||''} · ${tierForm.supplier_name||''}`" width="620px"><el-alert title="起订量和单价均按商品基础单位填写；达到阈值时自动采用最高已满足档位。" type="info" :closable="false"/><div v-for="(item,index) in tierForm.tier_prices" :key="index" class="tier-row"><el-input-number v-model="item.min_base_quantity" :min="0.0001" :precision="4" placeholder="起订量"/><span>{{tierForm.base_unit_name}}起，单价</span><el-input-number v-model="item.base_unit_price" :min="0.0001" :precision="4"/><el-button link type="danger" @click="tierForm.tier_prices.splice(index,1)">删除</el-button></div><el-button plain @click="tierForm.tier_prices.push({min_base_quantity:1,base_unit_price:tierForm.standard_base_price||1})">新增价格档位</el-button><template #footer><el-button @click="tierVisible=false">取消</el-button><el-button type="primary" @click="saveTier">保存规则</el-button></template></el-dialog>
    <el-dialog v-model="weightVisible" title="质量评分指标权重" width="520px"><el-form label-width="150px"><el-form-item label="到货准时率权重"><el-input-number v-model="config.weights.on_time" :min="0" :precision="2"/></el-form-item><el-form-item label="质检合格率权重"><el-input-number v-model="config.weights.inspection" :min="0" :precision="2"/></el-form-item><el-form-item label="低退换货率权重"><el-input-number v-model="config.weights.return" :min="0" :precision="2"/></el-form-item></el-form><template #footer><el-button @click="weightVisible=false">取消</el-button><el-button type="primary" @click="saveWeights">保存并重新计算</el-button></template></el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { cancelSmartSplitPlan, generateSmartSplit, getSmartSplitConfig, getSmartSplitPlans, getSmartSplitSources, previewSmartSplit, updateQualityWeights, updateSmartSplitAssignment, updateSmartSplitCategoryLoss, updateSupplierPerformance } from '@/api'

const route=useRoute(),router=useRouter(),activeTab=ref('workbench'),sourceType=ref('sales'),sourceId=ref(null),strategy=ref('price')
const sources=reactive({sales_orders:[],requisitions:[]}),config=reactive({assignments:[],categories:[],suppliers:[],weights:{on_time:.4,inspection:.4,return:.2}}),plans=ref([]),preview=ref(null)
const previewing=ref(false),generating=ref(false),notes=ref(''),reductionStrategy=ref('proportional'),ruleKeyword=ref(''),ruleCategory=ref(''),tierVisible=ref(false),weightVisible=ref(false),tierForm=reactive({})
const strategyOptions=[{value:'quota',name:'配额比例拆分',description:'按长期协议配额分配，超产能自动顺延',icon:'PieChart'},{value:'capacity',name:'供货能力拆分',description:'优先级由高到低依次填满产能',icon:'Histogram'},{value:'price',name:'价格优先拆分',description:'含阶梯价，低价供应商优先填满',icon:'TrendCharts'},{value:'quality',name:'质量评分拆分',description:'准时率、质检率、退货率综合排序',icon:'Medal'}]
const currentSources=computed(()=>sourceType.value==='sales'?sources.sales_orders:sources.requisitions)
const filteredAssignments=computed(()=>config.assignments.filter(row=>(!ruleCategory.value||row.category===ruleCategory.value)&&(!ruleKeyword.value||`${row.product_name}${row.supplier_name}`.toLowerCase().includes(ruleKeyword.value.toLowerCase()))))
const num=v=>Number(v||0).toLocaleString('zh-CN',{maximumFractionDigits:4}),money=v=>Number(v||0).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:4})
const allocated=item=>item.allocations.reduce((sum,row)=>sum+Number(row.base_quantity||0),0),balance=item=>Number((Number(item.required_base_quantity)-allocated(item)).toFixed(4))
const hasGap=computed(()=>preview.value?.items.some(item=>Math.abs(balance(item))>.0001))
const hasPurchasable=computed(()=>preview.value?.items.some(item=>Number(item.required_base_quantity)>0))
const allocationPercent=(item,row)=>item.required_base_quantity?((Number(row.base_quantity||0)/Number(item.required_base_quantity))*100).toFixed(2):'0.00'
const availableCandidates=item=>item.candidates.filter(row=>!item.allocations.some(a=>a.assignment_id===row.assignment_id))
const addAllocation=item=>{const row=item.candidates.find(c=>c.assignment_id===item.add_assignment_id);if(row)item.allocations.push({...row,base_quantity:0});item.add_assignment_id=null}
const removeAllocation=(item,index)=>item.allocations.splice(index,1)
const fillRemaining=item=>{let rest=balance(item);if(rest<=0)return;for(const row of item.allocations){const available=Number(row.capacity)-Number(row.base_quantity||0),added=Math.min(rest,available);row.base_quantity=Number((Number(row.base_quantity||0)+added).toFixed(4));rest=Number((rest-added).toFixed(4));if(rest<=0)break}if(rest>0)ElMessage.warning(`仍有 ${num(rest)} ${item.base_unit_name} 超出当前供应商总产能`)}
const loadBase=async()=>{const [sourceData,configData]=await Promise.all([getSmartSplitSources(),getSmartSplitConfig()]);Object.assign(sources,sourceData);Object.assign(config,configData)}
const runPreview=async()=>{previewing.value=true;try{preview.value=await previewSmartSplit({source_type:sourceType.value,source_id:sourceId.value,strategy:strategy.value});preview.value.items.forEach(item=>item.add_assignment_id=null)}finally{previewing.value=false}}
const generate=async()=>{if(hasGap.value)return ElMessage.warning('请先使每个商品的拆分数量与应采购量完全一致');await ElMessageBox.confirm(`将生成多个供应商采购草稿，确认使用“${preview.value.strategy_name}”方案吗？`,'生成拆分采购单',{type:'warning'});generating.value=true;try{const result=await generateSmartSplit({source_type:sourceType.value,source_id:sourceId.value,strategy:strategy.value,reduction_strategy:reductionStrategy.value,notes:notes.value||null,items:preview.value.items.filter(i=>Number(i.required_base_quantity)>0).map(item=>({product_id:item.product_id,allocations:item.allocations.filter(a=>Number(a.base_quantity)>0).map(a=>({assignment_id:a.assignment_id,base_quantity:a.base_quantity}))}))});ElMessage.success(result.message);preview.value=null;await Promise.all([loadBase(),loadPlans()]);activeTab.value='plans'}finally{generating.value=false}}
const saveRule=async row=>{row.saving=true;try{Object.assign(row,await updateSmartSplitAssignment(row.id,{split_enabled:row.split_enabled,priority:row.priority,daily_capacity_base:row.daily_capacity_base||null,order_capacity_base:row.order_capacity_base||null,quota_percent:row.quota_percent||0,tier_prices:row.tier_prices}));ElMessage.success('供应规则已保存')}finally{row.saving=false}}
const openTier=row=>{Object.assign(tierForm,JSON.parse(JSON.stringify(row)));tierVisible.value=true}
const saveTier=async()=>{const original=config.assignments.find(i=>i.id===tierForm.id);original.tier_prices=JSON.parse(JSON.stringify(tierForm.tier_prices));await saveRule(original);tierVisible.value=false}
const saveCategory=async item=>{await updateSmartSplitCategoryLoss(item.id,{purchase_loss_rate:item.purchase_loss_rate});ElMessage.success('品类损耗率已保存')}
const savePerformance=async item=>{const result=await updateSupplierPerformance(item.id,{on_time_rate:item.on_time_rate,inspection_pass_rate:item.inspection_pass_rate,return_rate:item.return_rate,payment_term_days:item.payment_term_days||0});item.quality_score=result.quality_score;ElMessage.success('供应商绩效已保存')}
const saveWeights=async()=>{config.weights=await updateQualityWeights(config.weights);weightVisible.value=false;await loadBase();ElMessage.success('评分权重已更新')}
const loadPlans=async()=>{plans.value=await getSmartSplitPlans()}
const cancelPlan=async row=>{await ElMessageBox.confirm('仅当全部子采购单仍为草稿时才能撤销。撤销后原需求可重新拆分。','撤销拆单',{type:'warning'});const result=await cancelSmartSplitPlan(row.id);ElMessage.success(result.message);await Promise.all([loadPlans(),loadBase()])}
const tabChanged=name=>{if(name==='plans')loadPlans();if(name==='rules')loadBase()}
onMounted(async()=>{await loadBase();await loadPlans();if(route.query.source&&route.query.id){sourceType.value=route.query.source==='requisition'?'requisition':'sales';sourceId.value=Number(route.query.id);strategy.value=route.query.strategy||'price';await runPreview();await router.replace('/smart-split')}})
</script>

<style scoped>
.split-tabs :deep(.el-tabs__item){font-size:16px}.source-card,.result-card{margin-bottom:16px}.step-title{display:flex;align-items:center;gap:12px}.step-title i{width:32px;height:32px;border-radius:50%;background:#3478ce;color:#fff;display:grid;place-items:center;font-style:normal;font-weight:800}.step-title b,.step-title span{display:block}.step-title b{font-size:17px}.step-title span,.muted{color:#8490a2;margin-top:3px}.source-fields{display:flex;gap:14px;margin:18px 0}.source-fields small{float:right;color:#8b96a8;margin-left:20px}.strategy-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.strategy-grid button{display:flex;align-items:flex-start;gap:12px;border:1px solid #dfe5ed;background:#fff;border-radius:11px;padding:16px;text-align:left;cursor:pointer}.strategy-grid button.active{border-color:#3b82d0;background:#edf6ff;box-shadow:0 0 0 2px #d9ebff}.strategy-grid .el-icon{font-size:25px;color:#3477c7}.strategy-grid b,.strategy-grid span{display:block}.strategy-grid span{color:#7d8899;line-height:18px;margin-top:5px}.preview-action{text-align:right;margin-top:18px}.result-head,.card-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px}.product-split{border:1px solid #e2e8f0;border-radius:10px;margin-top:14px;overflow:hidden}.product-split.invalid{border-color:#e7a29c}.product-head{display:flex;align-items:center;justify-content:space-between;padding:13px 15px;background:#f7f9fc}.product-head>div:first-child{display:flex;align-items:center;gap:9px}.quantity-chain{display:flex;gap:17px;font-size:13px;color:#718096}.quantity-chain strong{color:#d85f34}.product-split small{display:block;color:#8490a2;margin-top:4px}.price{color:#dc6538}.split-footer{display:flex;align-items:center;gap:8px;padding:10px 13px}.balance{margin-left:auto;color:#d64d45;font-weight:700}.balance.ok{color:#35a36b}.generate-bar{display:flex;justify-content:flex-end;gap:10px;align-items:center;margin-top:18px}.toolbar{display:flex;gap:10px;align-items:center;margin-bottom:14px}.toolbar .muted{margin-left:auto}.config-grid{display:grid;grid-template-columns:1fr 1.4fr;gap:15px;margin-top:15px}.config-row{display:grid;grid-template-columns:1fr 150px 25px 55px;align-items:center;gap:8px;margin:9px 0}.supplier-score{display:grid;grid-template-columns:1fr 80px repeat(3,125px) 50px;gap:7px;align-items:center;margin:10px 0}.supplier-score small{grid-column:3/6;color:#8994a5;text-align:center}.tier-row{display:flex;align-items:center;gap:9px;margin:15px 0}.plan-detail{display:flex;align-items:center;gap:11px;padding:9px 45px;background:#f8fafc;border-bottom:1px solid #eef1f5}.plan-detail>b{min-width:130px}.plan-detail>span{color:#768397;min-width:300px}@media(max-width:1200px){.strategy-grid{grid-template-columns:1fr 1fr}.config-grid{grid-template-columns:1fr}.quantity-chain{flex-wrap:wrap}.supplier-score{grid-template-columns:1fr 80px 1fr 1fr 1fr 50px}}
</style>
