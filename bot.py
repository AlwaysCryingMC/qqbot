#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QQ 群管理机器人 (对接 OneBot 11 / NapCat)
==========================================

命令 (默认前缀 / ，仅群主/管理员可用):
    /ban    <QQ号> <时长> <原因>   封禁(踢出群)，时长=0 为永久
    /unban  <QQ号>                  解除封禁 (允许重新加群)
    /mute   <QQ号> <时长> <原因>   禁言，时长=0 为永久(每30天自动续期)
    /unmute <QQ号>                  解除禁言
    /list                           查看本群当前封禁/禁言名单
    /help                           显示帮助

时长格式: 纯数字 = 分钟；或带单位 30s / 10m / 2h / 1d / 3w；0 或 "永久" = 永久。
示例:
    /mute 123456 30m 刷屏
    /ban  10001 0 发广告
"""

import asyncio
import json
import os
import random
import re
import sys
import threading
import time
import uuid

try:
    import websockets
except ImportError:
    print("[错误] 缺少依赖 websockets。")
    print("       请双击 启动.bat ，或手动运行: pip install -r requirements.txt")
    sys.exit(1)

# Pillow / requests 是可选依赖，仅 /github 需要，缺失时提示
_PIL_OK = False
try:
    from PIL import Image, ImageDraw, ImageFont
    _PIL_OK = True
except ImportError:
    pass

_REQUESTS_OK = False
try:
    import requests as _requests
    _REQUESTS_OK = True
except ImportError:
    pass

# ============================================================
#  路径与默认配置
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
DB_PATH = os.path.join(BASE_DIR, "data.json")

DEFAULT_CONFIG = {
    "ws_url": "ws://127.0.0.1:3001",
    "super_admins": [],
    "banned_users": [],
    "admins": [],  # Admin QQ IDs, 由Owner通过 /admin 私聊命令管理
    "allow_owner": True,
    "allow_admin": True,
    "allowed_groups": [],
    "command_prefix": "/",
    "reconnect_delay": 5,
    "reapply_interval": 86400,
    "mute_max_seconds": 2592000,  # QQ 单次禁言上限 = 30 天
    "welcome_message": "你好！{nick}({user_id})！你是本群的第 {member_count} 位成员 🎉",
    "leave_message": "哔哔哔！群友 {nick}({user_id}) 退群了！",
    "reject_non_owner_invites": True,  # 自动拒绝非Owner的群邀请
    "reject_calls": True,              # 自动拒绝语音/视频通话
}

HELP_SHORT = (
    "🤖 QQ群管理机器人\n"
    "——————————————————\n"
    "🔒 管理: /ban /unban /mute /unmute /list\n"
    "📝 内容: /say /note /unnote /essence /unessence\n"
    "🛡️ 白名单: /whitelist add|remove|on|off\n"
    "🚫 黑名单: /black /unblack (仅Owner)  /blacklist (查看)\n"
    "🔍 查询: /github /bilibili /sid /pending\n"
    "👑 Admin: /admin add|remove|list (仅Owner私聊)\n"
    "✅ 审批: /yes|no <ID> (Owner/Admin)\n"
    "🔄 /reload — 热重载配置\n"
    "💬 /welcome — 自定义欢迎/退群消息\n"
    "❤️ 赞我 — 给发送者点赞(每日20次)\n"
    "——————————————————\n"
    "时长: 30s/10m/2h/1d/3w, 0=永久\n"
    "发送 /help full 查看完整命令列表"
)

HELP_FULL = (
    "🤖 QQ群管理机器人 完整命令列表\n"
    "——————————————————\n"
    "【群主/管理员 及 Bot Admin 可用】\n"
    "/ban <QQ号> <时长> <原因>   封禁(踢出)\n"
    "/unban <QQ号>               解封(允许重新加群)\n"
    "/mute <QQ号> <时长> <原因>  禁言\n"
    "/unmute <QQ号>              解禁\n"
    "/whitelist add <QQ>         添加白名单\n"
    "/whitelist remove <QQ>      移除白名单\n"
    "/whitelist on|off           启用/关闭白名单模式\n"
    "/whitelist                  查看白名单\n"
    "/list                       查看封禁/禁言名单\n"
    "/say <内容>                 让机器人说一句话\n"
    "/note <内容> <yes|no>       发布群公告\n"
    "/unnote                     删除群公告\n"
    "/essence <内容>             发送群精华消息\n"
    "/unessence                  取消群精华\n"
    "/welcome                    自定义欢迎/退群消息\n"
    "/reload                     刷新配置(免重启)\n"
    "/blacklist                  查看黑名单\n"
    "/github <user/repo>         查看GitHub仓库(卡片+信息)\n"
    "/bilibili <BV/AV/URL>       查看B站视频(卡片+信息)\n"
    "/sid                         查看会话信息\n"
    "/pending                     查看待审批请求(Owner/Admin)\n"
    "/yes|no <ID>                同意/拒绝请求(Owner/Admin)\n"
    "——————————————————\n"
    "【仅 Owner 可用】\n"
    "/admin <add|remove> <QQ>    管理Bot Admin(私聊)\n"
    "/admin list                 查看Bot Admin列表(私聊)\n"
    "/black <QQ号>               拉黑用户(禁止使用命令)\n"
    "/unblack <QQ号>             取消拉黑\n"
    "——————————————————\n"
    "【任意成员可用】\n"
    "赞我                         给发送者点赞(每日20次)\n"
    "——————————————————\n"
    "时长：纯数字=分钟，或 30s/10m/2h/1d/3w，0=永久\n"
    "例：/mute 123456 30m 刷屏\n"
    "    /ban 10001 0 发广告"
)


def load_config():
    """读取 config.json，缺失则生成默认文件。"""
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
        print(f"[初始化] 已生成默认配置: {CONFIG_PATH}")

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        user_cfg = json.load(f)
    # 过滤掉用户写的说明性字段（以 _ 开头的键）
    user_cfg = {k: v for k, v in user_cfg.items() if not k.startswith("_")}
    merged = dict(DEFAULT_CONFIG)
    merged.update(user_cfg)
    # 规范化 super_admins / allowed_groups / banned_users 为 int 列表
    merged["super_admins"] = [int(x) for x in merged.get("super_admins") or []]
    merged["allowed_groups"] = [int(x) for x in merged.get("allowed_groups") or []]
    merged["banned_users"] = [int(x) for x in merged.get("banned_users") or []]
    merged["admins"] = [int(x) for x in merged.get("admins") or []]
    return merged


def save_config():
    """保存当前 CONFIG 到 config.json，保留用户注释字段。"""
    original = {}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            original = json.load(f)
    # 保留注释字段(以 _ 开头)，更新实际配置值
    for k, v in CONFIG.items():
        original[k] = v
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(original, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_PATH)


CONFIG = load_config()

# ============================================================
#  本地数据库 (data.json)：记录封禁/禁言/白名单/欢迎消息
# ============================================================
# 结构:
#   bans : { "群号_QQ号": {"group_id","user_id","reason","expire"(0=永久),"set_at","set_by"} }
#   mutes: 同上
#   whitelist : { 群号: [QQ号, ...] }
#   whitelist_enabled : [群号, ...]
#   welcome_msgs : { 群号: "消息模板" }   ← 每群独立欢迎消息
#   leave_msgs   : { 群号: "消息模板" }   ← 每群独立退群消息


def load_db():
    if not os.path.exists(DB_PATH):
        return {"bans": {}, "mutes": {}, "whitelist": {}, "whitelist_enabled": [],
                "welcome_msgs": {}, "leave_msgs": {}}
    try:
        with open(DB_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("bans", {})
        data.setdefault("mutes", {})
        data.setdefault("whitelist", {})
        data.setdefault("whitelist_enabled", [])
        data.setdefault("welcome_msgs", {})
        data.setdefault("leave_msgs", {})
        return data
    except Exception as e:
        print(f"[警告] data.json 读取失败，将使用空数据库: {e}")
        return {"bans": {}, "mutes": {}, "whitelist": {}, "whitelist_enabled": []}


def save_db():
    tmp = DB_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(DB, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DB_PATH)


DB = load_db()

# ============================================================
#  WebSocket 连接与 OneBot API 调用
# ============================================================
WS = None                 # 当前 WebSocket 连接
PENDING = {}              # echo -> asyncio.Future (匹配 API 请求/响应)

# 待处理请求: req_id -> {flag, user_id, group_id, type, nick, timestamp}
_PENDING_REQS = {}
_REQ_COUNTER = [0]  # 自增请求ID，用列表方便在闭包里修改


async def call_api(action, params=None, timeout=15):
    """调用 OneBot 11 API，返回完整响应 dict。"""
    global WS
    if WS is None:
        return {"status": "error", "retcode": -1, "msg": "未连接到 NapCat"}
    params = params or {}
    echo = uuid.uuid4().hex
    loop = asyncio.get_event_loop()
    fut = loop.create_future()
    PENDING[echo] = fut
    try:
        await WS.send(json.dumps({"action": action, "params": params, "echo": echo}))
        result = await asyncio.wait_for(fut, timeout=timeout)
        return result
    except asyncio.TimeoutError:
        return {"status": "error", "retcode": -1, "msg": f"调用 {action} 超时"}
    except Exception as e:
        return {"status": "error", "retcode": -1, "msg": str(e)}
    finally:
        PENDING.pop(echo, None)


def api_ok(res):
    return bool(res) and res.get("status") == "ok" and res.get("retcode") == 0


# 消息频率控制：防止被QQ风控
_SEND_QUEUE = {}  # {group_id: last_send_timestamp}
_MSG_MIN_INTERVAL = 0.8   # 同群两条消息最小间隔(秒)
_MSG_RANDOM_MAX = 1.5     # 随机延迟上限(秒)


async def send_group_text(group_id, text):
    """向群里发送纯文本消息（带随机延迟，防风控）。"""
    now = time.time()
    last = _SEND_QUEUE.get(group_id, 0)
    wait = _MSG_MIN_INTERVAL - (now - last)
    if wait > 0:
        await asyncio.sleep(wait + random.uniform(0, _MSG_RANDOM_MAX))
    _SEND_QUEUE[group_id] = time.time()
    await call_api("send_group_msg", {
        "group_id": group_id,
        "message": [{"type": "text", "data": {"text": text}}],
    })


async def get_nick(group_id, user_id):
    """获取群员名片/昵称，失败则回退为 用户<QQ>。"""
    res = await call_api("get_group_member_info",
                         {"group_id": group_id, "user_id": user_id}, timeout=8)
    if api_ok(res):
        info = res.get("data", {}) or {}
        return info.get("card") or info.get("nickname") or f"用户{user_id}"
    return f"用户{user_id}"

# ============================================================
#  工具：时长解析与格式化、权限判断
# ============================================================
_PERM_WORDS = {"0", "永久", "永久封禁", "永久禁言", "perm", "permanent", "forever"}
_UNIT_MULT = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def parse_duration(s):
    """
    解析时长字符串，返回秒数；0 表示永久；None 表示格式非法。
    纯数字默认按分钟；支持 30s/10m/2h/1d/3w；"0"/"永久" -> 0(永久)。
    """
    s = str(s).strip().lower()
    if s in _PERM_WORDS:
        return 0
    m = re.fullmatch(r"(\d+)\s*([smhdw]?)", s)
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2) or "m"
    return n * _UNIT_MULT[unit]


def fmt_duration(seconds):
    if seconds <= 0:
        return "永久"
    units = [("周", 604800), ("天", 86400), ("小时", 3600), ("分钟", 60), ("秒", 1)]
    parts = []
    for name, sec in units:
        if seconds >= sec:
            v, seconds = divmod(seconds, sec)
            if v:
                parts.append(f"{v}{name}")
    return "".join(parts) if parts else "0秒"


def format_msg(template, **kwargs):
    """用 {nick} {user_id} {group_id} {member_count} 替换模板中的变量。
    若模板为空字符串则返回 None（表示不发消息）。"""
    if not template or not template.strip():
        return None
    msg = template
    for k, v in kwargs.items():
        msg = msg.replace("{" + k + "}", str(v))
    return msg


def is_admin(event):
    """判断消息发送者是否有权使用管理命令。"""
    user_id = event.get("user_id")
    # Owner永远免疫
    if user_id in CONFIG["super_admins"]:
        return True
    # 被 banned 的用户(即使是群主/管理员)禁止使用命令
    if user_id in CONFIG.get("banned_users", []):
        return False
    role = (event.get("sender") or {}).get("role", "member")
    if CONFIG["allow_owner"] and role == "owner":
        return True
    if CONFIG["allow_admin"] and role in ("admin", "owner"):
        return True
    return False


def is_owner(user_id):
    """判断是否是 Owner（super_admins 中的用户）。"""
    return user_id in CONFIG["super_admins"]


def is_bot_admin(user_id):
    """判断是否是 Bot Admin（Owner 或 admins 列表中的用户）。
    Bot Admin 可以使用除 /black /unblack /admin 外的所有命令。"""
    return user_id in CONFIG["super_admins"] or user_id in CONFIG.get("admins", [])


def group_allowed(group_id):
    allowed = CONFIG["allowed_groups"]
    return (not allowed) or (group_id in allowed)


def parse_target_and_duration(rest):
    """解析 '<QQ号> <时长> <原因...>'。返回 (user_id, duration, reason) 或 (None,None,None)。"""
    p = rest.split(None, 2)
    if len(p) < 2:
        return None, None, None
    qq_str, time_str = p[0], p[1]
    reason = p[2].strip() if len(p) > 2 else "未说明"
    if not re.fullmatch(r"\d+", qq_str):
        return None, None, None
    dur = parse_duration(time_str)
    if dur is None:
        return None, None, None
    return int(qq_str), dur, reason


def parse_single_qq(rest):
    p = rest.split(None, 1)
    if not p or not re.fullmatch(r"\d+", p[0]):
        return None
    return int(p[0])

# ============================================================
#  命令处理
# ============================================================
async def cmd_ban(event, rest):
    group_id = event["group_id"]
    target, duration, reason = parse_target_and_duration(rest)
    if target is None:
        await send_group_text(
            group_id,
            "❌ 格式错误。用法: /ban <QQ号> <时长> <原因>\n"
            "例如: /ban 123456 7d 发广告   (时长 0 = 永久)"
        )
        return
    if target == event.get("user_id"):
        await send_group_text(group_id, "❌ 不能封禁自己。")
        return
    if target in CONFIG["super_admins"]:
        await send_group_text(group_id, "❌ 不能封禁Owner。")
        return

    nick = await get_nick(group_id, target)
    now = time.time()
    # reject_add_request=False：让机器人自己管理"封禁"（拦截重新加群），便于 /unban
    res = await call_api("set_group_kick", {
        "group_id": group_id,
        "user_id": target,
        "reject_add_request": False,
    })
    expire = 0 if duration == 0 else now + duration
    key = f"{group_id}_{target}"
    DB["bans"][key] = {
        "group_id": group_id, "user_id": target, "reason": reason,
        "expire": expire, "set_at": now, "set_by": event.get("user_id"),
    }
    save_db()

    dur_str = "永久" if duration == 0 else fmt_duration(duration)
    if api_ok(res):
        await send_group_text(
            group_id,
            f"✅ 已封禁 {nick}({target})\n时长: {dur_str}\n原因: {reason}"
        )
    else:
        msg = (res or {}).get("msg", "未知错误")
        await send_group_text(
            group_id,
            f"⚠️ 封禁可能未完全成功: {msg}\n"
            "(已记录到封禁名单；该成员若不在群内，重新申请加群时会被拒绝)"
        )


async def cmd_unban(event, rest):
    group_id = event["group_id"]
    target = parse_single_qq(rest)
    if target is None:
        await send_group_text(group_id, "❌ 格式错误。用法: /unban <QQ号>")
        return
    key = f"{group_id}_{target}"
    if key in DB["bans"]:
        del DB["bans"][key]
        save_db()
        await send_group_text(
            group_id, f"✅ 已解封 {target}。该成员现在可以重新申请加群。"
        )
    else:
        await send_group_text(group_id, f"ℹ️ {target} 不在封禁名单中。")


async def cmd_mute(event, rest):
    group_id = event["group_id"]
    target, duration, reason = parse_target_and_duration(rest)
    if target is None:
        await send_group_text(
            group_id,
            "❌ 格式错误。用法: /mute <QQ号> <时长> <原因>\n"
            "例如: /mute 123456 30m 刷屏   (时长 0 = 永久)"
        )
        return
    if target == event.get("user_id"):
        await send_group_text(group_id, "❌ 不能禁言自己。")
        return
    if target in CONFIG["super_admins"]:
        await send_group_text(group_id, "❌ 不能禁言Owner。")
        return

    nick = await get_nick(group_id, target)
    now = time.time()
    is_perm = (duration == 0)
    # 永久禁言：QQ 单次上限 30 天，先设上限，由后台任务定期续期
    api_duration = CONFIG["mute_max_seconds"] if is_perm else min(duration, CONFIG["mute_max_seconds"])
    res = await call_api("set_group_ban", {
        "group_id": group_id, "user_id": target, "duration": api_duration,
    })
    expire = 0 if is_perm else now + duration
    key = f"{group_id}_{target}"
    DB["mutes"][key] = {
        "group_id": group_id, "user_id": target, "reason": reason,
        "expire": expire, "set_at": now, "set_by": event.get("user_id"),
    }
    save_db()

    dur_str = "永久(自动续期)" if is_perm else fmt_duration(duration)
    if api_ok(res):
        await send_group_text(
            group_id,
            f"✅ 已禁言 {nick}({target})\n时长: {dur_str}\n原因: {reason}"
        )
    else:
        msg = (res or {}).get("msg", "未知错误")
        await send_group_text(group_id, f"⚠️ 禁言失败: {msg}")


async def cmd_unmute(event, rest):
    group_id = event["group_id"]
    target = parse_single_qq(rest)
    if target is None:
        await send_group_text(group_id, "❌ 格式错误。用法: /unmute <QQ号>")
        return
    res = await call_api("set_group_ban", {
        "group_id": group_id, "user_id": target, "duration": 0,
    })
    key = f"{group_id}_{target}"
    if key in DB["mutes"]:
        del DB["mutes"][key]
        save_db()
    if api_ok(res):
        await send_group_text(group_id, f"✅ 已解除 {target} 的禁言。")
    else:
        msg = (res or {}).get("msg", "未知错误")
        await send_group_text(group_id, f"⚠️ 解禁失败: {msg}")


async def cmd_list(event, rest):
    group_id = event["group_id"]
    now = time.time()
    bans, mutes = [], []
    for v in DB["bans"].values():
        if v["group_id"] != group_id:
            continue
        if v["expire"] != 0 and v["expire"] <= now:
            continue
        bans.append(v)
    for v in DB["mutes"].values():
        if v["group_id"] != group_id:
            continue
        if v["expire"] != 0 and v["expire"] <= now:
            continue
        mutes.append(v)

    out = [f"📋 群 {group_id} 管理名单"]
    out.append(f"\n🔒 封禁 ({len(bans)}):")
    if bans:
        for v in bans:
            t = "永久" if v["expire"] == 0 else f"剩{fmt_duration(int(v['expire'] - now))}"
            out.append(f"  · {v['user_id']} [{t}] {v['reason']}")
    else:
        out.append("  (无)")
    out.append(f"\n🤐 禁言 ({len(mutes)}):")
    if mutes:
        for v in mutes:
            t = "永久" if v["expire"] == 0 else f"剩{fmt_duration(int(v['expire'] - now))}"
            out.append(f"  · {v['user_id']} [{t}] {v['reason']}")
    else:
        out.append("  (无)")
    await send_group_text(group_id, "\n".join(out))


async def cmd_say(event, rest):
    """让机器人在群里发送指定文本(仅管理员)。"""
    group_id = event["group_id"]
    text = rest.strip()
    if not text:
        await send_group_text(group_id, "❌ 内容不能为空。用法: /say <要发送的内容>")
        return
    await send_group_text(group_id, text)


async def cmd_sid(event):
    """显示当前会话信息（任意成员可用）。"""
    group_id = event["group_id"]
    user_id = event.get("user_id") or event.get("sender", {}).get("user_id", "?")
    message_type = event.get("message_type", "GroupMessage")

    # 获取当前 Bot QQ 号
    bot_id = "default"
    login = await call_api("get_login_info", timeout=5)
    if api_ok(login):
        bot_id = (login.get("data", {}) or {}).get("user_id", "default")

    umo = f"{bot_id}:{message_type}:{group_id}"

    lines = [
        f"UMO: 「{umo}」",
        f"UID: 「{user_id}」",
        "",
        "Your session information:",
        f"Bot ID: 「{bot_id}」",
        f"Message Type: 「{message_type}」",
        f"Session ID: 「{group_id}」",
    ]
    await send_group_text(group_id, "\n".join(lines))


async def cmd_approve(event, rest, approve):
    """Owner 审批待处理请求: /yes [id] 或 /no [id]。
    不传 id 则处理最近一条待处理请求。
    """
    user_id = event.get("user_id")
    # 支持私聊和群聊回复
    reply = _reply_to(event)

    # 解析请求 ID
    rest = rest.strip()
    if rest:
        try:
            rid = int(rest)
        except ValueError:
            await reply("❌ 无效请求ID。用法: /yes <ID> 或 /no <ID>")
            return
    else:
        # 取最近的待处理请求
        if not _PENDING_REQS:
            await reply("ℹ️ 当前没有待处理的请求。")
            return
        rid = max(_PENDING_REQS.keys())

    req = _PENDING_REQS.get(rid)
    if not req:
        await reply(f"❌ 请求 #{rid} 不存在或已过期。")
        return

    flag = req["flag"]
    req_user = req["user_id"]
    kind = req["kind"]
    group_id = req.get("group_id")

    # 调用对应 API
    if kind == "friend":
        res = await call_api("set_friend_add_request", {
            "flag": flag, "approve": approve,
            "remark": "" if approve else "Owner 拒绝了你的好友请求",
        }, timeout=8)
        label = "好友请求"
    elif kind == "group_invite":
        res = await call_api("set_group_add_request", {
            "flag": flag, "sub_type": "invite", "approve": approve,
            "reason": "" if approve else "Owner 拒绝了邀请",
        }, timeout=8)
        label = "群邀请"
        if approve and group_id:
            gid = int(group_id)
            if gid and gid not in CONFIG["allowed_groups"]:
                CONFIG["allowed_groups"].append(gid)
                save_config()
                print(f"[自动注册] 群 {gid} 已添加到生效群列表")
    else:
        await reply(f"❌ 未知请求类型: {kind}")
        return

    if api_ok(res):
        verb = "✅ 已同意" if approve else "❌ 已拒绝"
        await reply(f"{verb} {label} #{rid} (用户{req_user})")
    else:
        msg = (res or {}).get("msg", res)
        await reply(f"⚠️ 操作失败: {msg}")

    # 清理
    del _PENDING_REQS[rid]


def _reply_to(event):
    """返回一个 async callable，自动判断私聊还是群聊回复。"""
    msg_type = event.get("message_type")
    group_id = event.get("group_id")
    user_id = event.get("user_id")

    async def _do(text):
        if msg_type == "private":
            await call_api("send_private_msg", {
                "user_id": user_id,
                "message": [{"type": "text", "data": {"text": text}}],
            }, timeout=8)
        else:
            await send_group_text(group_id, text)
    return _do


async def cmd_pending(event):
    """查看所有待审批的请求（仅 Owner）。"""
    reply = _reply_to(event)

    if not _PENDING_REQS:
        await reply("✅ 当前没有待处理的请求。")
        return

    now = time.time()
    # 清理超过 10 分钟的过期请求
    expired = [rid for rid, r in _PENDING_REQS.items() if now - r["timestamp"] > 600]
    for rid in expired:
        del _PENDING_REQS[rid]

    if not _PENDING_REQS:
        await reply("✅ 当前没有待处理的请求。")
        return

    lines = ["📋 待处理请求列表:"]
    for rid in sorted(_PENDING_REQS.keys()):
        r = _PENDING_REQS[rid]
        kind_label = "👤 好友请求" if r["kind"] == "friend" else "📨 群邀请"
        gid = r.get("group_id")
        detail = f"用户 {r['user_id']}"
        if gid:
            detail += f" → 群 {gid}"
        elapsed = int(now - r["timestamp"])
        lines.append(f"  #{rid} [{kind_label}] {detail}  ({elapsed}s前)")
    lines.append("\n💡 /yes <ID> 同意  |  /no <ID> 拒绝")
    await reply("\n".join(lines))


async def cmd_github(event, rest):
    """查看 GitHub 仓库信息: /github <user/repo> 或 /github <完整URL>"""
    group_id = event["group_id"]
    arg = rest.strip()
    if not arg:
        await send_group_text(group_id, "❌ 用法: /github <user/repo> 或 /github <完整URL>")
        return

    if not _REQUESTS_OK or not _PIL_OK:
        missing = []
        if not _REQUESTS_OK:
            missing.append("requests")
        if not _PIL_OK:
            missing.append("Pillow")
        await send_group_text(group_id, f"❌ 缺少依赖: {', '.join(missing)}\n请在 Bot 目录运行: pip install requests Pillow")
        return

    # 解析 owner/repo
    m = re.search(r"(?:github\.com[/:])?([^/\s]+)/([^/\s]+?)(?:\.git)?$", arg.rstrip("/"))
    if not m:
        await send_group_text(group_id, "❌ 无法解析仓库地址。\n正确格式: /github user/repo  或  /github https://github.com/user/repo")
        return
    owner, repo = m.group(1), m.group(2)

    # 异步获取 GitHub API
    loop = asyncio.get_event_loop()
    try:
        repo_data = await loop.run_in_executor(None, _fetch_github_repo, owner, repo)
    except Exception as e:
        await send_group_text(group_id, f"⚠️ 获取仓库信息失败: {e}")
        return

    if not repo_data:
        await send_group_text(group_id, f"❌ 仓库 {owner}/{repo} 不存在或无法访问。")
        return

    # 生成图片
    img_path = os.path.join(BASE_DIR, f"github_{group_id}_{int(time.time())}.png")
    try:
        await loop.run_in_executor(None, _draw_github_card, repo_data, img_path)
    except Exception as e:
        await send_group_text(group_id, f"⚠️ 生成图片失败: {e}")
        return

    # 发图片
    img_url = "file:///" + img_path.replace("\\", "/")
    res = await call_api("send_group_msg", {
        "group_id": group_id,
        "message": [{"type": "image", "data": {"file": img_url}}],
    }, timeout=10)

    # 发文字摘要
    stars = repo_data.get("stargazers_count", 0)
    forks = repo_data.get("forks_count", 0)
    desc = repo_data.get("description") or "无简介"
    lang = repo_data.get("language") or "?"
    issues = repo_data.get("open_issues_count", 0)
    topics = repo_data.get("topics", []) or []
    created = (repo_data.get("created_at") or "")[:10]
    updated = (repo_data.get("pushed_at") or "")[:10]
    license_info = (repo_data.get("license") or {}) or {}
    license_name = license_info.get("spdx_id", "无")

    lines = [
        f"📦 {owner}/{repo}",
        f"⭐ {stars:,}  |  🍴 {forks:,}  |  🔴 {issues:,}  |  📜 {license_name}",
        f"🔤 语言: {lang}",
        f"📅 创建: {created}  |  更新: {updated}",
        f"📝 {desc}",
    ]
    if topics:
        lines.append(f"🏷️ {' · '.join(topics[:8])}")
    lines.append(f"🔗 https://github.com/{owner}/{repo}")
    await send_group_text(group_id, "\n".join(lines))

    # 清理临时文件
    try:
        os.remove(img_path)
    except Exception:
        pass


def _fetch_github_repo(owner, repo):
    """同步请求 GitHub API，返回 repo dict 或 None。"""
    url = f"https://api.github.com/repos/{owner}/{repo}"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "QQ-Bot"}
    r = _requests.get(url, headers=headers, timeout=10)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def _draw_github_card(repo, out_path):
    """用 Pillow 生成 GitHub 仓库信息卡片。"""
    W, H = 800, 420
    BG    = (13, 17, 23)       # #0d1117
    CARD  = (22, 27, 34)       # #161b22
    BORDER= (48, 54, 61)       # #30363d
    TEXT  = (201, 209, 217)    # #c9d1d9
    SUB   = (139, 148, 158)    # #8b949e
    ACCENT= (88, 166, 255)     # #58a6ff
    STAR  = (227, 179, 65)     # #e3b341
    GREEN = (63, 185, 80)      # #3fb950

    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # 字体 (优先用支持中文的字体)
    def _load_font(size, bold=False):
        for path in [
            "C:/Windows/Fonts/msyh.ttc",       # 微软雅黑
            "C:/Windows/Fonts/msyhbd.ttc",     # 微软雅黑粗体
            "C:/Windows/Fonts/simhei.ttf",     # 黑体
            "C:/Windows/Fonts/simsun.ttc",     # 宋体
            "C:/Windows/Fonts/simfang.ttf",    # 仿宋
            "C:/Windows/Fonts/msjh.ttc",       # 微软正黑
        ]:
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
        return ImageFont.load_default()
    font_title = _load_font(28)
    font_bold  = _load_font(18)
    font_text  = _load_font(16)
    font_small = _load_font(14)

    # 卡片背景
    card_x, card_y, card_w, card_h = 20, 20, W - 40, H - 40
    draw.rounded_rectangle([card_x, card_y, card_x + card_w, card_y + card_h],
                           radius=16, fill=CARD, outline=BORDER, width=1)

    y = card_y + 24
    x = card_x + 28

    # Repo 名称
    owner = repo.get("owner", {}).get("login", "?")
    name = repo.get("name", "?")
    draw.text((x, y), f"{owner}/{name}", fill=ACCENT, font=font_title)
    y += 40

    # 描述
    desc = repo.get("description") or ""
    if desc:
        if len(desc) > 100:
            desc = desc[:97] + "..."
        draw.text((x, y), desc, fill=TEXT, font=font_text)
        y += 26

    # Stats 行
    stars = repo.get("stargazers_count", 0)
    forks = repo.get("forks_count", 0)
    issues = repo.get("open_issues_count", 0)
    watchers = repo.get("subscribers_count", 0)
    draw.text((x, y), f"⭐ {stars:,}", fill=STAR, font=font_bold)
    x2 = x + 110
    draw.text((x2, y), f"🍴 {forks:,}", fill=TEXT, font=font_bold)
    x2 += 100
    draw.text((x2, y), f"🔴 {issues:,}", fill=TEXT, font=font_bold)
    x2 += 100
    draw.text((x2, y), f"👀 {watchers:,}", fill=SUB, font=font_bold)
    y += 36

    # 分隔线
    draw.line([(x, y), (x + card_w - 56, y)], fill=BORDER, width=1)
    y += 16

    # 语言 (带色点)
    lang = repo.get("language") or "N/A"
    lang_colors = {
        "Python":     (53, 114, 165), "JavaScript": (241, 224, 90),
        "TypeScript": (49, 120, 198), "Java":       (176, 114, 25),
        "Go":         (0, 173, 216),  "Rust":       (222, 165, 132),
        "C++":        (243, 75, 125), "C":          (85, 85, 85),
        "Ruby":       (112, 21, 22),  "Kotlin":     (169, 123, 255),
        "Swift":      (240, 81, 56),  "PHP":        (79, 93, 149),
    }
    dot_color = lang_colors.get(lang, SUB)
    draw.ellipse([(x, y + 5), (x + 12, y + 17)], fill=dot_color)
    draw.text((x + 18, y), f"{lang}", fill=TEXT, font=font_text)

    # License
    lic = (repo.get("license") or {}) or {}
    lic_name = lic.get("spdx_id", "No License")
    draw.text((x + 140, y), f"📜 {lic_name}", fill=SUB, font=font_text)
    y += 28

    # 日期
    created = (repo.get("created_at") or "")[:10]
    updated = (repo.get("pushed_at") or "")[:10]
    draw.text((x, y), f"📅 创建 {created}    更新 {updated}", fill=SUB, font=font_small)
    y += 24

    # Topics
    topics = repo.get("topics", []) or []
    if topics:
        draw.text((x, y), "🏷️", fill=SUB, font=font_small)
        tag_x = x + 24
        for tag in topics[:6]:
            tw = draw.textlength(tag, font=font_small) + 16
            if tag_x + tw > card_x + card_w - 20:
                break
            draw.rounded_rectangle([tag_x, y, tag_x + tw, y + 22],
                                   radius=10, fill=(40, 58, 96), outline=(48, 74, 128))
            draw.text((tag_x + 8, y + 2), tag, fill=ACCENT, font=font_small)
            tag_x += tw + 8

    # 底部 URL
    url = f"github.com/{owner}/{name}"
    draw.text((x, card_y + card_h - 32), url, fill=SUB, font=font_small)

    img.save(out_path, "PNG")


# ============================================================
#  /bilibili — B站视频信息卡片
# ============================================================
async def cmd_bilibili(event, rest):
    """查看 B站视频信息: /bilibili <BV号/AV号/URL>"""
    group_id = event["group_id"]
    arg = rest.strip()
    if not arg:
        await send_group_text(group_id, "❌ 用法: /bilibili <BV号/AV号/URL>")
        return

    if not _REQUESTS_OK or not _PIL_OK:
        missing = []
        if not _REQUESTS_OK:
            missing.append("requests")
        if not _PIL_OK:
            missing.append("Pillow")
        await send_group_text(group_id, f"❌ 缺少依赖: {', '.join(missing)}\n请运行: pip install requests Pillow")
        return

    # 解析 BV / AV / URL
    m = re.search(r"(?:bilibili\.com/video/)?((?:BV|bv|AV|av)[A-Za-z0-9]+)", arg)
    vid = None
    if m:
        vid = m.group(1)
    else:
        # 可能只有纯数字 AV 号或没有前缀的 BV
        m2 = re.search(r"(?:bilibili\.com/video/)?([A-Za-z0-9]+)", arg)
        if m2:
            vid = m2.group(1)
    if not vid:
        await send_group_text(group_id, "❌ 无法解析视频ID。\n格式: /bilibili BVxxx  或  /bilibili https://www.bilibili.com/video/BVxxx")
        return
    # 判断 AV 还是 BV
    if re.fullmatch(r"[Aa][Vv]\d+", vid):
        param = {"aid": int(re.sub(r"[^0-9]", "", vid))}
    elif re.fullmatch(r"\d+", vid):
        param = {"aid": int(vid)}
    else:
        param = {"bvid": vid}

    loop = asyncio.get_event_loop()
    try:
        info = await loop.run_in_executor(None, _fetch_bilibili_video, param)
    except Exception as e:
        await send_group_text(group_id, f"⚠️ 获取视频信息失败: {e}")
        return

    if not info:
        await send_group_text(group_id, f"❌ 视频不存在或无法访问。")
        return

    code = info.get("code", -1)
    if code != 0:
        await send_group_text(group_id, f"❌ B站API返回错误: {info.get('message', '未知')}")
        return

    data = info.get("data", {}) or {}
    if not data:
        await send_group_text(group_id, "❌ 未获取到视频数据。")
        return

    # 下载封面
    cover_url = data.get("pic", "")
    cover_path = None
    if cover_url:
        cover_path = os.path.join(BASE_DIR, f"bili_cover_{group_id}_{int(time.time())}.jpg")
        try:
            await loop.run_in_executor(None, _download_image, cover_url, cover_path)
        except Exception:
            cover_path = None

    # 生成卡片
    img_path = os.path.join(BASE_DIR, f"bilibili_{group_id}_{int(time.time())}.png")
    try:
        await loop.run_in_executor(None, _draw_bilibili_card, data, cover_path, img_path)
    except Exception as e:
        await send_group_text(group_id, f"⚠️ 生成图片失败: {e}")
        _cleanup(cover_path, img_path)
        return

    # 发图片
    img_url = "file:///" + img_path.replace("\\", "/")
    await call_api("send_group_msg", {
        "group_id": group_id,
        "message": [{"type": "image", "data": {"file": img_url}}],
    }, timeout=10)

    # 发文字摘要
    stat = data.get("stat", {}) or {}
    owner = data.get("owner", {}) or {}
    title = data.get("title", "?")
    bvid = data.get("bvid", "?")
    dur = data.get("duration", 0)
    m, s = divmod(dur, 60)
    duration = f"{m}:{s:02d}"
    pubdate = data.get("pubdate", 0)
    from datetime import datetime as _dt
    pub_str = _dt.fromtimestamp(pubdate).strftime("%Y-%m-%d %H:%M") if pubdate else "?"
    tname = data.get("tname", "?")

    lines = [
        f"📺 {title}",
        f"👤 UP主: {owner.get('name', '?')}",
        f"⏱ {duration}  |  📂 {tname}  |  🕐 {pub_str}",
        f"▶️ 播放 {stat.get('view',0):,}  |  💬 弹幕 {stat.get('danmaku',0):,}",
        f"👍 点赞 {stat.get('like',0):,}  |  🪙 投币 {stat.get('coin',0):,}  |  ⭐ 收藏 {stat.get('favorite',0):,}",
        f"🔗 https://www.bilibili.com/video/{bvid or ('av'+str(data.get('aid','')))}",
    ]
    await send_group_text(group_id, "\n".join(lines))

    _cleanup(cover_path, img_path)


def _fetch_bilibili_video(params):
    """同步请求 B站视频 API。"""
    if "bvid" in params:
        url = f"https://api.bilibili.com/x/web-interface/view?bvid={params['bvid']}"
    else:
        url = f"https://api.bilibili.com/x/web-interface/view?aid={params['aid']}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Referer": "https://www.bilibili.com/",
        "Origin": "https://www.bilibili.com",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Cookie": "buvid3=unknown; fingerprint=unknown",
    }
    r = _requests.get(url, headers=headers, timeout=10)
    r.raise_for_status()
    return r.json()


def _download_image(url, path):
    """下载图片到本地。"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.bilibili.com/",
    }
    r = _requests.get(url, headers=headers, timeout=15)
    r.raise_for_status()
    with open(path, "wb") as f:
        f.write(r.content)


