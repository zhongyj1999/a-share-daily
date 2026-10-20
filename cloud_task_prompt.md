# Qoder Cloud 定时任务 Prompt

## 当前 Cloud 任务

- 任务 ID：`ca_JYWZS5KQNIOF22QK6CXOUFDFPB`
- 名称：A股每日行情报告（Cloud Every）
- 模式：每 24 小时执行一次（`everyMs=86400000`）
- 说明：Qoder Cloud 当前不支持带 weekdays/anchorAt 的 every 模式，因此该任务每天执行；脚本会自动识别非交易日并使用最近交易日数据。

## 旧的 cron 任务

- 任务 ID：`ca_MTLXYJ45L2ZC6LDFFPSQJUPSP4`
- 规则：`10 16 * * 1-5`，Asia/Shanghai
- 状态：2026-10-19 16:10 未产生提交，疑似 Cloud cron 未触发。可在 Qoder Automations 中手动删除，避免重复执行。

## Prompt 文本

```text
请从 GitHub 仓库 https://github.com/zhongyj1999/a-share-daily.git 的 main 分支拉取代码。

在仓库根目录执行以下步骤：

1. 安装依赖：
   pip install -r requirements.txt

2. 生成 A 股每日行情报告：
   python scripts/daily_report.py

3. 如果第 2 步失败，请排查网络/接口问题后重跑一次；仍失败则记录错误并停止，不要编造数据。

4. 将生成的产物提交并推送到仓库：
   git config user.email "qoder-bot@example.com"
   git config user.name "Qoder Bot"
   git add reports/
   git add data/snapshots/
   git add data/health_alert.json
   git commit -m "chore(report): daily report for $(date +%Y-%m-%d)"
   git push origin main

5. 最终回复中说明：数据日期、统计个股数、涨停数、是否发生数据源降级/失败。

注意：报告仅用于行情复盘，不构成投资建议。
```

## 前置条件

- 该仓库为私有仓库，需要先在 GitHub 安装 **Qoder AI App** 并授权访问 `zhongyj1999/a-share-daily`。
- 安装地址：https://github.com/settings/installations，找到 `qoderai`，确认仓库已勾选。

## 本地双保险

本地定时任务（ID：`fe7dbcce-05e5-4026-b447-97ed7ace625f`）已更新为：

- 工作日 16:10（Asia/Shanghai）
- 工作目录：`E:\tcode\daily`
- 生成报告后自动 `git add / commit / push` 到 `origin main`

如果 Cloud 任务未触发，本地任务会继续生成并推送报告。
