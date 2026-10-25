<template>
  <div>
    <div class="page-header"><div><h2>{{pickingMode?'分拣二维码标签':'普通商品标签打印'}}</h2><p>{{pickingMode?'二维码供分拣员和配送员手机扫码确认':'普通标签不包含二维码，也可以完全自定义标签内容'}}</p></div><el-button type="primary" :disabled="!selectedLabels.length" @click="printLabels">打印所选标签（{{printCount}}张）</el-button></div>
    <el-card class="panel setup-card">
      <el-tabs v-model="mode"><el-tab-pane label="引用客户销售单" name="order"><div class="source-row"><el-select v-model="selectedOrderId" filterable placeholder="搜索销售单号或客户" style="width:430px" @change="loadOrderLabels"><el-option v-for="o in orders" :key="o.id" :label="`${o.order_no} · ${o.customer_code||''} ${o.customer_name} · ${o.delivery_date||'未定配送日'}`" :value="o.id"/></el-select><el-date-picker v-model="batchProductionDate" value-format="YYYY-MM-DD" placeholder="统一生产日期"/><el-button :disabled="!labels.length" @click="applyProductionDate">批量套用生产日期</el-button></div></el-tab-pane><el-tab-pane label="完全自定义" name="custom"><div class="source-row"><el-button type="primary" plain @click="addCustom">+ 添加空白自定义标签</el-button><span>所有文字、日期、数量和保质期都可以修改</span></div></el-tab-pane></el-tabs>
      <div class="print-settings"><span>标签类型</span><el-radio-group v-model="pickingMode"><el-radio-button :value="false">普通标签</el-radio-button><el-radio-button :value="true">分拣二维码标签</el-radio-button></el-radio-group><span>标签纸尺寸</span><el-select v-model="size" style="width:190px"><el-option v-for="item in sizeOptions" :key="item.value" :label="item.label" :value="item.value" :disabled="pickingMode&&!item.qr"/></el-select><span>统一份数</span><el-input-number v-model="batchCopies" :min="1" :max="100"/><el-button @click="applyCopies">应用到全部</el-button><el-button @click="selectAll">{{selectedIds.length===labels.length?'取消全选':'全选'}}</el-button></div>
    </el-card>

    <el-empty v-if="!labels.length" description="请选择一张销售单，或添加自定义标签"/>
    <div v-else class="workspace">
      <el-card class="editor panel"><div class="editor-title"><b>标签内容编辑</b><span>每一行代表一种商品，可单独设置打印份数</span></div><el-table :data="labels" @selection-change="selectionChanged" ref="tableRef"><el-table-column type="selection" width="45"/><el-table-column label="客户名称" min-width="150"><template #default="s"><el-input v-model="s.row.customer_name"/></template></el-table-column><el-table-column label="商品名称" min-width="150"><template #default="s"><el-input v-model="s.row.product_name"/></template></el-table-column><el-table-column label="数量" width="125"><template #default="s"><el-input v-model="s.row.quantity_text" placeholder="如20斤"/></template></el-table-column><el-table-column label="生产日期" width="150"><template #default="s"><el-date-picker v-model="s.row.production_date" value-format="YYYY-MM-DD" style="width:135px"/></template></el-table-column><el-table-column label="保质期" width="115"><template #default="s"><el-input-number v-model="s.row.shelf_life_days" :min="1" controls-position="right"/></template></el-table-column><el-table-column label="配送日期" width="150"><template #default="s"><el-date-picker v-model="s.row.delivery_date" value-format="YYYY-MM-DD" style="width:135px"/></template></el-table-column><el-table-column label="批次/附加文字" min-width="160"><template #default="s"><el-input v-model="s.row.custom_text" placeholder="批次、储存要求等"/></template></el-table-column><el-table-column label="份数" width="105"><template #default="s"><el-input-number v-model="s.row.copies" :min="1" :max="100" controls-position="right"/></template></el-table-column><el-table-column width="60"><template #default="s"><el-button link type="danger" @click="removeLabel(s.$index)">删除</el-button></template></el-table-column></el-table></el-card>
      <el-card class="preview panel"><div class="editor-title"><b>标签预览</b><span>显示前6张，实际打印按所选份数生成</span></div><div class="label-grid"><div v-for="label in selectedLabels.slice(0,6)" :key="label.key" class="food-label" :class="`size-${size}`"><div class="customer">{{label.customer_name||'客户名称'}}</div><div class="product">{{label.product_name||'商品名称'}}</div><div class="quantity">{{label.quantity_text||'数量'}}</div><div class="meta"><span>生产：{{label.production_date||'—'}}</span><span>保质期：{{label.shelf_life_days?`${label.shelf_life_days}天`:'—'}}</span><span>配送：{{label.delivery_date||'—'}}</span><span v-if="expiryDate(label)">到期：{{expiryDate(label)}}</span></div><div v-if="label.custom_text" class="custom">{{label.custom_text}}</div></div></div></el-card>
    </div>
  </div>