def _cleanup(*paths):
    for p in paths:
        if p:
            try:
                os.remove(p)
            except Exception:
                pass


def _draw_bilibili_card(data, cover_path, out_path):
    """用 Pillow 绘制 B站视频信息卡片。"""
    W, H = 820, 500
    BG     = (244, 245, 247)   # #f4f5f7
    CARD   = (255, 255, 255)   # white
    PINK   = (251, 114, 153)   # B站粉 #fb7299
    DARK   = (33, 33, 33)      # #212121
    GRAY   = (153, 153, 153)   # #999
    LIGHT  = (230, 230, 230)   # border
    BLUE   = (0, 161, 214)     # accent

    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # 字体
    def _font(size, bold=False):
        for path in [
            "C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/msyhbd.ttc",
            "C:/Windows/Fonts/simhei.ttf", "C:/Windows/Fonts/simsun.ttc",
        ]:
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
        return ImageFont.load_default()
    f_title   = _font(26)
    f_body    = _font(18)
    f_stat    = _font(16)
    f_small   = _font(14)
    f_bigstat = _font(20)

    # 顶部粉色条
    draw.rectangle([(0, 0), (W, 6)], fill=PINK)

    # 封面区 (左侧)
    cover_w, cover_h = 360, 220
    cover_x, cover_y = 24, 28
    if cover_path and os.path.exists(cover_path):
        try:
            cover = Image.open(cover_path).convert("RGB")
            cover = cover.resize((cover_w, cover_h), Image.LANCZOS)
            img.paste(cover, (cover_x, cover_y))
        except Exception:
            draw.rectangle([cover_x, cover_y, cover_x + cover_w, cover_y + cover_h],
                           fill=(224, 224, 224))
            draw.text((cover_x + 120, cover_y + 90), "NO COVER", fill=GRAY, font=f_body)
    else:
        draw.rectangle([cover_x, cover_y, cover_x + cover_w, cover_y + cover_h],
                       fill=(224, 224, 224))
        draw.text((cover_x + 120, cover_y + 90), "NO COVER", fill=GRAY, font=f_body)

    # 时长标签
    dur = data.get("duration", 0)
    m, s = divmod(dur, 60)
    dur_str = f"{m:02d}:{s:02d}"
    dur_x, dur_y = cover_x + cover_w - 78, cover_y + cover_h - 32
    draw.rounded_rectangle([dur_x, dur_y, dur_x + 70, dur_y + 24], radius=4, fill=(0, 0, 0, 180))
    draw.text((dur_x + 6, dur_y + 2), dur_str, fill=(255, 255, 255), font=f_small)

    # 右侧信息区
    rx = cover_x + cover_w + 20
    ry = 28

    # 标题
    title = data.get("title", "?")
    if len(title) > 40:
        title = title[:38] + "…"
    draw.text((rx, ry), title, fill=DARK, font=f_title)
    ry += 40

    # UP主
    owner = data.get("owner", {}) or {}
    draw.text((rx, ry), f"👤 {owner.get('name', '?')}", fill=DARK, font=f_body)
    ry += 28

    # 分区 & 发布时间
    tname = data.get("tname", "?")
    pubdate = data.get("pubdate", 0)
    pub_str = f"🕐 {_fmt_ts(pubdate)}"
    draw.text((rx, ry), f"📂 {tname}    {pub_str}", fill=GRAY, font=f_small)
    ry += 30

    # 分隔线
    draw.line([(rx, ry), (W - 24, ry)], fill=LIGHT, width=1)
    ry += 18

    # 简介
    desc = data.get("desc") or ""
    if desc:
        if len(desc) > 80:
            desc = desc[:78] + "…"
        draw.text((rx, ry), desc, fill=GRAY, font=f_small)
        ry += 24
    else:
        draw.text((rx, ry), "（视频作者没有写简介哦~）", fill=GRAY, font=f_small)
        ry += 24

    # 底部统计区
    stats_y = cover_y + cover_h + 28
    stat = data.get("stat", {}) or {}
    stat_items = [
        ("▶️ 播放",  stat.get("view", 0),     BLUE),
        ("💬 弹幕",  stat.get("danmaku", 0),   PINK),
        ("👍 点赞",  stat.get("like", 0),      PINK),
        ("🪙 投币",  stat.get("coin", 0),      PINK),
        ("⭐ 收藏",  stat.get("favorite", 0),  PINK),
        ("🔄 转发",  stat.get("share", 0),     GRAY),
        ("💬 评论",  stat.get("reply", 0),     GRAY),
    ]
    # 第一行 4 个
    gx = cover_x
    for i, (label, val, color) in enumerate(stat_items[:4]):
        draw.text((gx, stats_y), label, fill=DARK, font=f_stat)
        val_str = _fmt_stat(val)
        tw = draw.textlength(label, font=f_stat) + 6
        draw.text((gx + tw, stats_y), val_str, fill=color, font=f_stat)
        gx += 175
    stats_y += 28
    # 第二行 3 个
    gx = cover_x
    for i, (label, val, color) in enumerate(stat_items[4:]):
        draw.text((gx, stats_y), label, fill=DARK, font=f_stat)
        val_str = _fmt_stat(val)
        tw = draw.textlength(label, font=f_stat) + 6
        draw.text((gx + tw, stats_y), val_str, fill=color, font=f_stat)
        gx += 175

    # 底部链接
    bvid = data.get("bvid", f"av{data.get('aid','')}")
    link = f"bilibili.com/video/{bvid}"
    draw.text((cover_x, H - 28), link, fill=GRAY, font=f_small)

    # 右下角 B站 logo 水印
    draw.text((W - 130, H - 28), "Bilibili", fill=PINK, font=f_bigstat)

    img.save(out_path, "PNG")


