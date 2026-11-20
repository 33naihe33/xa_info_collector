# 最终版本整合计划

**Goal:** 将已存在且验证通过的代码统一到本地 `master`，保留原分支及其他工作区。

**Architecture:** 以 `codex/wechat-date-pagination` 为基础建立整合分支，迁入批量日期采集工作区的代码，补齐边界和接口验证。原工作区不修改；分析运行数据留在磁盘，不纳入 Git。微信分页和自适应完整性仍标为设计状态。

**Tech Stack:** Python 3.11/3.12、FastAPI、APScheduler、SQLite、Vue、TypeScript、pytest、Vite。

## 整合步骤

- [x] 运行现有完整测试，记录基线；审查两个工作区的差异。
- [x] 创建 `codex/final-integration`，保留现有未提交的领导调研规则、数据库回滚修复、三次定时安排。
- [x] 先迁入范围采集测试并运行，确认旧代码不能满足 `until` 范围语义；迁入实现并验证。
- [x] 补齐范围日期校验、栏目游标隔离、批量 API 参数校验及顺序执行和锁释放测试；修复审查发现的缺陷。
- [x] 构建前端，检查可空日期、重复提交、错误反馈；运行完整后端测试。
- [x] 增加版本说明，明确已实现功能和仅设计内容；排除 `data/analysis_runs/`，不删除本机文件。
- [x] 提交审核后的源码、测试及文档，快进合入本地 `master`；保留其他分支，不推送远程。
- [x] 再验证合并结果，优雅重启本机服务并检查健康接口、前端资源和定时配置。

## 完成记录

源码整合提交：`06e593d`。合入 `master` 后完整回归仍为 314 passed、3 skipped。前端构建成功；运行中服务于 2026-11-20 15:56:09（北京时间）重启，健康接口返回 `status=ok`、`scheduler=running`，OpenAPI 中已注册 `POST /api/collect/range`。生产 Python 3.12 验证两组每日三次触发时间正确。复审未发现阻塞合并问题。

## 验证命令

```sh
/Users/caomengdi/miniforge3/envs/xa-info-collector/bin/python -m pytest -q
cd web/frontend
npm run build
```

生产环境使用 Python 3.12，另外用该解释器验证导入、调度触发时间和健康状态。测试均使用临时数据库与 mock，不触发真实抓取或付费模型调用。
