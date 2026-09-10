# 离线验收复现说明

本次验收使用 Windows、本地 RapidOCR、SQLite、hash Embedding 与 extractive LLM。下面的回归使用仓库内 fixture 或在临时目录生成的合成数据，不要求提供私有业务 PDF 或 pdf-evals 副本。外部 pdf-evals 是另外的提交前要求，不能以这些命令替代并标为通过。

## 验证环境

| 组件 | 实测版本 |
|---|---|
| Rust / Cargo | 1.97.1 / 1.97.1，Windows GNU 工具链 |
| Python | 3.12.14 |
| FastAPI / Uvicorn | 0.141.1 / 0.52.4 |
| PyMuPDF / RapidOCR | 1.28.2 / 3.9.2 |
| ONNX Runtime / NumPy | 1.23.2 / 2.3.5 |
| Pydantic / pytest | 2.13.5 / 9.1.1 |

Rust crate 和 Python 分发各自的版本字段分别为 0.1.7 和 0.2.6，沿用项目已有配置。本次没有发布包版本；验收对象通过源码差异和产物哈希标识，不根据已安装包的版本号推断二进制是否更新。

按 [后端说明](backend.md) 准备隔离 Python 环境，安装本地源码绑定及 backend/ocr 依赖。纯离线运行前须已具备 Rust 依赖、Python 依赖和 RapidOCR 模型文件；模型缺失、依赖缺失或真实 OCR 被跳过时，不得记为 OCR 验收通过。本机使用 `cargo build --offline --release --features python` 生成 DLL，并将该 DLL 放入隔离环境的 `pdf_inspector` 包作为 `.pyd`，核对两者 SHA-256 一致。其他平台按标准 Python 构建方式生成绑定。

## 全量本地回归

在仓库根目录、配置好的工具链及隔离 Python 环境中执行：

```powershell
cargo fmt --check
cargo clippy --offline -- -D warnings
cargo test --offline
cargo build --offline --release --features python
python -m unittest discover -s backend/tests -v
python -m pytest tests/test_python.py -q
python -m unittest discover -s scripts/tests
```

运行 Python 测试前确认已加载本次构建的原生扩展，不能仅重建 DLL 而继续测试旧 `.pyd`。本机结果是 Rust 893、后端 95 通过/1 跳过、Python 64、脚本 17；跳过项为当前 SQLite 范围外的 pgvector 真实连接。测试数量可能随后续源码变化而变化。

## 不依赖私有 PDF 的关键回归

```powershell
cargo test --offline test_merge_synthetic_bold_overprints_before_joining
cargo test --offline test_merge_preserves_repeated_text_with_distinct_geometry_or_semantics
cargo test --offline wrapped_chinese_words_keep_boundaries_in_both_conversion_paths
python -m unittest backend.tests.test_ocr backend.tests.test_processor
python -m unittest backend.tests.test_production.BackupTests
python -m unittest backend.tests.test_table_data
```

多栏、侧栏、普通双语说明及复选框的合成单测位于 [layout.rs](../src/extractor/layout.rs)、[detect_rects.rs](../src/tables/detect_rects.rs) 和 [fonts.rs](../src/extractor/fonts.rs)，由全量 `cargo test` 执行。封面真实 OCR 单测会生成只有图片标题和原生页脚的临时 PDF，检查标题可识别、页脚不重复；其数据与真实目录无关。恢复单测验证原目录不可用时的结果读取、重试及路径绑定。Freon 的真实 fixture 和快照已在仓库中。

## 本地接口与恢复复核步骤

在独立验收目录配置 `PDF_INSPECTOR_OCR_PROVIDER=rapidocr`、`PDF_INSPECTOR_VECTOR_STORE=sqlite`、`PDF_INSPECTOR_EMBEDDING_PROVIDER=hash`、`PDF_INSPECTOR_LLM_PROVIDER=extractive`，服务仅绑定 `127.0.0.1`。API 密钥应临时生成，不写入报告或提交。

1. 按 [任务工作流](backend.md#task-workflow) 上传自有测试 PDF，等待终态并读取结果。封面样本应含图片文字及少量边缘原生文字；有字段冲突的样本必须保留复核状态。
2. 创建知识库，通过 `/v1/knowledge-bases/{id}/documents` 入库；等待文档 ready。检索封面中的图片标题，检查片段内容、document_id 和页码。
3. 调用 `/v1/knowledge-bases/{id}/ask`，验证引用绑定到实际证据页。hash/extractive 模式只验证检索与引用协议；宽松阈值不证明真实模型语义质量。
4. 等任务和入库队列结束并停止验收服务，再运行备份与校验：

```powershell
python -m backend.backup create <验收源目录> <备份文件.tar.gz>
python -m backend.backup verify <备份文件.tar.gz>
python -m backend.backup restore <备份文件.tar.gz> <新的恢复目录>
```

5. 仅将本次创建的验收源目录临时改名；启动指向恢复目录的服务。确认任务上传文件和结果路径属于恢复目录，内容哈希及结果 JSON 与备份前一致。
6. 对比恢复前后的检索文档、片段、页码和引用；另建知识库重新入库一个恢复任务，验证读取源文件不依赖旧路径。测试结束后关闭验收服务。

这六步的本次真实接口记录共 22 项检查通过，使用两份已有业务样本；这些原始 PDF 未纳入新增提交。合成回归和上述接口步骤可供其他环境复现机制，但不冒充完全复现本机私有覆盖集。

## 结果与边界

实际 16 份、86 页覆盖、正文检查、发票正反例及 OCR 并发见 [修复验收记录](acceptance-deferred-fixes.md)；本次收尾结论见 [最终报告](acceptance-final-report.md)。本机原生扩展 SHA-256 为 `df247301d98aa6f1593b1b4bcaaebfc20d3d296ba8caafb1b9c4498aedeca294`，不要求其他平台构建得到相同二进制哈希。