def _fmt_stat(n):
    if n >= 10000:
        return f"{n/10000:.1f}万"
    return f"{n:,}"


def _fmt_ts(ts):
    if not ts:
        return "?"
    from datetime import datetime as _dt2
    return _dt2.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


async def cmd_note(event, rest):
    """发布群公告: /note <内容> [yes|no]  置顶标志可省略，默认不置顶"""
    group_id = event["group_id"]
    text = rest.strip()
    if not text:
        await send_group_text(group_id, "❌ 用法: /note <公告内容> [yes|no]")
        return

    # 判断最后一个词是否是置顶标志（yes/no 等），是则剥离，否则全当正文
    PIN_WORDS = {"yes", "y", "no", "n", "是", "否", "true", "false", "1", "0", "置顶", "不置顶"}
    parts = text.rsplit(maxsplit=1)  # 按空白从右边切一刀
    if len(parts) == 2 and parts[1].lower() in PIN_WORDS:
        content = parts[0]
        pin_str = parts[1].lower()
        pinned = pin_str in ("yes", "y", "是", "true", "1", "置顶")
    else:
        content = text  # 最后那个词不是标志 → 全部都是正文
        pinned = False

    if not content.strip():
        await send_group_text(group_id, "❌ 公告内容不能为空")
        return

    # NapCat 群公告 API: _send_group_notice
    for api_name in ("_send_group_notice", "send_group_notice", "set_group_notice"):
        params = {"group_id": group_id, "content": content}
        if pinned:
            params["pinned"] = True
        res = await call_api(api_name, params, timeout=8)
        if api_ok(res):
            await send_group_text(group_id, "✅ 群公告已发布" + ("（置顶）" if pinned else ""))
            return
    await send_group_text(group_id, "⚠️ 公告发布失败，当前 NapCat 版本可能不支持此 API")


