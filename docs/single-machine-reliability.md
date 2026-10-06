# 单机资料库可靠性与操作说明

## 2026年10月6日负责人确认与交付

使用者在公开回归结果与正式门槛说明之后明确回复“我已经审核过，没有问题，可以进行下一步”。本轮总体验收确认及采用公开完整 200 份回归的授权已记录在 [负责人确认](evidence/single-machine-owner-acceptance-2026-10-06.json)。用户接受固定资料的已知局限，授权继续提交、CI 和发布；未收到逐题标签导出，原空白模板及逐题人工计数仍保留，不能把总体确认伪造为 30 份逐题表单。

固定 8 项内的工程可靠性、实际 Ollama 接入、五项质量修复、30 题 AI 原文复核、Word 原生分页与公开完整回归已完成。公开回归是已实际运行的正式替代门槛，AGENTS.md 已按用户确认更新；原 pdf-evals 仍未取得、未执行，没有采用测试豁免。公开 200 份均完成，输出无变化，7 项指标无下降；1 份原生空输出也计入。后端 246 通过、2 项本机 PostgreSQL 配置缺失跳过；真实数据库检查由仓库 CI 执行。

验收证据见 [本轮证据](evidence/single-machine-reliability-2026-10-05.json)与[公开回归](external-public-regression.md)。实际提交、精确提交 CI 和合并状态以 [GitHub PR](https://github.com/jesko2004/pdf-inspector/pulls)、[Actions](https://github.com/jesko2004/pdf-inspector/actions)及 [本轮发布](https://github.com/jesko2004/pdf-inspector/releases/tag/single-machine-2026-10-06)为准；本轮发布包含实际 SHA 和验收附件，全部检查通过才合并发布，完成后停止。下方较早状态仅为历史审计，不能作为新的阻塞条件或重新开启旧清单。

## 以下为负责人确认前的历史说明

## 2026年10月6日公开外部回归续作

已自动取得上游公开套件、200 份真实 PDF、200 份标准答案和原版评估器，固定版本完成全量对照：200/200 完成，0 执行错误，0 缺失预测，0 快照变化，7 项质量指标均无下降；综合得分 0.8692001161。1 份原生空输出两版相同并计入，未启用 OCR。结果不是全部 PDF 提取正确率，也不替代问答验收。见 [回归说明](external-public-regression.md)与[完整证据](evidence/external-public-200-2026-10-06.json)。

原指定 `firecrawl/pdf-evals` 仍未取得、未执行。公开回归是已经完成测试的替代方案，待使用者批准成为正式提交门槛；尚未修改 AGENTS.md，没有采用跳过测试的例外，未提交、PR、CI 或发布。原 44 项暂存内容及全部历史记录保留。五项质量问题及 Word 原生 50 页检查此前已完成。

## 2026年10月6日收尾状态

2026年10月6日：原第 11、12、21、26、27 题的五项质量问题已关闭。完整 30 题为 24 作答、6 拒答、0 调用错误、0 误拒答；AI 逐条核对展示的声明及证据，24 题事实有原文支持、6 题拒答合理。这是两份已知 PDF 的 AI 事实与引用复核，不是通用准确率或独立人工签署；用户人工仍为 0/30。

- 新报告 `test_output/minimum-landing/ollama-acceptance-v2-20261006.json`，独立目录 `.pdf-inspector-data/ollama-acceptance-v2-20261006`。旧报告全部保留，未逐题挑选重试结果。
- [修复验收页](../output/30题Ollama修复验收/核对结果.html)列原页、答案、引用及理由；[完整包](../output/30题Ollama修复验收包.zip)含原 PDF、页面图和绑定新报告的人工空白模板。旧审核包保留。
- 四道价格现覆盖同一车型行、税后金额与 KRW 表头；中文日期误拒答已关闭。答案未硬编码。短表格介绍复制到同页同节的后续父片段；旧资料须重新解析及入库，单独重算向量不迁移正文。
- 严格 JSON、来源身份和原文摘录仍校验；服务器仅补充实际输入中同一行标签、邻近短表头。重复同文声明保留首项，其他项及摘录保存在 `validation.duplicate_claims_omitted`；所有原始项必须先通过契约及精确摘录校验。
- `grounded_json` 的普通与流式 OpenAI 兼容请求现在带 JSON Schema `response_format`。服务仍独立校验，不能假设提供方一定遵守 Schema；不支持时明确失败，不自动放宽或改成文本。[Ollama 官方格式说明](https://github.com/ollama/ollama/blob/main/docs/capabilities/structured-outputs.mdx)。
- 局限保留：英文日期题有时用中文回答，事实正确；物性父引用附带第 3 页，实际依据在第 2 页；中文型号存在性题的强制拒答标签有歧义。旧中文焓重复项误引熵的反例保留，不能宣称模型原始输出全部正确。
- 后端最终 248 项中 246 通过、2 项真实 PostgreSQL 未配置跳过；真实 HTTP 冷备份恢复 11 项通过。沙箱无法加载 ONNX DLL／清理原生服务进程的首轮失败保留，同一断言在原生执行环境通过。Rust 源码未变，893 项及格式、严格 Clippy、release 有效日志保留。
- 最终 30 次成功生成返回 prompt 56169、completion 2531、total 58700；不含历史运行、调试、Embedding 或契约检查，也不是账单。仍为本机 Ollama 的 1024 维向量和 8192 窗口生成别名；字符估算预算 1200、输出 1200。固定 seed 不保证新入库随机来源 ID 改变后输出一致。
- Word 保留 93 题、四段回答、139 个书签、2 张表；使用已校验 SHA256 和官方签名的工作区原生 LibreOffice 渲染，最终 50 页已逐页检查通过，未发现遮挡、裁切或表格溢出；结论及指纹见 [证据](evidence/single-machine-reliability-2026-10-05.json)。原生工具不是服务依赖。
- `F:/pdf-evals/bench.py` 尚未取得。已登录账号读取预期两个仓库均为 404，代码搜索无套件，使用者回复“没有地址”；404 不证明仓库不存在。`AGENTS.md` 要求提交前运行该套件，使用者拒绝例外；外部回归未执行，未提交、PR、CI 或发布。
- 原 44 个暂存文件保留，本轮未新增暂存，固定 8 项不扩展。

## 2026年10月5日及以前的说明与验收快照

以下保留操作说明与历史数字。当前状态以上方收尾记录及证据为准。

本次交付固定为一个人的本机 PDF 资料库：一个服务进程、本地文件、SQLite 元数据与向量、浏览器查看原页并纠正答案。部署方式和支持的资料通过逐题审核确认，不把两份 PDF 或 hash 向量实验当作通用正确率。当前清单只有 [8 项](single-machine-delivery-todolist.md)，全部关闭后停止开发。

## 本机运行

首次准备需要 Python 3.12、Rust 工具链和原生构建依赖。在项目目录创建虚拟环境后运行：

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install maturin
.venv\Scripts\python.exe -m pip install -e ".[backend,ocr]"
$env:PDF_INSPECTOR_DATA_DIR='F:\pdf-inspector-local-data'
$env:PDF_INSPECTOR_HOST='127.0.0.1'
$env:PDF_INSPECTOR_WORKERS='1'
$env:PDF_INSPECTOR_VECTOR_STORE='sqlite'
$env:PDF_INSPECTOR_RERANK_PROVIDER='none'
$env:PDF_INSPECTOR_OCR_PROVIDER='rapidocr'
.venv\Scripts\pdf-inspector-api.exe
```

打开 `http://127.0.0.1:8000/demo`，创建知识库、上传 PDF、等待入库、提问，并打开引用原页核对。扫描页按需 OCR；第一次运行 RapidOCR 需要下载其模型，下载失败保留明确的错误或待核对状态。已有 API Key 配置保留；这里的验收范围仅为本机单人使用。默认 hash 向量与 extractive 摘录用于检查链路，实际模型配置与业务质量仍需第 6、7 项验收。停止服务使用控制台 Ctrl+C，等待进程退出；不要启动第二个执行器访问同一数据目录。

## 本机 Ollama 配置

2026年10月5日已下载并检查 Ollama 0.35.1 的本机模型：`qwen3-embedding:0.6b`，1024 维；`qwen3:4b-instruct`，通过本地别名 `pdf-inspector-qwen3-instruct:4b` 固定 `num_ctx=8192`、`seed=42`。别名共用原权重并保留官方模板，不修改基础模型。不要把 `qwen3:4b` 标签当回答版使用：本次实际取得的是思考版，已保留失败契约记录。

本机现有环境可运行 `. .codex-tools/use-ollama.ps1`，随后用 `.codex-tools/api-venv/Scripts/python.exe -m scripts.check_models` 检查。该本机配置文件被 Git 忽略，不含密钥。换机器需先准备上述两个模型，再创建相同参数的别名；可在项目 PowerShell 中运行：

```powershell
ollama pull qwen3-embedding:0.6b
ollama pull qwen3:4b-instruct
Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/create' -Method Post -ContentType 'application/json' -Body '{"model":"pdf-inspector-qwen3-instruct:4b","from":"qwen3:4b-instruct","parameters":{"num_ctx":8192,"seed":42},"stream":false}'
$env:PDF_INSPECTOR_EMBEDDING_PROVIDER='openai_compatible'
$env:PDF_INSPECTOR_EMBEDDING_BASE_URL='http://127.0.0.1:11434/v1'
$env:PDF_INSPECTOR_EMBEDDING_MODEL='qwen3-embedding:0.6b'
$env:PDF_INSPECTOR_EMBEDDING_DIMENSIONS='1024'
$env:PDF_INSPECTOR_EMBEDDING_BATCH_SIZE='8'
$env:PDF_INSPECTOR_EMBEDDING_TIMEOUT_SECONDS='120'
$env:PDF_INSPECTOR_LLM_PROVIDER='openai_compatible'
$env:PDF_INSPECTOR_LLM_BASE_URL='http://127.0.0.1:11434/v1'
$env:PDF_INSPECTOR_LLM_MODEL='pdf-inspector-qwen3-instruct:4b'
$env:PDF_INSPECTOR_LLM_TIMEOUT_SECONDS='240'
$env:PDF_INSPECTOR_RAG_MAX_CONTEXT_TOKENS='1200'
$env:PDF_INSPECTOR_RAG_MAX_OUTPUT_TOKENS='1200'
$env:PDF_INSPECTOR_RAG_ANSWER_FORMAT='grounded_json'
```

模型只调用上述 loopback 地址，本地推理不需要云 API Key。本次普通回答与流式回答的严格 JSON／原文引用契约均通过，见 `test_output/minimum-landing/ollama-model-readiness-instruct-final-20261005.json`。新发现的嵌套 `prompt_tokens_details` 兼容问题已修复；用量只保存提供方返回的三个顶层 Token 数，缓存／推理明细不能重复相加。费用记录不把 Token 数当账单，本机电费与硬件成本未测算；失败调用、Embedding 和流式用量不计入成功生成 Token 汇总。

模型配置证据 `tmp/ollama-instruct-model-configuration.json` 保存 Ollama 版本、三项模型摘要及模板指纹。模型标签可能更新，复现须核对实际摘要并重新跑契约。8192 是本机加载窗口；项目上下文仍为字符估算，实际 30 题与 AI 原文核对均已完成，但发现的质量问题尚未关闭，不能仅凭接口检查验收质量。

## 已完成的可靠性边界

资料与模型更新先准备完整结果，再切换查询可见版本。正在查询的旧分块由文件锁租约保护，回收不能提前删除；保留代次可以把模型、正文和引用一起回滚。回滚后管理中的最新源文件不被改写，必须完整重建后继续入库。已删除的文档不能通过旧归档复活。

默认 PDF、OCR、原页预览和可选本地重排通过有期限、内存与输出预算的子进程执行。Windows 使用 Job Object 管理整个进程树，父执行器异常退出后也会终止普通后代；POSIX 使用独立进程组，Linux 额外安装父进程退出通知。资源约束不是权限沙箱，不证明远端模型已经停止。明确注入的 Python 处理器或重排器供可信嵌入与测试使用，不享有默认原生路径的硬终止保证。

启动先取得独占执行器锁，再清理服务自有的 worker 临时目录、未提交 UUID 上传、结果临时文件和无主租约文件。提交成功的任务、结果和普通用户文件保留。限流身份与业务桶最多保存 10000 项，表满时拒绝新身份；活跃身份不会因新身份涌入而被逐出。

可选重排默认关闭。每次子进程期限包括启动、模型加载及推理，原 500ms 默认值可能导致冷启动直接回退；需要模型缓存和本机实测后调整配置，不能把未运行真实重排的测试写成质量提升。超时、满额或推理失败保留召回顺序，并记录回退原因。

## 重复请求与费用

上传与问答支持 `Idempotency-Key`，长度 1—128，只允许不含空格的可打印 ASCII。操作身份与调用者绑定，同键不同请求返回 409。同键上传返回原任务；即使任务创建后响应检查点丢失，也能从同一个 UUID 恢复任务，避免再次解析。

问答结果持久化后，同键重试重放原答案、引用及用量，不重新检索或调用生成模型。模型超时、服务崩溃或本地保存失败时，操作变为 `failed_or_uncertain` 或重启后的 `uncertain`；同键不会自动再次收费。调用者必须先查 `GET /v1/operations/{operation_id}`，核对实际结果和提供方用量，决定是否明确发起新操作。模型成功到本地持久化之间仍可能丢失结果；这里选择阻止自动再次调用，不宣称提供方 exactly-once 或能恢复未保存的答案。

页面的上传与问答失败重试复用操作键。成功后新的点击是新的操作。API 调用者必须自己保留并发送同一键；未发送键的请求保留原行为，不享有跨请求去重。问答的同键流式请求先生成并保存完整结果，再发送 SSE；因此不能边生成边展示，但断线重放不会再调用模型。已完成结果反映原操作使用的文档版本，重试不会悄悄换成最新答案。

## 删除待办

删除意图先存入数据库。每次物理删除前核对暂存、发布、归档和活跃查询引用；物理身份已经重新使用时取消待办。共库 SQLite 的删除和确认共用事务；外部向量删除可幂等重放，不产生文档 Embedding 调用。

正常执行器每 5 秒检查一次；自动处理每次最多 1000 条。临时失败按 2、4、8、16 秒退避，第 5 次失败后阻塞，不能无期限重试。权限及无效参数错误直接阻塞。待办保存尝试次数、下次时间和错误类型，错误正文与凭据不写入记录。管理员可查看 `GET /v1/maintenance/vector-deletions`，其中包含总待办、阻塞数量、最早创建时间及最多 100 条记录；修复原因后调用 `POST /v1/maintenance/vector-deletions/retry` 显式重放。指标导出待办及阻塞数量。保留版本和活跃查询导致的延期不算外部删除失败。

## 一致备份与独立恢复

先停止服务，确认执行器已经退出，再备份到数据目录之外。备份工具必须取得相同的独占锁；服务仍在运行时拒绝备份。本版本只保证本地 SQLite 向量库的一致冷备份，不覆盖外部 PostgreSQL。

```powershell
.venv\Scripts\pdf-inspector-backup.exe create F:\pdf-inspector-local-data F:\pdf-inspector-backups\local-20261005.tar.gz
.venv\Scripts\pdf-inspector-backup.exe verify F:\pdf-inspector-backups\local-20261005.tar.gz
.venv\Scripts\pdf-inspector-backup.exe restore F:\pdf-inspector-backups\local-20261005.tar.gz F:\pdf-inspector-restored
$env:PDF_INSPECTOR_DATA_DIR='F:\pdf-inspector-restored'
.venv\Scripts\pdf-inspector-api.exe
```

备份记录各文件大小与 SHA-256，并验证 SQLite 完整性和外键；拒绝符号链接，不携带执行器锁、工作目录或活跃查询租约。环境中的模型密钥不在包内，恢复后需在本机配置。恢复拒绝不安全路径、非普通成员、校验不符、重复清单和非空目标；先在同盘临时目录完成校验、路径重绑定及过期租约清理，再一次发布新目录。校验失败不留下部分可用目录。

恢复后先检查知识库查询、原 PDF 引用、一个新上传与入库；旧目录应暂时不可用，防止表面成功实际仍依赖旧路径。回归已包含旧目录不存在时的查询、引用下载、重复上传重放、再入库、全库重建和回滚。密钥或远端模型不可用时不能算恢复了实际模型服务。

## 验收与停止条件

本轮故障测试覆盖重复请求、并发重试、付费超时与丢失检查点、执行器强杀、进程树终止、重排期限后复用名额、无请求时回收、有限退避、权限失败、已提交文件保留、独占备份、损坏库拒绝及独立恢复。完整本机回归与发布状态以 [本轮证据](evidence/single-machine-reliability-2026-10-05.json) 为准；缺少外部套件、真实 PostgreSQL、模型或人工审核时分别记为未执行。

旧离线 [审核包](../output/30题人工审核包.zip)保留原版。使用者要求 AI 自主检查后，已交付新的 [实际 Ollama 核对页](../output/30题Ollama核对/核对结果.html)，每题直接列原文、正确回答草稿、实际回答和理由。最终实际 30 题：23 个作答、7 个拒答、0 个调用错误；6 个资料不足题均拒答，中文发布日期有 1 个误拒答。AI 原文核对 30/30：19 题正文核心信息有支持、6 题拒答合理、5 题需修正或确认（四道价格的币种／证据完整性及中文日期）。这些数字不是最终答案准确率，用户人工仍为 0/30。 原文及正确回答由 AI 核对，不代替使用者签署；浏览器合成数据不计入。

最终本机检查：完整后端 242 项，240 通过、2 项真实 PostgreSQL 未配置跳过；页面回归与审核入口浏览器检查通过，真实 HTTP 冷备份／独立恢复 11 项通过。复现冒烟运行 `python scripts/smoke_single_machine.py`，使用临时目录、两份真实 PDF、hash-v1 与 extractive-v1，不调用付费模型；只清理自己的服务进程树。首轮 ONNX DLL 沙箱权限导致 OCR 失败，允许本机执行后完整原测试通过。

本机使用上方已验证的 Ollama 配置。复现须在**新的数据目录**运行，保留旧报告；不要复用源代码指纹不同的检查点：

```powershell
. .codex-tools/use-ollama.ps1
.codex-tools/api-venv/Scripts/python.exe -X utf8 -m scripts.check_models --output test_output/minimum-landing/readiness-reproduce.json
.codex-tools/api-venv/Scripts/python.exe -X utf8 -m scripts.minimum_landing --dataset examples/minimum_landing_eval_v2.json --require-real-models --work-dir .pdf-inspector-data/ollama-reproduce --output test_output/minimum-landing/ollama-reproduce.json
```

新提取保留标题中的单位定义；既有任务正文与旧分块不自动迁移，需要重新解析 PDF 并入库，单独向量重建不会修复旧正文。结构化上下文给多个父片段分配预算，避免首个长表格隐藏后续版本行；引用仍以完整原页复核。JSON 校验及原文精确引用未放宽，没有对已知数值硬编码补答。

最终完整运行见 `test_output/minimum-landing/ollama-bilingual-v2-report-final-20261005.json`。前三轮原报告与反例保留；最终报告一次完整生成，没有逐题择优替换。seed=42 固定抽样起点，但重新入库的随机 chunk ID 改变输入，不能声称所有重跑答案完全相同。

最终 30 次成功生成返回用量：prompt 43164、completion 2610、total 45774；最大实际 prompt 为 2823，输出预算 1200，本轮实测未触及 8192 窗口。该汇总不含其他报告、失败调用、Embedding、契约检查、调试和流式调用，不能称整个过程的总消耗。项目上下文仍是字符估算，不含聊天封装，`model_window_verified=false` 保留；这些样本的实测不保证任意资料不会超限。本机推理没有云 API 账单，电费和硬件成本未测量。

第 7 项已知局限：英文价格金额缺 KRW，四道价格的 evidence.quote 没有同时覆盖版本、金额和币种，中文日期有误拒答；分子质量摘录未带行名，若干物性父引用带额外第 3 页。新核对页包含正确原文与判断依据，质量保持待验收，不把核心信息支持数称作准确率。未启用真实重排，也不把 30 题当独立保留集。

用户反馈必须绑定这轮报告。人工空白模板位于 `output/30题Ollama核对/人工空白模板/review-template.json`，不含 AI 代填；接收真实导出后，用 `python -m scripts.score_landing score --dataset examples/minimum_landing_eval_v2.json --report test_output/minimum-landing/ollama-bilingual-v2-report-final-20261005.json --reviews <真实审核导出.json> --output-dir <新的评分目录>` 核对指纹。旧离线模板与新报告不能混用。

Rust 本轮已有格式、严格 Clippy、893 项测试和 release 构建日志，源码未变，不重复执行；最终证据记录对应源码指纹。外部 `F:\pdf-evals\bench.py test` 未执行且未获本轮例外，因此尚无新提交、PR、CI 或发布。Word 已同步内容与结构，缺少 soffice.exe 导致原生排版未验收。实际模型已接通，用户确认、已知质量问题与发布条件仍未关闭。
