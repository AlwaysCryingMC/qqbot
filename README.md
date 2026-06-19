# QQ 群管理机器人

一个对接 **OneBot 11 / NapCat** 的 QQ 群管理机器人，支持群主/管理员通过命令封禁、禁言群成员，并能解封、解禁。

> 命令前缀默认 `/`，可改。

---

## 一、命令一览

| 命令 | 作用 | 示例 |
|------|------|------|
| `/ban <QQ号> <时长> <原因>` | **封禁**（踢出群） | `/ban 123456 7d 发广告` |
| `/unban <QQ号>` | **解封**（允许重新加群） | `/unban 123456` |
| `/mute <QQ号> <时长> <原因>` | **禁言** | `/mute 123456 30m 刷屏` |
| `/unmute <QQ号>` | **解除禁言** | `/unmute 123456` |
| `/list` | 查看本群封禁/禁言名单 | `/list` |
| `/help` | 显示帮助 | `/help` |

**时长格式：**
- `0` 或 `永久` = **永久**
- 纯数字 = **分钟**，例如 `30` 表示 30 分钟
- 也可带单位：`30s`(秒) / `10m`(分钟) / `2h`(小时) / `1d`(天) / `3w`(周)

---

## 二、运行前你需要准备

1. **一个 QQ 小号**（用来当机器人，建议用小号，别用主号）。
2. 把这个**小号拉进你的群**，并在群里**把它设为管理员**（否则没法踢人/禁言）。
3. **NapCat**（协议端）：让机器人能真正登录 QQ、收发消息。

> ⚠️ 没有这些前提，机器人无法工作。机器人只是"大脑"，NapCat 才是"手脚"。

---

## 三、安装并运行 NapCat（关键步骤）

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

## 四、配置并启动机器人

### 1. 编辑 `config.json`
用记事本或 VSCode 打开 `Bot` 文件夹里的 `config.json`，至少改一项：

```json
"super_admins": [你的大号QQ号]
```

例如你的 QQ 是 `10001`，就写成 `"super_admins": [10001]`。
这里填的是**能下命令的人**（你自己），可以填多个，用逗号隔开。

其它字段含义见文件内注释。最常用的是：
- `ws_url`：NapCat 的正向 WebSocket 地址（默认 `ws://127.0.0.1:3001`）。
- `allowed_groups`：留空 `[]` = 所有群都响应；填群号则只在这些群工作。

### 2. 启动
**双击 `启动.bat`**。
脚本会自动安装依赖并运行机器人。看到下面这行就说明连上了：

```
[连接] 已连接到 NapCat ✓  等待消息...
[登录] 机器人账号: xxx (12345678)
```

### 3. 测试
在你的 QQ 群里发送 `/help`，机器人应回复命令列表。

---

## 五、工作原理说明（重要）

- **封禁 `/ban`** = 把成员**踢出群**。
  - 时长 `0`（永久）：成员被踢后，**再次申请加群会被机器人自动拒绝**。
  - 时长 > 0：到期后自动解除拦截，可重新加群。
  - `/unban` = 立即解除拦截，允许加群。

- **禁言 `/mute`** = 群禁言。
  - QQ 群单次禁言**最长 30 天**，所以"永久禁言"由机器人**每隔 1 天自动续期**实现
    （续期间隔见 `config.json` 的 `reapply_interval`）。
  - `/unmute` = 立即解除禁言。
  - 注意：要解除禁言请用 `/unmute` 命令，不要直接在 QQ 客户端手动解除
    （否则机器人不知道，可能下次续期又给禁上了）。

- **权限**：默认群主(owner)、群管理员(admin) 以及 `config.json` 里 `super_admins` 列出的人都能下命令。

---

## 六、常见问题

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
3. 机器人账号在群里是不是**管理员**（不是管理员无法踢人/禁言）。

**Q: 踢人/禁言失败？**
A: 多半是机器人账号在群里**权限不够**（必须是群管理员或群主）。

---

## 七、文件说明

| 文件 | 作用 |
|------|------|
| `bot.py` | 机器人主程序（核心逻辑） |
| `config.json` | 配置文件（**你需要改这里**） |
| `requirements.txt` | Python 依赖列表 |
| `启动.bat` | Windows 启动脚本（双击即可） |
| `data.json` | 运行后自动生成，保存封禁/禁言记录 |

---

把整个 `Bot` 文件夹打包就能搬到别的电脑用。只要那台电脑装了 Python 和 NapCat 即可。

---

## 八、☁️ 部署到云服务器（电脑关机也能跑）

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

```bash
# 一键安装 NapCat
curl -fsSL https://nclatest.znin.net/NapNeko/NapCat-Installer/main/script/install.sh | bash

# 或参考官方文档: https://github.com/NapNeko/NapCatQQ
# 注意: Linux 版 NapCat 需要先安装 QQ，推荐用 docker 版 NapCat
```

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

### 3. 配置并启动

```bash
cd /opt/qqbot

# 给脚本加执行权限
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
# 如果放在别的位置，改一下 bot.service 里的路径

cp bot.service /etc/systemd/system/
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