async def cmd_unnote(event, rest):
    """删除群公告:
    /unnote           → 列出本群所有公告(带序号)
    /unnote <序号>     → 删除指定公告
    /unnote all       → 删除全部公告
    """
    group_id = event["group_id"]
    rest = rest.strip()

    # ---- 获取公告列表 ----
    notices = None
    for get_api in ("_get_group_notice", "get_group_notice"):
        notices_res = await call_api(get_api, {"group_id": group_id}, timeout=8)
        if api_ok(notices_res):
            data = notices_res.get("data", {}) or {}
            if isinstance(data, list):
                notices = data
            elif isinstance(data, dict):
                notices = data.get("notices") or data.get("list") or data.get("feeds") or []
            else:
                notices = []
            break

    if notices is None:
        await send_group_text(group_id, "⚠️ 获取公告列表失败，请重试。")
        return

    if not notices:
        await send_group_text(group_id, "🗑️ 本群没有公告。")
        return

    # ---- 无参数: 列出公告 ----
    if not rest:
        lines = [f"📋 群 {group_id} 公告列表 (共 {len(notices)} 条):"]
        for i, n in enumerate(notices, 1):
            text = (n.get("message", {}) or {}).get("text", "") if isinstance(n, dict) else ""
            # 截断过长的内容，只显示前40字
            preview = text[:40].replace("\n", " ").replace("&#10;", " ")
            if len(text) > 40:
                preview += "..."
            publisher = n.get("sender_id", "?") if isinstance(n, dict) else "?"
            lines.append(f"  [{i}] {preview}  (发布者:{publisher})")
        lines.append("\n💡 用法: /unnote <序号> 删除指定  |  /unnote all 删除全部")
        await send_group_text(group_id, "\n".join(lines))
        return

    # ---- /unnote all → 删除全部 ----
    if rest.lower() in ("all", "全部", "所有"):
        deleted = 0
        for notice in notices:
            if not isinstance(notice, dict):
                continue
            nid = notice.get("notice_id") or notice.get("feed_id") or notice.get("id")
            if not nid:
                continue
            res = await call_api("_del_group_notice",
                                 {"group_id": group_id, "notice_id": nid}, timeout=8)
            if api_ok(res):
                deleted += 1
        if deleted:
            await send_group_text(group_id, f"🗑️ 已删除 {deleted}/{len(notices)} 条公告！")
        else:
            await send_group_text(group_id, "⚠️ 删除全部失败，当前 NapCat 版本可能不支持此 API。")
        return

    # ---- /unnote <序号或序列> → 删除指定公告 ----
    # 支持格式: 3  /  1,2,5  /  1-4  /  1,3-5,7
    import re as _re
    indices = set()
    for part in _re.split(r"[,，\s]+", rest):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            # 范围 如 1-5
            rng = part.split("-", 1)
            try:
                start, end = int(rng[0]), int(rng[1])
                for i in range(start, end + 1):
                    indices.add(i)
            except ValueError:
                await send_group_text(group_id, f"❌ 无效范围格式: {part}")
                return
        else:
            try:
                indices.add(int(part))
            except ValueError:
                await send_group_text(group_id, f"❌ 无效序号: {part}\n用法: /unnote <序号> 或 /unnote 1,2,5 或 /unnote 1-3 或 /unnote all")
                return

    if not indices:
        await send_group_text(group_id, "❌ 未指定有效序号。")
        return

    # 检查越界
    out_of_range = [i for i in indices if i < 1 or i > len(notices)]
    if out_of_range:
        await send_group_text(
            group_id,
            f"❌ 序号超出范围: {out_of_range}\n当前共 {len(notices)} 条公告，请重新输入。"
        )
        return

    # 逐个删除
    deleted = 0
    for idx in sorted(indices, reverse=True):  # 从大往小删，序号不乱
        notice = notices[idx - 1]
        if not isinstance(notice, dict):
            continue
        nid = notice.get("notice_id") or notice.get("feed_id") or notice.get("id")
        if not nid:
            continue
        res = await call_api("_del_group_notice",
                             {"group_id": group_id, "notice_id": nid}, timeout=8)
        if api_ok(res):
            deleted += 1

    if deleted:
        await send_group_text(group_id, f"🗑️ 已删除 {deleted}/{len(indices)} 条公告！")
    else:
        await send_group_text(group_id, "⚠️ 删除全部失败，当前 NapCat 版本可能不支持此 API。")


