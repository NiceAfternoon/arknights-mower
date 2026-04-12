<script setup>
import { storeToRefs } from 'pinia'
import { NTag } from 'naive-ui'
import { computed, h, inject, ref } from 'vue'
import { useConfigStore } from '@/stores/config'
import WeeklyPlanSelector from './WeeklyPlanSelector.vue'

const store = useConfigStore()
const { maa_weekly_plan, maa_enable, maa_expiring_medicine, exipring_medicine_on_weekend } =
  storeToRefs(store)

const mobile = inject('mobile')

const weekdays = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
const presetStages = [
  '',
  'Annihilation',
  '1-7',
  'LS-6',
  'CE-6',
  'AP-5',
  'SK-5',
  'CA-5',
  'PR-A-2',
  'PR-A-1',
  'PR-B-2',
  'PR-B-1',
  'PR-C-2',
  'PR-C-1',
  'PR-D-2',
  'PR-D-1'
]

const copyDialogVisible = ref(false)
const copyStageValue = ref('')
const copySourceWeekday = ref('')
const copyTargetDays = ref([])

const currentWeekdayIndex = computed(() => {
  const day = new Date().getDay()
  return day === 0 ? 6 : day - 1
})

const stageOptions = computed(() =>
  presetStages.map((value) => ({
    label: formatStageLabel(value),
    value
  }))
)

function formatStageLabel(value) {
  if (value === '') {
    return '上次作战'
  }
  if (value === 'Annihilation') {
    return '剿灭'
  }
  if (typeof value === 'string' && value.endsWith('-HARD')) {
    return `${value.slice(0, -5)} 困难`
  }
  if (typeof value === 'string' && value.endsWith('-NORMAL')) {
    return `${value.slice(0, -7)} 标准`
  }
  return value
}

function normalizeCreatedStage(label) {
  if (label === ' ' || label === '上次作战') {
    return ''
  }
  if (label === '剿灭') {
    return 'Annihilation'
  }
  if (label.endsWith('困难')) {
    return `${label.slice(0, -2)}-HARD`
  }
  if (label.endsWith('标准')) {
    return `${label.slice(0, -2)}-NORMAL`
  }
  return label
}

function createTag(label) {
  const value = normalizeCreatedStage(label.trim())
  return {
    label: formatStageLabel(value),
    value
  }
}

function renderStageTag(plan) {
  return ({ option, handleClose }) =>
    h(
      NTag,
      {
        type: isToday(plan.weekday) ? 'error' : 'default',
        closable: true,
        bordered: false,
        onMousedown: (event) => {
          event.preventDefault()
        },
        onContextmenu: (event) => {
          openCopyDialog(plan, option.value, event)
        },
        onClose: (event) => {
          event.stopPropagation()
          handleClose()
        }
      },
      {
        default: () => formatStageLabel(option.value)
      }
    )
}

function isToday(weekday) {
  return weekdays[currentWeekdayIndex.value] === weekday
}

function openCopyDialog(plan, stage, event) {
  event.preventDefault()
  copySourceWeekday.value = plan.weekday
  copyStageValue.value = stage
  copyTargetDays.value = maa_weekly_plan.value
    .filter((item) => Array.isArray(item.stage))
    .filter((item) => item.stage.includes(stage))
    .map((item) => item.weekday)
  copyDialogVisible.value = true
}

function toggleSelectAllCopyDays(checked) {
  copyTargetDays.value = checked ? [...weekdays] : []
}

function applyStageToSelectedDays() {
  for (const weekday of weekdays) {
    const plan = maa_weekly_plan.value.find((item) => item.weekday === weekday)
    if (!plan) {
      continue
    }
    if (!Array.isArray(plan.stage)) {
      plan.stage = []
    }
    const shouldInclude = copyTargetDays.value.includes(weekday)
    const alreadyIncluded = plan.stage.includes(copyStageValue.value)
    if (shouldInclude && !alreadyIncluded) {
      plan.stage = [...plan.stage, copyStageValue.value]
    } else if (!shouldInclude && alreadyIncluded) {
      plan.stage = plan.stage.filter((stage) => stage !== copyStageValue.value)
    }
  }
  closeCopyDialog()
}

function closeCopyDialog() {
  copyDialogVisible.value = false
  copyTargetDays.value = []
  copySourceWeekday.value = ''
  copyStageValue.value = ''
}
</script>

