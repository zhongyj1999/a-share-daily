# Qoder Cloud 定时任务 Prompt

把这个 prompt 复制到 Qoder Cloud 定时任务（`location=cloud`）的指令框里即可。

## 任务信息

- 仓库：请替换为你的 GitHub 仓库，例如 `yourname/a-share-daily`
- 分支：`main`
- 触发：cron `10 16 * * 1-5`
- 时区：`Asia/Shanghai`

## Prompt 文本

```text
请在关联的 GitHub 仓库 a-share-daily 根目录下完成以下操作：

1. 安装依赖：
   pip install -r requirements.txt

2. 生成 A 股每日行情报告：
   python scripts/daily_report.py

3. 如果第 2 步失败，请排查网络/接口问题后重跑一次；仍失败则记录错误并停止，不要编造数据。

4. 将生成的以下文件提交并推送到仓库（使用 git，提交信息包含日期）：
   - reports/latest.html
   - reports/YYYY-MM-DD.html
   - reports/YYYY-MM-DD.md
   - data/snapshots/YYYY-MM-DD.json
   - data/health_alert.json（如存在）

5. 最终回复中说明：数据日期、统计个股数、涨停数、是否发生数据源降级/失败。

注意：报告仅用于行情复盘，不构成投资建议。
```

## 本地测试命令

在把仓库推送到 GitHub 之前，可以先在本地验证：

```bash
cd E:/tcode/daily
pip install -r requirements.txt
python scripts/daily_report.py
python scripts/health_check.py
```