# 记忆 /essence 最后一条，供 /unessence 快速删除使用（可选）
_LAST_ESSENCE = {}  # {group_id: message_id}


async def cmd_essence(event, rest):
    """发送群精华消息: /essence <内容>"""
    group_id = event["group_id"]
    text = rest.strip()
    if not text:
        await send_group_text(group_id, "❌ 用法: /essence <精华内容>")
        return
    # 先发送消息，拿到 message_id 再设为精华
    res = await call_api("send_group_msg", {
        "group_id": group_id,
        "message": [{"type": "text", "data": {"text": text}}],
    }, timeout=8)
    if not api_ok(res):
        await send_group_text(group_id, "⚠️ 消息发送失败，无法设为精华。")
        return
    msg_id = (res.get("data", {}) or {}).get("message_id")
    if not msg_id:
        await send_group_text(group_id, "⚠️ 未获取到消息ID，精华设置失败。")
        return
    # 设为精华
    for api_name in ("set_essence_msg", "_set_essence_msg", "set_essence_message"):
        es_res = await call_api(api_name, {"message_id": msg_id}, timeout=5)
        if api_ok(es_res):
            _LAST_ESSENCE[group_id] = msg_id
            await send_group_text(group_id, "✨ 已设为群精华！")
            return
    await send_group_text(group_id, "⚠️ 精华设置失败，当前 NapCat 版本可能不支持此 API")


async def cmd_unessence(event, rest):
    """取消精华:
    /unessence           → 列出本群精华消息(带序号)
    /unessence <序号>     → 取消指定精华
    /unessence <1,2,5>   → 取消多条
    /unessence all       → 全部取消
    """
    group_id = event["group_id"]
    rest = rest.strip()

    # ---- 获取精华列表 ----
    essences = None
    for get_api in ("get_essence_msg_list", "_get_essence_msg_list",
                    "get_group_essence", "get_essence_list"):
        ess_res = await call_api(get_api, {"group_id": group_id}, timeout=8)
        if api_ok(ess_res):
            data = ess_res.get("data", {}) or {}
            if isinstance(data, list):
                essences = data
            elif isinstance(data, dict):
                essences = (data.get("messages") or data.get("list") or
                           data.get("essence_list") or data.get("essences") or [])
            else:
                essences = []
            break

    if essences is None:
        await send_group_text(group_id, "⚠️ 获取精华列表失败，请重试。")
        return

    if not essences:
        await send_group_text(group_id, "✨ 本群没有精华消息。")
        return

    # ---- 无参数: 列出精华 ----
    if not rest:
        lines = [f"✨ 群 {group_id} 精华消息 (共 {len(essences)} 条):"]
        for i, e in enumerate(essences, 1):
            if not isinstance(e, dict):
                continue
            # 试多种字段取内容
            text = ""
            for field in ("content", "message", "text", "raw_message"):
                val = e.get(field, "")
                if isinstance(val, list):
                    # 可能是消息段数组
                    parts = []
                    for seg in val:
                        if isinstance(seg, dict):
                            parts.append(seg.get("data", {}).get("text", "") if isinstance(seg.get("data"), dict) else str(seg))
                    text = "".join(parts)
                elif isinstance(val, str) and val:
                    text = val
                if text:
                    break
            preview = text[:40].replace("\n", " ")[:40]
            if len(text) > 40:
                preview += "..."
            sender = e.get("sender_id") or e.get("user_id") or e.get("sender_uin") or "?"
            lines.append(f"  [{i}] {preview}  (发送者:{sender})")
        lines.append("\n💡 用法: /unessence <序号> 取消指定  |  /unessence all 全部取消")
        await send_group_text(group_id, "\n".join(lines))
        return

    # ---- /unessence all → 全部取消 ----
    if rest.lower() in ("all", "全部", "所有"):
        deleted = await _delete_essences(group_id, essences, list(range(len(essences))))
        if deleted:
            await send_group_text(group_id, f"🗑️ 已取消 {deleted}/{len(essences)} 条精华！")
        else:
            await send_group_text(group_id, "⚠️ 取消全部精华失败，当前 NapCat 版本可能不支持此 API。")
        return

    # ---- /unessence <序号或序列> ----
    import re as _re2
    indices = set()
    for part in _re2.split(r"[,，\s]+", rest):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            rng = part.split("-", 1)
            try:
                start, end = int(rng[0]), int(rng[1])
                for i in range(start, end + 1):
                    indices.add(i)
            except ValueError:
                await send_group_text(group_id, f"❌ 无效范围格式: {part}")
                return
        else:
            try:
                indices.add(int(part))
            except ValueError:
                await send_group_text(group_id, f"❌ 无效序号: {part}\n用法: /unessence <序号> 或 /unessence 1,2,5 或 /unessence all")
                return

    if not indices:
        await send_group_text(group_id, "❌ 未指定有效序号。")
        return

    out_of_range = [i for i in indices if i < 1 or i > len(essences)]
    if out_of_range:
        await send_group_text(group_id, f"❌ 序号超出范围: {out_of_range}\n当前共 {len(essences)} 条精华。")
        return

    idx_list = [i - 1 for i in indices]  # 转 0-based
    deleted = await _delete_essences(group_id, essences, idx_list)
    if deleted:
        await send_group_text(group_id, f"🗑️ 已取消 {deleted}/{len(indices)} 条精华！")
    else:
        await send_group_text(group_id, "⚠️ 取消精华失败，当前 NapCat 版本可能不支持此 API。")


async def _delete_essences(group_id, essences, idx_list):
    """删除多条精华，返回成功条数。idx_list 为 0-based 索引列表。"""
    deleted = 0
    for idx in sorted(idx_list, reverse=True):
        if idx < 0 or idx >= len(essences):
            continue
        e = essences[idx]
        if not isinstance(e, dict):
            continue
        msg_id = e.get("message_id") or e.get("msg_id") or e.get("id") or e.get("msg_seq")
        if not msg_id:
            continue
        for api_name in ("delete_essence_msg", "_del_essence_msg",
                         "remove_essence_msg", "unset_essence_msg"):
            res = await call_api(api_name, {"message_id": msg_id}, timeout=5)
            if api_ok(res):
                # 同时清理内存记录
                if _LAST_ESSENCE.get(group_id) == msg_id:
                    del _LAST_ESSENCE[group_id]
                deleted += 1
                break
    return deleted


# 点赞计数: {"YYYYMMDD_QQ号": 点赞次数}
_LIKE_COUNT = {}
_LIKE_MAX = 20  # 每日每人最多点赞次数
_LIKE_PER_CALL = 5  # 每次API调用点赞数


async def cmd_like(event):
    """给发送者点赞(任意成员可用)。每人每日上限20赞。"""
    group_id = event["group_id"]
    user_id = event.get("user_id")
    nick = await get_nick(group_id, user_id)

    today = time.strftime("%Y%m%d")
    cd_key = f"{today}_{user_id}"
    current = _LIKE_COUNT.get(cd_key, 0)

    ok = False
    if current < _LIKE_MAX:
        res = await call_api("send_like", {"user_id": user_id, "times": _LIKE_PER_CALL}, timeout=5)
        if api_ok(res):
            _LIKE_COUNT[cd_key] = current + _LIKE_PER_CALL
            ok = True
        else:
            # API失败视为当日上限耗尽
            _LIKE_COUNT[cd_key] = _LIKE_MAX
            print(f"[点赞] {user_id} send_like 失败，标记当日已满")

    if ok:
        remaining = _LIKE_MAX - _LIKE_COUNT[cd_key]
        msg = random.choice([
            f"给 {nick} 点了赞！今日剩余 {remaining} 赞～",
            f";-; 点了！点了！{nick} 回个赞吧～（剩{remaining}）",
        ])
    else:
        msg = random.choice([
            f"今日点赞已达上限（{_LIKE_MAX}赞），明天再来吧～",
            f"今天已经给 {nick} 点满啦~👍",
        ])
    await send_group_text(group_id, msg)


async def cmd_black(event, rest):
    """将用户加入黑名单(仅Owner可用)。同时加入Bot内部黑名单和QQ原生黑名单。"""
    group_id = event["group_id"]
    target = parse_single_qq(rest)
    if target is None:
        await send_group_text(group_id, "❌ 格式错误。用法: /black <QQ号>")
        return
    if target in CONFIG["super_admins"]:
        await send_group_text(group_id, "❌ 不能将Owner加入黑名单。")
        return
    if target in CONFIG.get("banned_users", []):
        await send_group_text(group_id, f"ℹ️ {target} 已在黑名单中。")
        return

    # 1) Bot 内部黑名单
    CONFIG.setdefault("banned_users", []).append(target)
    save_config()

    # 2) QQ 原生黑名单（阻止加好友、发消息）
    qq_blocked = False
    for api_name in ("set_blacklist", "_set_blacklist",
                     "add_blacklist", "_add_blacklist",
                     "block_user", "_block_user",
                     "set_friend_blacklist", "_set_friend_blacklist"):
        res = await call_api(api_name, {"user_id": target}, timeout=5)
        if api_ok(res):
            qq_blocked = True
            print(f"[黑名单] QQ原生拉黑 {target} 成功 (API: {api_name})")
            break
    if not qq_blocked:
        # 有些版本用 delete_friend 来拉黑（会同时删好友+拉黑）
        res = await call_api("delete_friend", {"user_id": target}, timeout=5)
        if api_ok(res):
            qq_blocked = True
            print(f"[黑名单] 通过 delete_friend 拉黑 {target}")

    if qq_blocked:
        await send_group_text(group_id, f"✅ 已将 {target} 加入黑名单（Bot内部 + QQ原生），该用户无法使用任何命令、添加好友或邀请入群。")
    else:
        await send_group_text(group_id, f"✅ 已将 {target} 加入Bot内部黑名单。\n⚠️ QQ原生拉黑失败(API不支持)，但Bot内部已拦截。")


