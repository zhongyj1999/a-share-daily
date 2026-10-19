# Qoder Cloud 定时任务 Prompt

已创建的 Cloud 任务 ID：`ca_MTLXYJ45L2ZC6LDFFPSQJUPSP4`

- 仓库：`https://github.com/zhongyj1999/a-share-daily.git`
- 分支：`main`
- 触发：cron `10 16 * * 1-5`
- 时区：`Asia/Shanghai`

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

## 本地测试命令

在把仓库推送到 GitHub 之前，可以先在本地验证：

```bash
cd E:/tcode/daily
pip install -r requirements.txt
python scripts/daily_report.py
python scripts/health_check.py
```

## 双保险

本地仍保留了一个工作日 16:10 的定时任务（ID：`fe7dbcce-05e5-4026-b447-97ed7ace625f`），工作目录为 `E:\tcode\daily`。如果 Cloud 任务因授权/网络问题失败，本地任务会继续生成报告。