</template>

<script setup>
import { computed,nextTick,onMounted,ref,watch } from 'vue'
import { useRoute } from 'vue-router'
import QRCode from 'qrcode'
import { ElMessage } from 'element-plus'
import { getLabelSalesOrders } from '@/api'
const today=()=>new Date().toLocaleDateString('sv-SE')
const orders=ref([]),labels=ref([]),selectedIds=ref([]),selectedOrderId=ref(null),tableRef=ref(),mode=ref('order'),size=ref('50x30'),batchCopies=ref(1),batchProductionDate=ref(today())
const route=useRoute()
const pickingMode=ref(route.query.picking==='1')
const sizeOptions=[
  {label:'30 × 20 mm · 迷你',value:'30x20',qr:false},
  {label:'40 × 25 mm · 小号',value:'40x25',qr:false},
  {label:'40 × 30 mm · 小号二维码',value:'40x30',qr:true},
  {label:'50 × 25 mm · 长条',value:'50x25',qr:false},
  {label:'50 × 30 mm · 常用',value:'50x30',qr:true},
  {label:'60 × 30 mm · 长条',value:'60x30',qr:true},
  {label:'60 × 40 mm · 标准',value:'60x40',qr:true},
  {label:'70 × 40 mm · 大号',value:'70x40',qr:true},
  {label:'80 × 50 mm · 大号',value:'80x50',qr:true},
  {label:'100 × 60 mm · 特大',value:'100x60',qr:true},
]
watch(pickingMode,enabled=>{if(enabled&&!sizeOptions.find(item=>item.value===size.value)?.qr)size.value='40x30'})
let keySeed=1
const selectedLabels=computed(()=>labels.value.filter(l=>selectedIds.value.includes(l.key))),printCount=computed(()=>selectedLabels.value.reduce((n,l)=>n+Number(l.copies||1),0))
const makeLabel=data=>({key:keySeed++,customer_name:'',product_name:'',quantity_text:'',production_date:today(),shelf_life_days:null,delivery_date:null,custom_text:'',copies:1,picking_code:null,qr_data_url:null,...data})
const selectRows=async()=>{await nextTick();tableRef.value?.clearSelection();labels.value.forEach(row=>tableRef.value?.toggleRowSelection(row,true))}
const loadOrderLabels=async id=>{const order=orders.value.find(o=>o.id===id);if(!order)return;labels.value=await Promise.all(order.items.map(async item=>{const scanUrl=item.picking_code?`${window.location.origin}/scan-picking?code=${item.picking_code}`:null;return makeLabel({customer_name:order.customer_name,product_name:item.product_name,quantity_text:`${Number(item.quantity).toLocaleString('zh-CN',{maximumFractionDigits:2})}${item.unit_name}`,production_date:item.production_date||batchProductionDate.value,shelf_life_days:item.shelf_life_days,delivery_date:order.delivery_date,custom_text:[`单号：${order.order_no}`,item.batch_no?`批次：${item.batch_no}`:''].filter(Boolean).join(' · '),picking_code:item.picking_code,qr_data_url:scanUrl?await QRCode.toDataURL(scanUrl,{margin:0,width:240,errorCorrectionLevel:'M'}):null})}));if(pickingMode.value&&!order.picking_task_no)ElMessage.warning('该销售单还未生成分拣任务，无法打印分拣二维码；请先到“扫码分拣”生成任务');await selectRows()}
const addCustom=async()=>{labels.value.push(makeLabel({production_date:batchProductionDate.value}));await selectRows()}
const removeLabel=i=>{labels.value.splice(i,1);selectedIds.value=selectedIds.value.filter(id=>labels.value.some(l=>l.key===id))}
const selectionChanged=rows=>selectedIds.value=rows.map(r=>r.key)
const applyProductionDate=()=>{labels.value.forEach(l=>l.production_date=batchProductionDate.value);ElMessage.success('已批量设置生产日期')}
const applyCopies=()=>{labels.value.forEach(l=>l.copies=batchCopies.value);ElMessage.success('已批量设置打印份数')}
const selectAll=()=>selectedIds.value.length===labels.value.length?tableRef.value?.clearSelection():selectRows()
const expiryDate=label=>{if(!label.production_date||!label.shelf_life_days)return'';const d=new Date(`${label.production_date}T00:00:00`);d.setDate(d.getDate()+Number(label.shelf_life_days));return d.toLocaleDateString('sv-SE')}
const esc=value=>String(value??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]))
const printLabels=()=>{
  if(!selectedLabels.value.length)return
  if(pickingMode.value&&!selectedLabels.value.some(label=>label.qr_data_url))return ElMessage.warning('当前订单没有分拣二维码，请先生成分拣任务')
  const [sizeW,sizeH]=size.value.split('x').map(Number)
  const mini=sizeW<=40||sizeH<=25
  const compact=sizeW<=60||sizeH<=30
  const qrSize=sizeW<=40?14:sizeW<=60?16:20
  const padding=mini?1.5:compact?2.2:3
  const customerFont=mini?8:compact?10:12
  const productFont=mini?10:compact?13:17
  const quantityFont=mini?9:compact?11:15
  const metaFont=mini?5.5:compact?7:8.5
  const cards=[]
  selectedLabels.value.forEach(label=>{
    const withQr=Boolean(pickingMode.value&&label.qr_data_url)
    for(let i=0;i<Number(label.copies||1);i++)cards.push(`<section class="label ${withQr?'with-qr':''}"><div class="customer">${esc(label.customer_name)}</div><div class="product">${esc(label.product_name)}</div><div class="quantity">${esc(label.quantity_text)}</div><div class="meta"><span>生产：${esc(label.production_date||'—')}</span><span>保质：${esc(label.shelf_life_days?`${label.shelf_life_days}天`:'—')}</span><span>配送：${esc(label.delivery_date||'—')}</span>${expiryDate(label)?`<span>到期：${esc(expiryDate(label))}</span>`:''}</div>${label.custom_text?`<div class="custom">${esc(label.custom_text)}</div>`:''}${withQr?`<div class="qr"><img src="${label.qr_data_url}"><small>扫码分拣</small></div>`:''}</section>`)
  })
  const win=window.open('','_blank')
  if(!win)return ElMessage.error('浏览器拦截了打印窗口，请允许弹窗')
  win.document.write(`<!doctype html><html><head><meta charset="utf-8"><title>${pickingMode.value?'分拣二维码标签':'普通商品标签'}</title><style>@page{size:${sizeW}mm ${sizeH}mm;margin:0}*{box-sizing:border-box}body{margin:0;font-family:"Microsoft YaHei",sans-serif}.label{width:${sizeW}mm;height:${sizeH}mm;padding:${padding}mm;border:.25mm solid #111;page-break-after:always;overflow:hidden;position:relative}.customer{font-size:${customerFont}px;font-weight:700;border-bottom:.2mm solid #111;padding-bottom:${mini?0.6:1.2}mm;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.product{font-size:${productFont}px;font-weight:800;margin-top:${mini?0.6:1.2}mm;line-height:1.05}.quantity{position:absolute;right:${padding}mm;top:${mini?6.5:compact?9:12}mm;font-size:${quantityFont}px;font-weight:700}.meta{display:grid;grid-template-columns:1fr 1fr;gap:${mini?0.35:0.8}mm;font-size:${metaFont}px;line-height:1.1;margin-top:${mini?0.8:1.5}mm}.custom{font-size:${metaFont}px;margin-top:${mini?0.5:1}mm;border-top:.2mm dashed #777;padding-top:${mini?0.4:0.8}mm;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.with-qr .customer{padding-right:${qrSize+2}mm}.with-qr .product,.with-qr .meta,.with-qr .custom{max-width:calc(100% - ${qrSize+2}mm)}.with-qr .quantity{right:${qrSize+padding+2}mm}.qr{position:absolute;right:${padding}mm;bottom:${padding}mm;text-align:center;font-size:6px}.qr img{display:block;width:${qrSize}mm;height:${qrSize}mm}.qr small{font-size:6px}</style></head><body>${cards.join('')}</body></html>`)
  win.document.close();win.focus();setTimeout(()=>win.print(),400)
}
onMounted(async()=>{orders.value=await getLabelSalesOrders();const orderId=Number(route.query.order);if(orderId&&orders.value.some(row=>row.id===orderId)){selectedOrderId.value=orderId;await loadOrderLabels(orderId)}})
</script>