async def cmd_unblack(event, rest):
    """将用户移出黑名单(仅Owner可用)。同时移出QQ原生黑名单。"""
    group_id = event["group_id"]
    target = parse_single_qq(rest)
    if target is None:
        await send_group_text(group_id, "❌ 格式错误。用法: /unblack <QQ号>")
        return
    banned = CONFIG.get("banned_users", [])
    if target not in banned:
        await send_group_text(group_id, f"ℹ️ {target} 不在黑名单中。")
        return

    # 1) 移出 Bot 内部黑名单
    banned.remove(target)
    save_config()

    # 2) 移出 QQ 原生黑名单
    for api_name in ("delete_blacklist", "_del_blacklist",
                     "remove_blacklist", "_remove_blacklist",
                     "unblock_user", "_unblock_user"):
        res = await call_api(api_name, {"user_id": target}, timeout=5)
        if api_ok(res):
            print(f"[黑名单] QQ原生移出 {target} 成功 (API: {api_name})")
            break

    await send_group_text(group_id, f"✅ 已将 {target} 移出黑名单（Bot内部 + QQ原生）。")


async def cmd_reload(event, rest):
    """重新加载 config.json，使配置改动立即生效(无需重启bot)。"""
    group_id = event["group_id"]
    global CONFIG
    try:
        CONFIG = load_config()
    except Exception as e:
        await send_group_text(group_id, f"❌ 配置刷新失败(已保留旧配置): {e}")
        return
    await send_group_text(
        group_id,
        f"✅ 配置已刷新\n"
        f"Owner: {CONFIG['super_admins'] or '(无)'}\n"
        f"黑名单: {CONFIG['banned_users'] or '(无)'}\n"
        f"生效群: {CONFIG['allowed_groups'] or '全部'}"
    )


# ============================================================
#  事件分发
# ============================================================
async def handle_message(event):
    msg_type = event.get("message_type")
    group_id = event.get("group_id")
    user_id = event.get("user_id")

    # 私聊消息：接受 Owner 的 /yes /no /admin 指令，以及 Admin 的 /yes /no
    if msg_type == "private":
        raw = (event.get("raw_message") or "").strip()
        if raw.startswith(CONFIG["command_prefix"]):
            body = raw[len(CONFIG["command_prefix"]):].strip()
            parts = body.split(None, 1)
            cmd = parts[0].lower() if parts else ""
            rest = parts[1].strip() if len(parts) > 1 else ""
            if cmd in ("yes", "y", "同意", "accept", "agree"):
                if is_bot_admin(user_id):
                    await cmd_approve(event, rest, approve=True)
                return
            if cmd in ("no", "n", "拒绝", "reject", "deny"):
                if is_bot_admin(user_id):
                    await cmd_approve(event, rest, approve=False)
                return
            if cmd in ("admin", "admins", "管理", "setadmin"):
                if is_owner(user_id):
                    reply_text = await cmd_admin(event, rest)
                    await call_api("send_private_msg", {
                        "user_id": user_id,
                        "message": [{"type": "text", "data": {"text": reply_text}}],
                    }, timeout=8)
                return
        return

    if msg_type != "group":
        return
    if not group_id or not group_allowed(group_id):
        return

    raw = event.get("raw_message", "") or ""
    # 将 @mention [CQ:at,qq=xxx] 替换为纯 QQ 号，支持艾特封禁/禁言
    raw = re.sub(r'\[CQ:at,qq=(\d+)\]', r'\1', raw)
    # 关键词触发(任意成员, 无需前缀): 发"赞我" -> 点10个赞
    if raw.strip() in ("赞我", "/赞我"):
        await cmd_like(event)
        return
    prefix = CONFIG["command_prefix"]
    if not raw.startswith(prefix):
        return

    body = raw[len(prefix):].strip()
    parts = body.split(None, 1)
    if not parts:
        return
    cmd = parts[0].lower()
    rest = parts[1].strip() if len(parts) > 1 else ""

    # help/sid/like 无需权限，放最前面
    if cmd in ("help", "帮助", "?", "菜单"):
        sub = rest.strip().lower()
        if sub in ("full", "all", "详细", "全部", "完整"):
            await send_group_text(group_id, HELP_FULL)
        else:
            await send_group_text(group_id, HELP_SHORT)
        return

    # 黑名单拦截
    if event.get("user_id") in CONFIG.get("banned_users", []):
        owner_qq = CONFIG["super_admins"][0] if CONFIG["super_admins"] else "未知"
        await send_group_text(
            group_id,
            f"× 你被加入黑名单了 请寻找Owner({owner_qq})解ban"
        )
        return

    admin = is_admin(event)

    if cmd in ("mute", "禁言"):
        if not admin and not is_bot_admin(user_id):
            await send_group_text(group_id, "⛔ 仅群主/管理员可使用此命令。")
            return
        await cmd_mute(event, rest)
    elif cmd in ("unmute", "解禁", "解除禁言"):
        if not admin and not is_bot_admin(user_id):
            await send_group_text(group_id, "⛔ 仅群主/管理员可使用此命令。")
            return
        await cmd_unmute(event, rest)
    elif cmd in ("ban", "封禁", "封人", "kick", "踢"):
        if not admin and not is_bot_admin(user_id):
            await send_group_text(group_id, "⛔ 仅群主/管理员可使用此命令。")
            return
        await cmd_ban(event, rest)
    elif cmd in ("unban", "解封", "解封禁"):
        if not admin and not is_bot_admin(user_id):
            await send_group_text(group_id, "⛔ 仅群主/管理员可使用此命令。")
            return
        await cmd_unban(event, rest)
    elif cmd in ("list", "名单", "列表"):
        if not admin and not is_bot_admin(user_id):
            await send_group_text(group_id, "⛔ 仅群主/管理员可使用此命令。")
            return
        await cmd_list(event, rest)
    elif cmd in ("say", "说", "发言", "复读"):
        if not admin and not is_bot_admin(user_id):
            await send_group_text(group_id, "⛔ 仅群主/管理员可使用此命令。")
            return
        await cmd_say(event, rest)
    elif cmd in ("note", "公告", "发布公告"):
        if not admin and not is_bot_admin(user_id):
            await send_group_text(group_id, "⛔ 仅群主/管理员可使用此命令。")
            return
        await cmd_note(event, rest)
    elif cmd in ("unnote", "删除公告", "清除公告"):
        if not admin and not is_bot_admin(user_id):
            await send_group_text(group_id, "⛔ 仅群主/管理员可使用此命令。")
            return
        await cmd_unnote(event, rest)
    elif cmd in ("essence", "精华"):
        if not admin and not is_bot_admin(user_id):
            await send_group_text(group_id, "⛔ 仅群主/管理员可使用此命令。")
            return
        await cmd_essence(event, rest)
    elif cmd in ("unessence", "取消精华", "删除精华"):
        if not admin and not is_bot_admin(user_id):
            await send_group_text(group_id, "⛔ 仅群主/管理员可使用此命令。")
            return
        await cmd_unessence(event, rest)
    elif cmd in ("reload", "刷新", "重载", "重新加载"):
        if not admin and not is_bot_admin(user_id):
            await send_group_text(group_id, "⛔ 仅群主/管理员可使用此命令。")
            return
        await cmd_reload(event, rest)
    elif cmd in ("whitelist", "wl", "白名单"):
        if not admin and not is_bot_admin(user_id):
            await send_group_text(group_id, "⛔ 仅群主/管理员可使用此命令。")
            return
        await cmd_whitelist(event, rest)
    elif cmd in ("welcome", "欢迎", "欢迎消息"):
        if not admin and not is_bot_admin(user_id):
            await send_group_text(group_id, "⛔ 仅群主/管理员可使用此命令。")
            return
        await cmd_welcome(event, rest)
    elif cmd in ("black", "拉黑"):
        if not is_owner(user_id):
            await send_group_text(group_id, "⛔ 仅Owner可使用此命令。")
            return
        await cmd_black(event, rest)
    elif cmd in ("unblack", "取消拉黑"):
        if not is_owner(user_id):
            await send_group_text(group_id, "⛔ 仅Owner可使用此命令。")
            return
        await cmd_unblack(event, rest)
    elif cmd in ("blacklist", "黑名单"):
        if not admin and not is_bot_admin(user_id):
            await send_group_text(group_id, "⛔ 仅群主/管理员可使用此命令。")
            return
        banned = CONFIG.get("banned_users", [])
        if banned:
            await send_group_text(group_id, f"📋 黑名单 ({len(banned)} 人):\n" + "\n".join(f"  · {u}" for u in banned))
        else:
            await send_group_text(group_id, "📋 黑名单: (空)")
    elif cmd in ("sid", "session", "会话", "身份"):
        await cmd_sid(event)
    elif cmd in ("github", "gh", "repo", "仓库"):
        await cmd_github(event, rest)
    elif cmd in ("bilibili", "bili", "b站", "bv"):
        await cmd_bilibili(event, rest)
    elif cmd in ("yes", "y", "同意", "accept", "agree"):
        if not is_bot_admin(user_id):
            await send_group_text(group_id, "⛔ 仅Owner/Admin可使用此命令。")
            return
        await cmd_approve(event, rest, approve=True)
    elif cmd in ("no", "n", "拒绝", "reject", "deny"):
        if not is_bot_admin(user_id):
            await send_group_text(group_id, "⛔ 仅Owner/Admin可使用此命令。")
            return
        await cmd_approve(event, rest, approve=False)
    elif cmd in ("pending", "requests", "审批", "待处理"):
        if not is_bot_admin(user_id):
            await send_group_text(group_id, "⛔ 仅Owner/Admin可使用此命令。")
            return
        await cmd_pending(event)
    else:
        # 未知指令
        await send_group_text(
            group_id,
            f"🤔 未知指令 /{cmd}，该功能尚未开发。\n发送 /help 查看可用命令列表。"
        )


