# QQ 群管理机器人

一个对接 **OneBot 11 / NapCat** 的 QQ 群管理机器人，支持群主/管理员通过命令封禁、禁言群成员，以及白名单管理、群公告、精华消息、黑名单、GitHub/B站信息查询、Owner 自动保护等功能。

> 命令前缀默认 `/`，可在 `config.json` 中修改。

---

## 一、功能与命令一览

### 群管理命令 (群主/管理员可用)

| 命令 | 作用 | 示例 |
|------|------|------|
| `/ban <QQ号> <时长> <原因>` | **封禁**（踢出群），到期自动解封 | `/ban 123456 7d 发广告` |
| `/unban <QQ号>` | **解封**（允许重新加群） | `/unban 123456` |
| `/mute <QQ号> <时长> <原因>` | **禁言**，永久禁言自动续期 | `/mute 123456 30m 刷屏` |
| `/unmute <QQ号>` | **解除禁言** | `/unmute 123456` |
| `/list` | 查看本群当前封禁/禁言名单 | `/list` |
| `/whitelist add <QQ>` | 添加白名单 | `/whitelist add 123456` |
| `/whitelist remove <QQ>` | 移除白名单 | `/whitelist remove 123456` |
| `/whitelist on\|off` | 启用/关闭白名单模式 | `/whitelist on` |
| `/whitelist` | 查看白名单 | `/whitelist` |
| `/blacklist` | 查看黑名单 | `/blacklist` |

### 群内容管理命令 (群主/管理员可用)

| 命令 | 作用 | 示例 |
|------|------|------|
| `/say <内容>` | 让机器人发送一条消息 | `/say 大家好` |
| `/note <内容> [yes\|no]` | 发布群公告，可选置顶 | `/note 欢迎新人 yes` |
| `/unnote` | 列出所有公告 | `/unnote` |
| `/unnote <序号>` | 删除指定公告 | `/unnote 3` |
| `/unnote 1,2,5` | 删除多条公告 | `/unnote 1,3,5` |
| `/unnote 1-3` | 删除范围内的公告 | `/unnote 1-3` |
| `/unnote all` | 删除全部公告 | `/unnote all` |
| `/essence <内容>` | 发送群精华消息 | `/essence 重要通知` |
| `/unessence` | 列出所有精华消息 | `/unessence` |
| `/unessence <序号>` | 取消指定精华 | `/unessence 2` |
| `/unessence all` | 取消全部精华 | `/unessence all` |

### 信息查询命令 (群主/管理员可用)

| 命令 | 作用 | 示例 |
|------|------|------|
| `/github <user/repo>` | 查看 GitHub 仓库信息（卡片+详情） | `/github torvalds/linux` |
| `/bilibili <BV号/URL>` | 查看 B 站视频信息（卡片+详情） | `/bilibili BV1xx411c7mD` |
| `/sid` | 查看当前会话信息（Bot ID、群号等） | `/sid` |

### Owner 专属命令

| 命令 | 作用 | 示例 |
|------|------|------|
| `/black <QQ号>` | 拉黑用户（禁止使用命令、添加好友、邀请入群） | `/black 123456` |
| `/unblack <QQ号>` | 取消拉黑 | `/unblack 123456` |
| `/pending` | 查看待审批的加好友/加群请求 | `/pending` |
| `/yes <ID>` | 同意指定请求 | `/yes 3` |
| `/no <ID>` | 拒绝指定请求 | `/no 3` |
| `/reload` | 刷新配置（免重启，立即生效） | `/reload` |

### 任意成员可用

| 指令 | 作用 |
|------|------|
| `赞我` | 给发送者点赞（每人每日上限 20 次） |
| `/help` | 显示帮助信息 |

### 时长格式

- `0` 或 `永久` = **永久**
- 纯数字 = **分钟**，例如 `30` 表示 30 分钟
- 也可带单位：`30s`(秒) / `10m`(分钟) / `2h`(小时) / `1d`(天) / `3w`(周)

---

## 二、自动保护机制

机器人内置了多项自动保护功能，无需手动操作：

- **Owner 防禁言**：Owner 被任何人禁言时，机器人会**自动解除**。
- **Owner 防踢**：Owner 被踢出群时，机器人会**自动邀请回群**。若邀请失败，会私聊通知 Owner 重新申请（自动通过）。
- **Owner 自动进群**：Owner 申请加群时自动同意。
- **Owner 邀请自动同意**：Owner 邀请机器人进群时自动同意并注册该群。
- **黑名单拦截**：黑名单用户的好友请求、群邀请、加群申请均会被自动拒绝。
- **封禁拦截**：被封禁的用户申请加群会被自动拒绝，直到封禁到期或被解封。
- **白名单模式**：开启后仅白名单内用户可加群（与封禁名单独立）。
- **机器人被踢自动注销**：机器人被踢出群后自动从生效群列表移除该群。
- **消息频率控制**：同群消息带随机延迟，防止被 QQ 风控。

---

## 三、运行前你需要准备

