# PDF 与 OCR 进程资源隔离

## 2026年10月6日负责人确认与交付

使用者在公开回归结果与正式门槛说明之后明确回复“我已经审核过，没有问题，可以进行下一步”。本轮总体验收确认及采用公开完整 200 份回归的授权已记录在 [负责人确认](evidence/single-machine-owner-acceptance-2026-10-06.json)。用户接受固定资料的已知局限，授权继续提交、CI 和发布；未收到逐题标签导出，原空白模板及逐题人工计数仍保留，不能把总体确认伪造为 30 份逐题表单。

固定 8 项内的工程可靠性、实际 Ollama 接入、五项质量修复、30 题 AI 原文复核、Word 原生分页与公开完整回归已完成。公开回归是已实际运行的正式替代门槛，AGENTS.md 已按用户确认更新；原 pdf-evals 仍未取得、未执行，没有采用测试豁免。公开 200 份均完成，输出无变化，7 项指标无下降；1 份原生空输出也计入。后端 246 通过、2 项本机 PostgreSQL 配置缺失跳过；真实数据库检查由仓库 CI 执行。

验收证据见 [本轮证据](evidence/single-machine-reliability-2026-10-05.json)与[公开回归](external-public-regression.md)。实际提交、精确提交 CI 和合并状态以 [GitHub PR](https://github.com/jesko2004/pdf-inspector/pulls)、[Actions](https://github.com/jesko2004/pdf-inspector/actions)及 [本轮发布](https://github.com/jesko2004/pdf-inspector/releases/tag/single-machine-2026-10-06)为准；本轮发布包含实际 SHA 和验收附件，全部检查通过才合并发布，完成后停止。下方较早状态仅为历史审计，不能作为新的阻塞条件或重新开启旧清单。

## 以下为负责人确认前的历史说明

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

更新：2026-10-05。本阶段让卡住或崩溃的 PDF 解码、OCR 和原页渲染能被终止，并释放执行名额；保留持久任务的失败、显式重试和重启恢复。验证环境为本机 Windows，HTTP 实验使用合成 PDF 和故意卡住的命令 OCR。

## 执行方式

默认服务路径为每份 PDF 启动独立 Python 进程，在其中检查页数、执行原生提取、初始化 OCR、提取字段、表格和分块。原页 PNG 预览另有独立进程和并发名额，预览请求不等待无限队列。主服务只接收有大小上限的结果文件；子进程的标准输出与错误输出不会累积在主服务内存。

Windows 使用 Job Object 限制单项操作及其普通子进程的**合计提交内存**。工作进程先等父进程释放，再读取和解码 PDF；资源限制设置或进程归属失败时停止操作。超时、停机和操作完成都会终止该组剩余子进程，包括命令 OCR 留下的后代；关闭组句柄也会终止工作。这些行为依据 [Windows Job Object 文档](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects) 和 [内存限制定义](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_extended_limit_information)，并通过本机真实进程验证。

POSIX 路径使用独立进程组和继承的 `RLIMIT_AS`，限制每个进程的地址空间并终止普通同组后代；它不是 Windows 的合计提交内存口径。Linux 原生工作进程安装父进程退出通知，其他 POSIX 平台轮询父进程身份；父进程退出后终止普通同组后代。原始 HTTP 实验仅在 Windows 运行，旧版 Linux 结果见 [阶段 PR 的 CI](https://github.com/jesko2004/pdf-inspector/pull/16)，本轮新增行为尚无 Linux CI 结论；未实现 cgroup 合计内存。此实现是故障与资源控制，不是恶意代码的权限沙箱；服务端配置的 OCR 命令仍具有当前操作系统账户权限。

上传与失败重试都在同一准入锁内检查 `queued + processing` 配额，已满时返回 429，失败任务不会被提前改为 queued。停机先取消未开始的线程任务，再终止活动子进程：已开始的任务持久化 `ProcessingCancelledError`，未认领任务保留 queued，下一次启动继续处理。普通解析超时持久化 `ProcessingTimeoutError`，通过现有失败重试接口恢复。

## 默认预算和返回状态

| 配置 | 默认值 | 作用 |
|---|---:|---|
| `PDF_INSPECTOR_WORKERS` | 2 | 同时处理的 PDF 数量，每份占一个独立进程 |
| `PDF_INSPECTOR_MAX_ACTIVE_TASKS` | 100 | 上传与重试共用的 queued 加 processing 上限 |
| `PDF_INSPECTOR_PROCESS_TIMEOUT_SECONDS` | 300 | PDF 处理启动与运行的墙钟期限 |
| `PDF_INSPECTOR_PROCESS_MEMORY_MB` | 2048 | 每项 PDF／预览的内存预算，单位 MiB；平台口径见上文 |
| `PDF_INSPECTOR_PROCESS_MAX_RESULT_BYTES` | 33554432 | 结果 JSON 或预览 PNG 的最大字节数 |
| `PDF_INSPECTOR_PDF_MAX_PAGES` | 2000 | 在受限进程中检查的页数上限 |
| `PDF_INSPECTOR_PREVIEW_TIMEOUT_SECONDS` | 15 | 原页预览启动与渲染的墙钟期限 |
| `PDF_INSPECTOR_PREVIEW_WORKERS` | 1 | 并发原页渲染名额；已满立即返回 429 |
| `PDF_INSPECTOR_OCR_MAX_PIXELS` | 20000000 | RapidOCR 按当前 DPI 预计的单页渲染像素上限 |

期限监督间隔约 20 ms，进程终止与文件清理另需时间。Windows 默认最多有 2 个解析和 1 个预览操作，各自预算 2 GiB，服务自身内存另计；配置这些默认值不等于测得合适的生产容量。每份 PDF 都重新启动解释器与 OCR，冷启动开销需要在实际扫描文档负载下测量。

隔离工作进程的 OpenBLAS、OpenMP、MKL、NumExpr 和 Accelerate 线程环境值固定为 1；RapidOCR 的 ONNX intra-op／inter-op 线程数也显式设为 1，避免硬件默认线程池叠加到进程并发上。父服务的环境不修改。数值库按环境控制线程，ONNX 默认线程数随物理核心扩展，分别见 [OpenBLAS 说明](https://github.com/OpenMathLib/OpenBLAS/blob/develop/USAGE.md) 与 [ONNX 线程说明](https://onnxruntime.ai/docs/performance/tune-performance/threading.html)。这不等于操作系统 CPU 配额，也不能约束自定义 OCR 程序自行创建线程。

RapidOCR 在分配 pixmap、加载识别模型前检查页尺寸与 DPI，超过像素上限不会先生成大图。普通 OCR 错误或命令 OCR 自身超时仍可保留原生部分结果，标记 `needs_review`。如果整个处理进程达到总期限、发生不可恢复的内存分配失败或崩溃，任务为 failed，本轮不能交付该进程内尚未持久化的原生结果；已有成功任务和已发布知识库不受替换。Abrupt exit 只记录 worker 失败，不猜测一定是内存耗尽。

预览接口保持原有鉴权：不存在页 404，损坏文件 422，名额满 429 并给出 Retry-After，超时 504，资源限制不可用或工作进程异常 503。解析任务仍异步返回 202，后续失败原因通过任务查询读取。直接调用底层 `process_document`／`render_source_page`，或程序显式注入自定义 `processor` 时由调用方负责资源限制；普通 HTTP 服务不提供客户端切换到此模式的参数。

## 回归与 HTTP 故障实验

新增 14 项回归验证实际忙循环及 OCR 后代终止、成功后的后代清理、OS 内存分配拒绝、崩溃、超大结果、限制设置失败、停机与队列恢复、真实 PDF／损坏文件／页数上限、巨大页检查、预览状态码、重试准入，以及本地 RapidOCR 在默认预算内识别扫描页。局部组件错误注入与真实进程、真实 PDF 验证分别保留，不把模拟故障当作生产负载。

```powershell
python -m unittest backend.tests.test_process_isolation -v
python scripts/check_resource_isolation.py --output-dir test_output/resource-isolation/2026-10-05
```

HTTP 实验启动临时本地服务，固定 1 个解析进程、3 个活跃任务名额、3 秒总处理期限和 512 MiB 单项预算。连续上传两份扫描 PDF，命令 OCR 启动普通子进程后持续忙循环；同时排队一份原生 PDF，并验证第 4 次上传被拒绝。两份慢任务均持久化超时，两个 OCR 适配器及两个后代均停止，后续原生 PDF 和原页预览成功，损坏文件预览返回 422。

原始报告记录配置、平台、Python 版本、源码与原生扩展指纹、输入 PDF 哈希、逐请求状态与耗时、任务错误及实际被终止 PID：[本轮报告快照](evidence/resource-isolation-2026-10-05.json)。运行产物保留在 `test_output/resource-isolation/2026-10-05/report.json`，证据快照随此阶段提交供审查。当前本机观测与最终后端回归数字在 [最小落地记录](minimum-landing.md) 中更新。实验不是持续负载测试，未覆盖真实模型服务、多人流量、长时间运行或生产容量目标。

首次 Linux CI 发现默认预算内扫描页 OCR 未完成，未跳过该用例或提高内存限额。明确数值线程预算后，本机再次运行完整 204 项回归，203 通过、1 项真实 pgvector 未配置跳过；扫描页测试还故意继承 64 线程的父环境，必须识别出金额才通过。重新执行同一 HTTP 实验：[最终代码报告](evidence/resource-isolation-thread-budget-2026-10-05.json) 保留 240 个请求、69 个检查，全部通过；工作期间健康检查 P95 2.413 ms、最大 2.589 ms，任务查询 P95 2.698 ms，单次预览 161.418 ms。原报告保留为修复前证据，不把其源码指纹改成新版本。Linux 最终结果与精确提交以 PR #16 检查记录为准。

## 固定单机交付中的收尾

默认 FlashRank 已改为受限子进程，期限覆盖启动、模型加载和推理；超时或满额回退原顺序，明确注入的可信重排器仍走线程路径。执行器先取得独占锁，再清理服务自有的遗留工作目录、未提交 UUID 上传、结果临时文件和无主租约；已提交任务与用户文件保留。限流身份／业务桶最多 10000 项，表满拒绝新身份，不逐出活跃额度。

本轮 Windows 强杀与后代终止、清理、重排期限和名额恢复回归通过，完整后端 237 项中 235 通过、2 项真实 PostgreSQL 未配置跳过。证据见 [单机可靠性记录](evidence/single-machine-reliability-2026-10-05.json)。远端模型超时仍不能证明提供方停止执行；真实模型、人工质量和持续容量未验收。剩余工作只按 [固定 8 项](single-machine-delivery-todolist.md) 推进。
