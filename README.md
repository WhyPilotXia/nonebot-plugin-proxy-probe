<div>
    <a href="https://v2.nonebot.dev/store">
    <img src="https://raw.githubusercontent.com/fllesser/nonebot-plugin-template/refs/heads/resource/.docs/NoneBotPlugin.svg" width="310" alt="logo"></a>
</div>

## ✨ 代理扫描 ✨

[![LICENSE](https://img.shields.io/github/license/WhyPilotXia/nonebot_plugin_proxy_probe.svg)](./LICENSE)[![pypi](https://img.shields.io/pypi/v/nonebot-plugin-proxy-probe.svg)](https://pypi.python.org/pypi/nonebot-plugin-proxy-probe)[![python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org)[![NoneBot](https://img.shields.io/badge/NoneBot-2.x-green.svg)](https://github.com/nonebot/nonebot2)

## 📖 介绍

扫描目标 IPv4 网段中的 Clash HTTP 代理，验证代理可用性，查询代理出口
IP 与属地，并将结果持久化缓存、渲染为图片的 NoneBot2 插件。

功能特色：

- **三级流水线**：端口扫描、代理验证、出口属地探测同时运行。
- **后台任务**：扫描和刷新不会阻塞 NoneBot，可随时查看缓存或停止任务。
- **自动识别网络**：可自动获取本机出站网卡 IPv4 和直连公网 IPv4。
- **跨平台**：兼容 Windows 与 Linux 的网卡和默认路由识别。
- **多端口支持**：可同时扫描多个 Clash HTTP 代理端口。
- **本地缓存**：使用 `nonebot-plugin-localstore` 持久化结果与用户设置。
- **图片输出**：使用插件自带字体绘制表格，以 Base64 图片发送。
- **属地高亮**：新加坡和其他非中国属地使用不同底色突出显示。


## 🎉 使用

### 指令表

| 指令 | 权限 | 说明 |
|:--:|:--:|:--|
| `/proxy` | 所有用户 | 显示当前缓存结果图片。 |
| `/proxy -h`、`/proxy --help` | 所有用户 | 显示命令帮助。 |
| `/proxy -i <IPv4>`、`/proxy --ip <IPv4>` | 所有用户 | 将目标参考 IPv4 持久化到 LocalStore。也支持 `--ip=<IPv4>`。 |
| `/proxy -p`、`/proxy --probe` | 所有用户 | 在后台重新扫描目标网段，任务开始时添加表情 `427`。 |
| `/proxy -r`、`/proxy --refresh` | 所有用户 | 刷新缓存代理的可用性、出口 IP 和属地，任务开始时添加表情 `294`。 |
| `/proxy -c`、`/proxy --cancel` | 所有用户 | 停止当前后台任务，保存并输出已有结果。 |
| `/proxy -s <编号>`、`/proxy --set <编号>` | 超级用户 | 将结果图片中对应编号的代理设置为当前 Bot 进程代理。也支持 `--set=<编号>`。 |
| `/proxy -e`、`/proxy --export` | 所有用户 | 将全部缓存代理导出为 Clash YAML，并作为群文件发送。 |

同一时间只允许一个重新扫描或缓存刷新任务运行。任务运行期间仍可使用
`/proxy` 查看当前缓存和实时进度,或`/proxy -c`来中止任务。


## 💿 安装

### 使用 nb-cli 安装

在 NoneBot2 项目根目录下执行：

```bash
nb plugin install nonebot-plugin-proxy-probe
```

### 使用 pip 安装

```bash
pip install nonebot-plugin-proxy-probe
```

使用 `pip` 安装后，在 NoneBot2 项目根目录的 `pyproject.toml` 中加载插件：

```toml
[tool.nonebot]
plugins = ["nonebot_plugin_proxy_probe"]
```

如果已有其他插件，请将 `nonebot_plugin_proxy_probe` 追加到现有
`plugins` 列表中。

### 本地源码安装

也可以在 NoneBot2 项目环境中安装本仓库：

```bash
pip install -e .
```

然后在 `pyproject.toml` 中加载：

```toml
[tool.nonebot]
plugins = ["nonebot_plugin_proxy_probe"]
```

## ⚙️ 配置

所有配置项均为可选项，**必填：否**。可在 NoneBot2 项目的 `.env` 或
`.env.prod` 中覆盖默认值。

| 配置项 | 必填 | 默认值 | 说明 |
|:--:|:--:|:--:|:--|
| `proxy_probe_local_ip` | 否 | (空字符串) | 绑定出站连接的本机 IPv4。留空时自动选择有默认网关的实体网卡。 |
| `proxy_probe_target_ip` | 否 | (空字符串) | 用于计算扫描网段的参考 IPv4。留空时优先读取 LocalStore 用户设置，否则直连查询自身公网 IPv4。 |
| `proxy_probe_prefix_length` | 否 | `20` | 扫描网段的 IPv4 前缀长度，默认扫描 `/20`。 |
| `proxy_probe_ports` | 否 | `[7897,7890]` | 需要扫描和验证的代理端口列表。 |
| `proxy_probe_connect_timeout` | 否 | `0.35` | TCP 端口连接超时时间，单位秒。 |
| `proxy_probe_proxy_timeout` | 否 | `5.0` | HTTPS 代理验证超时时间，单位秒。 |
| `proxy_probe_geo_timeout` | 否 | `5.0` | 出口 IP 与属地接口超时时间，单位秒。 |
| `proxy_probe_workers` | 否 | `256` | 端口扫描工作线程数。 |
| `proxy_probe_proxy_workers` | 否 | `256` | 代理验证工作线程数。 |
| `proxy_probe_geo_workers` | 否 | `256` | 出口 IP 与属地探测工作线程数。 |
| `proxy_probe_bind_source_ip` | 否 | `true` | 是否将网络连接绑定到选定的本机 IPv4。 |
| `proxy_probe_test_urls` | 否 | 太长同示例 | HTTPS 代理验证地址，按列表顺序回退。 |
| `proxy_probe_exclude_ips` | 否 | `[]` | 扫描时需要排除的 IPv4 地址列表。 |

配置示例：

```dotenv
proxy_probe_local_ip=
proxy_probe_target_ip=
proxy_probe_prefix_length=20
proxy_probe_ports=[7897]
proxy_probe_connect_timeout=0.35
proxy_probe_proxy_timeout=5.0
proxy_probe_geo_timeout=5.0
proxy_probe_workers=256
proxy_probe_proxy_workers=256
proxy_probe_geo_workers=256
proxy_probe_bind_source_ip=true
proxy_probe_test_urls=["https://api.ip.sb/ip","https://cp.cloudflare.com/generate_204","https://www.gstatic.com/generate_204"]
proxy_probe_exclude_ips=[]
```

### 自动获取 IP

- `proxy_probe_local_ip` 为空时，插件自动选择有默认网关的实体 IPv4
  网卡，并排除 Meta、Tailscale、ZeroTier 等常见虚拟接口。
- `proxy_probe_target_ip` 为空且没有 LocalStore 用户设置时，插件禁用
  环境代理，绑定选定网卡，直连回退接口查询自身公网 IPv4。
- 自动成功取得本机内网 IP 与直连公网 IP 后，会给任务发起消息添加
  表情 `4`。

### 目标 IP 优先级

```text
LocalStore 用户设置 > proxy_probe_target_ip 环境变量 > 自动探测
```

如果环境变量和 LocalStore 设置同时存在，插件启动时会输出 warning，
并使用 LocalStore 中的值。

## 🔍 扫描与刷新

### 重新扫描

重新扫描采用动态三级流水线：

1. 扫描目标网段和配置端口。
2. 开放端口立即进入 HTTPS 代理验证队列。
3. 确认可用的代理立即进入出口 IP 与属地探测队列。

重新扫描本身已经包含代理和属地刷新，因此任务结束或停止保存部分结果
时，扫描时间和刷新时间会同时更新。

### 缓存刷新

缓存刷新只处理上一次结果列表：

- 已经无法代理访问 HTTPS 的项目会从结果中移除。
- 代理仍可用但属地接口全部失败时，项目仍会保留。
- 查询失败时，代理后 IP 和属地显示为“无法探测代理后地址”。

### 流水线统计

结果图片顶部显示：

```text
端口扫描：开放端口数 open in 已扫描 IP 数
代理验证：确认代理数 proxy in 已验证开放端口数
属地探测：查询成功数 tested in 已查询代理数
```

例如：

```text
端口扫描：500 open in 4096
代理验证：20 proxy in 500
属地探测：20 tested in 20
```

## 🎨 图片输出

表格包含五列：

| 编号 | IP | 端口 | 代理后 IP | 代理后属地 |
|:--:|:--:|:--:|:--:|:--|

- 每个 `IP:端口` 固定占一行，不折行。
- 编号从 `1` 开始，超级用户可用 `/proxy -s <编号>` 选择对应代理。
- 图片最多显示前 50 条，LocalStore 中仍保存全部结果。
- 新加坡属地整行使用 `#FFCE46`。
- 其他非中国属地整行使用 `#C0FF02`。
- 中国大陆、香港、台湾、澳门以及无法判断的属地保持默认底色。

## 📦 数据与缓存

插件在导入 LocalStore 前执行：

```python
require("nonebot_plugin_localstore")
```

数据保存在 `nonebot-plugin-localstore` 为本插件分配的数据目录：

- `proxy_cache.json`：扫描结果、扫描/刷新时间、流水线进度和任务状态。
- `settings.json`：通过 `/proxy -i` 或 `/proxy --ip` 保存的目标参考 IP。
- `xx个-xx月xx日xx时xx分.yaml`：通过 `/proxy -e` 导出的 Clash 配置。节点以探测属地命名；“自动选择”优先在新加坡节点中测速并选择最低延迟，没有新加坡节点时回退为全部节点。

JSON 使用临时文件替换方式原子写入，降低异常退出导致缓存损坏的概率。
Bot 重启后不会尝试恢复旧线程，未完成任务会标记为因重启中止。

## 🧐 图片示例

### `/proxy`

<img width="486" height="503" alt="proxy command" src="https://github.com/user-attachments/assets/d4d4f917-8c16-4a28-8714-da5e30759c01" />

<img width="1280" height="1378" alt="proxy result" src="https://github.com/user-attachments/assets/fe7af0c4-e7cf-4f0c-bcb8-a9181d12b2d2" />

### `/proxy -h`

<img width="520" height="329" alt="proxy help" src="https://github.com/user-attachments/assets/ce9804da-3c93-4667-9450-48fb7e6d64c9" />

### `/proxy -r`

<img width="444" height="533" alt="proxy refresh" src="https://github.com/user-attachments/assets/c3888e1a-8fbc-4fcb-b8ea-544c3ed461cc" />

<img width="1900" height="1988" alt="proxy refresh result" src="https://github.com/user-attachments/assets/aae2675d-9da3-423d-a707-c6f78023048e" />

### `/proxy -p`

<img width="371" height="539" alt="image" src="https://github.com/user-attachments/assets/763d31f6-5e8f-4fd1-9789-a7546873e94c" />

<img width="1280" height="1730" alt="475d52f2fc0555bb884ed6bb389d5086_720" src="https://github.com/user-attachments/assets/339aad57-f489-4236-820a-8cbf364dc9b9" />

### `/proxy -e`


<img width="799" height="355" alt="image" src="https://github.com/user-attachments/assets/237696ea-ac96-4f03-bc13-8c2caea098be" />

<img width="2560" height="1371" alt="image" src="https://github.com/user-attachments/assets/95b38017-6f7d-4a2d-b246-0023298c71f7" />



## 🗂️ 项目结构

```text
nonebot_plugin_proxy_probe/
├── __init__.py        # 插件元数据与命令模块加载
├── cache.py           # LocalStore 结果缓存和用户设置持久化
├── commands.py        # /proxy 命令解析与 OneBot 事件处理
├── config.py          # NoneBot/Pydantic 配置模型
├── exporter.py        # 生成 Clash YAML 并缓存到 LocalStore
├── manager.py         # 后台任务、进程代理设置与 YAML 导出调度
├── models.py          # 代理结果、流水线进度和缓存模型
├── probe.py           # 网卡识别、端口扫描、代理验证和属地探测
├── render.py          # 结果排序、Pillow 表格绘制与图片转换
└── assets/
    └── 原神字体.ttf   # 图片渲染字体
```

## 🧩 兼容性

- Python `3.10+`
- NoneBot2 `2.3.0+`
- OneBot v11 适配器
- Windows / Linux
- 依赖 `nonebot-plugin-localstore`

## 📄 License

本项目遵循仓库中的 [LICENSE](./LICENSE) 文件。
