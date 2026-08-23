<script setup>
import { inject, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useConfigStore } from '@/stores/config'

const token = inject('token')
const manual_url = `${import.meta.env.VITE_HTTP_URL}/hot-update/manual`

const config_store = useConfigStore()
const { hot_update_enable } = storeToRefs(config_store)

const manual_result = ref('')

function on_manual_finish({ event }) {
  let text = '更新包应用失败'
  try {
    const data = JSON.parse(event.target.response)
    if (data && typeof data.message === 'string') {
      text = data.message
    }
  } catch (e) {
    // keep default failure text
  }
  manual_result.value = text
}
</script>

<template>
  <n-card title="手动更新">
    <n-form :show-feedback="false" label-placement="left" label-width="72">
      <n-form-item label="自动检查">
        <n-switch v-model:checked="hot_update_enable" />
        <span class="hint">打开 mower 时检查热更新</span>
      </n-form-item>
      <n-form-item label="手动应用">
        <n-upload
          style="width: 100%"
          :action="manual_url"
          :headers="{ token: token }"
          name="update"
          :show-file-list="false"
          @finish="on_manual_finish"
        >
          <n-upload-dragger>
            <div>点击或拖入更新包</div>
            <div class="hint">自动识别热更包 / 资源包，用于直连 GitHub 不稳时的兜底</div>
          </n-upload-dragger>
        </n-upload>
      </n-form-item>
      <n-form-item v-if="manual_result" :show-label="false">
        <span>{{ manual_result }}</span>
      </n-form-item>
    </n-form>
  </n-card>
</template>

<style scoped>
.hint {
  margin-left: 8px;
  font-size: 12px;
  opacity: 0.6;
}
</style>
