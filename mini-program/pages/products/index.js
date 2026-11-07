const request = require('../../utils/request')
const { apiBase } = require('../../config')

Page({
  data:{products:[],categories:[],keyword:'',category:'',loading:true,apiBase},
  onShow(){this.load()}, onPullDownRefresh(){this.load().finally(wx.stopPullDownRefresh)},
  async load(){
    this.setData({loading:true})
    try{
      const query=[]
      if(this.data.keyword)query.push(`keyword=${encodeURIComponent(this.data.keyword)}`)
      if(this.data.category)query.push(`category=${encodeURIComponent(this.data.category)}`)
      const data=await request(`/api/mini/products${query.length?'?'+query.join('&'):''}`)
      const products=data.products.filter(row=>row.units.length).map(row=>({...row,unitIndex:0,units:row.units.map(unit=>({...unit,label:unit.available?`${unit.name}  ¥${Number(unit.price).toFixed(2)}`:`${unit.name}  待定价`,priceText:unit.price==null?'待定':Number(unit.price).toFixed(2)}))}))
      this.setData({products,categories:data.categories})
    }catch(error){
      if(String(error.message).includes('绑定')) wx.navigateTo({url:'/pages/bind/index'})
      else wx.showModal({title:'加载失败',content:error.message,showCancel:false})
    }finally{this.setData({loading:false})}
  },
  onKeyword(e){this.setData({keyword:e.detail.value})}, search(){this.load()},
  chooseCategory(e){this.setData({category:e.currentTarget.dataset.value},()=>this.load())},
  chooseUnit(e){const key=`products[${e.currentTarget.dataset.index}].unitIndex`;this.setData({[key]:Number(e.detail.value)})},
  addCart(e){
    const product=this.data.products[e.currentTarget.dataset.index],unit=product.units[product.unitIndex]
    const cart=wx.getStorageSync('mini_cart')||[]
    const existing=cart.find(row=>row.product_id===product.id)
    if(existing&&existing.unit_id===unit.id)existing.quantity+=1
    else if(existing)Object.assign(existing,{unit_id:unit.id,unit_name:unit.name,price:unit.price,quantity:1})
    else cart.push({product_id:product.id,name:product.name,image_url:product.image_url,unit_id:unit.id,unit_name:unit.name,price:unit.price,quantity:1})
    wx.setStorageSync('mini_cart',cart);wx.showToast({title:'已加入购物车'})
  }
})
