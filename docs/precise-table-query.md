# 精确表格查询

阶段日期：2026-10-05。`/search`、`/ask` 和 `/retrieval-evaluations` 共用 `table_filters`。

旧字符串条件现在表示**等值**：`{"Model":"X100"}` 不命中 `X1000`。文本比较采用 NFKC、大小写折叠和空白规整，保留型号连字符；子串查询须显式使用 `contains`。多个条件必须在同一行成立。

```json
{
  "query": "X100 的美元报价",
  "retrieval_mode": "hybrid",
  "kinds": ["table"],
  "table_filters": {
    "Model": "X100",
    "Price": {
      "op": "between",
      "min_value": "950",
      "max_value": "1950",
      "currency": "USD",
      "currency_column": "Currency"
    }
  }
}
```

`eq/contains` 默认比较文本；数值等值使用 `value_type: "number"`。`gt/gte/lt/lte` 自动比较数值，`between` 包含两端。数值须为有限十进制字符串，支持规范千分位，不支持科学计数、NaN 或猜测地区格式。请求值不夹带单位。

`unit` 支持 g/kg/t、mm/cm/m/km、mL/L、Pa/kPa/MPa、pcs 及代码列出的中文别名。相同量纲按 Decimal 换算；来源须包含单位，或用 `unit_column` 指向同一行的单位列。不同量纲、未知单位及冲突单位不匹配。

`currency` 支持 CNY/USD/EUR/GBP/JPY/HKD/KRW 及明确别名。来源须明确币种，或由 `currency_column` 指定同一行的币种列。不同币种不换汇，裸 `$`、`¥` 不猜币种，无币种的 950 不默认解释成 950 美元。

每列保留 `column_1`、`column_2` 等位置身份。重名表头按名称查询返回 422，应使用列身份；不会覆盖后一列或任选一列。旧索引已有位置单元格时可直接读取；缺少位置证据的重复表头需要重新入库。

结果保留完整 `table` 供核对，增加 `matched_table_rows`，其中有表块内原行号、列身份、表头和原值。用于重排及问答的 `content/context_content` 只含表头与命中行，引用限制到表块页码；恢复父块不会重新带入其他行。跨页视觉行号仍需原页核对。

非法条件和歧义列在计算查询向量之前失败。SQLite、BM25 与 PostgreSQL 共用条件判断。PostgreSQL 取消过滤前 `top_k * 10` 截断，按相似度继续读到足够匹配或范围穷尽；仍有范围扫描成本，没有专用结构化表格索引或生产容量结论。

新增 11 项回归覆盖边界值、同一行 AND、区间、单位、币种、重复列与旧元数据、候选截断、三种召回路径的证据投影以及错误输入不消耗查询向量调用。完整后端 176 项：175 通过，真实 pgvector 1 项因未配置跳过。PostgreSQL 候选截断通过连接替身验证，不能记为真实服务验收。Rust 格式、严格 Clippy、893 项测试及 release 构建通过；外部 pdf-evals 尚不可用，不记为通过。

```powershell
& '.codex-tools\api-venv\Scripts\python.exe' -m unittest backend.tests.test_table_query
& '.codex-tools\api-venv\Scripts\python.exe' -m unittest discover -s backend/tests -t .
```

当前保护已经正确解析的行列。OCR 错位、合并单元格、隐含单位、跨页对齐及真实业务表格准确性仍需数据验收；查询层不能修复解析错误。
