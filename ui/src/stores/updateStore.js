import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useUpdateStore = defineStore('update', () => {
  // ================= State (状态) =================
  const status = ref('idle')
  const progress = ref(0)
  const errorMsg = ref('')

  const localVersion = ref('')
  const localResTag = ref('')
  const updateInfo = ref(null)

  // 从 localStorage 初始化上次检查时间
  const lastCheckTime = ref(localStorage.getItem('last_update_check') || '')

  let timer = null

  // ================= Actions (动作) =================

  /**
   * 轮询获取后端下载/解压进度
   */
  const fetchStatus = async () => {
    try {
      const res = await fetch('/update/status')
      const data = await res.json()

      status.value = data.status
      progress.value = data.progress
      errorMsg.value = data.error || ''

      // 处于非运行状态时，停止轮询
      if (['idle', 'ready_to_restart', 'error'].includes(data.status)) {
        if (timer) clearInterval(timer)
      }
    } catch (error) {
      console.error('获取更新进度失败:', error)
    }
  }

  /**
   * 检查是否有新版本
   */
const checkUpdate = async () => {
    try {
      // 1. 修正路径（去掉 /api，或根据你实际后端情况调整）
      const res = await fetch('/update/check') 
      const result = await res.json()

      // 2. 增加业务状态码判断
      if (result.code !== 200) {
        throw new Error(result.msg || '后端检查失败')
      }

      localVersion.value = result.local_version || ''
      localResTag.value = result.local_res_tag || ''

      const now = new Date().toLocaleString()
      lastCheckTime.value = now
      localStorage.setItem('last_update_check', now)

      // 3. 校验 data 内部的逻辑
      // 注意：根据后端 api_check_update，数据都在 result.data 里
      if (result.data && result.data.type && result.data.type !== 'none') {
        updateInfo.value = result.data
        return true
      }

      updateInfo.value = null
      return false
    } catch (error) {
      console.error('检查更新失败:', error)
      errorMsg.value = error.message || '无法连接到服务器'
      return false
    }
  }

    /**
   * 向后端发送开始更新的指令
   */
  const startUpdate = async () => {
    if (!updateInfo.value) return

    try {
      // 1. 修正路径
      const res = await fetch('/update/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        // 2. 确保 updateInfo 内部有 type, asset, diff 等后端需要的 key
        body: JSON.stringify(updateInfo.value)
      })

      const result = await res.json()
      
      if (res.ok && result.code === 200) {
        if (timer) clearInterval(timer)
        timer = setInterval(fetchStatus, 1000)
      } else {
        errorMsg.value = result.msg || '启动下载失败'
      }
    } catch (error) {
      console.error('启动更新失败:', error)
      errorMsg.value = '网络请求失败'
    }
  }

  // ================= 暴露接口 =================
  return {
    // 状态
    status,
    progress,
    errorMsg,
    localVersion,
    localResTag,
    updateInfo,
    lastCheckTime,

    // 方法
    checkUpdate,
    startUpdate
  }
})
