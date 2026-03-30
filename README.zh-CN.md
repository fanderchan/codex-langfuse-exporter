# Codex Langfuse Exporter

[![CI](https://github.com/fanderchan/codex-langfuse-exporter/actions/workflows/ci.yml/badge.svg)](https://github.com/fanderchan/codex-langfuse-exporter/actions/workflows/ci.yml)

[English](./README.md) | 简体中文

将 Codex 本地会话数据回填到 Langfuse，并以 synthetic `generation`
observation 的形式展示。

这个项目适合本地运行 Codex、同时将 tracing 发往 Langfuse 的团队。Codex
本身已经会发送 OTEL spans，但这些 spans 不一定包含 Langfuse 直接可识别的
prompt、output 和 token usage 字段。这个 exporter 会读取 Codex 本地
session JSONL 文件，并补发稳定的 synthetic observations，让这些字段在
Langfuse 中可见。

## 它能做什么

- 从 `~/.codex/sessions` 读取 Codex session 文件
- 按 Codex turn 重建 observation
- 提取 turn 的输入、最终 assistant 输出和 token usage
- 有意跳过启动时注入的 AGENTS 和环境上下文
- 使用稳定的 trace id 和 span id，重复同步时会落到同一批回填 observation 上
- 支持用 state file 做增量同步
- 可以手动执行，也可以挂 cron 或 systemd timer

## 它不能做什么

- 不会修改 Codex 本身
- 不会修改 Langfuse
- 无法重建本地 session 文件里根本不存在的隐藏内部轮次
- 不能替代 Codex 原生 OTEL spans，它只是补充

## 快速开始

### 1. 创建虚拟环境

```bash
cd exporter
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -e .
```

### 2. 检查读取到的配置

默认会从 `/root/.codex/config.toml` 读取 Langfuse OTLP 配置。

```bash
codex-langfuse-exporter --dry-run
```

### 3. 同步最近的 session

```bash
codex-langfuse-exporter --days 3 --limit 30
```

## 安装方式

### Editable install

适合开发和调试 exporter：

```bash
pip install -e .
```

### 直接执行脚本

适合保留你当前已有的本地调用方式：

```bash
python3 /path/to/exporter/codex_langfuse_sync.py --days 1 --limit 50
```

兼容脚本入口会继续保留，内部只是转发到打包后的 CLI。

## 配置说明

### 默认 Codex 路径

- Codex config：`/root/.codex/config.toml`
- Codex sessions：`/root/.codex/sessions`

你也可以覆盖它们：

```bash
codex-langfuse-exporter \
  --config /path/to/config.toml \
  --sessions-root /path/to/sessions
```

### 手动覆盖 OTLP endpoint

适合临时切换到另一个 Langfuse 实例，而不修改 Codex 配置：

```bash
codex-langfuse-exporter \
  --endpoint https://langfuse.example.com/api/public/otel \
  --header 'Authorization=Basic ...' \
  --header 'x-langfuse-ingestion-version=2'
```

### 增量同步

使用 state file 跳过未变化的 turn：

```bash
codex-langfuse-exporter \
  --days 1 \
  --limit 50 \
  --state-file /var/lib/codex-langfuse-exporter/state.json
```

### 只同步单个 session

```bash
codex-langfuse-exporter \
  --session-id 019d3d85-2065-7dc0-b58c-5e31d9c80368
```

## CLI 说明

```text
usage: codex-langfuse-exporter [options]

核心参数:
  --config PATH
  --sessions-root PATH
  --days N
  --limit N
  --session-id ID
  --state-file PATH
  --dry-run

OTLP 参数:
  --endpoint URL
  --header NAME=VALUE
  --public-key KEY
  --langfuse-environment NAME
  --timeout-sec N
```

完整参数请执行 `codex-langfuse-exporter --help`。

## systemd timer

示例 unit 文件位于 [`systemd/`](./systemd)。安装前请先检查路径是否符合你的环境。

```bash
sudo install -m 0644 systemd/codex-langfuse-sync.service /etc/systemd/system/codex-langfuse-sync.service
sudo install -m 0644 systemd/codex-langfuse-sync.timer /etc/systemd/system/codex-langfuse-sync.timer
sudo systemctl daemon-reload
sudo systemctl enable --now codex-langfuse-sync.timer
```

## 数据映射方式

对于每个 Codex turn，exporter 会发出一个 synthetic Langfuse
`generation` observation，包含：

- `langfuse.trace.name`
- `langfuse.trace.input`
- `langfuse.trace.output`
- `langfuse.observation.type = generation`
- `langfuse.observation.input`
- `langfuse.observation.output`
- `langfuse.observation.usage_details`

trace id 和 span id 会根据 `session_id + turn_id` 稳定生成，所以从
exporter 的视角看，重复同步是幂等的。

## 隐私与安全

- exporter 会读取本地 Codex session 文件，这些文件可能包含敏感 prompt
  和输出
- 它会把这些内容发送到配置好的 Langfuse OTLP endpoint
- 在启用定时同步前，请先确认 Codex 保留策略、文件权限和 Langfuse 部署环境

## 开发

运行测试：

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

对本地 session 做 dry run：

```bash
python3 codex_langfuse_sync.py --dry-run
```

## Release 检查清单

1. 更新 `pyproject.toml` 和 `src/codex_langfuse_exporter/__init__.py` 中的版本号
2. 更新 `CHANGELOG.md`
3. 运行单元测试
4. 用真实的 Codex session 目录执行一次 `--dry-run`
5. 打 tag 并发布

## 许可证

MIT，见 [`LICENSE`](./LICENSE)。
