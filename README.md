# pdf-inspector

**面向文档处理与智能体应用的 PDF 分类、文字提取和结构化转换工具。**

使用 Rust 解析 PDF，将可提取的文字、表格和页面结构转换为 Markdown 或 JSON；提供 Python、Node.js 和浏览器 WebAssembly 绑定。可选本地后端支持扫描页文字识别、业务字段提取、知识库检索、来源引用及备份恢复。

[快速开始](#快速开始) · [本地后端](#本地后端) · [验收与适用边界](#验收与适用边界) · [文档入口](#文档入口)

**项目关键词：** PDF 解析 · 文字提取 · 文档分类 · 表格识别 · 本地文字识别 · 知识库检索

## 可以用来做什么

- **整理文档内容**：将报告、论文、说明书等 PDF 转为便于检索和处理的 Markdown，保留已识别的标题、列表、表格及链接。
- **分流文字页与扫描页**：先判断页面内容，再对需要的页面调用文字识别流程，减少重复处理。
- **提取已知业务字段**：通过业务模板提取供应商报价、发票等文档中的字段、表格和证据位置，并保留冲突提示。
- **构建本地知识库**：上传文档、跟踪任务、建立索引、检索片段，并将回答引用定位到来源文档和页码。
- **接入已有应用**：使用命令行、语言绑定或可选 HTTP 接口接入文档处理流程。

## 核心能力

| 能力 | 说明 |
|---|---|
| PDF 分类 | 区分文字型、扫描型、图像型和混合型文档，返回置信度及需要文字识别的页码等信息 |
| 版面感知提取 | 保留文字位置、字体信息，识别多栏阅读顺序，并处理部分侧栏和跨栏结构 |
| Markdown 转换 | 识别标题、列表、代码块、粗体、斜体、链接及表格；可输出分页标记或紧凑内容 |
| 三种表格检测 | 按矩形、线条网格、文字对齐启发式的顺序尝试检测，首个有效结果优先 |
| 字体与编码处理 | 支持 ToUnicode 映射、CID 字体及部分字体回退，标记可疑乱码以便调用方复核或转入文字识别 |
| 文字边界处理 | 对重复绘制标题、中文和日文换行连接等情况提供定向处理 |
| 多语言接入 | 提供 Rust、Python、Node.js 及浏览器 WebAssembly 接口 |
| 可选本地后端 | 提供异步任务、业务模板、本地文字识别、知识库检索、权限控制、审计和备份恢复 |

Rust 核心本身不执行光学字符识别（OCR），也不需要加载识别模型。需要扫描页识别时，可启用后端的本地 RapidOCR；其依赖和模型需要单独准备。

## 快速开始

所有公共接口的 PDF 页码从 **1** 开始，第一页是 `1`；传入 `0` 会报错。内部集合索引和结构化表格的行列索引仍从 `0` 开始。

### 命令行

需要先安装 Rust 工具链和当前平台所需的编译工具。

```bash
# 从仓库安装命令行工具
cargo install --git https://github.com/jesko2004/pdf-inspector.git

# 将 PDF 转为 Markdown
pdf2md document.pdf

# 输出结构化 JSON
pdf2md document.pdf --json

# 输出带位置和下划线标记的文字条目
pdf2md document.pdf --items-json

# 仅输出 Markdown 正文
pdf2md document.pdf --raw

# 压缩长引导点等源文件排版，减少冗余文本
pdf2md document.pdf --compact

# 插入分页标记，格式为 <!-- Page N -->
pdf2md document.pdf --pages

# 只处理指定页码
pdf2md document.pdf --select-pages 1,3,5-10

# 只检测文档类型
detect-pdf document.pdf --json

# 检测类型并分析表格、多栏等版面信息
detect-pdf document.pdf --analyze --json
```

在源码目录中，也可以执行 `cargo run --bin pdf2md -- document.pdf` 或 `cargo run --bin detect-pdf -- document.pdf`。

### Python

在已激活的 Python 虚拟环境中，从源码构建绑定；需要 Rust 工具链。

```bash
git clone https://github.com/jesko2004/pdf-inspector.git
cd pdf-inspector
pip install maturin
maturin develop --release --features python
```

```python
import pdf_inspector

result = pdf_inspector.process_pdf("document.pdf")
print(result.pdf_type)  # 类型标识：text_based、scanned、image_based 或 mixed
print(result.markdown)  # Markdown 文本；没有可用结果时为 None

# 只处理第 1、3、5 页
selected = pdf_inspector.process_pdf("document.pdf", pages=[1, 3, 5])
print(selected.markdown)
```

完整接口见 [Python 使用说明](docs/python.md)。

### Node.js

在仓库根目录执行：

```bash
cd napi
npm install
npm run build
cd ..
```

在仓库根目录创建并运行模块脚本：

```javascript
import { readFileSync } from 'node:fs';
import { processPdf } from './napi/index.js';

const result = processPdf(readFileSync('document.pdf'));
console.log(result.pdfType);   // 文档类型标识
console.log(result.markdown);  // Markdown 文本；没有可用结果时为 null
```

完整接口见 [Node.js 使用说明](napi/README.md)。

### 浏览器

安装 Rust 及 `wasm-pack` 后，在仓库根目录构建：

```bash
wasm-pack build wasm --target web --out-dir pkg --release
```

在由本地开发服务器提供的页面中加载模块：

```javascript
import init, { processPdf } from './wasm/pkg/pdf_inspector_wasm.js';

await init();
const response = await fetch('/document.pdf');
const pdf = new Uint8Array(await response.arrayBuffer());
const result = processPdf(pdf);

console.log(result.pdfType);
console.log(result.markdown);
```

解析在浏览器本地执行；可以使用工作线程避免阻塞页面。完整说明见 [浏览器使用说明](wasm/README.md)。

### Rust

添加依赖：

```toml
[dependencies]
pdf-inspector = { git = "https://github.com/jesko2004/pdf-inspector.git" }
```

```rust
use pdf_inspector::process_pdf;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let result = process_pdf("document.pdf")?;
    println!("文档类型：{:?}", result.pdf_type);
    if let Some(markdown) = &result.markdown {
        println!("{}", markdown);
    }
    Ok(())
}
```

完整接口见 [Rust 使用说明](docs/rust-api.md)。

## 本地后端

可选后端将提取能力组织为持久化任务和知识库服务，支持上传、状态查询、读取结果、重试、业务字段校验、检索引用和备份恢复。内置供应商报价模板 `purchase_quote`；已知发票模板的适用版式和导入方法见 [发票模板说明](docs/yeslogic-invoice-template.md)。

完成上面的 Python 源码构建后，在同一虚拟环境中安装后端和本地识别依赖：

```bash
pip install -e ".[backend,ocr]"
```

下面是 Windows PowerShell 的本地配置示例：

```powershell
$env:PDF_INSPECTOR_OCR_PROVIDER = 'rapidocr'
$env:PDF_INSPECTOR_VECTOR_STORE = 'sqlite'
$env:PDF_INSPECTOR_EMBEDDING_PROVIDER = 'hash'
$env:PDF_INSPECTOR_LLM_PROVIDER = 'extractive'
pdf-inspector-api
```

默认地址为 `http://127.0.0.1:8000`，交互式接口文档位于 `http://127.0.0.1:8000/docs`。纯离线使用前，需要提前准备依赖和识别模型。默认未配置接口密钥时不启用鉴权；开放给其他设备前，应按 [后端使用说明](docs/backend.md) 配置密钥、角色及访问入口。

`hash` 和 `extractive` 用于验证本地检索与引用流程，不代表真实模型的语义理解或回答质量。需要其他模型服务、重排或存储配置时，参考后端文档。

## 验收与适用边界

本轮离线本地版本已在约定范围内基本验收通过。以下结果对应已验收的修复候选，详细证据和复现方式见 [最终验收报告](docs/acceptance-final-report.md) 与 [验收复现说明](docs/acceptance-reproduction.md)。

| 验证项 | 已记录结果 |
|---|---|
| Rust 测试 | 893 项通过；格式检查与严格静态检查通过 |
| 后端测试 | 95 项通过；真实 pgvector 连接 1 项因不在本地 SQLite 范围内而跳过 |
| Python 绑定与脚本测试 | 分别为 64 项、17 项通过 |
| PDF 内容覆盖 | 16 份、86 页；37 项保护断言及 45 项后续检查通过 |
| 本地识别稳定性 | 8 个任务通过，包含并发处理与队列清空检查 |
| 完整接口及独立恢复 | 22 项检查通过，原数据目录不可用时仍可读取、检索和重新入库 |

当前验收范围是单实例 SQLite、本地 RapidOCR，以及 `hash` / `extractive` 检索引用流程。浏览器、Node.js 接口虽已提供，不应据此将本轮本地后端验收扩写为全部平台验收。

- **扫描与图像文字**：后端对已判定需要识别的页面执行 OCR，并对符合保守条件的图片封面补充文字、保留原生内容；不保证补齐任意页面上的所有图像文字。
- **任务状态**：`ready` 表示已实现的检查未要求复核，不代表每个可见字符均已提取。关键业务证据仍需核对来源。
- **字段冲突**：已知发票的 BSB 字段冲突保持 `needs_review`，不为取得成功状态而自动选定一个值。
- **仍有限制的场景**：完整手写、旋转印章、未验证的复杂表头及版式不在当前保证范围内；影响金额、单位、含义或来源关系的问题不能仅作为排版差异忽略。
- **服务能力**：本轮不证明真实模型回答质量、生产服务等级或多实例部署能力。
- **外部回归**：`pdf-evals` 未运行，项目负责人已批准本次收尾的单次豁免；不能表述为外部回归通过或等价覆盖，长期提交规则保持不变。

更多说明见 [范围与已知限制](docs/acceptance-scope.md)、[后续修复记录](docs/acceptance-deferred-fixes.md) 和 [外部回归处理记录](docs/external-regression-resolution.md)。比较自有样本的新旧结果时，可参考 [基准对比说明](docs/benchmarking.md)。

## 分类与处理方式

分类器分析页面中的文字、图像及相关内容，结合扫描策略形成类型和置信度。当前 `DetectionConfig::default()` 使用 `Sample(8)`：最多均匀抽样 8 页。抽样或提前退出的结果不代表对每一页都做了完整检查。

| 扫描策略 | 行为 | 适用情况 |
|---|---|---|
| `Sample(n)` | 均匀抽样最多 n 页；当前默认参数为 8 | 需要控制检测开销的大型文档 |
| `Full` | 检查全部页面，不提前退出 | 需要更完整地区分混合型与扫描型文档 |
| `EarlyExit` | 扫描时在遇到首个非文字页后提前退出 | 判断是否可直接进入文字提取流程 |
| `Pages(vec)` | 只检查指定的页码 | 调用方已经知道需要核对的页面 |

```text
接收 PDF
  → 分类与页面分析
  → 提取可用原生文字、识别版面和表格
  → 需要文字识别且已启用后端识别能力时，处理相应页面
  → 生成 Markdown 或结构化结果
  → 根据业务校验结果决定是否需要人工复核
```

文档加载后在分类与提取阶段共享，减少重复解析。具体耗时取决于文件结构、页数、机器配置和处理选项，应使用自有样本测量。

## 项目结构

```text
src/
  lib.rs                — 公共接口、选项与处理流程
  detector.rs           — 文档分类与页面分析
  types.rs              — 文字、行、矩形等共享类型
  text_utils.rs         — 字符、语言边界与文本处理
  tounicode.rs          — 字体字符映射解析
  extractor/            — 内容流、字体、链接及版面提取
  tables/               — 矩形、线条和启发式表格检测及格式化
  markdown/             — 标题、段落、列表和 Markdown 转换
  python.rs             — Python 绑定
  bin/                  — 命令行工具
backend/                — 任务、业务模板、文字识别与知识库服务
napi/                   — Node.js 绑定
wasm/                   — 浏览器绑定
tests/                  — 集成测试及仓库内样本
docs/                   — 接口文档、使用说明及验收记录
```

## 开发与验证

```bash
# 检查格式
cargo fmt --check

# 严格静态检查
cargo clippy -- -D warnings

# 单元测试、集成测试及文档测试
cargo test

# 构建发布优化产物
cargo build --release
```

后端、绑定和离线验收命令见 [验收复现说明](docs/acceptance-reproduction.md)；模块日志和定位方法见 [调试说明](docs/debugging.md)。提交要求以仓库中的 [开发约定](AGENTS.md) 为准。

## 文档入口

| 主题 | 文档 |
|---|---|
| Python 接口 | [使用与接口说明](docs/python.md) |
| Node.js 接口 | [构建与调用说明](napi/README.md) |
| 浏览器接口 | [WebAssembly 使用说明](wasm/README.md) |
| Rust 接口 | [类型与调用说明](docs/rust-api.md) |
| 本地后端 | [配置、接口和运维说明](docs/backend.md) |
| 已知发票模板 | [模板导入与适用范围](docs/yeslogic-invoice-template.md) |
| 验收记录 | [最终报告](docs/acceptance-final-report.md) · [复现步骤](docs/acceptance-reproduction.md) |

## 许可证

本项目采用 [MIT 许可证](LICENSE)。
