<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/images/janus-wordmark-dark.svg">
    <img src="docs/images/janus-wordmark.svg" alt="Janus" width="420">
  </picture>
</p>

<p align="center">
  <b>回望以推理，记忆以预测。</b><br>
  一个有记忆、也有前瞻的市场 Agent：记住你相信过什么，再把这份记忆变成可校准的概率判断。
</p>

<p align="center">
  <a href="https://github.com/HugoXK/janus/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/HugoXK/janus/actions/workflows/ci.yml/badge.svg?branch=main"></a>
  <img alt="Python" src="https://img.shields.io/badge/python-%E2%89%A53.11-3776AB?logo=python&logoColor=white">
  <img alt="DSH" src="https://img.shields.io/badge/DSH-plugin-3B5BFD">
  <img alt="MCP" src="https://img.shields.io/badge/MCP-server-6366f1">
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-Apache_2.0-green"></a>
  <img alt="Status" src="https://img.shields.io/badge/status-v0.1%20scaffold-orange">
</p>

<p align="center"><a href="README.md">English</a> | 中文</p>

---

> **状态：** `v0.1.0` 脚手架。point-in-time 存储、技术指标引擎、预测账本、校准原语、人设画像、DSH 插件骨架已经就位。实时数据适配器、大盘/行业/个股看板、完整预测引擎、复盘工作流是下一步。这是研究工具，不是投资建议，也不执行交易。

Janus 有两张脸。**Memory** 记录你相信过什么、当时知道什么、后来对不对；**Foresight** 把这份记录变成关于未来的、可校准的概率。

大多数市场工具要么把你淹没在数据里，要么直接卖你一个预测。Janus 保留证据、记住推理，并在你错的时候告诉你。它本地优先、point-in-time、可审计。

## 为什么叫 Janus

Janus 是罗马神话里的门神、过渡之神、开端与终结之神，**January（一月）** 就以他命名。市场充满门槛：每一次决策，都站在“已知”和“未知”之间。

两张脸不是“两面派”。它们是这个产品的两种纪律：**记忆**与**前瞻**。Janus 不是神谕，是仪器。

命名决策见 [docs/adr/0001-name.md](docs/adr/0001-name.md)，完整品牌规则见 [docs/BRAND.md](docs/BRAND.md)。

## 它是什么

- 个人化的、point-in-time 的市场记忆：观察、判断、预测、结果，全部带来源和时间。
- 带校准的概率预测账本，不是价格预言机。
- 面向大盘、行业、个股的分析引擎。
- 一个 Python 核心，外加 DSH 插件与 MCP 服务。
- 本地优先、默认免费数据、模型无关。

## 它不是什么

- 不是荐股工具，不是交易机器人。
- 不接券商，不执行交易。
- 不承诺收益。
- 不是 Bloomberg 终端。
- 不是“事后诸葛亮”：每个预测都在结果之前落库。
- 不是投资建议。

## 脚手架今天证明了什么

先不谈收益。脚手架先证明不变量：

| 不变量 | 位置 |
| --- | --- |
| 领域契约与 JSON Schema 已冻结 | `schemas/janus.schema.json`、`tests/test_contracts.py` |
| 迁移确定、可重复执行 | `tests/test_migrations.py`、`janus migrate` |
| 配置优先级与 doctor 有测试 | `tests/test_config.py`、`janus config doctor` |
| 未来数据永远不会进入 as-of 视图 | `tests/test_asof.py` |
| published / observed 两种模式、快照、分页 | `tests/test_asof.py` |
| as-of 性质在生成输入下成立 | `tests/test_asof_hypothesis.py` |
| Tiingo 复权字段正确，重复摄入幂等 | `tests/test_tiingo.py` |
| 实体图能解析 ticker、CIK、名称 | `tests/test_entities.py` |
| provenance trace 与 as-of 搜索 | `tests/test_provenance.py` |
| yfinance 复权字段映射 | `tests/test_yfinance.py` |
| FRED 最新值与 ALFRED vintage | `tests/test_fred.py` |
| SEC 重述不会覆盖 as-filed 事实 | `tests/test_sec_edgar.py` |
| 公开文案没有收益承诺 | `tests/test_copy.py` |
| 宽度、regime、行业轮动是确定性的 | `tests/test_breadth.py`、`tests/test_regime.py`、`tests/test_sector.py` |
| 特征是 point-in-time 且带 hash | `tests/test_features.py` |
| Dashboard contracts 可验证 | `tests/test_dashboards.py` |
| 预测不可变，只能结算一次 | `tests/test_ledger.py` |
| RSI 有界；MACD / Bollinger / OBV 行为正确 | `tests/test_indicators.py` |
| 离线闭环不需要付费 API，且输出匹配 golden file | `tests/test_demo_golden.py` |

Demo 会展示：20 条可见观察、排除一条未来数据、计算 RSI、记录并结算一个预测、在一个玩具样本上计算 Brier / ECE、匹配一个人设。数字只是冒烟测试，不是 benchmark。

## 功能状态

