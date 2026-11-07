<template>
  <div>
    <div class="page-header"><div><h2>采购订单</h2><p>查看采购员已经确认并正式下达给本供应商的订单</p></div><el-button type="primary" @click="load">刷新</el-button></div>
    <el-card class="panel"><el-table :data="rows" row-key="id"><el-table-column type="expand"><template #default="s"><el-table :data="s.row.items" size="small" border><el-table-column prop="product_name" label="商品"/><el-table-column prop="category" label="分类"/><el-table-column label="数量"><template #default="c">{{c.row.quantity}} {{c.row.unit_name}}</template></el-table-column><el-table-column label="单价"><template #default="c">¥{{money(c.row.unit_price)}}</template></el-table-column><el-table-column label="金额"><template #default="c">¥{{money(c.row.amount)}}</template></el-table-column><el-table-column prop="remark" label="备注"/></el-table></template></el-table-column><el-table-column prop="order_no" label="采购单号" min-width="190"/><el-table-column prop="title" label="订单标题" min-width="180"/><el-table-column prop="expected_date" label="要求到货" width="120"/><el-table-column label="订单金额" width="140"><template #default="s"><b class="price">¥{{money(s.row.total_amount)}}</b></template></el-table-column><el-table-column label="下达时间" min-width="170"><template #default="s">{{time(s.row.confirmed_at)}}</template></el-table-column><el-table-column label="操作" width="180"><template #default="s"><el-button link @click="download(s.row,'png')">下载图片</el-button><el-button link @click="download(s.row,'xlsx')">下载表格</el-button></template></el-table-column></el-table></el-card>
  </div>
</template>
<script setup>
import { onMounted,ref } from 'vue'
import { downloadOrderReport,getSupplierOrders } from '@/api'
const rows=ref([])
const money=v=>Number(v||0).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:4})
const time=v=>v?new Date(v).toLocaleString('zh-CN',{hour12:false}):'—'
const load=async()=>rows.value=await getSupplierOrders()
const download=async(row,format)=>{const blob=await downloadOrderReport(row.id,format);const url=URL.createObjectURL(blob);const link=document.createElement('a');link.href=url;link.download=`${row.order_no}.${format}`;link.click();URL.revokeObjectURL(url)}
onMounted(load)
</script>
<style scoped>.price{color:#df6539}</style>