<template>
  <n-card>
    <template #header>
      <n-checkbox v-model:checked="maa_enable">
        <div class="card-title">刷理智周计划</div>
      </n-checkbox>
      <help-text>
        <div>支持 MAA 支持的所有关卡。</div>
        <div>操作流程：</div>
        <div>1. 先在“方案”里选择已有方案，或输入新方案名后按回车创建。</div>
        <div>2. 在每天的关卡栏里可直接下拉选择，也可以手动输入后回车生成关卡标签。</div>
        <div>3. 右键关卡标签，可快速追加或移除到其他日期。</div>
        <div>4. 每天可分别设置吃药次数和体力阈值（敬请期待）。</div>
      </help-text>
      <n-button
        text
        tag="a"
        href="https://m.prts.wiki/w/%E5%85%B3%E5%8D%A1%E4%B8%80%E8%A7%88/%E8%B5%84%E6%BA%90%E6%94%B6%E9%9B%86"
        target="_blank"
        type="primary"
        class="prts-wiki-link"
      >
        <div class="prts-wiki-link-text">PRTS.wiki：关卡一览 / 资源收集</div>
      </n-button>
    </template>
    <n-form
      :label-placement="mobile ? 'top' : 'left'"
      :show-feedback="false"
      label-width="72"
      label-align="left"
    >
      <n-form-item :show-label="false">
        <n-flex class="weekly-plan-toolbar" align="center">
          <n-checkbox v-model:checked="maa_expiring_medicine">使用将要过期的理智药</n-checkbox>
          <n-checkbox
            v-model:checked="exipring_medicine_on_weekend"
            :disabled="!maa_expiring_medicine"
          >
            周末使用
          </n-checkbox>
          <div class="weekly-plan-selector-wrap">
            <WeeklyPlanSelector compact />
          </div>
        </n-flex>
      </n-form-item>
    </n-form>

    <table class="weekly-plan-table">
      <thead>
        <tr>
          <th class="weekday-column">日期</th>
          <th>关卡</th>
          <th class="number-column">每次吃药</th>
          <th class="number-column">体力阈值</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="plan in maa_weekly_plan" :key="plan.weekday">
          <td class="weekday-column">
            <span class="weekday-pill" :class="{ 'today-pill': isToday(plan.weekday) }">
              {{ plan.weekday }}
            </span>
          </td>
          <td>
            <n-select
              v-model:value="plan.stage"
              multiple
              filterable
              tag
              :options="stageOptions"
              :render-tag="renderStageTag(plan)"
              :on-create="createTag"
            />
          </td>
          <td class="number-column">
            <n-input-number v-model:value="plan.medicine" :min="0" :max="999" :show-button="false">
              <template #suffix>药</template>
            </n-input-number>
          </td>
          <td class="number-column">
            <n-input-number
              v-model:value="plan.sanity_threshold"
              :min="0"
              :max="189"
              :show-button="false"
            >
              <template #suffix>理智</template>
            </n-input-number>
          </td>
        </tr>
      </tbody>
    </table>

    <n-modal
      v-model:show="copyDialogVisible"
      preset="card"
      title="追加到其他日期"
      :style="{ width: '320px', maxWidth: 'calc(100vw - 32px)' }"
      :mask-closable="false"
    >
      <n-space vertical :size="12">
        <div>
          关卡：<b>{{ formatStageLabel(copyStageValue) }}</b>
        </div>
        <div>
          来源日期：<b>{{ copySourceWeekday }}</b>
        </div>
        <n-checkbox
          :checked="copyTargetDays.length === weekdays.length"
          :indeterminate="copyTargetDays.length > 0 && copyTargetDays.length < weekdays.length"
          @update:checked="toggleSelectAllCopyDays"
        >
          全选
        </n-checkbox>
        <n-checkbox-group v-model:value="copyTargetDays">
          <n-space vertical>
            <n-checkbox v-for="weekday in weekdays" :key="weekday" :value="weekday">
              {{ weekday }}
            </n-checkbox>
          </n-space>
        </n-checkbox-group>
        <n-flex justify="end">
          <n-button @click="closeCopyDialog">取消</n-button>
          <n-button type="primary" @click="applyStageToSelectedDays">确认追加</n-button>
        </n-flex>
      </n-space>
    </n-modal>
  </n-card>
</template>

<style scoped lang="scss">
.weekly-plan-table {
  width: 100%;
  border-collapse: collapse;

  th,
  td {
    padding: 8px 6px;
    vertical-align: middle;
  }
}

.weekday-column {
  width: 88px;
  white-space: nowrap;
}

.number-column {
  width: 92px;
}

.weekday-pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 48px;
  padding: 4px 10px;
  border-radius: 8px;
}

.today-pill {
  border-radius: 8px;
  border: 1px solid #d03050;
  color: #d03050;
  background: rgba(208, 48, 80, 0.05);
  font-weight: 600;
}

.weekly-plan-toolbar {
  width: 100%;
  flex-wrap: nowrap;
}

.weekly-plan-selector-wrap {
  flex: 1;
  min-width: 0;
}

.prts-wiki-link {
  margin: 8px 0;
  flex-shrink: 1;
  min-width: 0;
}

.prts-wiki-link-text {
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
