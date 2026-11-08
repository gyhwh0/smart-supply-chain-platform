<template>
  <div class="import-page">
    <div class="page-header"><div><h2>商品 Excel 导入中心</h2><p>模板下载、智能字段映射、三级校验、预览确认和导入审计集中处理</p></div><div><el-button @click="$router.push('/products')">返回商品管理</el-button><el-button @click="activeTab='records';loadJobs()">导入记录</el-button></div></div>
    <el-alert type="info" :closable="false" show-icon title="上传文件不会立即修改数据。必须先完成字段映射与校验，确认后才写入商品、单位、供应商报价和期初库存。"/>
    <el-tabs v-model="activeTab" class="tabs">
      <el-tab-pane label="新建导入" name="import">
        <el-card class="panel">
          <template #header><b>1. 选择模板或导出现有商品</b></template>
          <div class="template-grid">
            <button class="template-card primary-card" @click="downloadTemplate('full')"><b>全字段标准模板</b><span>商品、单位、价格、供应商、批次与期初库存</span></button>
            <button v-for="item in config.industries" :key="item.key" class="template-card" @click="downloadTemplate('industry',item.key)"><b>{{item.name}}行业模板</b><span>仅保留该品类常用字段，降低填写成本</span></button>
            <button class="template-card export-card" @click="exportCurrent"><b>导出现有商品</b><span>导出后修改，再以增量或覆盖方式导回</span></button>
          </div>
        </el-card>

        <el-card class="panel">
          <template #header><b>2. 上传与导入策略</b></template>
          <div class="upload-row">
            <el-upload drag :show-file-list="false" :http-request="uploadExcel" accept=".xlsx,.xls" class="uploader"><div class="upload-title">拖入 Excel，或点击选择文件</div><div class="muted">支持 .xlsx / .xls，最大 20MB</div></el-upload>
            <div class="mode-box"><label>导入模式</label><el-radio-group v-model="mode"><el-radio value="create">纯新增</el-radio><el-radio value="incremental">增量更新</el-radio><el-radio value="overwrite">覆盖更新</el-radio></el-radio-group><p>{{modeHelp}}</p><el-upload :show-file-list="false" :http-request="uploadImages" accept=".zip"><el-button plain>上传商品图片 ZIP</el-button></el-upload><small>图片按“SKU.jpg / SKU_详情1.jpg”自动关联。</small></div>
          </div>
        </el-card>

        <el-card v-if="job.id" class="panel">
          <template #header><div class="card-head"><b>3. 字段智能匹配</b><span>{{job.filename}} · {{job.rawRows}} 行 · {{job.savedName?`已套用方案：${job.savedName}`:'自动识别结果'}}</span></div></template>
          <el-alert v-for="(issue,index) in job.fileIssues" :key="index" :title="`${issue.message}；建议：${issue.suggestion}`" type="warning" :closable="false" class="issue"/>
          <div class="mapping-tools"><el-input v-model="schemeName" placeholder="可选：保存为字段映射方案" clearable/><el-checkbox v-model="skipErrors">跳过错误行，导入其余有效数据</el-checkbox><el-button type="primary" :loading="validating" @click="validateFile">校验并生成预览</el-button></div>
          <el-table :data="mappingRows" border max-height="430"><el-table-column prop="header" label="Excel 原始列" min-width="180"/><el-table-column label="映射到系统字段" min-width="250"><template #default="s"><el-select v-model="mapping[s.row.header]" clearable filterable placeholder="不导入此列" style="width:100%"><el-option v-for="field in config.fields" :key="field.key" :label="`${field.label}${field.required?'（必填）':''}`" :value="field.key" :disabled="usedTargets.has(field.key)&&mapping[s.row.header]!==field.key"/></el-select></template></el-table-column><el-table-column label="识别状态" width="130"><template #default="s"><el-tag :type="mapping[s.row.header]?'success':'info'">{{mapping[s.row.header]?'已匹配':'忽略'}}</el-tag></template></el-table-column></el-table>
        </el-card>

        <el-card v-if="validation" class="panel">
          <template #header><b>4. 校验结果与导入预览</b></template>
          <div class="metrics"><div><span>原始数据</span><b>{{validation.raw_rows}}</b></div><div><span>可导入</span><b class="ok">{{validation.valid_rows}}</b></div><div><span>错误行</span><b class="danger">{{validation.error_rows}}</b></div><div><span>跳过</span><b class="warning">{{validation.skipped_rows}}</b></div></div>
          <div class="summary-row"><span>分类分布：{{categoryText}}</span><span>售价区间：{{priceText}}</span><el-button v-if="validation.error_count" type="danger" plain @click="downloadErrors">下载错误报告</el-button></div>
          <el-table v-if="errors.length" :data="errors" border max-height="260" class="error-table"><el-table-column prop="row" label="行" width="70"/><el-table-column prop="column" label="字段" width="140"/><el-table-column prop="level" label="层级" width="100"/><el-table-column prop="message" label="错误原因" min-width="230"/><el-table-column prop="suggestion" label="修正建议" min-width="230"/></el-table>
          <el-table :data="previewRows" border max-height="360" class="preview-table"><el-table-column type="index" width="55"/><el-table-column v-for="column in previewColumns" :key="column" :prop="column" :label="fieldLabel(column)" min-width="135" show-overflow-tooltip/></el-table>
          <div class="commit-bar"><el-checkbox v-if="mode==='overwrite'" v-model="overwriteConfirmed">我确认覆盖已有商品的非空字段</el-checkbox><span v-else></span><el-button type="success" size="large" :disabled="!canCommit" :loading="committing" @click="commit">确认导入 {{validation.valid_rows}} 行</el-button></div>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="导入记录" name="records">
        <el-card class="panel"><div class="record-head"><b>最近 200 次导入</b><el-button @click="loadJobs">刷新</el-button></div><el-table :data="jobs" stripe><el-table-column prop="job_no" label="任务号" min-width="195"/><el-table-column prop="filename" label="文件" min-width="180"/><el-table-column prop="operator" label="操作人" width="100"/><el-table-column label="模式" width="100"><template #default="s">{{modeName(s.row.mode)}}</template></el-table-column><el-table-column label="结果" min-width="220"><template #default="s"><span>{{s.row.summary?.created??0}} 新增 / {{s.row.summary?.updated??0}} 更新 / {{s.row.summary?.error_rows??0}} 错误</span></template></el-table-column><el-table-column label="状态" width="120"><template #default="s"><el-tag :type="statusType(s.row.status)">{{statusName(s.row.status)}}</el-tag></template></el-table-column><el-table-column prop="created_at" label="时间" width="170"><template #default="s">{{datetime(s.row.created_at)}}</template></el-table-column><el-table-column label="操作" width="240"><template #default="s"><el-button link @click="downloadOriginal(s.row)">原文件</el-button><el-button v-if="s.row.has_error_report" link type="danger" @click="downloadJobErrors(s.row)">错误报告</el-button><el-button v-if="s.row.status==='committed'&&s.row.summary?.product_ids?.length" link type="primary" @click="openBatch(s.row)">批量整理</el-button></template></el-table-column></el-table></el-card>
      </el-tab-pane>
    </el-tabs>
    <el-dialog v-model="batchVisible" title="导入后批量整理" width="650px"><el-alert type="info" :closable="false" title="只处理本次导入涉及的商品；留空的项目不会修改。"/><el-form label-width="120px" class="batch-form"><el-form-item label="统一商品分类"><el-select v-model="batchForm.category_id" clearable filterable style="width:100%"><el-option v-for="c in categories" :key="c.id" :label="c.name" :value="c.id"/></el-select></el-form-item><el-form-item label="追加绑定供应商"><el-select v-model="batchForm.supplier_ids" multiple clearable filterable style="width:100%"><el-option v-for="s in suppliers" :key="s.id" :label="s.name" :value="s.id"/></el-select></el-form-item><el-form-item label="销售价调整"><el-input-number v-model="batchForm.sales_price_percent" :min="0.01" :precision="2"/><span class="percent-tip">%（100 不变，105 上调5%，95 下调5%）</span></el-form-item><el-row :gutter="12"><el-col :span="12"><el-form-item label="库存预警下限"><el-input-number v-model="batchForm.inventory_min" :min="0"/></el-form-item></el-col><el-col :span="12"><el-form-item label="库存预警上限"><el-input-number v-model="batchForm.inventory_max" :min="0"/></el-form-item></el-col></el-row><el-form-item label="启停状态"><el-select v-model="batchForm.active" clearable placeholder="保持原状态"><el-option label="统一启用" :value="true"/><el-option label="统一停用" :value="false"/></el-select></el-form-item></el-form><template #footer><el-button @click="batchVisible=false">取消</el-button><el-button type="primary" @click="saveBatch">确认批量处理</el-button></template></el-dialog>
  </div>