| 模块 | 现在 | 下一步 |
| --- | --- | --- |
| **Memory** | bitemporal 存储、published/observed 模式、快照、实体图、provenance | 去重、保留策略、快照导出 |
| **Foresight** | 预测账本、校准、baseline | 特征库、概率模型、情景树 |
| **Analysis** | RSI/MACD/ATR/Bollinger/OBV、宽度、regime、行业 RRG、feature store、dashboard contracts | DSH 面板与完整 UI |
| **Review** | debrief API、归因辅助 | 归因引擎、反事实重放 |
| **Taste** | 10 题 profile、大师先验 | 人设条件检索、进化 |
| **Interface** | CLI、demo、MCP 骨架 | DSH 面板、cron、审批 |
| **Data** | Tiingo、yfinance、SEC EDGAR、FRED / ALFRED、cache、blob store | GDELT、RSS |

## 它是怎么工作的

### 三个时间

每条观察都带：

- `published_at`：世界什么时候可能知道；
- `observed_at`：Janus 什么时候真的抓到；
- `valid_from` / `valid_to`：这条事实自身的有效期。

as-of 查询只看 `published_at` 和有效期。未来的数据可以已经在库里，但对历史视图不可见。这是回测和幻想的分界线。

### 预测账本

预测在结果之前写入：概率、horizon、模型版本、特征 hash。预测本身没有编辑路径，唯一允许的变更是在结果出来之后挂上 outcome。一个不能被证伪的预测，也无法被校准。

### 校准闭环

结果出来之后，Janus 打分、归因、写复盘。账本积累后，它能回答单次回测回答不了的问题：

- 高波动 regime 下，模型是不是过度自信？
- RSI 在震荡市有用、在趋势市反而有害吗？
- 哪个人设在哪个 horizon 上校准得更好？
- 证据变化之前，我们到底相信什么？

## 架构

```
┌─────────────────────────────────────────────────────────┐
│                      DSH (TypeScript)                    │
│  UI: 大盘 / 行业 / 个股 / 判断 / 校准                    │
│  Agent loop · cron · approvals · skill                   │
└───────────────────────────┬─────────────────────────────┘
                            │ MCP
┌───────────────────────────▼─────────────────────────────┐
│                    Janus Core (Python)                   │
│  data → memory → analysis → forecast → review → persona  │
│  bitemporal store · entity graph · feature store         │
│  calibration · BeliefBench · CLI                         │
└───────────────────────────┬─────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
   免费数据             本地模型            可选付费
   Tiingo/yfinance      DeepSeek/Qwen       Polygon/FMP
   SEC/FRED/GDELT       Ollama/vLLM         (增强)
```

**为什么是 DSH：** 插件模型直接给 UI、cron、审批；也能接 FlyBot 和 bot-social。

**为什么是 Python：** 数据、指标、财报、回测、校准都在 Python 生态里。核心可以脱离 DSH 使用。

**为什么是 MCP：** 核心应该能被 Claude、ChatGPT、OpenCode、Cursor 调用。DSH 是第一个壳，不是唯一的壳。

更多见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) 和 [docs/adr/0002-architecture.md](docs/adr/0002-architecture.md)。

## 快速开始

