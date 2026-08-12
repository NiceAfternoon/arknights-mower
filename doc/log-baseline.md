# 日志降噪基线采集

`arknights_mower.log_baseline` 只采集和统计日志，不修改生产日志语义。原始日志、SQLite 快照与完整报告必须保存在仓库已忽略的 `.scratch/log-baseline/` 下。

## 采集一个窗口

先为每个窗口准备一个输入 manifest，例如 `.scratch/log-baseline/before-1-input.json`：

```json
{
  "window_id": "before-1",
  "phase": "before",
  "environment": {
    "simulator": "mumu-12-daily",
    "account_fingerprint": "sha256:<脱敏指纹>",
    "resolution": "1920x1080",
    "performance_profile": "4c6g-60fps",
    "mower_config_fingerprint": "sha256:<conf.yml 哈希>",
    "code_revision": "<git rev-parse HEAD>",
    "log_config_fingerprint": "sha256:<日志配置哈希>"
  },
  "workload": {
    "infrastructure_read": true,
    "shift_completed": true,
    "native_agent_rounds": 3,
    "maa_completed": false,
    "maa_duration_seconds": 600,
    "webui_connected_throughout": true
  }
}
```

`account_fingerprint` 只能填写别名或不可逆指纹，不得填写账号、UID 或凭证。三个改造前窗口的 `environment` 必须完全相同。

在 PowerShell 中从仓库根目录启动采集：

```powershell
.\venv\Scripts\python.exe -m arknights_mower.log_baseline capture `
  --live-log-dir log `
  --database tmp\data.db `
  --output-dir .scratch\log-baseline\before-1 `
  --manifest .scratch\log-baseline\before-1-input.json `
  -- .\venv\Scripts\python.exe webview_ui.py
```

采集器会冷启动命令、监测 Mower 进程 CPU 与峰值 RSS、抽取本次运行新增的 `runtime.log*` 原始字节，并在进程退出后备份 SQLite。正常完成规定工作负载后，通过 WebUI 正常退出。有效窗口须持续 7200–7500 秒；过短、超时、缺工作负载或异常退出都会生成报告，但命令返回非零状态。

每个输出目录包含：

- `manifest.json`：采集器写入的实际起止时间、CPU、RSS、冷启动和退出结果；
- `log/runtime.log*`：仅包含窗口内新增字节；
- `data.db`：退出后的 SQLite 一致性快照；
- `report.json`：实际文件字节、逻辑记录、平均事件字节、SQLite 指标及调用点 Pareto。

依次采集 `before-1`、`before-2`、`before-3`。同组三次之间不得修改代码、日志配置、模拟器、账号、分辨率、性能或 Mower 配置。

## 冻结 ledger

从三份 `report.json` 的 Pareto 创建本地声明文件。每行必须包含以下字段：

```json
{
  "source": "arknights_mower/utils/recognize.py:709",
  "function": "find",
  "level": "DEBUG",
  "message_shape": "find: connecting",
  "target_message_shape": "<silent>",
  "category": "visual_device_core",
  "consumers": ["text"],
  "decision": "include",
  "reason": "dominant low-level success noise",
  "change": "silent",
  "bounded_fields": [],
  "test": "high-level recognition result contract",
  "selection_basis": "scope_required"
}
```

非静默目标必须为每个占位符给出逐字段上限，例如：

```json
{
  "target_message_shape": "task={task_type} elapsed_seconds={elapsed_seconds}",
  "change": "progress_summary",
  "bounded_fields": [
    {"name": "task_type", "kind": "string", "max_length": 32},
    {"name": "elapsed_seconds", "kind": "integer", "minimum": 0, "maximum": 7500}
  ]
}
```

字段描述允许 `boolean`、带上下界的 `integer`、带 `max_length` 的 `string`、显式有限值的 `enum`，以及带 `max_items` 和有限 `items` 描述的 `list`。每行自行声明与语义相符的上限；检查器不施加全局字符数或项目数上限。

声明文件使用对象外壳：`rows` 保存六类 ledger 行，`out_of_scope_rules` 只用于给完整稳定残余 Pareto 中不属于六类的 selector 分类。每条范围外规则必须同时给出 `source`、`function`、`level`、`message_shape` 的完整匹配正则和非空理由。任何既没有 ledger 行、也没有被唯一范围外规则覆盖的稳定 selector 都会阻止冻结；范围外 selector 不参与最小补差集合。

```json
{
  "rows": [],
  "out_of_scope_rules": [
    {
      "source": "arknights_mower/other\\.py:[0-9]+",
      "function": "health_check",
      "level": "INFO",
      "message_shape": "healthy",
      "reason": "不属于本轮六类源码范围"
    }
  ]
}
```

允许的 `category` 为 `visual_device_core`、`visual_intermediate`、`object_dump`、`scheduler_state_sqlite`、`repeated_polling` 和 `retry_error_duplication`。体积主范围使用 `scope_required`；超过双 95% 截止线、但为避免同一源码范围出现两套日志语义而继续纳入的稳定行使用 `scope_consistency`。只有门槛不足时追加的最小稳定补差行使用 `pareto_gap`；移除后仍能过门槛的冗余补差行会被拒绝。

执行冻结检查：

```powershell
.\venv\Scripts\python.exe -m arknights_mower.log_baseline freeze `
  --report .scratch\log-baseline\before-1\report.json `
  --report .scratch\log-baseline\before-2\report.json `
  --report .scratch\log-baseline\before-3\report.json `
  --declaration .scratch\log-baseline\ledger-declaration.json `
  --output .scratch\log-baseline\ledger.json
```

冻结检查固定使用 95% 门槛，不提供降低阈值的参数。三份报告必须具有唯一的窗口 ID、带时区的起止时间且互不重叠。非静默目标形状必须用 `{field}` 声明全部有限字段，并与 `bounded_fields` 一一对应；对象或列表 dump、`repr/str`、自由扩展字段和截断输出会被拒绝。`scope_consistency` 行参与改造和覆盖率，但不冒充门槛不足时的 `pareto_gap` 补差行。检查器仍会在所有三窗口稳定的残余候选中搜索最少 `pareto_gap` 集合，并把推荐 selector 写入 `residual_pareto`。

只有三窗均有效、环境完全一致，且纳入行在每窗同时覆盖至少 95% 的逻辑记录和实际文件字节时，命令才返回成功。
