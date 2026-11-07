const request=require('../../utils/request')
const pad=n=>String(n).padStart(2,'0')
const dateText=date=>`${date.getFullYear()}-${pad(date.getMonth()+1)}-${pad(date.getDate())}`
Page({
  data:{cart:[],today:'',deliveryDate:'',notes:'',total:'0.00',submitting:false},
  onShow(){const today=dateText(new Date());this.setData({today,deliveryDate:this.data.deliveryDate||today,cart:wx.getStorageSync('mini_cart')||[]},this.recount)},
  recount(){const cart=this.data.cart.map((row,index)=>({...row,cart_key:row.cart_key||`${row.product_id}-${row.unit_id}-${index}`}));this.setData({cart,total:cart.reduce((sum,row)=>sum+Number(row.price)*Number(row.quantity),0).toFixed(2)});wx.setStorageSync('mini_cart',cart)},
  plus(e){const key=`cart[${e.currentTarget.dataset.index}].quantity`;this.setData({[key]:this.data.cart[e.currentTarget.dataset.index].quantity+1},this.recount)},
  minus(e){const index=e.currentTarget.dataset.index,current=this.data.cart[index].quantity;if(current<=1)return;this.setData({[`cart[${index}].quantity`]:current-1},this.recount)},
  remove(e){const cart=[...this.data.cart];cart.splice(e.currentTarget.dataset.index,1);this.setData({cart},this.recount)},
  itemRemarkChange(e){const key=`cart[${e.currentTarget.dataset.index}].remark`;this.setData({[key]:e.detail.value},this.recount)},
  dateChange(e){this.setData({deliveryDate:e.detail.value})},notesChange(e){this.setData({notes:e.detail.value})},goProducts(){wx.switchTab({url:'/pages/products/index'})},
  async submit(){
    this.setData({submitting:true})
    try{
      const data=await request('/api/mini/orders',{method:'POST',data:{external_order_no:`MP-${Date.now()}-${Math.random().toString(16).slice(2,8)}`,delivery_date:this.data.deliveryDate,notes:this.data.notes,items:this.data.cart.map(row=>({product_id:row.product_id,unit_id:row.unit_id,quantity:row.quantity,remark:(row.remark||'').trim()||null}))}})
      wx.removeStorageSync('mini_cart');this.setData({cart:[],notes:''});wx.showModal({title:data.merged?'加单成功':'下单成功',content:data.merged?`商品已作为加单合并到 ${data.order_no}，后台和分拣任务已同步更新。`:`订单号：${data.order_no}`,showCancel:false,success:()=>wx.switchTab({url:'/pages/orders/index'})})
    }catch(error){wx.showModal({title:'提交失败',content:error.message,showCancel:false})}finally{this.setData({submitting:false})}
  }
})
