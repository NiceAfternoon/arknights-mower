# Commit 消息规范

> 约束文档：仓库内所有 commit 消息统一遵循此规范。配套的卡片式记忆在 Claude 的 memory 目录（`commit-convention.md`），此处为仓库内持久化版本。

本仓库所有 commit 消息遵循【约定式提交】（Conventional Commits，中文 v1.0.0-beta.4）。

## 格式

`<type>[scope]: 简短描述`，空一行后正文，可选 `Refs: #ticket` 脚注。

- **type**：`feat` / `fix` / `build` / `chore` / `docs` / `style` / `refactor` / `perf` / `test`。
- **scope**：改动所属组件（如 `ui`、`config`、`device`、`recognition`、`utils`、`plan`）。
- **标题**：简短、不带 `——` 子句、不堆术语，用中文（贴合仓库）。

## 正文讲「为什么改」

正文写**动机 / 问题 / 事故 / 痛点（大白话）**，再写怎么解决。不要堆行话、不要复述 diff。例：

```
fix(plan): 导出图被改过后无法导入

某展示图把数据编码成二维码贴图内，图被第三方改过（更大画布/压缩）后导回失败。
原因 a、b…… 改成按几何位置聚簇排序 + 多档放大重扫，导出不变、旧图全部兼容。
```

## 其他约定

- **去掉所有 `Co-Authored-By` trailer**。
- **票号放 `Refs:` 脚注**（如 `Refs: #166`），不塞进标题；多票用空格分隔。
- 改历史 commit 消息 = 纯 reword（树 diff 为空）；改完 force-push 到 fork/alpha，并同步更新相关票的 Resolution 与 map body 里引用的 SHA。