async def cmd_whitelist(event, rest):
    """白名单管理: /whitelist add|remove <qq> / on / off / list"""
    group_id = event["group_id"]
    gid = str(group_id)

    parts = rest.strip().split(None, 1)
    sub = parts[0].lower() if parts else "list"

    if sub in ("add", "添加", "加入", "+"):
        target = parse_single_qq(parts[1] if len(parts) > 1 else "")
        if target is None:
            await send_group_text(group_id, "❌ 格式错误。用法: /whitelist add <QQ号>")
            return
        wl = DB["whitelist"].setdefault(gid, [])
        if target in wl:
            await send_group_text(group_id, f"ℹ️ {target} 已在白名单中。")
        else:
            wl.append(target)
            save_db()
            await send_group_text(group_id, f"✅ 已添加 {target} 到白名单。")

    elif sub in ("remove", "del", "delete", "移除", "删除", "去掉", "-"):
        target = parse_single_qq(parts[1] if len(parts) > 1 else "")
        if target is None:
            await send_group_text(group_id, "❌ 格式错误。用法: /whitelist remove <QQ号>")
            return
        wl = DB["whitelist"].get(gid, [])
        if target in wl:
            wl.remove(target)
            if not wl:
                del DB["whitelist"][gid]
            save_db()
            await send_group_text(group_id, f"✅ 已从白名单移除 {target}。")
        else:
            await send_group_text(group_id, f"ℹ️ {target} 不在白名单中。")

    elif sub in ("on", "enable", "启用", "开启"):
        enabled = DB.setdefault("whitelist_enabled", [])
        if group_id in enabled:
            await send_group_text(group_id, "ℹ️ 白名单模式已处于启用状态。")
        else:
            enabled.append(group_id)
            save_db()
            await send_group_text(group_id, "🛡️ 白名单模式已【启用】。仅白名单内的成员可以申请加群。")

    elif sub in ("off", "disable", "禁用", "关闭"):
        enabled = DB.setdefault("whitelist_enabled", [])
        if group_id in enabled:
            enabled.remove(group_id)
            save_db()
            await send_group_text(group_id, "🔓 白名单模式已【关闭】。任何人(封禁除外)均可申请加群。")
        else:
            await send_group_text(group_id, "ℹ️ 白名单模式当前未启用。")

    else:  # list / 查看
        wl = DB["whitelist"].get(gid, [])
        enabled = DB.get("whitelist_enabled", [])
        status = "🟢 已启用" if group_id in enabled else "⚪ 已关闭"
        out = [f"📋 群 {group_id} 白名单 ({status})"]
        out.append(f"\n共 {len(wl)} 人:")
        if wl:
            for uid in wl:
                out.append(f"  · {uid}")
        else:
            out.append("  (空)")
        await send_group_text(group_id, "\n".join(out))


async def cmd_welcome(event, rest):
    """自定义欢迎/退群消息（每群独立）: /welcome [<消息>] / welcome leave <消息> / welcome off
    群主/管理员/Bot Admin 可用。
    变量: {nick} {user_id} {group_id} {member_count} (member_count 仅欢迎消息有效)
    设为 off 清除本群自定义，恢复使用全局默认值。
    """
    group_id = event["group_id"]
    gid = str(group_id)
    parts = rest.strip().split(None, 1)
    sub = parts[0].lower() if parts else ""

    if sub in ("leave", "退群", "离开", "bye"):
        content = parts[1].strip() if len(parts) > 1 else ""
        if not content:
            current = DB.get("leave_msgs", {}).get(gid)
            default = CONFIG.get("leave_message", "")
            lines = ["📝 本群退群消息:"]
            if current is not None:
                lines.append(f"  自定义: {current if current else '(已关闭)'}")
                lines.append(f"  全局默认: {default if default else '(已关闭)'}")
            else:
                lines.append(f"  (使用全局默认) {default if default else '(已关闭)'}")
            lines.append("\n💡 设置: /welcome leave <消息>")
            lines.append("   关闭: /welcome leave off（恢复全局默认）")
            lines.append("   变量: {nick} {user_id} {group_id}")
            await send_group_text(group_id, "\n".join(lines))
            return
        if content.lower() in ("off", "关闭", "禁用", "none", "无"):
            DB.setdefault("leave_msgs", {}).pop(gid, None)
            save_db()
            await send_group_text(group_id, "✅ 本群退群消息已清除，恢复使用全局默认。")
            return
        DB.setdefault("leave_msgs", {})[gid] = content
        save_db()
        await send_group_text(group_id, f"✅ 本群退群消息已更新为:\n{content}")
        return

    if sub in ("off", "关闭", "禁用", "none", "无"):
        DB.setdefault("welcome_msgs", {}).pop(gid, None)
        save_db()
        await send_group_text(group_id, "✅ 本群欢迎消息已清除，恢复使用全局默认。")
        return

    if not sub or sub in ("show", "查看", "status"):
        w_current = DB.get("welcome_msgs", {}).get(gid)
        l_current = DB.get("leave_msgs", {}).get(gid)
        w_default = CONFIG.get("welcome_message", "")
        l_default = CONFIG.get("leave_message", "")
        lines = ["📝 本群消息设置:"]
        if w_current is not None:
            lines.append(f"  欢迎(自定义): {w_current if w_current else '(已关闭)'}")
        else:
            lines.append(f"  欢迎(全局): {w_default if w_default else '(已关闭)'}")
        if l_current is not None:
            lines.append(f"  退群(自定义): {l_current if l_current else '(已关闭)'}")
        else:
            lines.append(f"  退群(全局): {l_default if l_default else '(已关闭)'}")
        lines.append("\n💡 设置欢迎: /welcome <消息>")
        lines.append("   设置退群: /welcome leave <消息>")
        lines.append("   关闭本群自定义: /welcome off")
        lines.append("   变量: {nick} {user_id} {group_id} {member_count}")
        await send_group_text(group_id, "\n".join(lines))
        return

    # 设置本群欢迎消息
    DB.setdefault("welcome_msgs", {})[gid] = rest.strip()
    save_db()
    await send_group_text(group_id, f"✅ 本群欢迎消息已更新为:\n{rest.strip()}")


async def cmd_admin(event, rest):
    """管理 Bot Admin: /admin add <qq> [qq...] / remove / list
    仅 Owner 可在私聊中使用。
    """
    parts = rest.strip().split()
    sub = parts[0].lower() if parts else "list"

    if sub in ("add", "添加", "加入", "+"):
        targets = []
        for p in parts[1:]:
            p = p.strip()
            if re.fullmatch(r"\d+", p):
                targets.append(int(p))
        if not targets:
            return "❌ 格式错误。用法: /admin add <QQ号> [QQ号...]"
        added = []
        existed = []
        current = CONFIG.setdefault("admins", [])
        for qq in targets:
            if qq in CONFIG["super_admins"]:
                existed.append(f"{qq}(已是Owner)")
            elif qq in current:
                existed.append(str(qq))
            else:
                current.append(qq)
                added.append(str(qq))
        if added:
            save_config()
        msgs = []
        if added:
            msgs.append(f"✅ 已添加 Admin: {', '.join(added)}")
        if existed:
            msgs.append(f"ℹ️ 已在列表中: {', '.join(existed)}")
        return "\n".join(msgs) if msgs else "ℹ️ 没有需要添加的用户。"

    elif sub in ("remove", "del", "delete", "移除", "删除", "-"):
        targets = []
        for p in parts[1:]:
            p = p.strip()
            if re.fullmatch(r"\d+", p):
                targets.append(int(p))
        if not targets:
            return "❌ 格式错误。用法: /admin remove <QQ号> [QQ号...]"
        removed = []
        not_found = []
        current = CONFIG.get("admins", [])
        for qq in targets:
            if qq in current:
                current.remove(qq)
                removed.append(str(qq))
            else:
                not_found.append(str(qq))
        if removed:
            save_config()
        msgs = []
        if removed:
            msgs.append(f"✅ 已移除 Admin: {', '.join(removed)}")
        if not_found:
            msgs.append(f"ℹ️ 不在 Admin 列表中: {', '.join(not_found)}")
        return "\n".join(msgs) if msgs else "ℹ️ 没有需要移除的用户。"

    else:  # list / 查看
        admins = CONFIG.get("admins", [])
        if admins:
            return f"📋 Bot Admin 列表 (共 {len(admins)} 人):\n" + "\n".join(f"  · {u}" for u in admins)
        else:
            return "📋 Bot Admin 列表: (空)\n💡 用法: /admin add <QQ号> 添加 Admin"


async def handle_notice(event):
    """处理通知事件：成员加入/退出 + Owner自动保护。"""
    notice_type = event.get("notice_type")
    group_id = event.get("group_id")
    if not group_id or not group_allowed(group_id):
        return

    user_id = event.get("user_id")
    if not user_id:
        return

    # ---- Owner被禁言 → 自动解禁 ----
    if notice_type == "group_ban" and event.get("sub_type") == "ban":
        if user_id in CONFIG["super_admins"]:
            operator = event.get("operator_id")
            await call_api("set_group_ban", {
                "group_id": group_id, "user_id": user_id, "duration": 0,
            })
            # 清理本地禁言记录
            key = f"{group_id}_{user_id}"
            if key in DB.get("mutes", {}):
                del DB["mutes"][key]
                save_db()
            print(f"[Owner保护] {user_id} 在群 {group_id} 被 {operator} 禁言，已自动解禁")
            await send_group_text(
                group_id,
                f"🛡️ 检测到Owner被禁言，已自动解除！"
            )
        return

    # ---- 通话邀请（语音/视频）→ 自动拒绝 ----
    if CONFIG.get("reject_calls", True):
        notice_type = event.get("notice_type", "")
        sub_type = event.get("sub_type", "")
        if notice_type == "notify" and sub_type in (
            "av_call", "video_call", "voice_call", "call", "video", "voice",
            "p2p_av_call", "group_call", "invite_to_av",
        ):
            # 尝试调用各种可能的挂断/拒绝 API
            for api_name in ("set_group_ban", "reject_call", "_reject_call",
                             "set_call_request", "hang_up", "_hang_up"):
                await call_api(api_name, {
                    "group_id": group_id, "user_id": user_id, "duration": 0,
                }, timeout=3)
            print(f"[通话拦截] 已拒绝来自 {user_id} 的通话邀请 (notice: {sub_type})")
            return

    # ---- 机器人自己被踢 → 自动从生效群移除 ----
    if notice_type == "group_decrease" and event.get("sub_type") == "kick_me":
        if group_id in CONFIG["allowed_groups"]:
            CONFIG["allowed_groups"].remove(group_id)
            save_config()
            print(f"[自动注销] 群 {group_id} 已从生效群列表移除（机器人被踢）")
        return

    # ---- Owner被踢 → 清理记录 + 自动邀请回群 ----
    if notice_type == "group_decrease" and event.get("sub_type") == "kick":
        if user_id in CONFIG["super_admins"]:
            operator = event.get("operator_id")
            key = f"{group_id}_{user_id}"
            # 清理本地封禁/禁言记录
            for table in ("bans", "mutes"):
                if key in DB.get(table, {}):
                    del DB[table][key]
                    save_db()
            nick = await get_nick(group_id, user_id)
            print(f"[Owner保护] {nick}({user_id}) 在群 {group_id} 被 {operator} 踢出")

            # 尝试自动邀请回群 (NapCat 扩展 API)
            invited = False
            for api_name in ("invite_group_member", "send_group_invite",
                             "set_group_invite", "group_invite"):
                res = await call_api(api_name,
                    {"group_id": group_id, "user_id": user_id}, timeout=6)
                if api_ok(res):
                    invited = True
                    print(f"  → 已通过 {api_name} 自动邀请回群")
                    break

            if invited:
                await send_group_text(
                    group_id,
                    f"🛡️ Owner {nick}({user_id}) 被踢出，已自动邀请回群！"
                )
            else:
                # 兜底：私聊提醒重新申请（会由 handle_request 自动同意）
                await call_api("send_private_msg", {
                    "user_id": user_id,
                    "message": [
                        {"type": "text",
                         "data": {"text": f"你在群 {group_id} 被踢出了。"
                                          f"重新申请即可自动通过。"}}],
                }, timeout=6)
                await send_group_text(
                    group_id,
                    f"🛡️ Owner {nick}({user_id}) 被踢出！"
                    f"记录已清除，重新申请加群将自动通过。"
                )
        else:
            # 普通人被踢 — 不发消息 (/ban 已发，或QQ原生踢人有系统提示)
            pass
        return

    # ---- 有人入群 ----
    if notice_type == "group_increase":
        nick = await get_nick(group_id, user_id)
        info_res = await call_api("get_group_info", {"group_id": group_id}, timeout=8)
        member_count = "?"
        if api_ok(info_res):
            info_data = (info_res.get("data", {}) or {})
            member_count = info_data.get("member_count", "?")
        # 优先使用本群自定义消息，否则用全局默认
        template = DB.get("welcome_msgs", {}).get(str(group_id)) or CONFIG.get("welcome_message", "")
        msg = format_msg(template,
                         nick=nick, user_id=user_id, group_id=group_id,
                         member_count=member_count)
        if msg:
            await send_group_text(group_id, msg)

    # 普通退群 (leave)
    elif notice_type == "group_decrease":
        nick = await get_nick(group_id, user_id)
        template = DB.get("leave_msgs", {}).get(str(group_id)) or CONFIG.get("leave_message", "")
        msg = format_msg(template,
                         nick=nick, user_id=user_id, group_id=group_id)
        if msg:
            await send_group_text(group_id, msg)


