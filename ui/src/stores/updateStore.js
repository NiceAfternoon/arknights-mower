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
      const res = await fetch('/api/update/status')
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
      const res = await fetch('/api/update/check')
      const result = await res.json()

      // 更新本地版本显示
      localVersion.value = result.local_version || ''
      localResTag.value = result.local_res_tag || ''

      // 记录当前时间并持久化到本地，更新上次检查时间
      const now = new Date().toLocaleString()
      lastCheckTime.value = now
      localStorage.setItem('last_update_check', now)

      // 校验是否有实际更新
      if (result.data && result.data.type !== 'none') {
        updateInfo.value = result.data
        return true
      }

      updateInfo.value = null
      return false
    } catch (error) {
      console.error('检查更新失败:', error)
      errorMsg.value = '无法连接到服务器检查更新'
      return false
    }
  }

  /**
   * 向后端发送开始更新的指令
   */
  const startUpdate = async () => {
    try {
      const res = await fetch('/api/update/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updateInfo.value)
      })

      if (res.ok) {
        // 指令发送成功后，开启定时器每秒拉取一次进度
        if (timer) clearInterval(timer)
        timer = setInterval(fetchStatus, 1000)
      }
    } catch (error) {
      console.error('启动更新失败:', error)
      errorMsg.value = '网络请求失败，无法启动更新'
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