1. **一个 QQ 小号**（用来当机器人，建议用小号，别用主号）。
2. 把这个**小号拉进你的群**，并在群里**把它设为管理员**（否则没法踢人/禁言）。
3. **NapCat**（协议端）：让机器人能真正登录 QQ、收发消息。

> ⚠️ 没有这些前提，机器人无法工作。机器人只是"大脑"，NapCat 才是"手脚"。

---

## 四、安装并运行 NapCat（关键步骤）

> NapCat 版本更新较快，下面是大致流程；具体界面以 NapCat 官方为准。
> 项目地址：https://github.com/NapNeko/NapCatQQ

### 1. 安装新版 QQ 桌面端 (QQNT)
到 https://im.qq.com/pcqq/index.shtml 下载并安装**新版 QQ**（Windows 版）。
（NapCat 需要依赖 QQNT 运行。）

### 2. 下载 NapCat
到 NapCat 的 GitHub Releases 页面，下载 Windows 版（一般选 `NapCat.Shell` 的 zip 包）。
解压到一个文件夹，例如 `D:\NapCat`。

### 3. 启动 NapCat 并登录
运行解压后的启动脚本（如 `launcher.bat` 或 `napcat.bat`）。
首次启动会显示一个**二维码**，用你的**QQ 小号**扫码登录。

### 4. 配置「正向 WebSocket」
登录后，打开 NapCat 的 **WebUI**（浏览器访问，默认地址一般是 http://127.0.0.1:6099 ，
首次会有 token，看启动日志里的提示）。

在 WebUI 的「网络配置 / Network」里，**新建一个连接**：
- 类型选 **正向 WebSocket (WebSocket Server)**
- 监听端口填 **3001**（或你喜欢的端口）
- 保存并启用

> 如果端口被占用或想换端口，记得**同步改**本项目 `config.json` 里的 `ws_url`。

---

## 五、配置并启动机器人

### 1. 安装依赖

**Windows：** 安装 Python 3.12+（推荐 `winget install Python.Python.3.12`），然后双击 `启动.bat` 即可自动安装依赖。

**Linux/macOS：**
```bash
pip install -r requirements.txt
```

依赖项：
- `websockets>=12.0`（必需，WebSocket 通信）
- `requests>=2.28`（可选，/github 和 /bilibili 需要）
- `Pillow>=9.0`（可选，生成图片卡片需要）

### 2. 编辑 `config.json`

用记事本或 VSCode 打开 `config.json`，至少改一项：

```json
"super_admins": [你的大号QQ号]
```

例如你的 QQ 是 `10001`，就写成 `"super_admins": [10001]`。
这里填的是**能下命令的人**（你自己），可以填多个，用逗号隔开。

完整配置项说明：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `ws_url` | `ws://127.0.0.1:3001` | NapCat 的 WebSocket 地址 |
| `super_admins` | `[]` | Owner QQ 号列表，这些人可以用全部命令 |
| `banned_users` | `[]` | 被禁用命令的用户 QQ 号 |
| `allow_owner` | `true` | 是否允许群主使用管理命令 |
| `allow_admin` | `true` | 是否允许群管理员使用管理命令 |
| `allowed_groups` | `[]` | 限制生效的群，空列表=所有群生效 |
| `command_prefix` | `/` | 命令前缀 |
| `reconnect_delay` | `5` | 断线后多少秒自动重连 |
| `reapply_interval` | `86400` | 永久禁言续期间隔（秒），默认每天 |
| `mute_max_seconds` | `2592000` | QQ 单次禁言上限（30天），一般不改 |

### 3. 启动

**Windows：**
- 双击 `启动.bat` — 前台运行，支持重启
- 双击 `后台运行.vbs` — 后台静默运行
- 双击 `停止.bat` — 停止后台运行的机器人

**Linux：**
```bash
chmod +x start.sh
./start.sh           # 前台运行
./start.sh -d         # 后台守护模式
./start.sh stop       # 停止
./start.sh status     # 查看状态
```

### 4. 测试

在你的 QQ 群里发送 `/help`，机器人应回复命令列表。

---

## 六、工作原理说明

- **封禁 `/ban`** = 把成员**踢出群**。
  - 时长 `0`（永久）：成员被踢后，**再次申请加群会被机器人自动拒绝**。
  - 时长 > 0：到期后自动解除拦截，可重新加群。
  - `/unban` = 立即解除拦截，允许加群。

- **禁言 `/mute`** = 群禁言。
  - QQ 群单次禁言**最长 30 天**，所以"永久禁言"由机器人**自动续期**实现
    （续期间隔见 `config.json` 的 `reapply_interval`，默认每天一次）。
  - `/unmute` = 立即解除禁言。
  - ⚠️ 要解除禁言请用 `/unmute` 命令，不要直接在 QQ 客户端手动解除
    （否则机器人不知道，可能下次续期又给禁上了）。

- **白名单 `/whitelist`** = 加群申请过滤器。
  - 开启后仅白名单内的 QQ 号可以申请加群。
  - 被封禁的用户始终无法加群（无论白名单状态）。

- **黑名单 `/black`** = 全局禁止用户。
  - 被拉黑的用户无法使用任何命令、无法添加机器人为好友、无法邀请机器人进群。
  - 同时写入 QQ 原生黑名单（如果 NapCat 版本支持）。

