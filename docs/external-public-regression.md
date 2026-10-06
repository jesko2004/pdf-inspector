# 公开外部回归：完整 200 份 PDF

2026年10月6日已自动下载并完成完整回归。原指定 `firecrawl/pdf-evals` 尚未取得或执行；使用者已审核并确认继续交付，批准本文完整公开回归作为正式替代门槛，授权记录见 [负责人确认](evidence/single-machine-owner-acceptance-2026-10-06.json)。没有跳过外部测试，也没有把不同套件标成原套件。

原门槛来自 `AGENTS.md`：兄弟仓库 `pdf-evals`，179+ 份快照 PDF，release 构建后执行 `bench.py test`。上游 PR [#492](https://github.com/firecrawl/pdf-inspector/pull/492) 的仓库依赖明确指向 `github.com/firecrawl/pdf-evals`。该仓库当前返回 404，用户没有下载地址；404 不能证明仓库不存在。

公开方案采用上游的 [OpenDataLoader 对照协议](https://github.com/firecrawl/pdf-inspector/blob/main/docs/benchmarking.md)及 [firecrawl/opendataloader-bench](https://github.com/firecrawl/opendataloader-bench) 的完整 200 份 PDF 与标准 Markdown。固定版本 `340f25d70f5b2dbc4bc1cc6b154769f74b1fc745`，位于本机 `F:/opendataloader-bench`。仓库 Apache-2.0，数据集 DP-Bench 按上游第三方声明使用 MIT；许可证仍保留在下载仓库。

## 实测结果

基线为本项目已提交版本 `13cf480813f7a77a9adbe723c15ac246a023a9be`；候选为当前工作区。两个二进制分别由对应源码构建。基线未跟踪 Cargo.lock，因此使用候选的同一锁文件控制依赖变量。独立保留二进制和构建日志；候选最终使用独立 target 目录构建，避免同名 Cargo 产物互相覆盖。

| 检查 | 基线 | 候选 |
|---|---:|---:|
| 实际 CLI 完成 | 200/200 | 200/200 |
| 执行错误 | 0 | 0 |
| 评估器缺失预测 | 0 | 0 |
| 综合均分 | 0.8692001161 | 0.8692001161 |
| 阅读顺序 NID（200 份） | 0.9124964184 | 0.9124964184 |
| 表格 TEDS（42 份适用） | 0.7464057391 | 0.7464057391 |
| 标题 MHS（107 份适用） | 0.7904020762 | 0.7904020762 |

全部 Markdown 与结构化 JSON 快照一致，JSON 仅忽略运行耗时；全部 7 项上游聚合指标均未下降。没有删除文档、择优重试或用候选重建基线。原版评估器每版覆盖 200 个唯一文档 ID，全部 PDF、标准答案、评估器文件运行前后 SHA256 相同。回归门槛自身的 6 项故障注入测试通过，覆盖缺件、重复件、执行异常、快照变化、评估器漏件和评分退步／无效。

`01030000000141` 的原生 Markdown 在两版均为空，未启用 OCR，仍计入完整评估。通过表示相对基线没有退步，不表示全部提取正确；这也不替代问答模型与原文引用验收。

原始结果在 `test_output/external/public-200-20261006/`：400 个原始 JSON、400 个 Markdown、CLI 错误输出、两版上游 evaluation.json 与 CSV、完整报告和逐件检查点。发布证据副本为 [external-public-200-2026-10-06.json](evidence/external-public-200-2026-10-06.json)，其指纹绑定原报告、输入和二进制。

## 可复现命令

先保留基线，再构建候选。不得对两次构建共用会覆盖同名产物的 target 目录；基线与候选路径必须分别传入。首次获取公开套件：

```powershell
git clone --branch abi/pdf-parser-benchmark-results --single-branch https://github.com/firecrawl/opendataloader-bench.git F:/opendataloader-bench
git -C F:/opendataloader-bench checkout 340f25d70f5b2dbc4bc1cc6b154769f74b1fc745
uv venv --python 3.14 .codex-tools/opendataloader-eval-venv
uv pip install --python .codex-tools/opendataloader-eval-venv/Scripts/python.exe -r scripts/public-benchmark-requirements.txt
```

本轮运行：

```powershell
.codex-tools/opendataloader-eval-venv/Scripts/python.exe -m unittest scripts.tests.test_bench_public_pdf -v
.codex-tools/opendataloader-eval-venv/Scripts/python.exe scripts/bench_public_pdf.py test --corpus-root F:/opendataloader-bench --baseline .codex-tools/regression-binaries/baseline-13cf480-pdf2md.exe --candidate .codex-tools/regression-binaries/candidate-pdf2md.exe --python .codex-tools/opendataloader-eval-venv/Scripts/python.exe --output-dir test_output/external/public-200-20261006
```

输出目录已存在时工具拒绝覆盖。重跑须使用新目录，旧报告保留。工具直接调用指定 CLI，再运行未经改动的上游评估器；不调用上游 SDK 引擎入口，避免测到另外安装的 pdf-inspector 版本。该工具不调用大模型，不产生模型费用。

## 已批准的正式门槛

使用者已批准在原套件无法取得时，正式采用这个固定公开版本的完整 200 份回归：全部文档执行成功、无缺失预测、全部快照一致、7 项聚合指标无下降，且 fmt、严格 Clippy 和 Rust 测试继续必须通过。任何非一致快照必须先审查，不能自动更新基线。原套件状态保持“未取得、未执行”。全部本轮提交检查通过后按用户授权进行提交、CI、合并与发布。
