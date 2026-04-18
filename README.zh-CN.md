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

本项目里的 `prompt` 指的是某个 Codex turn 的用户输入原文。
`output` 指的是该 turn 的最终 assistant 回复原文。

## 它能做什么

- 从当前用户的 `.codex/sessions` 读取 Codex session 文件
- 按 Codex turn 重建 observation
- 提取 turn 的输入、最终 assistant 输出和 token usage
- 可以按需分别导出 prompt、output 和 usage，适合隐私敏感场景
- 有意跳过启动时注入的 AGENTS 和环境上下文
- 使用稳定的 trace id 和 span id，重复同步时会落到同一批回填 observation 上
- 支持用 state file 做增量同步
- 可以手动执行，也可以挂 cron 或 systemd timer
- 在 macOS 上同样适用于 Codex CLI 和 Codex Desktop/App，因为它们的
  session 都落在 `~/.codex/sessions`

## 它不能做什么

- 不会修改 Codex 本身
- 不会修改 Langfuse
- 无法重建本地 session 文件里根本不存在的隐藏内部轮次
- 不能替代 Codex 原生 OTEL spans，它只是补充

## 快速开始

### 1. 创建虚拟环境

```bash
cd codex-langfuse-exporter
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -e .
```

### 2. 检查读取到的配置

默认会从当前用户的 Codex `config.toml` 读取 Langfuse OTLP 配置。

```bash
codex-langfuse-exporter --dry-run
```

### 3. 同步最近的 session

```bash
codex-langfuse-exporter --days 3 --limit 30
```

## 启用 Codex OTEL

exporter 默认会从 Codex 的 `config.toml` 里读取 Langfuse OTLP endpoint
和 headers。如果你希望 exporter 自动发现发送目标，先把 Codex 的 OTEL
配置好。

Linux/macOS 示例路径：`~/.codex/config.toml`  
Windows 示例路径：`%USERPROFILE%\.codex\config.toml`

```toml
[otel]
environment = "dev"
log_user_prompt = true

trace_exporter = { otlp-http = {
  endpoint = "http://127.0.0.1:3000/api/public/otel/v1/traces",
  protocol = "binary",
  headers = {
    Authorization = "Basic <base64(public_key:secret_key)>",
    x-langfuse-ingestion-version = "4"
  }
}}
```

`Authorization` 是 Langfuse public key 和 secret key 按
`public_key:secret_key` 拼接后再做 Base64 编码得到的 HTTP Basic auth。

Linux/macOS 生成方式：

```bash
printf '%s' 'pk-lf-...:sk-lf-...' | base64
```

Windows PowerShell 生成方式：

```powershell
[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("pk-lf-...:sk-lf-..."))
```

如果你只想让 exporter 回填 token usage，不发送 prompt 和 output 原文，可
以运行 exporter 时带上 `--no-prompt --no-output`。如果你还希望 Codex 原生
OTEL spans 也不要包含用户输入，可以把 `log_user_prompt = false`。

## 安装方式

### Editable install

适合开发和调试 exporter：

```bash
pip install -e .
```

### 直接执行脚本

适合保留你当前已有的本地调用方式：

```bash
python3 /path/to/codex-langfuse-exporter/codex_langfuse_sync.py --days 1 --limit 50
```

兼容脚本入口会继续保留，内部只是转发到打包后的 CLI。

### macOS 快速开始

如果这台 Mac 的 `~/.codex/config.toml` 里还没有 Langfuse OTEL 配置，可以先
走环境变量方式，不必马上改 Codex 配置：

```bash
cp macos/codex-langfuse-exporter.env.example macos/codex-langfuse-exporter.env
```

把真实的 `CODEX_LANGFUSE_SECRET_KEY` 填进去后，直接运行：

```bash
./macos/run-codex-langfuse-exporter.sh
```

仓库里也带了一个和 Windows `.bat` 等价的 macOS 隧道脚本：

```bash
./macos/start-langfuse-tunnel.command
```

这个脚本会先打开 `http://127.0.0.1:3000`，然后在当前 Terminal 窗口维持 SSH
隧道，按 `Ctrl+C` 即可停止。

## 配置说明

### 默认 Codex 路径

- Linux/macOS config：`~/.codex/config.toml`
- Linux/macOS sessions：`~/.codex/sessions`
- Windows config：`%USERPROFILE%\.codex\config.toml`
- Windows sessions：`%USERPROFILE%\.codex\sessions`

你也可以覆盖它们：

```bash
codex-langfuse-exporter \
  --config /path/to/config.toml \
  --sessions-root /path/to/sessions
```

### 隐私控制

默认会同时导出三类字段：

- `--prompt`：导出用户输入原文
- `--output`：导出最终 assistant 输出原文
- `--usage`：导出 token usage

