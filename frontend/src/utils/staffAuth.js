const TOKEN_KEY='jiacai_staff_token'
const STAFF_KEY='jiacai_staff_profile'

export const getStaffToken=()=>localStorage.getItem(TOKEN_KEY)||''
export const getStaffProfile=()=>{try{return JSON.parse(localStorage.getItem(STAFF_KEY)||'null')}catch{return null}}
export const setStaffSession=(token,staff)=>{localStorage.setItem(TOKEN_KEY,token);localStorage.setItem(STAFF_KEY,JSON.stringify(staff))}
export const clearStaffSession=()=>{localStorage.removeItem(TOKEN_KEY);localStorage.removeItem(STAFF_KEY)}
export const staffAuthConfig=()=>({headers:{Authorization:`Bearer ${getStaffToken()}`}})