async def handle_request(event):
    """处理加好友/加群请求：
    - friend: 询问Owner(yes/no)
    - group/invite: Owner邀请自动同意；其他人询问Owner
    - group/add: 拦截被封禁成员 + 白名单检查
    """
    req_type = event.get("request_type")
    sub_type = event.get("sub_type")
    group_id = event.get("group_id")
    user_id = event.get("user_id")
    flag = event.get("flag")
    comment = event.get("comment", "")

    if not user_id or not flag:
        return

    # ---- 黑名单自动拒绝 ----
    if user_id in CONFIG.get("banned_users", []):
        if req_type == "friend":
            await call_api("set_friend_add_request", {
                "flag": flag, "approve": False,
                "remark": "你已被拉黑，无法添加好友。",
            }, timeout=8)
            print(f"[黑名单] 自动拒绝 {user_id} 的好友请求")
        elif req_type == "group" and sub_type == "invite":
            await call_api("set_group_add_request", {
                "flag": flag, "sub_type": "invite", "approve": False,
                "reason": "你已被拉黑，无法邀请机器人。",
            }, timeout=8)
            print(f"[黑名单] 自动拒绝 {user_id} 邀请进群 {group_id}")
        return

    # ---- 好友请求：询问Owner ----
    if req_type == "friend":
        await _notify_owner_for_approval(user_id, flag, "friend", group_id=None,
                                         comment=comment)
        return

    # ---- 以下为群相关 ----
    if req_type != "group":
        return
    if not group_id:
        return

    # ---- 机器人被邀请加群 ----
    if sub_type == "invite":
        if user_id in CONFIG["super_admins"]:
            # Owner邀请 → 自动同意
            res = await call_api("set_group_add_request", {
                "flag": flag, "sub_type": "invite", "approve": True,
            })
            print(f"[邀请] Owner {user_id} 邀请进群 {group_id} → 自动同意 resp={res}")
            gid = int(group_id)
            if gid and gid not in CONFIG["allowed_groups"]:
                CONFIG["allowed_groups"].append(gid)
                save_config()
                print(f"[自动注册] 群 {gid} 已添加到生效群列表")
        elif CONFIG.get("reject_non_owner_invites", True):
            # 非Owner邀请 → 自动拒绝
            await call_api("set_group_add_request", {
                "flag": flag, "sub_type": "invite", "approve": False,
                "reason": "仅Owner可邀请机器人入群。",
            }, timeout=8)
            print(f"[邀请拦截] 非Owner {user_id} 邀请进群 {group_id} → 已自动拒绝")
        else:
            # 配置关闭了自动拒绝 → 询问Owner
            await _notify_owner_for_approval(user_id, flag, "group_invite",
                                             group_id=group_id, comment=comment)
        return

    # ---- 通话邀请（语音/视频）→ 自动拒绝 ----
    if (CONFIG.get("reject_calls", True) and
        sub_type in ("call", "video", "voice", "av_call", "p2p_call",
                     "group_call", "invite_call", "request_video",
                     "request_voice", "request_call")):
        for api_name in ("set_group_add_request",
                         "set_call_request", "_set_call_request",
                         "reject_call", "_reject_call"):
            res = await call_api(api_name, {
                "flag": flag, "sub_type": sub_type, "approve": False,
                "reason": "机器人不接受通话邀请。",
            }, timeout=5)
            if api_ok(res):
                print(f"[通话拦截] 已拒绝 {user_id} 的通话邀请 (API: {api_name})")
                return
        # 兜底：尝试 approve=False
        print(f"[通话拦截] 尝试通用拒绝 {user_id} 的通话邀请 (sub_type={sub_type})")
        await call_api("set_group_add_request", {
            "flag": flag, "sub_type": sub_type, "approve": False,
            "reason": "机器人不接受通话邀请。",
        }, timeout=5)
        return

    # ---- 普通加群申请(add) ----
    if sub_type not in ("add", None):
        return
    if not group_allowed(group_id):
        return

    now = time.time()
    key = f"{group_id}_{user_id}"

    # 0) Owner自动同意进群
    if user_id in CONFIG["super_admins"]:
        res = await call_api("set_group_add_request", {
            "flag": flag, "sub_type": "add", "approve": True,
        })
        ok = "成功" if api_ok(res) else "失败"
        print(f"[Owner] {user_id} 申请加群 {group_id}，自动同意({ok})")
        return

    # 1) 封禁检查
    rec = DB["bans"].get(key)
    if rec:
        if rec["expire"] == 0 or rec["expire"] > now:
            await call_api("set_group_add_request", {
                "flag": flag, "sub_type": "add", "approve": False,
                "reason": f"封禁中: {rec['reason']}",
            })
            print(f"[封禁拦截] 已拒绝 {user_id} 加入群 {group_id} (原因: {rec['reason']})")
            return
        else:
            del DB["bans"][key]
            save_db()

    # 2) 白名单检查
    wl_enabled = DB.get("whitelist_enabled", [])
    if group_id in wl_enabled:
        wl = DB["whitelist"].get(str(group_id), [])
        if user_id not in wl:
            await call_api("set_group_add_request", {
                "flag": flag, "sub_type": "add", "approve": False,
                "reason": "不在白名单中，禁止加群。",
            })
            print(f"[白名单拦截] 已拒绝 {user_id} 加入群 {group_id} (不在白名单)")
            return


async def _notify_owner_for_approval(user_id, flag, req_kind, group_id=None, comment=""):
    """将请求存储并私聊通知Owner决定。"""
    _REQ_COUNTER[0] += 1
    rid = _REQ_COUNTER[0]
    _PENDING_REQS[rid] = {
        "flag": flag, "user_id": user_id, "group_id": group_id,
        "kind": req_kind, "comment": comment, "timestamp": time.time(),
    }

    # 获取请求者昵称
    nick = f"用户{user_id}"
    if req_kind == "friend":
        info = await call_api("get_stranger_info", {"user_id": user_id}, timeout=5)
    else:
        info = await call_api("get_group_member_info",
                              {"group_id": group_id, "user_id": user_id}, timeout=5)
    if api_ok(info):
        data = info.get("data", {}) or {}
        nick = data.get("nickname") or data.get("card") or nick

    # 构造通知消息
    if req_kind == "friend":
        title = f"👤 {nick}({user_id}) 请求添加机器人为好友"
    else:
        title = f"📨 {nick}({user_id}) 邀请机器人加入群 {group_id}"
    if comment:
        title += f"\n📝 验证消息: {comment}"
    title += f"\n\n[请求ID: {rid}]  回复 /yes {rid} 同意  |  /no {rid} 拒绝"

    for owner_qq in CONFIG["super_admins"]:
        await call_api("send_private_msg", {
            "user_id": owner_qq,
            "message": [{"type": "text", "data": {"text": title}}],
        }, timeout=8)
    print(f"[审批] 请求ID={rid} kind={req_kind} user={user_id} group={group_id} 已通知Owner")


async def dispatch(raw):
    try:
        msg = json.loads(raw)
    except Exception:
        return
    if not isinstance(msg, dict):
        return

    echo = msg.get("echo")
    if echo and echo in PENDING:
        fut = PENDING.pop(echo, None)
        if fut and not fut.done():
            fut.set_result(msg)
        return

    post = msg.get("post_type")
    if post == "message":
        await _safe(handle_message, msg)
    elif post == "request":
        await _safe(handle_request, msg)
    elif post == "notice":
        await _safe(handle_notice, msg)


async def _safe(coro_func, *args):
    try:
        await coro_func(*args)
    except Exception as e:
        print(f"[异常] {coro_func.__name__}: {e}")


async def _safe_dispatch(raw):
    """带异常保护的 dispatch，防止 create_task 静默失败。"""
    try:
        await dispatch(raw)
    except Exception as e:
        print(f"[异常] dispatch: {e}")

# ============================================================
#  后台任务：永久禁言续期 + 过期记录清理
# ============================================================
async def background_tasks():
    interval = max(60, CONFIG["reapply_interval"])
    while True:
        await asyncio.sleep(interval)
        try:
            now = time.time()
            # 1) 给所有"永久禁言"重新上 30 天禁言
            for key, v in list(DB["mutes"].items()):
                if v["expire"] == 0:
                    res = await call_api("set_group_ban", {
                        "group_id": v["group_id"], "user_id": v["user_id"],
                        "duration": CONFIG["mute_max_seconds"],
                    })
                    if api_ok(res):
                        print(f"[续期] 永久禁言 {v['user_id']} @ 群{v['group_id']} 已续期")
            # 2) 清理已过期的限时封禁/禁言记录
            changed = False
            for key, v in list(DB["bans"].items()):
                if v["expire"] != 0 and v["expire"] <= now:
                    del DB["bans"][key]
                    changed = True
            for key, v in list(DB["mutes"].items()):
                if v["expire"] != 0 and v["expire"] <= now:
                    del DB["mutes"][key]
                    changed = True
            if changed:
                save_db()
        except Exception as e:
            print(f"[后台任务异常] {e}")

# ============================================================
#  CMD 输入监听：在 CMD 里输入 r + 回车 -> 重新加载 bot
# ============================================================
def stdin_reloader_loop():
    """监听 CMD 输入: r / reload / 重启 / 刷新 + 回车 -> 以退出码 2 结束,
    由 启动.bat 检测退出码后自动重启 bot(重新加载最新 bot.py)。"""
    while True:
        try:
            line = input()
        except (EOFError, OSError):
            return
        if line.strip().lower() in ("r", "reload", "restart", "刷新", "重启", "重载"):
            print("[重启] 收到刷新指令，正在重新加载 bot...")
            os._exit(2)


# ============================================================
#  主循环：连接 NapCat + 断线重连
# ============================================================
async def run():
    global WS
    url = CONFIG["ws_url"]
    print("=" * 56)
    print("  QQ 群管理机器人 启动中")
    print(f"  NapCat 地址 : {url}")
    print(f"  Owner   : {CONFIG['super_admins'] or '(未设置!) 请编辑 config.json'}")
    print(f"  禁用用户     : {CONFIG['banned_users'] or '(无)'}")
    print(f"  允许群主     : {CONFIG['allow_owner']} | 允许管理员: {CONFIG['allow_admin']}")
    print(f"  生效群       : {'全部' if not CONFIG['allowed_groups'] else CONFIG['allowed_groups']}")
    print("=" * 56)

    asyncio.create_task(background_tasks())
    threading.Thread(target=stdin_reloader_loop, daemon=True).start()

    while True:
        try:
            async with websockets.connect(
                url, ping_interval=20, ping_timeout=60, close_timeout=5
            ) as ws:
                WS = ws
                print("[连接] 已连接到 NapCat ✓  等待消息...")
                # 试着获取登录信息，确认是哪个QQ
                login = await call_api("get_login_info", timeout=8)
                if api_ok(login):
                    d = login.get("data", {}) or {}
                    print(f"[登录] 机器人账号: {d.get('nickname')} ({d.get('user_id')})")
                async for raw in ws:
                    # 用 create_task，避免单条消息处理阻塞接收循环(否则API响应会死锁)
                    asyncio.create_task(_safe_dispatch(raw))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"[断开] {type(e).__name__}: {e} — {CONFIG['reconnect_delay']} 秒后重连...")
        finally:
            WS = None
        await asyncio.sleep(CONFIG["reconnect_delay"])


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\n[退出] 已停止。")
        sys.exit(0)
    except Exception as e:
        print(f"\n[致命错误] {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        print("5 秒后退出，启动器将自动重启...")
        time.sleep(5)
        sys.exit(3)
