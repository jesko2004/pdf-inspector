# GitHub 收尾标题、描述与总结

更新日期：2026-09-10。文案已按最终本地候选重写；负责人已选择路径 B，本次外部回归单次豁免生效。套件仍未运行；下方描述用于收尾 PR，实际发布结果另行记录。

## 标题

`fix: preserve PDF content and harden offline backend workflows`

## PR 描述

PDF extraction could interleave newspaper columns, insert sidebar headings into body text, mistake bilingual instructions for tables, distort checkboxes, and lose superscript units. This change corrects those cases, removes coincident synthetic-bold overprints without dropping intentional repeated text, and avoids inserting spaces at covered Chinese/Japanese line-wrap boundaries. The known invoice profile preserves the invoice number and four-column table; conflicting source bank fields still require review.

The local RapidOCR backend now supplements image-cover text on pages that meet conservative geometry checks while preserving native text. Backup restoration rebases and validates task paths so restored results and ingestion work when the original directory is unavailable. The change also fixes Uvicorn error logging and USD amount normalization, updates the encrypted-PDF test expectation and the reviewed Freon snapshot, and includes regression tests, the invoice profile, and acceptance/reproduction documentation.

### Validation

- Formatting and strict Clippy passed. Rust: 893 passed; backend: 95 passed, 1 skipped for the unselected live pgvector configuration; Python bindings: 64 passed; scripts: 17 passed.
- Local content coverage: 16 PDFs / 86 pages, including 23 full-page OCR pages and one supplemented cover. All 37 existing protection assertions and 45 follow-up checks passed. Source review targeted annotated evidence and affected pages; this is not a claim of exhaustive word-by-word review.
- OCR stability: eight tasks completed, including six concurrent submissions handled by three workers; the queue drained without unexpected failures.
- Final live offline API and independent restore: 22 checks passed, covering upload, extraction, review status, ingestion, search, page citations, backup verification, restored paths/results/profiles and fresh ingestion with the original directory unavailable.
- These results cover the same verified source and native artifact; unaffected suites were not rerun for the final documentation-only updates.
- External pdf-evals: not run because a compatible accessible source could not be obtained. On 2026-09-10, the project owner selected path B and approved a one-time exception for this closeout. The local checks above do not establish equivalent coverage of the unavailable corpus. Standing repository policy and acceptance scope are unchanged.

### Scope and reproduction

Acceptance covers a local single-instance SQLite backend with RapidOCR and hash/extractive retrieval and responses. It does not establish real-model answer quality or production SLAs. Cover supplementation is bounded; general image-text completion, full handwriting/rotated-stamp recognition and unvalidated complex layouts remain limitations. The Rust CLI itself does not run OCR. Source-field conflicts remain `needs_review`.

See `docs/acceptance-final-report.md`, `docs/acceptance-reproduction.md`, `docs/acceptance-scope.md` and `docs/yeslogic-invoice-template.md`. Tracked synthetic tests and existing fixtures reproduce the key mechanisms without private business PDFs. Raw local corpora, databases, credentials and unrelated documents are excluded.

## 分支与发布记录

- 本地基线：`42c8faa874820b77a9a9c73efa87e4e9ae382598`，原工作分支 `feat/advanced-retrieval`。
- 2026-09-10 经 GitHub API 核实，目标 `main` 为 `faca8a36742d6fa516529df81dcb99ac70947aae`，仅多出合并 PR #11 的提交；两者文件差异为空。本次拟交付范围为 [35 个文件](acceptance-submit-manifest.md) 中的本地修复，不重复描述已合并的高级检索功能。
- 本次例外已批准，从经重新核实的 `main` 创建 `codex/offline-acceptance-closeout` 分支，应用并提交已审查修复，再推送并创建 PR；如远程内容变化，重新检查差异与受影响验证。
- GitHub CLI 登录凭据无效（401）；连接器对目标仓库返回 `push: false`，Git HTTPS 刷新曾连接超时。需恢复目标仓库写入能力后完成远程交付；本文不是已发布记录。

## 中文收尾总结

离线本地版本在约定范围内基本验收通过。PDF 正文顺序、表单与符号、单位、受限封面 OCR、发票提取、备份恢复及日志问题已修复并有回归保护；本轮完整接口与独立恢复 22 项检查全部通过。既有最终候选自动化与 16 份、86 页内容覆盖继续有效。

可共享复现说明、提交清单、标题和描述均已准备。外部 pdf-evals 未运行，负责人已批准本次单次豁免。继续完成本地收尾提交；远程交付需要有效的目标仓库写入权限，目前尚无 PR 链接。真实模型质量、生产 SLA、通用图像文字及完整手写/旋转印章识别不在本轮通过范围。

外部回归的作用、剩余风险及本次批准记录见 [完整解决方案](external-regression-resolution.md)。路径 B 已批准；长期规则变更未授权，AGENTS.md 保持不变。
