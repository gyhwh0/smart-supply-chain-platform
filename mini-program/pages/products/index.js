const request = require('../../utils/request')
const { apiBase } = require('../../config')

Page({
  data:{products:[],categories:[],keyword:'',category:'',loading:true,apiBase,specVisible:false,selectedProduct:null,specUnitIndex:0,specQuantity:1,specRemark:'',specSubtotal:'0.00'},
  onShow(){this.load()}, onPullDownRefresh(){this.load().finally(wx.stopPullDownRefresh)},
  async load(){
    this.setData({loading:true})
    try{
      const query=[]
      if(this.data.keyword)query.push(`keyword=${encodeURIComponent(this.data.keyword)}`)
      if(this.data.category)query.push(`category=${encodeURIComponent(this.data.category)}`)
      const data=await request(`/api/mini/products${query.length?'?'+query.join('&'):''}`)
      const products=data.products.filter(row=>row.units.length).map(row=>{
        const units=row.units.map(unit=>({...unit,label:unit.available?`${unit.name}  ¥${Number(unit.price).toFixed(2)}`:`${unit.name}  待定价`,priceText:unit.price==null?'待定':Number(unit.price).toFixed(2)}))
        const prices=units.filter(unit=>unit.available).map(unit=>Number(unit.price))
        const priceText=!prices.length?'待定价':Math.min(...prices)===Math.max(...prices)?`¥${Math.min(...prices).toFixed(2)}`:`¥${Math.min(...prices).toFixed(2)} 起`
        return {...row,units,priceText}
      })
      this.setData({products,categories:data.categories})
    }catch(error){
      if(String(error.message).includes('绑定')) wx.navigateTo({url:'/pages/bind/index'})
      else wx.showModal({title:'加载失败',content:error.message,showCancel:false})
    }finally{this.setData({loading:false})}
  },
  onKeyword(e){this.setData({keyword:e.detail.value})}, search(){this.load()},
  chooseCategory(e){this.setData({category:e.currentTarget.dataset.value},()=>this.load())},
  openSpec(e){
    const product=this.data.products[Number(e.currentTarget.dataset.index)]
    const first=product.units.findIndex(unit=>unit.available)
    const index=first<0?0:first
    this.setData({specVisible:true,selectedProduct:product,specUnitIndex:index,specQuantity:1,specRemark:'',specSubtotal:Number(product.units[index].price||0).toFixed(2)})
  },
  closeSpec(){this.setData({specVisible:false,selectedProduct:null})},
  stop(){},
  updateSubtotal(index,quantity){return (Number(this.data.selectedProduct.units[index].price||0)*Number(quantity||0)).toFixed(2)},
  selectSpec(e){const index=Number(e.currentTarget.dataset.index);if(this.data.selectedProduct.units[index].available)this.setData({specUnitIndex:index,specSubtotal:this.updateSubtotal(index,this.data.specQuantity)})},
  quantityInput(e){const value=Number(e.detail.value)>0?Number(e.detail.value):1;this.setData({specQuantity:value,specSubtotal:this.updateSubtotal(this.data.specUnitIndex,value)})},
  minusQuantity(){const value=Math.max(0.1,Number(this.data.specQuantity||1)-1);this.setData({specQuantity:value,specSubtotal:this.updateSubtotal(this.data.specUnitIndex,value)})},
  plusQuantity(){const value=Number(this.data.specQuantity||0)+1;this.setData({specQuantity:value,specSubtotal:this.updateSubtotal(this.data.specUnitIndex,value)})},
  remarkInput(e){this.setData({specRemark:e.detail.value})},
  addCart(){
    const product=this.data.selectedProduct,unit=product.units[this.data.specUnitIndex],quantity=Number(this.data.specQuantity)
    if(!unit.available)return wx.showToast({title:'该规格暂未设置销售价',icon:'none'})
    if(!quantity||quantity<=0)return wx.showToast({title:'请输入正确数量',icon:'none'})
    const remark=(this.data.specRemark||'').trim()
    const cart=wx.getStorageSync('mini_cart')||[]
    const existing=cart.find(row=>row.product_id===product.id&&row.unit_id===unit.id&&(row.remark||'')===remark)
    if(existing)existing.quantity=Number(existing.quantity)+quantity
    else cart.push({cart_key:`${product.id}-${unit.id}-${Date.now()}`,product_id:product.id,name:product.name,image_url:product.image_url,unit_id:unit.id,unit_name:unit.name,price:unit.price,quantity,remark})
    wx.setStorageSync('mini_cart',cart);this.closeSpec();wx.showToast({title:'已加入购物车'})
  }
})