</template>

<script setup>
import { computed,onMounted,reactive,ref } from 'vue'
import { ElMessage,ElMessageBox } from 'element-plus'
import { batchAdjustImportedProducts,commitProductImport,downloadProductImportErrors,downloadProductImportOriginal,downloadProductImportTemplate,exportProductsForImport,getCategories,getProductImportConfig,getProductImportJobs,getSuppliers,importProductImages,previewProductImport,validateProductImport } from '@/api'
const config=reactive({fields:[],industries:[],mappings:[]}),activeTab=ref('import'),mode=ref('incremental'),mapping=reactive({}),schemeName=ref(''),skipErrors=ref(false),overwriteConfirmed=ref(false),validation=ref(null),errors=ref([]),previewRows=ref([]),jobs=ref([]),validating=ref(false),committing=ref(false)
const job=reactive({id:null,filename:'',rawRows:0,savedName:null,fileIssues:[],headers:[]})
const categories=ref([]),suppliers=ref([]),batchVisible=ref(false),batchJobId=ref(null),batchForm=reactive({category_id:null,supplier_ids:[],sales_price_percent:null,inventory_min:null,inventory_max:null,active:null})
const saveBlob=(blob,name)=>{const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),300)}
const downloadTemplate=async(type,industry)=>saveBlob(await downloadProductImportTemplate({template_type:type,industry}),`${industry||'全字段'}商品导入模板.xlsx`)
const exportCurrent=async()=>saveBlob(await exportProductsForImport(),'现有商品可编辑导入表.xlsx')
const uploadExcel=async({file})=>{validation.value=null;errors.value=[];previewRows.value=[];const r=await previewProductImport(file,mode.value);Object.keys(mapping).forEach(k=>delete mapping[k]);Object.assign(mapping,r.mapping);Object.assign(job,{id:r.job_id,filename:file.name,rawRows:r.raw_rows,savedName:r.saved_mapping_name,fileIssues:r.file_issues||[],headers:r.headers||[]});ElMessage.success('文件解析完成，请检查字段映射')}
const uploadImages=async({file})=>{const r=await importProductImages(file);ElMessage.success(r.message);if(r.unmatched?.length)ElMessage.warning(`有 ${r.unmatched.length} 张图片未匹配到SKU`)}
const mappingRows=computed(()=>job.headers.map(header=>({header}))),usedTargets=computed(()=>new Set(Object.values(mapping).filter(Boolean)))
const modeHelp=computed(()=>({create:'仅创建不存在的 SKU，已存在商品自动跳过。',incremental:'只更新 Excel 中有值的字段，空白内容不会清空原数据。',overwrite:'按 Excel 覆盖已有商品字段，适合标准化重整。'}[mode.value]))
const validateFile=async()=>{if(!job.id)return;validating.value=true;try{const r=await validateProductImport(job.id,{mapping:{...mapping},mode:mode.value,skip_errors:skipErrors.value,save_mapping_name:schemeName.value.trim()||null});validation.value=r.summary;errors.value=r.errors||[];previewRows.value=r.preview||[];ElMessage.success(r.summary.can_commit?'校验完成，可以确认导入':'校验未通过，请按错误报告修正')}finally{validating.value=false}}
const previewColumns=computed(()=>previewRows.value.length?Object.keys(previewRows.value[0]).filter(k=>k!=='__row__').slice(0,12):[])
const fieldLabel=key=>config.fields.find(v=>v.key===key)?.label||key
const categoryText=computed(()=>Object.entries(validation.value?.categories||{}).map(([k,v])=>`${k} ${v}行`).join('，')||'—')
const priceText=computed(()=>validation.value?.price_min==null?'—':`¥${validation.value.price_min} ～ ¥${validation.value.price_max}`)
const canCommit=computed(()=>validation.value?.can_commit&&(mode.value!=='overwrite'||overwriteConfirmed.value))
const downloadErrors=async()=>saveBlob(await downloadProductImportErrors(job.id),`${job.filename}-错误报告.xlsx`)
const commit=async()=>{if(mode.value==='overwrite')await ElMessageBox.confirm('覆盖模式会修改已有商品信息，确认继续？','二次确认',{type:'warning'});committing.value=true;try{const r=await commitProductImport(job.id);ElMessage.success(r.message);activeTab.value='records';await loadJobs()}finally{committing.value=false}}
const loadJobs=async()=>jobs.value=await getProductImportJobs()
const downloadOriginal=async row=>saveBlob(await downloadProductImportOriginal(row.id),row.filename)
const downloadJobErrors=async row=>saveBlob(await downloadProductImportErrors(row.id),`${row.job_no}-错误报告.xlsx`)
const openBatch=row=>{batchJobId.value=row.id;Object.assign(batchForm,{category_id:null,supplier_ids:[],sales_price_percent:null,inventory_min:null,inventory_max:null,active:null});batchVisible.value=true}
const saveBatch=async()=>{const r=await batchAdjustImportedProducts(batchJobId.value,{...batchForm});ElMessage.success(r.message);batchVisible.value=false;await loadJobs()}
const modeName=v=>({create:'纯新增',incremental:'增量更新',overwrite:'覆盖更新'})[v]||v
const statusName=v=>({uploaded:'待校验',validated:'待确认',validation_failed:'校验失败',committed:'已导入'})[v]||v
const statusType=v=>v==='committed'?'success':v==='validation_failed'?'danger':v==='validated'?'warning':'info'
const datetime=v=>v?new Date(v).toLocaleString('zh-CN',{hour12:false}):'—'
onMounted(async()=>{const[c,s,importConfig]=await Promise.all([getCategories(),getSuppliers(),getProductImportConfig()]);categories.value=c.filter(v=>v.active);suppliers.value=s.filter(v=>v.active);Object.assign(config,importConfig);await loadJobs()})
</script>

