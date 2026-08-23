<script setup>
import { onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import { useResourceVersionStore } from '@/stores/resourceVersion'

const resource_store = useResourceVersionStore()
const { info, loading, installing, install_message } = storeToRefs(resource_store)
const { loadResourceVersion, installResource } = resource_store

onMounted(() => {
  loadResourceVersion()
})
</script>

<template>
  <n-card title="资源包版本">
    <n-form :show-feedback="false" label-placement="left" label-width="72">
      <n-form-item label="当前版本">
        <span>{{ info.current_display || '未安装' }}</span>
        <span v-if="info.current_version" class="hint">（{{ info.current_version }}）</span>
      </n-form-item>
      <n-form-item label="最新版本">
        <span>{{ info.remote_display || '—' }}</span>
        <span v-if="info.remote_version" class="hint">（{{ info.remote_version }}）</span>
      </n-form-item>
      <n-form-item label="状态">
        <n-tag v-if="info.update_available === true" type="warning">可更新</n-tag>
        <n-tag v-else-if="info.update_available === false" type="success">已是最新</n-tag>
        <n-tag v-else type="error">{{ info.error || '检查失败' }}</n-tag>
      </n-form-item>
      <n-form-item :show-label="false">
        <n-space>
          <n-button size="small" :loading="loading" @click="loadResourceVersion(true)">
            检查更新
          </n-button>
          <n-button
            v-if="info.update_available === true"
            size="small"
            type="primary"
            :loading="installing"
            @click="installResource"
          >
            下载并安装
          </n-button>
        </n-space>
      </n-form-item>
      <n-form-item v-if="install_message" :show-label="false">
        <span>{{ install_message }}</span>
      </n-form-item>
    </n-form>
  </n-card>
</template>

<style scoped>
.hint {
  font-size: 12px;
  opacity: 0.6;
}
</style>
