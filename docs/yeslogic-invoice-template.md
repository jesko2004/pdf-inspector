# 已知 YesLogic 发票模板

示例配置为 `examples/yeslogic_invoice.profile.json`（版本 2），适用于本地样本 `tests/local-fixtures/non-academic-20-batch-2/07-plain-invoice.pdf` 的固定版式。它不会自动替换默认采购模板，也不保证适配任意发票。

## 使用步骤

1. 启动本地后端，打开其 `/docs`。启用鉴权时使用具备对应权限的本地服务 Key；这不是外部模型 API Key。
2. 调用 `POST /v1/profiles`，请求体填入示例 JSON，预期 HTTP 201。若同 ID 模板已存在，先读取 `GET /v1/profiles/yeslogic_invoice`，核对后按需使用 `PUT /v1/profiles/yeslogic_invoice` 更新，保留修改前版本。
3. 调用 `POST /v1/tasks`，`file` 选择该 PDF，表单参数 `profile_id` 明确填写 `yeslogic_invoice`。预期 HTTP 202，并保存返回的任务 ID。
4. 轮询 `GET /v1/tasks/{任务ID}`，再读取 `/v1/tasks/{任务ID}/result`。不要仅看总状态，要检查字段候选、证据页码、表格及复核原因。
5. 读取 `/v1/tasks/{任务ID}/tables`，选取 `schema_id=invoice_lines` 的表格 ID，再读取 `/v1/tasks/{任务ID}/tables/{表格ID}.csv` 核对导出。

## 已验证的预期

| 项目 | 预期 |
|---|---|
| 发票编号 | 第 1 页 `161126`，不带付款说明文字 |
| 表头 | Description / From / Until / Amount，保持四列 |
| 商品行 | Prince Upgrades & Support / Nov 26, 2016 / Nov 26, 2017 / USD $950.00 |
| 金额 | 结构化十进制 `950.00`，CSV 导出成功 |
| BSB | 源文件候选冲突，保留 `needs_review` |
| 错误编号 | 将编号改为 BAD126 的独立反例中，value 为空、reason 为 pattern_mismatch；不静默交付错误编号 |

模板坐标为 PDF 点，原点在左上角，页码从 1 开始。编号和 BSB 的区域及六位数字规则针对已知版式冻结；页面缩放、字段移动或新增版式后应重新标注并测试。From/Until 当前保留原文本，不宣称完成日期标准化。

该原样本最终总状态应为 `needs_review`，因为 BSB 冲突尚需人工决定；字段与表格修复通过不意味着源文件矛盾被解决。装饰性标题重复字符仍列为质量限制。

验证证据：`test_output/acceptance-next/invoice-20260910-183451/` 中的 report.json、positive.json、negative.json、table-csv.json。复现脚本为 `test_output/acceptance-next/stage2_invoice.py`，需要本机既有验收环境与脚本支持。