<style scoped>
.setup-card{margin-bottom:16px}.source-row,.print-settings{display:flex;align-items:center;gap:12px}.source-row span,.print-settings span{color:#7e8999}.print-settings{padding-top:15px;border-top:1px solid #edf0f4}.workspace{display:grid;grid-template-columns:minmax(0,1.65fr) minmax(360px,.85fr);gap:16px}.editor-title{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}.editor-title span{color:#8490a3;font-size:13px}.label-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}.food-label{border:1px solid #27364d;background:white;padding:12px;min-height:150px;position:relative;overflow:hidden}.food-label .customer{font-weight:700;border-bottom:1px solid #8190a4;padding-bottom:6px}.food-label .product{font-size:20px;font-weight:800;margin-top:9px}.food-label .quantity{position:absolute;right:12px;top:48px;font-size:17px;font-weight:700}.food-label .meta{display:grid;grid-template-columns:1fr 1fr;gap:5px;font-size:11px;margin-top:14px}.food-label .custom{font-size:11px;border-top:1px dashed #a8b1be;margin-top:8px;padding-top:6px}.food-label.size-50x30{min-height:115px}.food-label.size-100x60{min-height:190px}@media(max-width:1200px){.workspace{grid-template-columns:1fr}.label-grid{grid-template-columns:repeat(3,1fr)}}
</style>
