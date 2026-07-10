# 执行计划：日报正式发布与异常快照隔离

**依据：** PRD `2026-07-10-failure-snapshot-publication-policy-prd.md` 与 TDD `2026-07-10-failure-snapshot-publication-policy-tdd.md`
**执行约束：** 不提交、不推送；不暂存 `resources/notice_records.csv`。

## 批次一：发布资格与状态库备份

1. 新增纯函数发布判定模块，区分 Python 运行资格与 workflow 最终发布结果。
2. 将资格和阻断原因写入 CLI 与 run summary v2，保持原有计数与退出码语义兼容。
3. 新增 SQLite 一致性备份 API，使用 `sqlite3.backup` 并验证完整性。
4. 先补充单元测试，覆盖阻断矩阵、稳定 blocker 顺序、run summary 字段、CLI 输出和 SQLite 备份。

**完成标准：** Python 层可独立判定 `published`、`no_report`、`blocked`，且不依赖 GitHub 环境。

## 批次二：异常快照构建工具

1. 新增可测试的快照构建模块与命令行脚本，负责日志脱敏、fallback run summary、`publication.json`、`metadata.md`、SQLite 快照和可选部分报告。
2. 新增快照目录保留清理工具，仅删除格式合法且超过 90 天的目录。
3. 使用临时目录测试正常快照、缺失状态库、未生成 run summary、Secret 脱敏和保留边界。

**完成标准：** 不依赖 GitHub 网络即可从一次失败运行的本地产物构造可上传的完整快照目录。

## 批次三：GitHub Actions 发布编排

1. 将 pipeline 输出解析、发布资格判定和最终发布判定集中为 workflow 输出。
2. 将 `published`、`no_report`、`blocked` 分为互斥路径：正式状态只写 `master`；blocked 路径只写 Artifact 与 `bot/failure-snapshots`。
3. 加入第二 checkout、显式暂存、90 天清理、一次 fetch/rebase/push 重试和失败告警。
4. 将异常邮件改为读取已脱敏快照资料，明确“日报未发布；master 正式状态未更新”。
5. 用 workflow 静态测试锁定条件、路径、Git 命令和步骤顺序。

**完成标准：** 源站级异常或致命巡检异常绝不会发送日报或污染 `master`；异常现场可从 Artifact 和独立分支获得。

## 批次四：端到端验证与文档回写

1. 跑完整 pytest、编译检查、doctor 和 diff 检查。
2. 使用临时目录与模拟 CLI 输出覆盖成功、正常无通知、源站异常、巡检异常、单条人工复核五类发布判定。
3. 对照 PRD/TDD 逐项检查实际接口、目录、保留策略和邮件字段；必要时同步修正设计文档。

**完成标准：** 全量自动测试通过，所有 PRD 验收场景均有可自动验证的覆盖或明确的 GitHub Actions 手工验收步骤。
