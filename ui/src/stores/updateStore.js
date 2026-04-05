import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useUpdateStore = defineStore('update', () => {
  const status = ref('idle')
  const progress = ref(0)
  const errorMsg = ref('')

  const localVersion = ref('')
  const localResTag = ref('')
  const updateInfo = ref(null)
  const lastCheckTime = ref(localStorage.getItem('last_update_check') || '')

  let timer = null

  const stopPolling = () => {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  }

  const fetchStatus = async () => {
    try {
      const res = await fetch('/update/status')
      const data = await res.json()

      status.value = data.status
      progress.value = data.progress
      errorMsg.value = data.error || ''

      // 非运行状态时，终止定时轮询
      if (['idle', 'ready_to_restart', 'error'].includes(data.status)) {
        stopPolling()
      }
    } catch (error) {
      console.error('获取更新进度失败:', error)
    }
  }

  const checkUpdate = async () => {
    try {
      const res = await fetch('/update/check') 
      const result = await res.json()

      if (result.code !== 200) throw new Error(result.msg || '后端检查失败')

      localVersion.value = result.local_version || ''
      localResTag.value = result.local_res_tag || ''

      const now = new Date().toLocaleString()
      lastCheckTime.value = now
      localStorage.setItem('last_update_check', now)

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

  const startUpdate = async () => {
    if (!updateInfo.value) return

    try {
      // 启动前重置前端状态
      errorMsg.value = ''
      progress.value = 0
      
      const res = await fetch('/update/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updateInfo.value)
      })

      const result = await res.json()
      
      if (res.ok && result.code === 200) {
        stopPolling() // 确保不会存在多个定时器实例
        timer = setInterval(fetchStatus, 1000)
      } else {
        errorMsg.value = result.msg || '启动下载失败'
      }
    } catch (error) {
      console.error('启动更新失败:', error)
      errorMsg.value = '网络请求失败'
    }
  }

  return {
    status,
    progress,
    errorMsg,
    localVersion,
    localResTag,
    updateInfo,
    lastCheckTime,
    checkUpdate,
    startUpdate,
    stopPolling
  }
})