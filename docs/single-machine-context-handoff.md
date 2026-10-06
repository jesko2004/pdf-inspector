# 单机资料库新窗口续作说明

## 2026年10月6日负责人确认与交付

使用者在公开回归结果与正式门槛说明之后明确回复“我已经审核过，没有问题，可以进行下一步”。本轮总体验收确认及采用公开完整 200 份回归的授权已记录在 [负责人确认](evidence/single-machine-owner-acceptance-2026-10-06.json)。用户接受固定资料的已知局限，授权继续提交、CI 和发布；未收到逐题标签导出，原空白模板及逐题人工计数仍保留，不能把总体确认伪造为 30 份逐题表单。

固定 8 项内的工程可靠性、实际 Ollama 接入、五项质量修复、30 题 AI 原文复核、Word 原生分页与公开完整回归已完成。公开回归是已实际运行的正式替代门槛，AGENTS.md 已按用户确认更新；原 pdf-evals 仍未取得、未执行，没有采用测试豁免。公开 200 份均完成，输出无变化，7 项指标无下降；1 份原生空输出也计入。后端 246 通过、2 项本机 PostgreSQL 配置缺失跳过；真实数据库检查由仓库 CI 执行。

验收证据见 [本轮证据](evidence/single-machine-reliability-2026-10-05.json)与[公开回归](external-public-regression.md)。实际提交、精确提交 CI 和合并状态以 [GitHub PR](https://github.com/jesko2004/pdf-inspector/pulls)、[Actions](https://github.com/jesko2004/pdf-inspector/actions)及 [本轮发布](https://github.com/jesko2004/pdf-inspector/releases/tag/single-machine-2026-10-06)为准；本轮发布包含实际 SHA 和验收附件，全部检查通过才合并发布，完成后停止。下方较早状态仅为历史审计，不能作为新的阻塞条件或重新开启旧清单。

## 以下为负责人确认前的历史说明

## 2026年10月6日公开外部回归续作

已自动取得上游公开套件、200 份真实 PDF、200 份标准答案和原版评估器，固定版本完成全量对照：200/200 完成，0 执行错误，0 缺失预测，0 快照变化，7 项质量指标均无下降；综合得分 0.8692001161。1 份原生空输出两版相同并计入，未启用 OCR。结果不是全部 PDF 提取正确率，也不替代问答验收。见 [回归说明](external-public-regression.md)与[完整证据](evidence/external-public-200-2026-10-06.json)。

原指定 `firecrawl/pdf-evals` 仍未取得、未执行。公开回归是已经完成测试的替代方案，待使用者批准成为正式提交门槛；尚未修改 AGENTS.md，没有采用跳过测试的例外，未提交、PR、CI 或发布。原 44 项暂存内容及全部历史记录保留。五项质量问题及 Word 原生 50 页检查此前已完成。

在 F:\pdf inspector 接续现有工作。唯一交付清单是 docs/single-machine-delivery-todolist.md 的固定 8 项。使用者要求：先完成工程可靠性，再交付 30 题人工审核；把清单做完就停止。旧 34 项、22 项只保留为历史审计，不能恢复为当前必做清单。新增故障归入现有项，不扩大范围。

## 2026年10月6日最新收尾状态

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

下一步仅取得规定外部套件并实际通过后，进行精确提交、CI 与发布；不扩展功能。项目测试服务已清理，本机 Ollama 服务保留。

## 2026年10月5日旧收尾快照

旧状态已被最新记录更新，仅作历史审计。

## 本窗口收尾快照（优先于下方历史说明）

- 使用者重启后明确要求“继续完成”，本轮已恢复并完成本机可执行的接入和验收。先读取固定 8 项，不重开旧 34／22 项。
- 第 1—4 项本机工程回归完成；新增 Ollama 兼容修复后，最终后端 242 项中 240 通过、2 项真实 PostgreSQL 未配置跳过，日志 tmp/ollama-backend-regression-final-20261005.log。真实 HTTP 备份恢复再次通过 11 项，自己的服务子进程已经清理。Rust 源码未变，893 项和严格检查日志保持有效。
- 第 6 项真实模型接入完成：Ollama 0.35.1，qwen3-embedding:0.6b（1024 维）与 pdf-inspector-qwen3-instruct:4b（基于 qwen3:4b-instruct，共享权重、官方模板、num_ctx=8192、seed=42）。普通与流式严格引用契约和 Embedding 批量契约均通过；最新 test_output/minimum-landing/ollama-model-readiness-instruct-final-20261005.json。原思考版和所有失败记录保留，不再使用。
- 本机配置点源 .codex-tools/use-ollama.ps1，新的 .pdf-inspector-data/ollama-local；本机 API 不需要云密钥。上下文字符估算预算 1200、输出 1200，实际窗口 8192。新提取保留标题定义，旧保存的分块／答案未迁移，旧资料要重新解析及入库；不可仅重算向量就声称获得新提取内容。
- 最终实际报告 test_output/minimum-landing/ollama-bilingual-v2-report-final-20261005.json；独立目录 .pdf-inspector-data/ollama-eval-final-20261005。两份真实 PDF、全部 30 题和 6 组检索比较运行完毕：23 作答、7 拒答、0 调用错误；6 资料不足题都拒答，1 个有依据的中文发布日期误拒答。没有用重试成功覆盖旧失败；前三轮报告及诊断保留。
- 第 5、7 项：AI 已重新核对两份 PDF 全部 4 页及最终 30 题的完整答案和引用。output/30题Ollama核对/核对结果.html：19 题正文核心信息有原文支持、6 题拒答合理、5 题需修正或确认（第 11、12、21、26、27 题，币种／引用完整性／中文日期）。质量仍未验收。使用者不需要重新寻找原文，逐题提供正确回答草稿。用户人工仍为 0/30，AI 结论不代填；新人工空白模板绑定最终报告，不能套用旧模板。
- 已修复嵌套 usage 兼容、标题定义遗漏、首个表格挤占后续父片段，以及结构化回答提示约束；未硬编码题目答案，未降低严格 JSON 和原文引用校验。当前 4B 模型仍有币种遗漏、证据摘录不完整及误拒答；固定 seed 不消除新入库随机 chunk ID 引起的输入差异，不能宣称完全确定或质量达标。
- 成功的最终 30 次生成用量合计 prompt 43164、completion 2610、total 45774；最大实际 prompt 2823，预留输出 1200；仅记录这轮返回值，不含之前失败、Embedding、契约检查、调试或其他运行。电费／硬件成本未测量，不把 Token 数当账单。模型摘要和模板指纹在 tmp/ollama-instruct-model-configuration.json。
- 第 8 项文档、Word 状态和源码指纹已同步；Word 保留 93 题、四段回答、139 个书签、2 张表。缺少 soffice.exe，不能称原生排版已验收。全部渲染辅助仅作内容检查。
- 外部 F:/pdf-evals/bench.py 仍缺失；公开预期 firecrawl/pdf-evals 返回 404，搜索无规定套件，记录 tmp/external-suite-lookup-20261005.json；不推断私有仓库不存在。使用者明确拒绝本轮提交例外，不再次索要例外，不提交、PR、合并或发布。
- 原 44 个暂存文件保留，新增修复和文档更新未提交。tmp、tools、output、原始文件未加入暂存；不要 reset 或 bulk add。当前 codex/index-lifecycle，HEAD 13cf480813f7a77a9adbe723c15ac246a023a9be。
- 下一步仅限：解决已有质量反例或取得用户对已知局限的确认；获得规定外部套件并实际通过；完成 Word 原生渲染后再按精确提交 CI 发布。全部 8 项关闭后停止。不能为了获得漂亮通过数循环换模型／重试择优，不能把当前结果报成完成发布。

## 重启接续前快照（历史，不作为当前状态）


- **使用者已在重启后明确要求“继续完成”，2026年10月5日本轮接续。** Ollama 0.35.1 的本机 API 可用，qwen3:4b-instruct 从缓存续下；仍需创建配置别名、通过三项契约后运行实际 30 题。已重新核对两份 PDF 的全部 4 页。公开套件查找记录 tmp/external-suite-lookup-20261005.json：预期本地路径不存在，公开 firecrawl/pdf-evals API 返回 404，搜索未找到规定套件；不推断私有仓库不存在，不替代套件，不提交发布。
- **使用者明确要求重启电脑，先停下（2026年10月5日）。本轮已停止下载客户端和检查，未启动项目服务。重启后只有收到使用者继续指令才接续。** 先确认 Ollama 的 http://127.0.0.1:11434/api/version 可用，再运行 `.codex-tools/api-venv/Scripts/python.exe -X utf8 tmp/ollama_pull_models.py qwen3:4b-instruct` 续下未完成模型（Ollama 可复用已有下载）。完成后执行 `tmp/configure_ollama_instruct.py`，再点源 `.codex-tools/use-ollama.ps1` 并运行 `python -m scripts.check_models --output test_output/minimum-landing/ollama-model-readiness-instruct-20261005.json`。全部契约通过后，才在全新隔离目录运行原有 bilingual-v2 的实际 30 题；保留旧报告，继续 AI 原文核对。
- 暂停点：Embedding 下载与中英文批量检查通过（1024 维），原始 qwen3:4b 思考版下载完成，但两轮生成／流式契约失败；qwen3:4b-instruct 尚未完成下载。本地环境脚本已经指向未来配置别名 pdf-inspector-qwen3-instruct:4b，**该别名尚未创建，不能现在把环境脚本视为已验收配置**。不安装其他软件，不降低引用或 JSON 校验，不把 AI 核对计入用户人工结论；提交例外仍被使用者明确拒绝。当前仅改动文档和本机临时／配置文件，既有 44 个暂存文件保留，未新增提交、PR 或发布。
- 第 1—4 项本机工程验收完成。最终完整后端 237 项中 235 通过、2 项真实 PostgreSQL 未配置跳过，日志 tmp/reliability-backend-closeout-native.log；首轮受 ONNX DLL 沙箱权限影响，允许本机执行后原用例通过。页面与审核入口浏览器回归通过。
- scripts/smoke_single_machine.py 已通过真实 HTTP 11 项检查，使用第二份 nexo-price-en.pdf 验证不同内容入库，保留业务去重。Windows Job Object 负责终止测试自己启动的虚拟环境启动器及服务子进程。结果 tmp/single-machine-smoke-result.json。
- 第 5 项已向使用者交接 output/30题人工审核/审核入口.html 和完整 ZIP，仍为 0/30。仅接收真实导出，tmp/review-packet-qa/synthetic-review.json 禁止计入。
- 使用者随后要求“开始检查”：AI 原文核对已完成 30/30，来源为两份 PDF 全部 4 页、独立 pdfplumber 抽取与保存的全部机器答案／引用。output/30题AI核对/核对结果.html 提供中文问题、原文依据、回答草稿和理由，AI核对结果.json 绑定数据／报告／来源指纹。17 题可定位核心信息，11 题关键遗漏／误拒答／无关摘录，2 题资料不足拒答合理；17 不是最终通过数。另有 15 题表格结构失真及中文型号存在性标签歧义。原始报告与人工模板未改，AI 结论不计为人工验收；真实模型接入后核对新结果，保留这些反例。
- 第 6 项本地接入进行中：使用者已安装 Ollama 0.35.1，服务为 http://127.0.0.1:11434。qwen3-embedding:0.6b 已下载并实测中英文批量向量，维度 1024。最初 qwen3:4b 当前标签是 thinking-2507，生成／流式契约失败，保留 ollama-model-readiness-20261005.json 和 v2；正在下载 qwen3:4b-instruct，准备仅设置 8192 窗口的本地配置别名 pdf-inspector-qwen3-instruct:4b。本机环境脚本 .codex-tools/use-ollama.ps1 使用新的 .pdf-inspector-data/ollama-local 目录；目前尚未通过全部契约或运行实际 30 题。模型和质量不可提前关闭。
- 第 8 项已同步操作说明、旧清单顶部历史标注、backend／minimum-landing／resource-isolation／index-lifecycle 文档和最终源码证据 docs/evidence/single-machine-reliability-2026-10-05.json。旧证据原指纹保留。
- 修改版 Word 已更新 B04、C06、E02、E08、I05、I12、I14、J05 和开头进度，保留 93 题、四段回答、139 个书签及 2 张表；D:\简历原文件未修改。authoring marker 已成功执行一次。原生渲染因缺少 soffice.exe 未通过，37 页 ReportLab 预览仅作内容辅助，不能称原生排版验证。
- 保留所有既有工作，明确暂存仅本轮代码、测试、文档和修改版 Word；tmp、tools、output 和原始文件不加入发布。F:\pdf-evals\bench.py 仍缺失，使用者已明确回复“不同意”本轮提交例外，不再次默认例外或沿用历史例外；须取得并通过套件后才提交。新提交、PR、精确提交 CI 和发布均未执行。
- 后续只接收审核／模型配置，或解决提交前外部套件条件及 Word 原生渲染；在固定 8 项内完成验收和发布后停止。不要重跑下方已完成的工程步骤或扩展旧清单。

## 历史交接快照（保留问题定位，不再代表当前待办）

## 固定范围和已经完成的工作

一个人、本机、单服务进程、本地 PDF 文件、SQLite 元数据和向量、上传入库、混合检索、问答、原页核对和反馈。一套实际 Embedding 与生成模型待配置。默认重排关闭。不要增加多用户共享、Redis、微服务、多执行器、ANN、LangChain 或 Agent。

第 1—3 项本机代码和回归已完成：索引完整发布／归档／查询租约／安全回收／回滚；PDF／OCR／预览和可选重排子进程边界；执行器强杀与遗留文件清理；限流身份上限；上传和问答操作键与结果重放；不确定付费操作停止自动调用；删除待办有限退避、阻塞和管理员重放。第 4 项冷备份与新目录恢复代码、恢复回归已完成，真实 HTTP 冒烟最后一个断言待收尾。新功能尚未提交或获得新 CI 结果。

## 按顺序完成剩余工作

### 第 4 项完成恢复冒烟

检查 tmp/single-machine-smoke.py 和 tmp/single-machine-smoke-summary.log。它启动真实 loopback HTTP 服务，用 thermo-freon12.pdf 验证重复上传、已保存问答重放、运行中备份拒绝、停机备份、旧目录不可用时恢复、原 PDF 下载和新查询。最后再次上传同一 PDF，并错误地要求新文档 ID，导致断言失败；同内容复用是项目行为，不要先改业务代码。可改用 tests/fixtures/nexo-price-en.pdf 验证另一份文档新增入库，再完整重跑。脚本使用离线模型，不产生付费调用。它已在 finally 中关闭自己启动的服务。

最终检查加入新增的后台回收测试，再运行全量后端和页面检查。已经通过的 Rust 检查无需无理由循环执行；代码新增或项目提交规范要求时再运行。新缺陷在本项内修复。

### 第 5 项交给使用者审核 30 题

审核包已准备：output/30题人工审核包.zip。解压后打开 审核入口.html；每题包含完整机器答案、待核对参考、原 PDF 与引用页码；填写标签、答案、引用三项判断及理由，导出 JSON。也有完整 Markdown 表和空白 review-template.json。15 英文、15 中文来自两份 PDF，当前是 hash-v1 与 extractive-v1 的离线结果，不能当实际模型或通用质量验收。人工仍为 0/30。

构建脚本 scripts/build_review_packet.py，页面模板 scripts/review_packet.html。浏览器 QA 在 tmp/review-packet-qa.cjs，截图和报告在 tmp/review-packet-qa；其中 synthetic-review.json 仅为合成测试，禁止当人工审核导入最终结果。审核包的版本指纹匹配原始 examples/minimum_landing_eval_v2.json 与 test_output/minimum-landing/bilingual-v2-report.json。

### 第 6 项配置一套实际模型

尚未得到服务地址、Embedding 模型名和维度、生成模型名。此前已向使用者询问这些配置。需要时在新窗口确认是否已经提供，不能自行选一个付费提供方并虚构成功。密钥只放本机环境变量，不发送到聊天、日志或 Git。模型配置固定后完整入库、查询和问答，记录实际提供方用量与费用口径；没有配置时保持待验收。

### 第 7 项按审核结果确认质量

接收真实人工导出结果，核对数据和报告指纹。错误参考先修标签、保留旧版，再重跑，不能把旧审核结论套到新报告。实际模型结果还需核对误答、过度拒答和引用支持。仅修验收范围内的问题，明确不能自动判断的资料并保留人工核对入口。不承诺任意 PDF、广泛泛化或生产 SLA，不另立扩展清单。

### 第 8 项文档证据和发布收尾

1. 更新 docs/single-machine-delivery-todolist.md，旧 docs/remaining-todolist.md、project-landing-todolist.md、post-mvp-todolist.md 顶部注明已被固定 8 项取代。旧证据保留，不把旧源码指纹改为新版本。
2. docs/single-machine-reliability.md 是本轮操作说明草稿；核对安装、默认配置、运行、停止、幂等、管理员恢复、冷备份和新目录恢复。同步 docs/backend.md、minimum-landing.md、resource-isolation.md、index-lifecycle.md 中已过时的线程重排、回收待补、备份和迁移版本描述。
3. 生成 docs/evidence/single-machine-reliability-2026-10-05.json，记录最终源码指纹、实测结果、未执行项目。当前该文件尚不存在；说明草稿中的链接要在交付前补齐。
4. 同步根目录 pdf inspector工程问题整理 修改版.docx，保持 93 道问答、四段回答格式、139 个书签和 2 张表。当前 Word 尚未同步本轮可靠性。至少核对 B04、C06、E02、E08、I05、I12、I14、J05 和开头进度；明确固定 8 项及真实状态。原 D:\简历\pdf inspector工程问题整理.docx 不动。
5. Word 工作按 documents skill 使用 bundled runtime；本轮尚未执行 authoring marker。native render_docx.py 之前因缺少 soffice.exe 失败，不安装 LibreOffice 作为服务依赖，也不能把 ReportLab 辅助预览说成 Word 原生排版验证。历史辅助检查脚本在 tmp/engineering-answers-revised、tmp/index-lifecycle-document，可复用辅助函数，避免盲目重跑一次性修改脚本。
6. 审查完整 diff，明确暂存本轮代码、测试和文档；不要 bulk add 用户的 tmp、tools、output、原始文件或 Word 锁文件。按授权创建 PR，精确提交的全部 CI 通过才合并；没有授权扩大部署。

## 测试和工具快照

- 完整后端最近一次：tmp/reliability-backend-final.log，236 项，234 通过、2 项真实 PostgreSQL 未配置跳过。新增的无请求后台回收测试随后单独通过；最终包含全部改动的全量回归待跑。
- 新故障测试：backend/tests/test_reliability_closeout.py。其他相关测试仍覆盖原子发布、生命周期和进程隔离。
- Python：.codex-tools/api-venv/Scripts/python.exe；PYTHONUTF8=1。完整命令：python -m unittest discover -s backend/tests -v，原生 OCR 与子进程需要允许相应本机执行权限。
- 页面：.codex-tools/node-v22.22.3-win-x64/node.exe scripts/test_manual_ui.cjs，已通过，包含失败重试复用操作键。
- Rust：CARGO_HOME 指向 .codex-tools/cargo，RUSTUP_HOME 指向 .codex-tools/rustup，PATH 增加 cargo/bin 与 mingw64/bin。格式、严格 Clippy、893 项测试、release 构建全部通过，日志 tmp/reliability-rust-*.log。
- 浏览器审核入口已在实际 Edge headless 中验证 30 题／90 个空白判断、导出、导入、缓存、桌面和手机布局；原审核包仍是 0/30。

## Git 和提交规则

分支 codex/index-lifecycle，HEAD 13cf480813f7a77a9adbe723c15ac246a023a9be。先前 PR #14、#15、#16 已合并。工作树同时包含已暂存的 R07 和未暂存的可靠性修改及新文件；直接 git commit 现有暂存区会漏掉本轮内容。先看 git diff 和 git diff --cached，不覆盖或重置现有改动。

AGENTS.md 要求提交前 Rust 格式、Clippy、测试以及兄弟 pdf-evals 的 bench.py test。F:\pdf-evals\bench.py 仍不存在；之前三个阶段的一次性例外已结束。本轮没有获得新的明确例外，自动 PR／合并授权不等于免除外部回归。继续完成本机工作后，提交需套件到位或使用者明确许可本次例外；不能声称已跑外部套件。暂不创建新的提交绕过规则。

Windows 的 gh 使用 C:\Program Files\GitHub CLI\gh.exe，通常需要可访问本机 keyring／网络的权限。Git 网络 push 之前失败，可参考 tmp/stage-publication-tools.py 的 API 发布工具，但应先核对其适用范围和精确 SHA。创建 PR 后 attach_artifact；未经全部精确提交 CI 通过不得自动合并。

## 停止条件

仅完成固定 8 项。人工与模型依赖缺失时如实交接，不代填、不伪造通过。所有项验收和交付完成后停止，不增加下一阶段、不设置自动唤醒或持续扩展。
