# PDF 与 OCR 进程资源隔离

更新：2026-10-05。本阶段让卡住或崩溃的 PDF 解码、OCR 和原页渲染能被终止，并释放执行名额；保留持久任务的失败、显式重试和重启恢复。验证环境为本机 Windows，HTTP 实验使用合成 PDF 和故意卡住的命令 OCR。

## 执行方式

默认服务路径为每份 PDF 启动独立 Python 进程，在其中检查页数、执行原生提取、初始化 OCR、提取字段、表格和分块。原页 PNG 预览另有独立进程和并发名额，预览请求不等待无限队列。主服务只接收有大小上限的结果文件；子进程的标准输出与错误输出不会累积在主服务内存。

Windows 使用 Job Object 限制单项操作及其普通子进程的**合计提交内存**。工作进程先等父进程释放，再读取和解码 PDF；资源限制设置或进程归属失败时停止操作。超时、停机和操作完成都会终止该组剩余子进程，包括命令 OCR 留下的后代；关闭组句柄也会终止工作。这些行为依据 [Windows Job Object 文档](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects) 和 [内存限制定义](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_extended_limit_information)，并通过本机真实进程验证。

POSIX 路径使用独立进程组和继承的 `RLIMIT_AS`，限制每个进程的地址空间并终止普通同组后代；它不是 Windows 的合计提交内存口径。该平台本轮没有执行验证，也没有实现父服务突然退出后的统一后代回收或 cgroup 合计内存。此实现是故障与资源控制，不是恶意代码的权限沙箱；服务端配置的 OCR 命令仍具有当前操作系统账户权限。

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

## 后续范围

Embedding 的远端超时不能证明提供方已停止执行，FlashRank 线程等待超时也不能强制终止本地推理；本阶段没有将它们改成同一进程治理。限流身份表的增长、请求体在应用之前的网关预算、用户级资源配额与完整容量报告仍待完善。异常强杀主服务可能留下工作目录文件，尚无按租约清理的启动垃圾回收；正常结束、超时与有序停机已清理。业务准确率、真实语义模型、人工标签、真实 PostgreSQL 和用户反馈验收保持原状态。