需要 Python 3.11+ 和 [uv](https://docs.astral.sh/uv/)。

```bash
uv sync --extra dev
uv run janus demo
uv run pytest
```

或者：

```bash
make install
make demo
make test
```

`pip` 备用：

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
janus demo
```

Demo 完全离线，不需要 API key，也不需要网络。

## Demo 输出

```text
Janus demo
============================================================
as_of:                 2026-01-15T00:00:00+00:00
observations visible:  20 (future row excluded)
current RSI(14):       85.5
thesis:                ACME remains constructive while RSI stays above 50 and price...
prediction:            P(up over 1M) = 0.65
prediction settled:    True
brier score:           0.1175
expected calib. error: 0.3333
taste match:           Lynch (0.96)
============================================================
This demo is research tooling, not investment advice.
```

数字来自玩具样本，只演示机制，不代表能力。

## 数据源

默认免费，付费源只是增强。遵守每个数据源的服务条款，不要转售数据。

| 需要 | 默认 | 备用 | 注意 |
| --- | --- | --- | --- |
| 行情 | Tiingo EOD | yfinance、Stooq | yfinance 非官方，会断 |
| 基本面 / 公告 | SEC EDGAR | FMP、Alpha Vantage | SEC 最权威；带 User-Agent |
| 宏观 | FRED / ALFRED | World Bank、IMF | point-in-time 用 ALFRED vintage |
| 新闻 / 事件 | GDELT | Marketaux、NewsAPI、RSS | GDELT 噪声大；RSS 更稳 |
| 中国 | AkShare | BaoStock、Tushare | 抓取型接口需要 fallback |

已知陷阱：延迟/非官方行情、财报重述、幸存者偏差、公司行动、发布时间 vs 抓取时间、新闻转载重复、股票代码变更。存储层会保留足够元数据来显式处理。

## 仓库结构

```
core/janus/
  data/          适配器契约与免费数据源
  memory/        models、SQLite store、as-of 辅助
  analysis/      指标、宽度、regime、行业
  forecast/      预测账本、校准、baseline
  thesis/        判断跟踪
  review/        debrief 与归因
  persona/       profile 向量与大师先验
  eval/          BeliefBench 与 walk-forward 骨架
  mcp/           可选 MCP server
  cli.py         本地 CLI
  demo.py        离线端到端 demo

dsh-plugin/      DSH 插件（TypeScript）：面板、命令、cron
docs/            架构、数据模型、预测、品牌、ADR
tests/           as-of、指标、账本测试
examples/        离线 demo 入口
```

## 路线图

完整的 50 个 issue 计划见 [docs/BACKLOG.md](docs/BACKLOG.md)。v0.1.0 发布计划见 [docs/RELEASE_0.1.0.md](docs/RELEASE_0.1.0.md)。

- [x] 仓库脚手架
- [x] 领域契约与 JSON Schema
- [x] Schema 迁移
- [x] 配置加载与 `janus config doctor`
- [x] Golden demo 与 property-based as-of 测试
- [x] point-in-time 存储与 as-of 查询
- [x] published / observed 查询模式、快照、分页
- [x] Tiingo EOD 适配器
- [x] yfinance fallback 适配器
- [x] SEC EDGAR submissions 与 XBRL 适配器
- [x] FRED / ALFRED vintage 适配器
- [x] 实体图与 alias resolution
- [x] Provenance traversal API
- [x] Review gate、merge gate、PR 流程
- [x] Secret scan 与 release workflow
- [x] 技术指标引擎
- [x] 宽度、regime、行业轮动特征
- [x] point-in-time feature store
- [x] 大盘 / 行业 / 个股 dashboard contracts
- [x] 预测账本与校准原语
- [x] 人设 profile 与大师先验
- [x] 离线 demo 与测试
- [ ] GDELT 事件摄入
- [ ] RSS / IR 摄入
- [ ] 大盘 / 行业 / 个股 DSH 面板
- [ ] 完整预测引擎与情景树
- [ ] 判断跟踪与复盘
- [ ] DSH 面板、命令、cron
- [ ] BeliefBench：lookahead-free 评测
- [ ] V1.1：期权 / 情绪特征、AgentDescent 人设进化
- [ ] V1.2：多市场、组合构建、协作

## 评测

Janus 不声称 alpha。它声称预测可以被检查。

**BeliefBench**（计划）是一个 lookahead-free 的评测框架：

- 历史 as-of 场景 + 解决时间；
- 证据 grounding：每个 claim 必须能落到来源 span；
- point-in-time 正确性：不用未来数据，不用重述数据；
- 校准：Brier、log loss、可靠性、ECE；
- 稳健性：按 regime、horizon、persona 切分。

Baseline 会包括 random、always-up、RSI-only、buy-and-hold。没有 walk-forward、交易成本和明确样本，就不发布任何收益数字。

## 安全与隐私

- 默认本地优先；SQLite 存在 `~/.janus/janus.db`。
- 不保存券商凭证，不执行交易，不碰真钱。
- 仓库不提交密钥；`.env`、key、本地数据都被忽略。
- 数据留在你的机器上，除非你显式导出。
- Janus 不是投资建议。在中国，证券投资咨询需要牌照；Janus 定位为个人研究工具，不是荐股服务。

## FAQ

**这是投资建议吗？**
不是。它是研究工具，不推荐买卖。

**它会预测价格吗？**
不会。它给概率、情景、regime 估计，并在事后打分。

**必须用付费 API 吗？**
不用。核心闭环设计为免费数据 + 本地模型可跑，付费源只是增强。

**它会交易吗？**
不会。V1 不接券商。

**为什么叫 Janus？**
罗马门神、过渡之神；January 以他命名。两张脸是记忆与前瞻，不是两面派。

**为什么基于 DSH？**
插件模型直接提供 UI、cron、审批；Python 核心保持独立，壳可以换。

**能和 Claude、ChatGPT、OpenCode 一起用吗？**
可以，通过 MCP。DSH 只是第一个壳。

**和别的开源金融 Agent 有什么不同？**
大多数优化“交易决策”；Janus 优化“记忆 + 校准”的闭环：point-in-time 证据、不可变预测账本、会改变下一次预测的复盘。

**最难的技术点是什么？**
point-in-time 正确性和校准。LLM 不是最难的部分。

**能上生产吗？**
不能。它是 `v0.1.0` 脚手架，用来探索，不用来管钱。

## 贡献

见 [CONTRIBUTING.md](CONTRIBUTING.md)。一句话：

- point-in-time，否则不算；
- LLM 负责推理，软件负责计算；
- 不做建议、不做执行、不承诺收益；
- 默认免费；
- 小接口，测不变量。

## License

Apache-2.0，见 [LICENSE](LICENSE)。

## 构建于

- [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)：插件壳与 agent loop。
- [MCP](https://modelcontextprotocol.io/)：工具契约。
- Python、pandas、NumPy、SQLite。
- 作者其他项目中的想法与模式：FlyBot、bot-social、AgentDescent、Fledge。Janus 是独立项目，不声称与它们存在隶属关系。
