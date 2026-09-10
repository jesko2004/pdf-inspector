# 收尾提交文件清单

本清单用于最终暂存与审查。仅包含本轮代码、测试、模板和使用/验收文档；不自动加入工作区的其他未跟踪文件。

## 纳入范围

- `README.md`
- `backend/app.py`
- `backend/backup.py`
- `backend/ocr.py`
- `backend/processor.py`
- `backend/table_data.py`
- `backend/tests/test_ocr.py`
- `backend/tests/test_processor.py`
- `backend/tests/test_production.py`
- `backend/tests/test_table_data.py`
- `docs/acceptance-closeout-plan.md`
- `docs/acceptance-deferred-fixes.md`
- `docs/acceptance-final-report.md`
- `docs/acceptance-next-review.md`
- `docs/acceptance-plan.md`
- `docs/acceptance-report.md`
- `docs/acceptance-reproduction.md`
- `docs/acceptance-review-findings.md`
- `docs/acceptance-scope.md`
- `docs/acceptance-stage1-report.md`
- `docs/acceptance-submit-manifest.md`
- `docs/backend.md`
- `docs/external-regression-resolution.md`
- `docs/github-closeout-draft.md`
- `docs/yeslogic-invoice-template.md`
- `examples/yeslogic_invoice.profile.json`
- `src/extractor/fonts.rs`
- `src/extractor/layout.rs`
- `src/extractor/mod.rs`
- `src/markdown/convert.rs`
- `src/tables/detect_lines.rs`
- `src/tables/detect_rects.rs`
- `tests/integration_tests.rs`
- `tests/snapshots/thermo-freon12.md`
- `tests/test_python.py`

## 保留本地，不提交

- `test_output/`：原始接口结果、备份、数据库、运行日志及哈希清单。
- `tests/local-fixtures/`：未确认允许再分发的业务 PDF。
- `.codex-tools/`、`target/`：工具、依赖和构建产物。
- 两份与项目无关的根目录简历 DOCX。
- `docs/acceptance-resume.md`：早期暂停恢复便签；当前状态已由最终报告替代。

最终提交前核对暂存路径与此清单一致，并检查无密钥、原始业务文件或意外二进制。此清单不意味着已经执行提交或推送。
