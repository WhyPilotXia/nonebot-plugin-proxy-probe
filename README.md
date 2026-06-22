# nonebot-plugin-proxy-probe

NoneBot2 / OneBot V11 插件。扫描目标 `/20` 网段中的 Clash HTTP 代理，
缓存代理可用性、出口 IP 和属地，并将结果渲染为图片。

## 命令

```text
/proxy                 显示缓存结果
/proxy -h
/proxy --help          显示命令帮助
/proxy -i 218.194.50.3
/proxy --ip 218.194.50.3
/proxy --ip=218.194.50.3
                       持久化设置目标参考 IPv4
/proxy -p
/proxy --probe         后台重新扫描目标网段
/proxy -r
/proxy --refresh       后台刷新缓存代理的可用性、出口 IP 和属地
/proxy -s
/proxy --stop          停止当前后台任务并输出已有结果
```

同一时间只允许运行一个扫描或刷新任务。

刷新时，已经无法作为代理访问 HTTPS 的缓存项会被移除；代理仍可用但
出口 IP 或属地接口全部失败时，该项会保留并显示“无法探测代理后地址”。

当 `proxy_probe_target_ip` 留空，并成功自动取得本机内网 IP 与直连
公网 IP 后，会给任务发起消息添加表情 `4`。

## 配置

可在 NoneBot `.env` 中覆盖以下配置：

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

`proxy_probe_local_ip` 是本机用于绑定出站连接的网卡地址。留空时根据
系统默认 IPv4 路由自动取得当前出站网卡地址。

`proxy_probe_target_ip` 仅用于计算待扫描网段。留空且没有通过命令保存
目标 IP 时，会禁用环境代理，绑定上述网卡，依次直连多个 IP 查询接口
取得自身出口 IPv4。

插件先 `require("nonebot_plugin_localstore")` 再导入 LocalStore。数据
保存在该插件分配的数据目录：

- `proxy_cache.json`：扫描结果、时间、进度和运行状态。
- `settings.json`：通过 `/proxy -i` 或 `/proxy --ip` 保存的目标 IP。

目标 IP 的优先级为：LocalStore 用户设置 > 环境变量 > 自动探测。如果
环境变量和 LocalStore 设置同时存在，启动时会输出 warning，并使用
LocalStore 值。

图片最多显示前 50 条结果，但缓存会保存全部结果。