<style scoped>
.tabs{margin-top:14px}.panel{margin-bottom:14px}.template-grid{display:grid;grid-template-columns:repeat(3,minmax(210px,1fr));gap:12px}.template-card{border:1px solid #dce5f0;border-radius:10px;background:#fff;padding:17px;text-align:left;cursor:pointer;color:#32445b}.template-card:hover{border-color:#409eff;box-shadow:0 5px 18px #3978b51c}.template-card b,.template-card span{display:block}.template-card span{color:#8491a5;font-size:13px;margin-top:8px;line-height:1.5}.primary-card{background:#edf6ff;border-color:#90c7ff}.export-card{background:#eefaf5;border-color:#87d4ae}.upload-row{display:grid;grid-template-columns:minmax(420px,1fr) 390px;gap:24px}.uploader{width:100%}.upload-title{font-size:17px;margin-bottom:7px}.mode-box{display:flex;flex-direction:column;gap:10px;padding:10px}.mode-box label{font-weight:700}.mode-box p,.mode-box small,.muted{color:#8491a5;font-size:13px}.card-head,.record-head,.summary-row,.commit-bar{display:flex;justify-content:space-between;align-items:center;gap:14px}.card-head span{font-size:13px;color:#8491a5}.issue{margin-bottom:8px}.mapping-tools{display:grid;grid-template-columns:320px 1fr auto;align-items:center;gap:14px;margin-bottom:13px}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:14px}.metrics>div{background:#f5f8fc;border-radius:10px;padding:16px}.metrics span,.metrics b{display:block}.metrics span{color:#7d8999}.metrics b{font-size:25px;margin-top:6px}.ok{color:#21946a}.danger{color:#d64b4b}.warning{color:#d98b22}.summary-row{background:#f7f9fc;padding:12px 14px;border-radius:8px}.error-table,.preview-table{margin-top:13px}.commit-bar{margin-top:16px}.batch-form{margin-top:16px}.percent-tip{margin-left:10px;color:#7d8999;font-size:12px}@media(max-width:1100px){.template-grid{grid-template-columns:repeat(2,1fr)}.upload-row{grid-template-columns:1fr}.mapping-tools{grid-template-columns:1fr}.metrics{grid-template-columns:repeat(2,1fr)}}
</style>