可以用对应的 `--no-...` 参数单独关闭。例如只回填 token usage，不发送
prompt 和 output 原文：

```bash
codex-langfuse-exporter \
  --days 3 \
  --no-prompt \
  --no-output
```

这些开关只影响之后新发送的 payload，不会删除 Langfuse 里已经入库的旧文
本。

### 手动覆盖 OTLP endpoint

适合临时切换到另一个 Langfuse 实例，而不修改 Codex 配置：

```bash
codex-langfuse-exporter \
  --endpoint https://langfuse.example.com/api/public/otel/v1/traces \
  --header 'Authorization=Basic ...' \
  --header 'x-langfuse-ingestion-version=4'
```

### 环境变量 OTLP 兜底

适合 macOS 场景下还不想先改 `~/.codex/config.toml` 的情况：

```bash
export CODEX_LANGFUSE_ENDPOINT='http://127.0.0.1:3000/api/public/otel/v1/traces'
export CODEX_LANGFUSE_PUBLIC_KEY='pk-lf-...'
export CODEX_LANGFUSE_SECRET_KEY='sk-lf-...'
export CODEX_LANGFUSE_INGESTION_VERSION='4'
codex-langfuse-exporter --days 1 --limit 50 --no-prompt --no-output
```

优先级顺序是：CLI 参数，其次环境变量，最后才是 Codex 的 `config.toml`。

### 增量同步

使用 state file 跳过未变化的 turn：

```bash
codex-langfuse-exporter \
  --days 1 \
  --limit 50 \
  --state-file /var/lib/codex-langfuse-exporter/codex_langfuse_sync_state.json
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
  --prompt / --no-prompt
  --output / --no-output
  --usage / --no-usage
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

仅适用于 Linux。Windows 用户请直接运行 CLI，或者使用 Task Scheduler。

示例 unit 文件位于 [`systemd/`](./systemd)。安装前请先检查路径是否符合你的环境。

```bash
sudo install -m 0644 systemd/codex-langfuse-sync.service /etc/systemd/system/codex-langfuse-sync.service
sudo install -m 0644 systemd/codex-langfuse-sync.timer /etc/systemd/system/codex-langfuse-sync.timer
sudo systemctl daemon-reload
sudo systemctl enable --now codex-langfuse-sync.timer
```

## Windows Task Scheduler

如果你在 Windows 上使用 Codex，请用 Task Scheduler，而不是 `systemd`。
你可以直接使用全局 Python 3.14，不强制要求虚拟环境。

仓库里已经带了一个一键安装脚本：
[`windows/install-codex-langfuse-task.ps1`](./windows/install-codex-langfuse-task.ps1)。
先修改文件顶部这些变量：

- `PythonPath`：全局 Python 路径，例如 `C:\Python314\python.exe`
- `ProjectDir`：本地项目目录，例如 `C:\work\codex-langfuse-exporter`
- `StateFilePath`：增量同步 state file 的保存位置
- `ExporterArgs`：exporter 的 CLI 参数，例如 `--no-prompt --no-output`
- `StartTime` 和 `RepeatMinutes`：调度时间

然后在 PowerShell 里执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\windows\install-codex-langfuse-task.ps1
```

这个脚本会为当前 Windows 用户创建或覆盖一个定时任务。默认使用
`LogonType Interactive`，所以只要该用户处于登录状态，任务就能运行，同时
不需要把账号密码写进脚本。

等价的手工命令示例：

```powershell
C:\Python314\python.exe C:\path\to\codex-langfuse-exporter\codex_langfuse_sync.py --days 1 --no-prompt --no-output
```

如果你手工在 Task Scheduler 里配置，推荐填写：

- `Program/script`：`C:\Python314\python.exe`
- `Add arguments`：`C:\path\to\codex-langfuse-exporter\codex_langfuse_sync.py --days 1 --no-prompt --no-output`
- `Start in`：`C:\path\to\codex-langfuse-exporter`

建议直接填写 `python.exe` 的完整路径，而不是 `py`，这样不会依赖 PATH 或
Python Launcher 的行为。

## macOS launchd

macOS 对应的定时机制是 `launchd`。仓库里提供了安装脚本，会为当前用户写入
一个 LaunchAgent，默认每 10 分钟执行一次 exporter：

```bash
./macos/install-codex-langfuse-launch-agent.sh
```

这个 LaunchAgent 实际执行的是
[`macos/run-codex-langfuse-exporter.sh`](./macos/run-codex-langfuse-exporter.sh)，
所以你可以把 secret 放在 `macos/codex-langfuse-exporter.env` 或
`~/.config/codex-langfuse-exporter.env`，不用提交到仓库里。

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
- 如果你只想发送 token usage，可以使用 `--no-prompt` 和/或 `--no-output`
- 它会把已启用的字段发送到配置好的 Langfuse OTLP endpoint
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