- **权限**：默认群主(owner)、群管理员(admin) 以及 `config.json` 里 `super_admins` 列出的人都能下命令。
  - `super_admins` 拥有最高权限，不会被封禁/禁言/踢出。
  - `banned_users` 中的用户即使有群内管理权限也不能使用命令。

---

## 七、常见问题

**Q: 双击启动.bat 闪退 / 提示找不到 Python？**
A: 确认已安装 Python 3.12+。可在命令行运行 `winget install Python.Python.3.12` 安装，安装完**新开一个窗口**再双击启动.bat。

**Q: 一直显示"断开...重连"？**
A: 说明连不上 NapCat。检查：
1. NapCat 是否已启动并登录；
2. NapCat 里是否配置了**正向 WebSocket** 且端口是 **3001**；
3. `config.json` 的 `ws_url` 是否和 NapCat 的端口一致。

**Q: 命令没反应？**
A: 检查：
1. 下命令的人是不是群主/管理员，或在 `super_admins` 里；
2. `allowed_groups` 是否限制了群；
3. 机器人账号在群里是不是**管理员**（不是管理员无法踢人/禁言）；
4. 该用户是否在 `banned_users` 黑名单中。

**Q: 踢人/禁言失败？**
A: 多半是机器人账号在群里**权限不够**（必须是群管理员或群主）。

**Q: /github 或 /bilibili 命令报错缺少依赖？**
A: 运行 `pip install requests Pillow` 安装可选依赖即可。

---

## 八、文件说明

| 文件 | 作用 |
|------|------|
| `bot.py` | 机器人主程序（核心逻辑） |
| `config.json` | 配置文件（**你需要改这里**） |
| `requirements.txt` | Python 依赖列表 |
| `启动.bat` | Windows 启动脚本（双击即可） |
| `停止.bat` | Windows 停止脚本 |
| `后台运行.vbs` | Windows 后台静默运行 |
| `start.sh` | Linux 启动/停止/后台脚本 |
| `data.json` | 运行时自动生成，保存封禁/禁言/白名单记录 |
| `bot.log` | 运行日志 |
| `examples/config.example.json` | 配置模板 |
| `scripts/linux/bot.service` | Linux systemd 服务文件 |

---

## 九、☁️ 部署到云服务器（电脑关机也能跑）

想要 24 小时不掉线，最好的办法是部署到一台**一直开机的 Linux 云服务器**上。
推荐：阿里云 / 腾讯云 轻量应用服务器（最低配 2核2G 即可，月费几十块）。

### 1. 服务器准备

```bash
# 选 Ubuntu 22.04 / Debian 12 系统，SSH 登录后：

# 安装 Python
apt update && apt install -y python3 python3-pip screen

# 上传 bot 文件夹到服务器
# 本地 PowerShell:
#   scp -r C:\Users\ytjac\Desktop\bot root@你的服务器IP:/opt/qqbot
```

### 2. 安装 NapCat (Linux 版)

**推荐用 Docker 版 NapCat（最简单）：**

```bash
# 安装 Docker
curl -fsSL https://get.docker.com | bash

# 拉取并运行 NapCat
docker run -d --name napcat \
  -p 3001:3001 \
  -p 6099:6099 \
  -v /opt/napcat:/app/.config/QQ \
  napneko/napcatqq:latest

# 查看二维码扫码登录
docker logs napcat
# 或浏览器访问 http://你的服务器IP:6099 配置 WebSocket (端口 3001)
```

也可用一键脚本安装：
```bash
curl -fsSL https://nclatest.znin.net/NapNeko/NapCat-Installer/main/script/install.sh | bash
```

### 3. 配置并启动

```bash
cd /opt/qqbot
chmod +x start.sh

# 编辑 config.json (填入你的 Owner QQ)
nano config.json

# 测试运行
./start.sh

# 确认正常后 Ctrl+C，以后台守护模式启动
./start.sh -d

# 查看日志
tail -f bot.log

# 停止
./start.sh stop
```

### 4. 注册为系统服务（开机自启 + 崩溃自动重启）

```bash
# 编辑 service 文件里的路径 (默认 /opt/qqbot)
# 如果放在别的位置，改一下 scripts/linux/bot.service 里的路径

cp scripts/linux/bot.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable bot
systemctl start bot

# 查看状态
systemctl status bot

# 查看日志
journalctl -u bot -f
```

### 5. 日常维护

```bash
systemctl restart bot   # 重启
systemctl stop bot      # 停止
systemctl start bot     # 启动
tail -f /opt/qqbot/bot.log  # 看日志
```

> 💡 部署到服务器后，本地 NapCat 记得关掉（一个 QQ 号不能同时在两个端登录）。
```

---

## 十、热重载

机器人支持**不重启进程即可刷新配置**：

- 在群里发送 `/reload`（需要管理员权限）
- 在 CMD 窗口中输入 `r` 回车（会重启进程，由启动脚本自动拉回）

---

把整个 `Bot` 文件夹打包就能搬到别的电脑用。只要那台电脑装了 Python 和 NapCat 即可。
