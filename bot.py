#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 AlwaysCryingMC <https://github.com/AlwaysCryingMC>
"""
QQ 群管理机器人 (对接 OneBot 11 / NapCat)
==========================================
版权所有 (C) 2026 AlwaysCryingMC
依据 GNU GPL v3.0（或更高版本）授权，详见 LICENSE。

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
from datetime import datetime

# 强制 stdout/stderr 使用 UTF-8。
# 否则后台运行.vbs 用 "cmd /c py bot.py >> bot.log" 拉起时不会设置
# PYTHONUTF8/PYTHONIOENCODING，stdout 默认是 GBK，打印 ✓(U+2713)/emoji
# 等非 GBK 字符会抛 UnicodeEncodeError，被 run() 的 except 捕获后
# 断开重连 -> 再打印 ✓ -> 再崩，陷入死循环（bot.log 里全是这个错误）。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    import websockets
except ImportError:
    print("[错误] 缺少依赖 websockets。")
    print("       请双击 启动.bat ，或手动运行: pip install -r requirements.txt")
    sys.exit(1)

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
    "admins": [],
    "allow_owner": True,
    "allow_admin": True,
    "allowed_groups": [],
    "command_prefix": "/",
    "reconnect_delay": 5,
    "reapply_interval": 86400,
    "mute_max_seconds": 2592000,
    "welcome_message": "你好！{nick}({user_id})！你是本群的第 {member_count} 位成员 🎉",
    "leave_message": "哔哔哔！群友 {nick}({user_id}) 退群了！",
    "reject_non_owner_invites": False,
    "auto_leave_check_interval": 300,
    "notify_dm": True,
    "bot_signature": "使用 /help 查看命令列表",
    "bot_nickname": "",
    "bot_avatar_path": "",
}

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


HELP_SHORT = (
    "🤖 QQ群管理机器人\n"
    "——————————————————\n"
    "🔒 管理: /封禁 /解封 /禁言 /解禁 /名单\n"
    "💬 /欢迎 — 自定义欢迎/退群消息\n"
    "🔄 /重载 — 热重载配置\n"
    "🎰 /抽奖 — 参与本群抽奖\n"
    "🎲 /roll — 抽奖管理 (仅Owner私聊)\n"
    "❤️ 赞我 — 给发送者点赞(每日20次)\n"
    "——————————————————\n"
    "时长: 30s/10m/2h/1d/3w, 0=永久\n"
    "别名: 所有命令同时支持 /英文 和 /中文"
)

HELP_FULL = (
    "🤖 QQ群管理机器人 完整命令列表\n"
    "——————————————————\n"
    "【群主/管理员 可用】\n"
    "/ban  <QQ号> <时长> <原因>  封禁(踢出)  |  /封禁 /封 /踢\n"
    "/unban  <QQ号>               解封        |  /解封 /解封禁\n"
    "/mute  <QQ号> <时长> <原因>  禁言        |  /禁言\n"
    "/unmute <QQ号>               解禁        |  /解禁 /解除禁言\n"
    "/list                        查看封禁禁言 |  /名单 /列表\n"
    "/welcome                     自定义欢迎/退群消息 | /欢迎\n"
    "/reload                      热重载配置   |  /重载 /刷新\n"
    "——————————————————\n"
    "【仅 Owner 可用(私聊或群聊)】\n"
    "/roll create <群号> <人数>   创建抽奖 | /roll 创建\n"
    "/roll draw <群号>            手动开奖 | /roll 开奖\n"
    "/roll cancel <群号>          取消抽奖 | /roll 取消\n"
    "/roll add <群号> <人数>      追加名额 | /roll 追加\n"
    "/roll pick <群号> <QQ>       指定中奖 | /roll 指定\n"
    "/roll time <群号> <时间>     定时开奖 | /roll 定时\n"
    "——————————————————\n"
    "【任意成员可用】\n"
    "赞我                          给发送者点赞(每日20次)\n"
    "/joinroll                     参与本群抽奖 | /抽奖 /参与抽奖\n"
    "/joinroll list                查看抽奖参与名单\n"
    "——————————————————\n"
    "时长格式：纯数字=分钟，或 30s/10m/2h/1d/3w，0=永久"
)

CONFIG = load_config()

_save_lock = threading.Lock()

def save_config():
    """保存当前 CONFIG 到 config.json，保留用户注释字段。"""
    with _save_lock:
        original = {}
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                original = json.load(f)
        for k, v in CONFIG.items():
            original[k] = v
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(original, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CONFIG_PATH)

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
                "welcome_msgs": {}, "leave_msgs": {}, "lottery": {}, "last_active": {}}
    try:
        with open(DB_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("bans", {})
        data.setdefault("mutes", {})
        data.setdefault("whitelist", {})
        data.setdefault("whitelist_enabled", [])
        data.setdefault("welcome_msgs", {})
        data.setdefault("leave_msgs", {})
        data.setdefault("lottery", {})
        data.setdefault("last_active", {})
        return data
    except Exception as e:
        print(f"[警告] data.json 读取失败，将使用空数据库: {e}")
        return {"bans": {}, "mutes": {}, "whitelist": {}, "whitelist_enabled": [],
                "welcome_msgs": {}, "leave_msgs": {}, "lottery": {}, "last_active": {}}


def save_db():
    with _save_lock:
        tmp = DB_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(DB, f, ensure_ascii=False, indent=2)
        os.replace(tmp, DB_PATH)


DB = load_db()

# ============================================================
#  WebSocket 连接与 OneBot API 调用
# ============================================================
WS = None                 # 当前 WebSocket 连接
BOT_QQ = None             # 机器人自己的 QQ 号（启动时获取）
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
    loop = asyncio.get_running_loop()
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


def parse_draw_time(s):
    """解析开奖时间字符串，返回 Unix 时间戳；None=立即/不排期；-1=格式错误。
    支持:
        "2026-07-05 20:00"  /  "2026.7.5 15:00"  /  "2026/7/5 15:00"
        "2026-07-05"                                   默认 20:00
        "30m" / "2h" / "3d" / "1w"                    相对时长
        纯数字                                          分钟
    """
    s = str(s).strip()
    if not s:
        return None
    # 尝试绝对时间: YYYY[-./]M[-./]D [HH:MM]
    # 先统一分隔符
    m = re.fullmatch(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})(?:\s+(\d{1,2}:\d{2}))?", s)
    if m:
        try:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            time_str = m.group(4) or "20:00"
            h, mi = map(int, time_str.split(":"))
            dt = datetime(y, mo, d, h, mi)
            return dt.timestamp()
        except ValueError:
            return -1
    # 尝试相对时长（复用 parse_duration 的格式）
    dur = parse_duration(s)
    if dur is not None:
        return time.time() + dur
    return -1


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


async def cmd_inactive(event, rest):
    """查看并清理不活跃成员（仅群主/管理员/Bot Admin 可用）。"""
    group_id = event["group_id"]
    now = time.time()
    last_active = DB.setdefault("last_active", {})

    parts = rest.strip().split(None, 2)
    if not parts or not re.fullmatch(r"\d+", parts[0]):
        await send_group_text(group_id,
            "❌ 格式错误。用法:\n"
            "  /inactive <天数>                 查看N天未发言的成员\n"
            "  /inactive <天数> kick <QQ号>      踢出指定不活跃成员\n"
            "  /inactive <天数> kick all         踢出所有不活跃成员")
        return

    days = int(parts[0])
    if days < 1:
        await send_group_text(group_id, "❌ 天数必须大于0。")
        return

    threshold = now - days * 86400

    # 尝试获取群成员列表
    members = []
    try:
        members_res = await call_api("get_group_member_list", {"group_id": group_id}, timeout=10)
        if api_ok(members_res):
            data_raw = members_res.get("data") or []
            members = data_raw if isinstance(data_raw, list) else data_raw.get("members", []) if isinstance(data_raw, dict) else []
    except Exception as e:
        print(f"[inactive] 获取群成员列表失败: {e}")

    # 解析子命令
    sub_cmd = parts[1].lower() if len(parts) >= 2 else ""
    target = parts[2].strip() if len(parts) >= 3 else ""

    # === 如果 API 失败或无成员列表，直接用 last_active 本地数据 ===
    if not members:
        # 从 last_active 中提取本群成员的 key
        prefix = f"{group_id}_"
        inactive_qqs = []
        for key, last in last_active.items():
            if key.startswith(prefix):
                uid_str = key[len(prefix):]
                if re.fullmatch(r"\d+", uid_str):
                    uid = int(uid_str)
                    if uid in CONFIG["super_admins"] or uid in CONFIG.get("admins", []):
                        continue
                    if BOT_QQ and uid == int(BOT_QQ):
                        continue
                    if last < threshold:
                        inactive_qqs.append((uid, f"用户{uid}", last))
        inactive_qqs.sort(key=lambda x: x[2])

        if sub_cmd != "kick":
            if not inactive_qqs:
                await send_group_text(group_id,
                    f"⚠️ 无法获取群成员列表，但本地记录中没有超过 {days} 天未发言的成员。\n"
                    f"(已记录 {len([k for k in last_active if k.startswith(prefix)])} 名成员)")
            else:
                lines = [f"📋 超过 {days} 天未发言的成员（本地记录，共 {len(inactive_qqs)} 人）:"]
                lines.append("")
                for uid, nick, la in inactive_qqs:
                    diff_days = int((now - la) / 86400)
                    lines.append(f"  · {nick}({uid})  {diff_days}天前")
                lines.append("")
                lines.append(f"💡 /inactive {days} kick <QQ号>  踢出指定成员")
                await send_group_text(group_id, "\n".join(lines))
        else:
            await send_group_text(group_id, "⚠️ 无法获取完整群成员列表，踢人功能暂不可用。")
        return

    # === 有成员列表，走完整逻辑 ===
    inactive_qqs = []
    init_count = 0
    for m in members:
        uid = int(m.get("user_id", 0))
        if not uid or (BOT_QQ and uid == int(BOT_QQ)):
            continue
        if uid in CONFIG["super_admins"] or uid in CONFIG.get("admins", []):
            continue
        la_key = f"{group_id}_{uid}"
        last = last_active.get(la_key, 0)
        if last == 0:
            last = now
            last_active[la_key] = now
            init_count += 1
        if last < threshold:
            nick = m.get("card") or m.get("nickname") or f"用户{uid}"
            inactive_qqs.append((uid, nick, last))

    if init_count > 0:
        save_db()

    # 列表模式
    if sub_cmd != "kick":
        if not inactive_qqs:
            await send_group_text(group_id, f"✅ 没有超过 {days} 天未发言的成员。")
        else:
            inactive_qqs.sort(key=lambda x: x[2])
            lines = [f"📋 超过 {days} 天未发言的成员（共 {len(inactive_qqs)} 人）:"]
            lines.append("")
            for uid, nick, la in inactive_qqs:
                diff_days = int((now - la) / 86400)
                lines.append(f"  · {nick}({uid})  {diff_days}天前")
            lines.append("")
            lines.append(f"💡 /inactive {days} kick <QQ号>  踢出指定成员")
            lines.append(f"💡 /inactive {days} kick all      踢出全部 ({len(inactive_qqs)}人)")
            await send_group_text(group_id, "\n".join(lines))
        return

    # 踢人模式
    if not target:
        await send_group_text(group_id, "❌ 请指定要踢出的QQ号，或使用 'all' 踢出全部。")
        return

    if target.lower() in ("all", "全部", "所有"):
        if not inactive_qqs:
            await send_group_text(group_id, f"✅ 没有超过 {days} 天未发言的成员，无需踢出。")
            return
        kicked, failed = [], []
        for uid, nick, _ in inactive_qqs:
            res = await call_api("set_group_kick", {
                "group_id": group_id, "user_id": uid, "reject_add_request": False})
            if api_ok(res):
                kicked.append(f"{nick}({uid})")
            else:
                failed.append(f"{nick}({uid})")
        msg = f"✅ 已踢出 {len(kicked)} 名不活跃成员。"
        if failed:
            msg += f"\n失败: {len(failed)} 人"
        await send_group_text(group_id, msg)
        return

    # 踢出单个
    if not re.fullmatch(r"\d+", target):
        await send_group_text(group_id, "❌ QQ号格式错误。")
        return
    target_uid = int(target)
    target_info = next(((uid, nick, la) for uid, nick, la in inactive_qqs if uid == target_uid), None)
    if not target_info:
        await send_group_text(group_id, f"❌ {target} 不在不活跃名单中。")
        return
    res = await call_api("set_group_kick", {
        "group_id": group_id, "user_id": target_uid, "reject_add_request": False})
    if api_ok(res):
        await send_group_text(group_id, f"✅ 已踢出不活跃成员 {target_info[1]}({target_uid})。")
    else:
        await send_group_text(group_id, f"❌ 踢出失败: {(res or {}).get('msg', '未知错误')}")


async def cmd_say(event, rest):
    """让机器人在群里发送指定文本(仅管理员)。"""
    group_id = event["group_id"]
    text = rest.strip()
    if not text:
        await send_group_text(group_id, "❌ 内容不能为空。用法: /say <要发送的内容>")
        return
    await send_group_text(group_id, text)


async def cmd_sid(event, rest=""):
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


async def _dm_owners(text):
    """私聊通知所有 Owner（用于进群/退群等无需回复上下文的事件通知）。"""
    for owner_qq in CONFIG["super_admins"]:
        try:
            await call_api("send_private_msg", {
                "user_id": owner_qq,
                "message": [{"type": "text", "data": {"text": text}}],
            }, timeout=8)
        except Exception:
            pass


async def _notify_owner_dm(event):
    """有人私聊 bot 时，通知 Owner。"""
    owners = CONFIG.get("super_admins") or []
    if not owners:
        return
    user_id = event.get("user_id")
    sender = event.get("sender") or {}
    nick = sender.get("nickname") or str(user_id)
    preview = (event.get("raw_message") or "").strip()
    if len(preview) > 80:
        preview = preview[:80] + "…"
    text = (f"📬 {nick}（{user_id}）私聊了我：\n{preview or '（非文本消息）'}\n"
            f"— 回复可用：/reply {user_id} <内容>")
    for owner in owners:
        await call_api("send_private_msg", {
            "user_id": owner,
            "message": [{"type": "text", "data": {"text": text}}],
        }, timeout=8)


async def cmd_pending(event, rest=""):
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


# 点赞计数: {"YYYYMMDD_QQ号": 点赞次数}
_LIKE_COUNT = {}
_LIKE_MAX = 20  # 每日每人最多点赞次数
_LIKE_PER_CALL = 10  # 每次API调用点赞数
_LIKE_FAIL_AT = {}           # {user_id: 上次失败时间戳}，避免反复失败时刷 send_like 加重风控
_LIKE_FAIL_COOLDOWN = 60     # 失败后该用户 60s 内不再重试


async def cmd_like(event):
    """给发送者点赞(任意成员可用，群聊/私聊均可)。每人每日上限20赞。"""
    user_id = event.get("user_id")
    group_id = event.get("group_id")
    if group_id:
        nick = await get_nick(group_id, user_id)
    else:
        sender = event.get("sender") or {}
        nick = sender.get("nickname") or str(user_id)
    reply = _reply_to(event)

    today = time.strftime("%Y%m%d")
    cd_key = f"{today}_{user_id}"
    current = _LIKE_COUNT.get(cd_key, 0)

    ok = False
    reason = ""
    now = time.time()
    last_fail = _LIKE_FAIL_AT.get(user_id, 0)
    if current >= _LIKE_MAX:
        reason = "今日已达上限"
    elif now - last_fail < _LIKE_FAIL_COOLDOWN:
        # 刚失败过，60s 内不重复调用 send_like，避免反复失败加重风控
        reason = "刚刚点赞失败，请稍后再试（或先加我为好友再赞）"
    else:
        # 计算本次实际点赞数：不超过每次上限，也不超过今日剩余
        remaining_today = _LIKE_MAX - current
        times = min(_LIKE_PER_CALL, remaining_today)
        res = await call_api("send_like", {"user_id": user_id, "times": times}, timeout=5)
        if api_ok(res):
            _LIKE_COUNT[cd_key] = current + times
            ok = True
        else:
            # 打印 NapCat 返回的真实原因(retcode/msg)，不再笼统说"今日已满"
            rc = res.get("retcode") if isinstance(res, dict) else "?"
            rm = (res.get("msg") or res.get("wording") or "") if isinstance(res, dict) else ""
            reason = f"send_like 失败 (retcode={rc})"
            if rm:
                reason += f" {rm}"
            print(f"[点赞] {user_id} send_like 失败 retcode={rc} msg={rm!r} resp={res}")
            _LIKE_FAIL_AT[user_id] = now

    if ok:
        remaining = _LIKE_MAX - _LIKE_COUNT[cd_key]
        msg = random.choice([
            f"给 {nick} 点了 {_LIKE_PER_CALL} 个赞！今日剩余 {remaining} 赞～",
            f";-; 点了！点了！{nick} 回个赞吧～（剩{remaining}）",
        ])
    else:
        msg = (f"❌ 点赞失败：{reason}\n"
               f"常见原因：① 你不是我的好友（名片赞通常只能给好友点）"
               f" ② 账号处于风控期（点赞对风控最敏感） ③ 今日次数用尽")
    await reply(msg)


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


async def cmd_group(event, rest):
    """管理机器人生效群(私聊/群聊均可，仅Owner/Bot Admin)。
    /group              列出生效群
    /group <群号>       激活该群(加入 allowed_groups)
    /group del <群号>   关闭该群(从 allowed_groups 移除)
    注意：allowed_groups 为空时机器人对所有群生效；一旦非空，只对列表内的群生效。
    """
    reply = _reply_to(event)
    parts = rest.strip().split(None, 1)

    # /group  或  /group list  → 查看
    if not parts or parts[0].lower() in ("list", "ls", "列表"):
        groups = CONFIG.get("allowed_groups", [])
        if groups:
            await reply("📋 生效群列表 (共 {} 个):\n{}".format(
                len(groups), "\n".join(f"  · {g}" for g in groups)))
        else:
            await reply("📋 生效群：全部群（allowed_groups 为空，机器人对所有群生效）")
        return

    sub = parts[0].lower()
    # /group del <群号>  → 移除
    if sub in ("del", "remove", "rm", "删除", "移除", "off", "关闭"):
        arg = parts[1].strip() if len(parts) > 1 else ""
        gid = parse_single_qq(arg)
        if gid is None:
            await reply("❌ 用法: /group del <群号>")
            return
        groups = CONFIG.get("allowed_groups", [])
        if gid in groups:
            groups.remove(gid)
            save_config()
            await reply(f"✅ 已将群 {gid} 从生效列表移除。")
        else:
            await reply(f"ℹ️ 群 {gid} 不在生效列表中。")
        return

    # /group <群号>  → 添加/激活
    gid = parse_single_qq(parts[0])
    if gid is None:
        await reply("❌ 用法: /group <群号>  或  /group del <群号>")
        return
    groups = CONFIG.setdefault("allowed_groups", [])
    if gid in groups:
        await reply(f"ℹ️ 群 {gid} 已在生效列表中。")
    else:
        groups.append(gid)
        save_config()
        await reply(f"✅ 已激活群 {gid}，机器人现在会在该群生效。")


# ============================================================
#  事件分发
# ============================================================
async def handle_message(event):
    msg_type = event.get("message_type")
    group_id = event.get("group_id")
    user_id = event.get("user_id")

    # 忽略 bot 自己的消息（防止 self-echo 触发重复处理）
    if BOT_QQ and str(user_id) == str(BOT_QQ):
        return

    # 私聊消息：仅支持 赞我 和 /roll 抽奖管理
    if msg_type == "private":
        raw = (event.get("raw_message") or "").strip()
        if raw in ("赞我", "/赞我"):
            await cmd_like(event)
            return
        # 非 Owner 私聊 → 通知 Owner
        if not is_owner(user_id) and CONFIG.get("notify_dm", True):
            await _notify_owner_dm(event)
        if raw.startswith(CONFIG["command_prefix"]):
            body = raw[len(CONFIG["command_prefix"]):].strip()
            parts = body.split(None, 1)
            cmd = parts[0].lower() if parts else ""
            rest = parts[1].strip() if len(parts) > 1 else ""
            if cmd in ("help", "帮助", "?", "菜单"):
                reply = _reply_to(event)
                if is_owner(user_id):
                    await reply(
                        "🤖 私聊命令 (Owner/Bot Admin):\n"
                        "  /yes|no <ID>         审批加好友/加群请求\n"
                        "  /admin add|remove|list  管理 Bot Admin (仅Owner)\n"
                        "  /group <群号>        激活/管理生效群\n"
                        "  /friend              查看好友列表\n"
                        "  /delfriend <QQ>      删除好友 (仅Owner)\n"
                        "  /reply <QQ> <内容>   代发私信 (仅Owner)\n"
                        "  /name <新昵称>       改机器人昵称 (仅Owner)\n"
                        "  /leave <群号>        退出群聊 (仅Owner)\n"
                        "  /roll create|draw|cancel ...  抽奖管理\n"
                        "  /roll mcreate ...    多群联合抽奖\n"
                        "  赞我                 给你点赞 (每日20次)"
                    )
                else:
                    await reply(
                        "你好！我是机器人 🤖\n"
                        "私聊能用的：发「赞我」→ 我给你点赞（每日20次）\n"
                        "其它功能请在群里使用哦。"
                    )
                return
            # /roll —— 抽奖系统（仅Owner私聊）
            if cmd == "roll":
                if not is_owner(user_id):
                    await _reply_to(event)("⛔ 仅 Owner 可用此命令。")
                    return
                sub_parts = rest.split(None, 1)
                sub_cmd = sub_parts[0].lower() if sub_parts else ""
                sub_rest = sub_parts[1].strip() if len(sub_parts) > 1 else ""
                if sub_cmd in ("create", "创建", "新建"):
                    await cmd_roll_create(event, sub_rest)
                elif sub_cmd in ("draw", "roll", "开奖", "抽"):
                    await cmd_roll_draw(event, sub_rest)
                elif sub_cmd in ("redraw", "重抽", "补抽", "re", "rd"):
                    await cmd_roll_redraw(event, sub_rest)
                elif sub_cmd in ("add", "追加", "增加"):
                    await cmd_roll_add(event, sub_rest)
                elif sub_cmd in ("pick", "指定", "选"):
                    await cmd_roll_pick(event, sub_rest)
                elif sub_cmd in ("cancel", "取消"):
                    await cmd_roll_cancel(event, sub_rest)
                elif sub_cmd in ("time", "schedule", "定时", "时间"):
                    await cmd_roll_schedule(event, sub_rest)
                elif sub_cmd in ("mcreate", "mdraw", "mlist", "mcancel"):
                    await _route_multi_roll(event, sub_cmd, sub_rest)
                else:
                    await cmd_roll_help(event)
                return
            # 私聊其他命令路由
            if not is_owner(user_id):
                await _reply_to(event)("⛔ 仅 Owner 可用此命令。")
                return
            if cmd in ("yes", "no", "同意", "拒绝"):
                await cmd_yesno(event, cmd, rest)
            elif cmd in ("admin", "管理", "管理员"):
                await cmd_admin(event, rest)
            elif cmd in ("group", "群", "群聊", "生效群"):
                await cmd_group(event, rest)
            elif cmd in ("friend", "好友", "好友列表"):
                await cmd_friend(event)
            elif cmd in ("delfriend", "删除好友", "删好友"):
                await cmd_delfriend(event, rest)
            elif cmd in ("reply", "回复", "代发", "私信"):
                await cmd_reply(event, rest)
            elif cmd in ("name", "改名", "昵称", "重命名"):
                await cmd_name(event, rest)
            elif cmd in ("leave", "退群", "退出"):
                await cmd_leave(event, rest)
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

    # 抽奖参与: /joinroll 任意成员可用（权限闸门之前）
    if cmd in ("joinroll", "参与抽奖", "jr"):
        await cmd_joinroll(event, rest)
        return
    # /roll (无参数或help) → 显示抽奖帮助（非Owner只显示joinroll）
    if cmd == "roll" and (not rest or rest.split()[0].lower() in ("help", "帮助", "?")):
        await cmd_roll_help(event)
        return
    # /roll 子命令 → Owner/BotAdmin 在群里也能操作
    if cmd == "roll":
        if not (is_admin(event) or is_bot_admin(user_id)):
            await send_group_text(group_id, "⛔ 抽奖管理命令仅群主/管理员/Owner可用。\n群成员可发送 /joinroll 参与抽奖。")
            return
        sub_parts = rest.split(None, 1)
        sub_cmd = sub_parts[0].lower() if sub_parts else ""
        sub_rest = sub_parts[1].strip() if len(sub_parts) > 1 else ""
        if sub_cmd in ("create", "创建", "新建"):
            await cmd_roll_create(event, sub_rest)
        elif sub_cmd in ("draw", "roll", "开奖", "抽"):
            await cmd_roll_draw(event, sub_rest)
        elif sub_cmd in ("redraw", "重抽", "补抽", "re", "rd"):
            await cmd_roll_redraw(event, sub_rest)
        elif sub_cmd in ("add", "追加", "增加"):
            await cmd_roll_add(event, sub_rest)
        elif sub_cmd in ("pick", "指定", "选"):
            await cmd_roll_pick(event, sub_rest)
        elif sub_cmd in ("cancel", "取消"):
            await cmd_roll_cancel(event, sub_rest)
        elif sub_cmd in ("time", "schedule", "定时", "时间"):
            await cmd_roll_schedule(event, sub_rest)
        elif sub_cmd in ("mcreate", "mdraw", "mlist", "mcancel"):
            await _route_multi_roll(event, sub_cmd, sub_rest)
        else:
            await cmd_roll_help(event)
        return

    # 黑名单拦截
    if event.get("user_id") in CONFIG.get("banned_users", []):
        owner_qq = CONFIG["super_admins"][0] if CONFIG["super_admins"] else "未知"
        await send_group_text(
            group_id,
            f"× 你被加入黑名单了 请寻找Owner({owner_qq})解ban"
        )
        return

    # === 权限闸门：除「赞我」外，所有命令仅 群主/管理员/Owner 可用 ===
    # is_admin = QQ群主/管理员(含Owner)；is_bot_admin = Bot Admin(含Owner)
    if not (is_admin(event) or is_bot_admin(user_id)):
        await send_group_text(
            group_id,
            "⛔ 本机器人命令仅群主/管理员/Owner可用。普通成员可发送「赞我」点赞。"
        )
        return

    # help（已受上方权限闸门保护，非特权成员看不到）
    if cmd in ("help", "帮助", "?", "菜单"):
        sub = rest.strip().lower()
        if sub in ("full", "all", "详细", "全部", "完整"):
            await send_group_text(group_id, HELP_FULL)
        else:
            await send_group_text(group_id, HELP_SHORT)
        return

    # 查命令表: 别名 -> (handler, tier, deny_msg)
    entry = _GROUP_ALIASES.get(cmd)
    if entry is None:
        await send_group_text(
            group_id,
            f"🤔 未知指令 /{cmd}，该功能尚未开发。\n发送 /help 查看可用命令列表。"
        )
        return
    handler, tier, deny_msg = entry
    # 权限闸门已保证发送者是 群主/管理员/Owner/Bot Admin；
    # 此处只需对 owner / botadmin 专属命令再做一次收紧判断。
    if tier == "owner" and not is_owner(user_id):
        await send_group_text(group_id, deny_msg)
        return
    if tier == "botadmin" and not is_bot_admin(user_id):
        await send_group_text(group_id, deny_msg)
        return
    await handler(event, rest)


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
    reply = _reply_to(event)
    parts = rest.strip().split()
    sub = parts[0].lower() if parts else "list"

    if sub in ("add", "添加", "加入", "+"):
        targets = []
        for p in parts[1:]:
            p = p.strip()
            if re.fullmatch(r"\d+", p):
                targets.append(int(p))
        if not targets:
            await reply("❌ 格式错误。用法: /admin add <QQ号> [QQ号...]")
            return
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
        await reply("\n".join(msgs) if msgs else "ℹ️ 没有需要添加的用户。")

    elif sub in ("remove", "del", "delete", "移除", "删除", "-"):
        targets = []
        for p in parts[1:]:
            p = p.strip()
            if re.fullmatch(r"\d+", p):
                targets.append(int(p))
        if not targets:
            await reply("❌ 格式错误。用法: /admin remove <QQ号> [QQ号...]")
            return
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
        await reply("\n".join(msgs) if msgs else "ℹ️ 没有需要移除的用户。")

    else:  # list / 查看
        admins = CONFIG.get("admins", [])
        if admins:
            await reply(f"📋 Bot Admin 列表 (共 {len(admins)} 人):\n" + "\n".join(f"  · {u}" for u in admins))
        else:
            await reply("📋 Bot Admin 列表: (空)\n💡 用法: /admin add <QQ号> 添加 Admin")


# ============================================================
#  私聊命令: /yes /no /friend /delfriend /reply /name /leave
# ============================================================

async def cmd_yesno(event, cmd, rest):
    """Owner 私聊: /yes <ID> 或 /no <ID> — 审批加好友/加群请求"""
    reply = _reply_to(event)
    parts = rest.strip().split()
    if not parts or not re.fullmatch(r"\d+", parts[0]):
        await reply(f"❌ 格式: /{cmd} <请求ID>")
        return
    approve = cmd in ("yes", "同意")
    await cmd_approve(event, rest, approve=approve)


async def cmd_friend(event):
    """Owner 私聊: /friend — 查看好友列表"""
    reply = _reply_to(event)
    try:
        friends = await call_api("get_friend_list")
        if not friends:
            await reply("📋 好友列表: (空)")
            return
        lines = [f"📋 好友列表 (共 {len(friends)} 人):"]
        for f in friends[:50]:
            lines.append(f"  · {f.get('nickname','?')}({f.get('user_id','?')})")
        await reply("\n".join(lines))
    except Exception as e:
        await reply(f"❌ 获取失败: {e}")


async def cmd_delfriend(event, rest):
    """Owner 私聊: /delfriend <QQ> — 删除好友"""
    reply = _reply_to(event)
    parts = rest.strip().split()
    if not parts or not re.fullmatch(r"\d+", parts[0]):
        await reply("❌ 格式: /delfriend <QQ号>")
        return
    qq = int(parts[0])
    try:
        await call_api("delete_friend", {"user_id": qq})
        await reply(f"✅ 已删除好友 {qq}")
    except Exception as e:
        await reply(f"❌ 删除失败: {e}")


async def cmd_reply(event, rest):
    """Owner 私聊: /reply <QQ> <内容> — 代机器人发私信"""
    reply = _reply_to(event)
    parts = rest.strip().split(None, 1)
    if len(parts) < 2 or not re.fullmatch(r"\d+", parts[0]):
        await reply("❌ 格式: /reply <QQ号> <消息内容>")
        return
    target_qq = int(parts[0])
    msg = parts[1]
    try:
        await call_api("send_private_msg", {"user_id": target_qq, "message": msg})
        await reply(f"✅ 已向 {target_qq} 发送私信。")
    except Exception as e:
        await reply(f"❌ 发送失败: {e}")


async def cmd_name(event, rest):
    """Owner 私聊: /name <新昵称> — 改机器人昵称"""
    reply = _reply_to(event)
    new_name = rest.strip()
    if not new_name:
        await reply("❌ 格式: /name <新昵称>")
        return
    try:
        await call_api("set_qq_profile", {"nickname": new_name})
        await reply(f"✅ 昵称已改为: {new_name}")
    except Exception as e:
        await reply(f"❌ 改名失败: {e}")


async def cmd_leave(event, rest):
    """Owner 私聊: /leave <群号> — 退出群聊"""
    reply = _reply_to(event)
    parts = rest.strip().split()
    if not parts or not re.fullmatch(r"\d+", parts[0]):
        await reply("❌ 格式: /leave <群号>")
        return
    gid = int(parts[0])
    try:
        await call_api("set_group_leave", {"group_id": gid})
        await reply(f"✅ 已退出群 {gid}")
    except Exception as e:
        await reply(f"❌ 退群失败: {e}")


# ============================================================
#  群命令注册表
# ============================================================
# 统一签名: async def handler(event, rest) -> None
async def _approve_yes(event, rest):
    """同意请求(供命令表调用)。"""
    await cmd_approve(event, rest, approve=True)


async def _approve_no(event, rest):
    """拒绝请求(供命令表调用)。"""
    await cmd_approve(event, rest, approve=False)


async def _cmd_blacklist(event, rest):
    """查看黑名单(供命令表调用)。"""
    group_id = event["group_id"]
    banned = CONFIG.get("banned_users", [])
    if banned:
        await send_group_text(
            group_id,
            f"📋 黑名单 ({len(banned)} 人):\n" + "\n".join(f"  · {u}" for u in banned),
        )
    else:
        await send_group_text(group_id, "📋 黑名单: (空)")


# 群命令: (别名..., 处理函数, 权限等级, 拒绝提示)
# 权限等级:
#   None        → 任意通过权限闸门者(群主/管理员/Owner/Bot Admin)
#   "botadmin"  → 仅 Owner / Bot Admin
#   "owner"     → 仅 Owner
# 注: handle_message 的权限闸门已保证到达此处的是特权成员，故 tier=None
#     的命令无需再做判断（原先每条命令里重复的
#     `if not admin and not is_bot_admin` 因闸门存在属不可达死代码，已移除）。
# ============================================================
#  抽奖 /roll 命令
# ============================================================
# 数据结构: DB["lottery"] = {
#     "<group_id>": {
#         "num_winners": 3,
#         "participants": {qq: nick},
#         "winners": [qq, ...],           # 已中奖者
#         "active": True,
#         "created_by": owner_qq,
#         "created_at": timestamp,
#     }
# }

async def cmd_roll_create(event, rest):
    """Owner 私聊: /roll create <群号> <中奖人数> [开奖时间]
    在指定群创建抽奖，可选定时开奖。

    时间格式:
        2026-07-05 20:00  → 指定日期时间
        3d / 2h / 30m     → 几天/小时/分钟后
        不填              → 手动开奖
    """
    reply = _reply_to(event)
    user_id = event.get("user_id")

    if not is_owner(user_id):
        await reply("⛔ 仅 Owner 可用此命令。")
        return

    parts = rest.strip().split()
    if len(parts) < 2:
        await reply(
            "❌ 格式: /roll create <群号> <中奖人数> [开奖时间]\n"
            "例如: /roll create 1097874048 3\n"
            "      /roll create 1097874048 3 3d\n"
            "      /roll create 1097874048 3 2026-07-05 20:00"
        )
        return

    gid_str = parts[0]
    if not re.fullmatch(r"\d+", gid_str):
        await reply("❌ 群号必须是纯数字。")
        return
    group_id = int(gid_str)

    if not re.fullmatch(r"\d+", parts[1]):
        await reply("❌ 中奖人数必须是数字。")
        return
    num_winners = int(parts[1])
    if num_winners < 1 or num_winners > 100:
        await reply("❌ 中奖人数必须在 1-100 范围内。")
        return

    # 解析可选的开奖时间
    draw_at = None
    time_str = " ".join(parts[2:]) if len(parts) > 2 else ""
    if time_str:
        draw_at = parse_draw_time(time_str)
        if draw_at == -1:
            await reply(
                "❌ 时间格式错误。支持:\n"
                "  2026-07-05 20:00  绝对时间\n"
                "  3d / 2h / 30m      相对时长\n"
                "  不填               手动开奖"
            )
            return
        if draw_at is not None and draw_at <= time.time():
            await reply("❌ 开奖时间必须在未来。")
            return

    gid = str(group_id)
    DB.setdefault("lottery", {})[gid] = {
        "num_winners": num_winners,
        "participants": {},
        "winners": [],
        "active": True,
        "created_by": user_id,
        "created_at": time.time(),
        "draw_at": draw_at,          # None=手动开奖, timestamp=定时开奖
        "auto_drawn": False,         # 标记是否已自动开奖
    }
    save_db()

    # 公告群内
    announce = (
        "🎉 抽奖已开启！\n"
        f"中奖名额: {num_winners} 人\n"
    )
    if draw_at:
        dt_str = datetime.fromtimestamp(draw_at).strftime("%Y-%m-%d %H:%M")
        announce += f"⏰ 定时开奖: {dt_str}\n"
    announce += (
        "参与方式: 在群里发送 /joinroll\n"
        f"发起人: Owner({user_id})"
    )
    await send_group_text(group_id, announce)

    # 回复 Owner
    reply_msg = (
        f"✅ 已在群 {group_id} 创建抽奖！\n"
        f"中奖人数: {num_winners}\n"
    )
    if draw_at:
        dt_str = datetime.fromtimestamp(draw_at).strftime("%Y-%m-%d %H:%M")
        reply_msg += f"⏰ 定时开奖: {dt_str}\n"
    reply_msg += (
        "群成员发送 /joinroll 即可参与。\n"
        "命令: /roll draw <群号> (手动开奖)\n"
        "      /roll cancel <群号> (取消)"
    )
    await reply(reply_msg)


async def cmd_roll_cancel(event, rest):
    """Owner 私聊: /roll cancel <群号> 取消抽奖。"""
    reply = _reply_to(event)
    user_id = event.get("user_id")

    if not is_owner(user_id):
        await reply("⛔ 仅 Owner 可用此命令。")
        return

    parts = rest.strip().split()
    if not parts or not re.fullmatch(r"\d+", parts[0]):
        await reply("❌ 格式: /roll cancel <群号>")
        return

    gid = parts[0]
    lottery = DB.get("lottery", {}).get(gid)
    if not lottery:
        await reply(f"ℹ️ 群 {gid} 没有进行中的抽奖。")
        return

    # 检查是否属于某个活跃的多群联合抽奖
    for lid, md in DB.get("multi_lottery", {}).items():
        if md.get("active") and gid in md.get("groups", []):
            await reply(f"⚠️ 群 {gid} 正在参与联合抽奖「{lid}」，请先 /roll mcancel {lid} 取消联合抽奖。")
            return

    group_id = int(gid)
    cnt = len(lottery.get("participants", {}))
    del DB["lottery"][gid]
    save_db()

    await send_group_text(group_id, "🚫 抽奖已被 Owner 取消。")
    await reply(f"✅ 已取消群 {gid} 的抽奖（参与人数: {cnt}）。")


async def cmd_roll_schedule(event, rest):
    """Owner 私聊: /roll time <群号> <时间> — 给已有抽奖设置/修改定时开奖。
    /roll time <群号> off — 取消定时。
    """
    reply = _reply_to(event)
    user_id = event.get("user_id")

    if not is_owner(user_id):
        await reply("⛔ 仅 Owner 可用此命令。")
        return

    parts = rest.strip().split()
    if len(parts) < 2:
        await reply(
            "❌ 格式: /roll time <群号> <时间>\n"
            "例如: /roll time 1097874048 3d\n"
            "      /roll time 1097874048 2026-07-05 20:00\n"
            "      /roll time 1097874048 off   → 取消定时"
        )
        return

    gid = parts[0]
    if not re.fullmatch(r"\d+", gid):
        await reply("❌ 群号必须是纯数字。")
        return

    lottery = DB.get("lottery", {}).get(gid)
    if not lottery or not lottery.get("active"):
        await reply(f"ℹ️ 群 {gid} 没有进行中的抽奖。")
        return

    # 取消定时
    time_str = " ".join(parts[1:])
    if time_str.strip().lower() in ("off", "none", "取消", "关闭", "clear", "remove"):
        lottery["draw_at"] = None
        lottery["auto_drawn"] = False
        save_db()
        await reply(f"✅ 已取消群 {gid} 的定时开奖，改为手动开奖。")
        await send_group_text(
            int(gid),
            "ℹ️ 抽奖定时已取消，改为手动开奖。"
        )
        return

    # 设置/修改定时
    draw_at = parse_draw_time(time_str)
    if draw_at == -1:
        await reply(
            "❌ 时间格式错误。支持:\n"
            "  2026-07-05 20:00  绝对时间\n"
            "  3d / 2h / 30m      相对时长\n"
            "  off                取消定时"
        )
        return
    if draw_at is not None and draw_at <= time.time():
        await reply("❌ 开奖时间必须在未来。")
        return

    lottery["draw_at"] = draw_at
    lottery["auto_drawn"] = False  # 重置，允许新的定时触发
    save_db()

    dt_str = datetime.fromtimestamp(draw_at).strftime("%Y-%m-%d %H:%M")
    await reply(f"✅ 群 {gid} 的抽奖已设置定时开奖: {dt_str}")
    await send_group_text(
        int(gid),
        f"⏰ 抽奖定时开奖已设置为: {dt_str}\n"
        "发送 /joinroll 参与！"
    )


async def cmd_joinroll(event, rest):
    """群聊: /joinroll — 参与当前群的抽奖。
    /joinroll list — 查看参与名单。"""
    group_id = event["group_id"]
    user_id = event.get("user_id")
    gid = str(group_id)

    lottery = DB.get("lottery", {}).get(gid)
    if not lottery or not lottery.get("active"):
        await send_group_text(group_id, "ℹ️ 本群当前没有进行中的抽奖。")
        return

    participants = lottery.setdefault("participants", {})
    winners = lottery.setdefault("winners", [])

    # /joinroll list → 查看名单
    if rest.strip().lower() in ("list", "名单", "查看", "ls"):
        total = len(participants)
        slots = lottery["num_winners"]
        # 检查是否属于多群联合抽奖，使用真实名额
        multi_name = ""
        for lid, md in DB.get("multi_lottery", {}).items():
            if md.get("active") and gid in md.get("groups", []):
                slots = md["num_winners"]
                multi_name = f" [联合抽奖: {lid}]"
                break
        won = len(winners)
        # 定时开奖信息
        draw_at = lottery.get("draw_at")
        time_note = ""
        if draw_at and not lottery.get("auto_drawn"):
            dt_str = datetime.fromtimestamp(draw_at).strftime("%m-%d %H:%M")
            time_note = f"⏰ 定时开奖: {dt_str}\n"

        if total == 0:
            await send_group_text(
                group_id,
                f"📋 当前抽奖{multi_name}（{slots} 个中奖名额，已开 {won} 个）: 暂无人参与。\n"
                f"{time_note}发送 /joinroll 即可加入！"
            )
        else:
            names = []
            for qq, nick in participants.items():
                tag = " 🏆" if qq in winners else ""
                names.append(f"  · {nick}({qq}){tag}")
            await send_group_text(
                group_id,
                f"📋 抽奖名单{multi_name}（{slots} 个名额，已开 {won} 人，共 {total} 人参与）:\n" +
                time_note +
                "\n".join(names) +
                "\n\n发送 /joinroll 加入！"
            )
        return

    # 默认行为: 加入抽奖
    uid_key = str(user_id)

    # 已经中奖了
    if uid_key in winners:
        await send_group_text(
            group_id,
            f"🎉 你已经中奖了！快去兑奖吧～ 当前共 {len(participants)} 人参与。"
        )
        return

    # 已经参与
    if uid_key in participants:
        await send_group_text(
            group_id,
            f"ℹ️ 你已经参与过了！当前共 {len(participants)} 人参与。查看名单: /joinroll list"
        )
        return

    nick = await get_nick(group_id, user_id)
    participants[uid_key] = nick
    save_db()

    await send_group_text(
        group_id,
        f"✅ {nick}({user_id}) 已加入抽奖！\n"
        f"当前参与人数: {len(participants)}"
    )


async def cmd_roll_draw(event, rest):
    """Owner 私聊: /roll draw <群号> — 随机抽取中奖者并在群里公布。
    支持多次调用（补抽），自动排除已中奖者。"""
    reply = _reply_to(event)
    user_id = event.get("user_id")

    if not is_owner(user_id):
        await reply("⛔ 仅 Owner 可用此命令。")
        return

    parts = rest.strip().split()
    if not parts or not re.fullmatch(r"\d+", parts[0]):
        await reply("❌ 格式: /roll draw <群号>\n(首次抽满名额；之后每次补抽1人)")
        return

    gid = parts[0]
    lottery = DB.get("lottery", {}).get(gid)
    if not lottery or not lottery.get("active"):
        await reply(f"ℹ️ 群 {gid} 没有进行中的抽奖。")
        return

    group_id = int(gid)
    participants = lottery.get("participants", {})
    winners = lottery.setdefault("winners", [])

    if not participants:
        await reply(f"群 {gid} 的抽奖没有任何人参与，无法抽奖。")
        return

    # 计算剩余可抽人数
    remaining = [q for q in participants if q not in winners]
    if not remaining:
        await reply(f"群 {gid} 的所有参与者都已经中奖了！")
        return

    num_winners = lottery["num_winners"]
    slots_left = num_winners - len(winners)

    # 首次抽奖: 抽满名额；补抽: 每次抽1人
    if slots_left <= 0:
        # 名额已满但还有剩余参与者 - 补抽模式，每次1人
        draw_count = 1
    else:
        draw_count = min(slots_left, len(remaining))

    random.shuffle(remaining)
    new_winners = remaining[:draw_count]

    # 标记已开奖（防止定时开奖重复触发）
    lottery["auto_drawn"] = True

    # 生成中奖名单
    winner_lines = []
    for w in new_winners:
        nick = participants[w]
        winner_lines.append(f"🏆 {nick}({w})")
        winners.append(w)

    owner_nick = await get_nick(group_id, lottery["created_by"])

    if slots_left <= 0 and draw_count == 1:
        # 补抽
        await send_group_text(
            group_id,
            "🔄 **补抽！**\n\n" +
            "\n".join(winner_lines) +
            f"\n\n恭喜 {participants[new_winners[0]]}({new_winners[0]}) 递补中奖！\n"
            f"请找 Owner({owner_nick}) 兑奖 🎁"
        )
    else:
        # 正常开奖
        await send_group_text(
            group_id,
            "🎉 **开奖了！**\n\n" +
            "\n".join(winner_lines) +
            f"\n\n恭喜以上 {draw_count} 位中奖者！\n"
            f"请找 Owner({owner_nick}) 兑奖 🎁"
        )

    # 通知 Owner
    all_won = sum(1 for w in winners if w in participants)
    await reply(
        f"✅ 群 {gid} 抽奖结果:\n"
        f"本次中奖:\n" + "\n".join(f"  🏆 {participants[w]}({w})" for w in new_winners) +
        f"\n\n累计中奖: {all_won}/{num_winners}（参与 {len(participants)} 人）"
    )

    # 全部名额抽完 → 关闭
    if len(winners) >= num_winners and len(winners) >= len([p for p in participants if p not in winners]):
        pass  # 不自动关闭，Owner 可继续补抽

    save_db()


async def cmd_roll_redraw(event, rest):
    """Owner 私聊: /roll redraw <群号> — 重新抽一个人（排除已中奖者）。"""
    await cmd_roll_draw(event, rest)


async def cmd_roll_add(event, rest):
    """Owner 私聊: /roll add <群号> <追加人数> — 追加中奖名额。"""
    reply = _reply_to(event)
    user_id = event.get("user_id")

    if not is_owner(user_id):
        await reply("⛔ 仅 Owner 可用此命令。")
        return

    parts = rest.strip().split()
    if len(parts) < 2:
        await reply("❌ 格式: /roll add <群号> <追加人数>\n例如: /roll add 1097874048 2")
        return

    gid_str = parts[0]
    if not re.fullmatch(r"\d+", gid_str):
        await reply("❌ 群号必须是纯数字。")
        return

    if not re.fullmatch(r"\d+", parts[1]):
        await reply("❌ 追加人数必须是数字。")
        return
    add_count = int(parts[1])
    if add_count < 1 or add_count > 100:
        await reply("❌ 追加人数必须在 1-100 范围内。")
        return

    gid = gid_str
    lottery = DB.get("lottery", {}).get(gid)
    if not lottery or not lottery.get("active"):
        await reply(f"ℹ️ 群 {gid} 没有进行中的抽奖。")
        return

    old_num = lottery["num_winners"]
    lottery["num_winners"] = old_num + add_count
    save_db()

    group_id = int(gid)
    await send_group_text(
        group_id,
        f"📢 抽奖名额追加！\n"
        f"原名额: {old_num} → 现名额: {lottery['num_winners']}\n"
        f"(新增 {add_count} 个中奖名额，已参与者无需重新加入)"
    )

    await reply(
        f"✅ 已为群 {gid} 追加 {add_count} 个名额。\n"
        f"总名额: {old_num} → {lottery['num_winners']}"
    )


async def cmd_roll_pick(event, rest):
    """Owner 私聊: /roll pick <群号> <QQ号> — 指定某人中奖，自动补抽剩余名额。"""
    reply = _reply_to(event)
    user_id = event.get("user_id")

    if not is_owner(user_id):
        await reply("⛔ 仅 Owner 可用此命令。")
        return

    parts = rest.strip().split()
    if len(parts) < 2:
        await reply("❌ 格式: /roll pick <群号> <QQ号>\n例如: /roll pick 1097874048 123456789")
        return

    if not re.fullmatch(r"\d+", parts[0]) or not re.fullmatch(r"\d+", parts[1]):
        await reply("❌ 群号和QQ号必须是纯数字。")
        return

    gid = parts[0]
    target_qq = parts[1]

    lottery = DB.get("lottery", {}).get(gid)
    if not lottery or not lottery.get("active"):
        await reply(f"ℹ️ 群 {gid} 没有进行中的抽奖。")
        return

    group_id = int(gid)
    participants = lottery.get("participants", {})
    winners = lottery.setdefault("winners", [])

    # 是否在参与名单中
    if target_qq not in participants:
        await reply(f"❌ QQ {target_qq} 没有参与抽奖，无法指定中奖。")
        return

    # 是否已经中过
    if target_qq in winners:
        await reply(f"ℹ️ {participants[target_qq]}({target_qq}) 已经中过奖了。")
        return

    # 指定中奖
    winners.append(target_qq)
    pick_nick = participants[target_qq]

    num_winners = lottery["num_winners"]
    slots_left = num_winners - len(winners)

    # 自动补抽剩余名额
    remaining = [q for q in participants if q not in winners]
    auto_winners = []
    if slots_left > 0 and remaining:
        random.shuffle(remaining)
        draw_count = min(slots_left, len(remaining))
        auto_winners = remaining[:draw_count]
        for w in auto_winners:
            winners.append(w)

    owner_nick = await get_nick(group_id, lottery["created_by"])

    # 生成中奖名单（不区分指定/随机）
    winner_lines = []
    winner_lines.append(f"🏆 {pick_nick}({target_qq})")
    for w in auto_winners:
        nick = participants[w]
        winner_lines.append(f"🏆 {nick}({w})")

    total_won = len(winners)

    await send_group_text(
        group_id,
        f"🎉 **中奖了！**\n\n" +
        "\n".join(winner_lines) +
        f"\n\n恭喜以上 {len(winner_lines)} 位中奖者！\n"
        f"请找 Owner({owner_nick}) 兑奖 🎁"
    )

    # 标记已开奖（防止定时开奖重复触发）
    lottery["auto_drawn"] = True
    save_db()

    await reply(
        f"✅ 已指定 {pick_nick}({target_qq}) 中奖"
        + (f"，自动补抽 {len(auto_winners)} 人" if auto_winners else "")
        + f"。\n累计中奖: {total_won}/{num_winners}"
    )


# ============================================================
#  多群联合抽奖 /roll mcreate / mdraw / mlist / mcancel
#  数据结构: DB["multi_lottery"] = {
#      "<lottery_id>": {
#          "groups": ["123", "456"],
#          "num_winners": 3,
#          "winners": [],
#          "active": True,
#          "created_by": owner_qq,
#          "created_at": timestamp,
#      }
#  }
#  每个群仍用 DB["lottery"][group_id] 存储参与者，/joinroll 不变。
#  开奖时从所有关联群收集参与者，去重后抽取。
# ============================================================

def _get_multi_pool(lottery_id):
    """收集多群抽奖的全部参与者（跨群去重）"""
    mdata = DB.get("multi_lottery", {}).get(lottery_id)
    if not mdata:
        return None, {}
    all_parts = {}
    for gid in mdata["groups"]:
        group_lot = DB.get("lottery", {}).get(gid, {})
        for qq, nick in group_lot.get("participants", {}).items():
            if qq not in all_parts:  # 去重：同一 QQ 只算一次
                all_parts[qq] = nick
    return mdata, all_parts


async def _route_multi_roll(event, sub_cmd, rest):
    """路由多群联合抽奖子命令"""
    if sub_cmd == "mcreate":
        await cmd_roll_mcreate(event, rest)
    elif sub_cmd == "mdraw":
        await cmd_roll_mdraw(event, rest)
    elif sub_cmd == "mlist":
        await cmd_roll_mlist(event, rest)
    elif sub_cmd == "mcancel":
        await cmd_roll_mcancel(event, rest)


async def cmd_roll_mcreate(event, rest):
    """Owner 私聊: /roll mcreate <抽奖ID> <人数> <群号1> <群号2> ...
    创建跨群联合抽奖，每个群的参与者合在一起抽。"""
    reply = _reply_to(event)
    user_id = event.get("user_id")
    if not is_owner(user_id):
        await reply("⛔ 仅 Owner 可用此命令。")
        return

    parts = rest.strip().split()
    if len(parts) < 4:
        await reply(
            "❌ 格式: /roll mcreate <抽奖ID> <中奖人数> <群号1> <群号2> ...\n"
            "例如: /roll mcreate 新年抽奖 3 123456 789012 345678"
        )
        return

    lottery_id = parts[0]
    if not re.fullmatch(r"\d+", parts[1]):
        await reply("❌ 中奖人数必须是数字。")
        return
    num_winners = int(parts[1])
    if num_winners < 1 or num_winners > 100:
        await reply("❌ 中奖人数必须在 1-100 范围内。")
        return

    groups = []
    for g in parts[2:]:
        if not re.fullmatch(r"\d+", g):
            await reply(f"❌ 群号 '{g}' 必须是纯数字。")
            return
        groups.append(g)

    if len(groups) < 2:
        await reply("❌ 至少需要 2 个群号。单群请用 /roll create。")
        return

    # 检查群是否已在其他联合抽奖中
    existing_multi = DB.setdefault("multi_lottery", {})
    for lid, md in existing_multi.items():
        if md.get("active"):
            overlap = set(groups) & set(md["groups"])
            if overlap:
                await reply(f"❌ 群 {overlap} 已在联合抽奖 '{lid}' 中。")
                return

    # 确保每个群都有独立的 lottery 条目存储参与者
    lotteries = DB.setdefault("lottery", {})
    for gid in groups:
        lotteries.setdefault(gid, {
            "num_winners": 0, "participants": {}, "winners": [],
            "active": True, "created_by": user_id, "created_at": time.time(),
            "draw_at": None, "auto_drawn": False,
        })

    existing_multi[lottery_id] = {
        "groups": groups,
        "num_winners": num_winners,
        "winners": [],
        "active": True,
        "created_by": user_id,
        "created_at": time.time(),
    }
    save_db()

    # 公告每个群
    for gid in groups:
        try:
            await send_group_text(int(gid),
                f"🎉 跨群联合抽奖「{lottery_id}」已开启！\n"
                f"联合群: {', '.join(groups)}\n"
                f"中奖名额: {num_winners} 人\n"
                f"参与方式: 在本群发送 /joinroll\n"
                "跨群参与自动去重，同一 QQ 只算一次！"
            )
        except Exception:
            pass

    await reply(
        f"✅ 联合抽奖「{lottery_id}」已创建！\n"
        f"参与群: {', '.join(groups)}\n"
        f"中奖人数: {num_winners} 人\n\n"
        f"命令: /roll mdraw {lottery_id}  (开奖)\n"
        f"      /roll mlist              (列表)\n"
        f"      /roll mcancel {lottery_id} (取消)"
    )


async def cmd_roll_mdraw(event, rest):
    """Owner 私聊: /roll mdraw <抽奖ID> — 联合抽奖开奖"""
    reply = _reply_to(event)
    user_id = event.get("user_id")
    if not is_owner(user_id):
        await reply("⛔ 仅 Owner 可用此命令。")
        return

    parts = rest.strip().split()
    if not parts:
        await reply("❌ 格式: /roll mdraw <抽奖ID>")
        return

    lottery_id = parts[0]
    mdata, all_parts = _get_multi_pool(lottery_id)
    if mdata is None:
        await reply(f"ℹ️ 联合抽奖「{lottery_id}」不存在。")
        return
    if not mdata["active"]:
        await reply(f"ℹ️ 联合抽奖「{lottery_id}」已结束。")
        return
    if not all_parts:
        await reply(f"联合抽奖「{lottery_id}」没有任何人参与，无法开奖。")
        return

    num_winners = mdata["num_winners"]
    winners = mdata.setdefault("winners", [])
    remaining = [q for q in all_parts if q not in winners]
    if not remaining:
        await reply("所有参与者都已中奖。")
        return

    draw_count = min(num_winners - len(winners), len(remaining))
    if draw_count <= 0:
        draw_count = 1  # 补抽模式

    random.shuffle(remaining)
    new_wins = remaining[:draw_count]

    # 生成结果
    lines = []
    for w in new_wins:
        lines.append(f"🏆 {all_parts[w]}({w})")
        winners.append(w)

    # 公告每个群
    announce = (
        f"🎉 跨群联合抽奖「{lottery_id}」开奖！\n\n"
        + "\n".join(lines) +
        f"\n\n恭喜以上 {len(new_wins)} 位中奖者！\n"
        f"(参与 {len(all_parts)} 人，来自 {len(mdata['groups'])} 个群)"
    )
    for gid in mdata["groups"]:
        try:
            await send_group_text(int(gid), announce)
        except:
            pass

    total_won = len(winners)
    await reply(
        f"✅ 联合抽奖「{lottery_id}」开奖完成！\n"
        f"中奖者:\n" + "\n".join(f"  {all_parts[w]}({w})" for w in new_wins) +
        f"\n\n累计中奖: {total_won}/{num_winners}"
    )

    if total_won >= num_winners:
        mdata["active"] = False
        await reply("🎊 所有名额已抽完，抽奖关闭。")

    save_db()


async def cmd_roll_mlist(event, rest=None):
    """Owner 私聊: /roll mlist — 列出所有联合抽奖"""
    reply = _reply_to(event)
    user_id = event.get("user_id")
    if not is_owner(user_id):
        await reply("⛔ 仅 Owner 可用此命令。")
        return

    multi = DB.get("multi_lottery", {})
    if not multi:
        await reply("ℹ️ 目前没有联合抽奖。")
        return

    lines = ["📋 联合抽奖列表:"]
    for lid, md in multi.items():
        _, pool = _get_multi_pool(lid)
        status = "进行中" if md["active"] else "已结束"
        lines.append(
            f"  [{status}] {lid}: "
            f"{len(md['groups'])}群, "
            f"{len(pool)}人参与, "
            f"{len(md.get('winners',[]))}/{md['num_winners']}已中"
        )
    await reply("\n".join(lines))


async def cmd_roll_mcancel(event, rest):
    """Owner 私聊: /roll mcancel <抽奖ID> — 取消联合抽奖"""
    reply = _reply_to(event)
    user_id = event.get("user_id")
    if not is_owner(user_id):
        await reply("⛔ 仅 Owner 可用此命令。")
        return

    parts = rest.strip().split()
    if not parts:
        await reply("❌ 格式: /roll mcancel <抽奖ID>")
        return

    lottery_id = parts[0]
    mdata = DB.get("multi_lottery", {}).get(lottery_id)
    if not mdata:
        await reply(f"ℹ️ 联合抽奖「{lottery_id}」不存在。")
        return

    mdata["active"] = False
    _, pool = _get_multi_pool(lottery_id)

    # 同时停用关联群的独立抽奖条目,防止继续参与
    for gid in mdata["groups"]:
        glot = DB.get("lottery", {}).get(gid)
        if glot:
            glot["active"] = False
    save_db()

    for gid in mdata["groups"]:
        try:
            await send_group_text(int(gid), f"🚫 联合抽奖「{lottery_id}」已被取消。(参与 {len(pool)} 人)")
        except Exception:
            pass

    await reply(f"✅ 联合抽奖「{lottery_id}」已取消。")


async def cmd_roll_help(event, rest=None):
    """私聊或群聊: /roll — 显示抽奖帮助。"""
    reply = _reply_to(event)
    user_id = event.get("user_id")
    msg_type = event.get("message_type", "")

    if is_owner(user_id):
        if msg_type == "group":
            await reply(
                "🎲 抽奖管理命令请私聊机器人使用。\n\n"
                "群成员命令:\n"
                "  /joinroll          参与本群抽奖\n"
                "  /joinroll list     查看当前参与名单"
            )
        else:
            await reply(
                "🎰 **抽奖系统 /roll (Owner 私聊命令):**\n"
                "  /roll create <群号> <人数> [时间]  创建抽奖\n"
                "      时间可选: 3d/2h/30m 或 2026-07-05 20:00\n"
                "  /roll add <群号> <人数>     追加名额(不覆盖)\n"
                "  /roll pick <群号> <QQ>      指定某人中奖\n"
                "  /roll draw <群号>           手动开奖(首次抽满)\n"
                "  /roll time <群号> <时间>    设置/修改定时开奖\n"
                "  /roll redraw <群号>         补抽1人(排除已中奖)\n"
                "  /roll cancel <群号>         取消抽奖\n\n"
                "**多群联合抽奖:**\n"
                "  /roll mcreate <ID> <人数> <群1> <群2> ...\n"
                "  /roll mdraw <ID>            开奖\n"
                "  /roll mlist                 列出联合抽奖\n"
                "  /roll mcancel <ID>          取消联合抽奖\n\n"
                "**群成员命令:**\n"
                "  /joinroll                   参与抽奖\n"
                "  /joinroll list              查看参与名单"
            )
    else:
        await reply(
            "🎰 **抽奖系统:**\n"
            "  /joinroll          参与本群抽奖\n"
            "  /joinroll list     查看当前参与名单"
        )


_GROUP_COMMAND_TABLE = (
    # 核心管理
    (("mute",   "禁言"),                        cmd_mute,   None, None),
    (("unmute", "解禁", "解除禁言"),              cmd_unmute, None, None),
    (("ban",    "封禁", "封", "kick", "踢", "踢出"),  cmd_ban,    None, None),
    (("unban",  "解封", "解封禁"),                 cmd_unban,  None, None),
    (("list",   "名单", "列表", "管理名单"),         cmd_list,   None, None),
    # 群维护
    (("welcome", "欢迎", "欢迎消息", "退群消息"),      cmd_welcome, None, None),
    (("reload",  "刷新", "重载", "重载配置"),         cmd_reload,  None, None),
    (("inactive", "不活跃", "清理不活跃"),             cmd_inactive, "botadmin", "仅 Bot Admin/Owner 可用此命令。"),
    (("say",    "说", "复读"),                     cmd_say,    None, None),
    (("black",  "拉黑"),                          cmd_black,   "owner", "仅 Owner 可用此命令。"),
    (("unblack", "取消拉黑", "解除拉黑"),               cmd_unblack, "owner", "仅 Owner 可用此命令。"),
    (("blacklist", "黑名单", "查看黑名单"),             _cmd_blacklist, None, None),
    # 抽奖
    (("joinroll", "参与抽奖", "抽奖", "jr", "加入抽奖"), cmd_joinroll, None, None),
)

# 展开为 {别名: (handler, tier, deny_msg)} 查找表
_GROUP_ALIASES = {
    alias: (handler, tier, deny)
    for aliases, handler, tier, deny in _GROUP_COMMAND_TABLE
    for alias in aliases
}


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

    # ---- 通话邀请（语音/视频）----
    # ⚠️ NapCat / OneBot 11 不上报通话邀请事件，也没有拒绝/挂断通话的 API
    #    (见 NapCat issue #245，仍是未实现的 feature request)。
    #    因此无法自动拒绝电话邀请。曾经这里调用的 reject_call / hang_up /
    #    set_call_request 等都是不存在的 API，已移除以免误导。
    # 通话走的是 QQNT 独立的实时通道，不在本事件流里。

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

        # 机器人自己被邀入群 → 检查是否Owner邀请，不是则自动退群
        if (BOT_QQ and user_id == BOT_QQ and
            CONFIG.get("reject_non_owner_invites", True)):
            operator = event.get("operator_id")
            if operator and operator not in CONFIG["super_admins"]:
                print(f"[邀请拦截] 非Owner {operator} 将机器人拉入群 {group_id}，自动退出!")
                await call_api("set_group_leave", {"group_id": group_id}, timeout=8)
                if group_id in CONFIG["allowed_groups"]:
                    CONFIG["allowed_groups"].remove(group_id)
                    save_config()
                return

        # 优先使用本群自定义消息，否则用全局默认
        template = DB.get("welcome_msgs", {}).get(str(group_id)) or CONFIG.get("welcome_message", "")
        msg = format_msg(template,
                         nick=nick, user_id=user_id, group_id=group_id,
                         member_count=member_count)
        if msg:
            await send_group_text(group_id, msg)

    # 普通退群 (leave) —— 修 BUG: get_nick 在用户退群后会失败
    elif notice_type == "group_decrease":
        try:
            nick = await get_nick(group_id, user_id)
        except Exception:
            nick = f"用户{user_id}"
        template = DB.get("leave_msgs", {}).get(str(group_id)) or CONFIG.get("leave_message", "")
        msg = format_msg(template,
                         nick=nick, user_id=user_id, group_id=group_id)
        if msg:
            await send_group_text(group_id, msg)


async def handle_request(event):
    """处理加好友/加群请求：
    - friend: 询问Owner(yes/no)
    - group/invite: Owner邀请自动同意；非Owner自动拒绝
    - group/add: 拦截被封禁成员 + 白名单检查
    """
    req_type = event.get("request_type")
    sub_type = event.get("sub_type")
    group_id = event.get("group_id")
    user_id = event.get("user_id")
    flag = event.get("flag")
    comment = event.get("comment", "")

    # 调试日志：打印完整请求事件
    print(f"[请求事件] type={req_type} sub={sub_type} user={user_id} "
          f"group={group_id} flag={flag} comment={comment[:50] if comment else ''}")

    if not user_id:
        return
    # 邀请类请求即使没有 flag 也尝试处理
    if not flag:
        if sub_type and "invite" in str(sub_type).lower():
            print(f"[邀请] 收到无flag邀请: user={user_id} group={group_id} sub_type={sub_type}")
            if (CONFIG.get("reject_non_owner_invites", True) and
                user_id not in CONFIG["super_admins"]):
                print(f"[邀请拦截] 非Owner {user_id} (无flag, 无法主动拒绝)")
            return
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
        # 记录未知请求类型以便调试
        print(f"[请求] 未知类型: req_type={req_type} sub_type={sub_type} "
              f"user={user_id} group={group_id} flag={flag} comment={comment}")
        return
    if not group_id:
        return

    # ---- 机器人被邀请加群 ----
    if sub_type in ("invite", "invite_group", "group_invite", "InviteMe"):
        print(f"[邀请] 收到邀请: user={user_id} group={group_id} "
              f"flag={flag} sub_type={sub_type}")
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
            # 进群成功 → 私聊通知 Owner（含群名）
            if api_ok(res):
                gname = ""
                gi = await call_api("get_group_info", {"group_id": gid}, timeout=5)
                if api_ok(gi):
                    gname = (gi.get("data", {}) or {}).get("group_name", "")
                await _dm_owners(
                    f"✅ 已通过 {user_id} 的邀请加入群 {gid}"
                    + (f"（{gname}）" if gname else "")
                    + "，并已登记为生效群。"
                )
        elif CONFIG.get("reject_non_owner_invites", False):
            # 显式开启自动拒绝 → 直接拒绝非Owner邀请
            rejected = False
            for api_name in ("set_group_add_request", "set_group_invite",
                             "_set_group_add_request", "handle_group_invite"):
                res = await call_api(api_name, {
                    "flag": flag, "sub_type": "invite", "approve": False,
                    "reason": "Owner 未通过该邀请。",
                }, timeout=8)
                if api_ok(res):
                    rejected = True
                    print(f"[邀请拦截] 非Owner {user_id} 邀请进群 {group_id} → 已拒绝 (API: {api_name})")
                    break
            if not rejected:
                print(f"[邀请拦截] 拒绝失败! user={user_id} group={group_id} flag={flag} — 请检查NapCat版本")
        else:
            # 默认：非Owner邀请 → 转交 Owner 审批（/yes 同意、/no 拒绝），与好友请求一致
            print(f"[邀请] 非Owner {user_id} 邀请进群 {group_id} → 转交 Owner 审批")
            await _notify_owner_for_approval(user_id, flag, "group_invite",
                                             group_id=group_id, comment=comment)
        return

    # 记录未识别的群请求子类型
    if sub_type:
        print(f"[请求] 未识别的群请求: sub_type={sub_type} user={user_id} "
              f"group={group_id} flag={flag}")

    # ---- 通话邀请（语音/视频）----
    # ⚠️ NapCat / OneBot 11 没有「通话请求」事件，也没有拒绝通话的 API，
    #    因此无法在此自动拒绝电话邀请（曾经这里的 reject_call /
    #    set_call_request 等调用都已移除，那些是不存在的 API）。

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


_SEEN_MSG_IDS = set()
_MAX_SEEN = 5000
_LAST_MSG = {}

async def dispatch(raw):
    """统一事件分发 + 全类型去重。NapCat 会对同一条消息/入群事件发 2 次，
    这里用 (post_type, event_key) 做 2 秒窗口去重。"""
    global _LAST_MSG
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

    post = msg.get("post_type", "")
    if not post:
        return

    if post == "message":
        pass
    elif post == "notice":
        pass
    elif post == "request":
        pass
    else:
        pass

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
    long_interval = max(60, CONFIG["reapply_interval"])
    tick = 0
    while True:
        await asyncio.sleep(60)  # 每60秒检查一次
        tick += 1
        try:
            now = time.time()

            # 1) 定时开奖检查（每60秒）
            lotteries = DB.get("lottery", {})
            for gid, lot in list(lotteries.items()):
                if not lot.get("active"):
                    continue
                draw_at = lot.get("draw_at")
                if not draw_at:
                    continue  # 手动开奖，跳过
                if lot.get("auto_drawn"):
                    continue  # 已经自动开过了
                if draw_at > now:
                    continue  # 还没到时间

                # 时间到了 → 自动开奖！
                print(f"[定时开奖] 群 {gid} 的抽奖已到开奖时间，自动开奖中...")
                group_id = int(gid)
                participants = lot.get("participants", {})
                winners = lot.setdefault("winners", [])

                if participants:
                    remaining = [q for q in participants if q not in winners]
                    if remaining:
                        num_winners = lot["num_winners"]
                        draw_count = min(num_winners, len(remaining))
                        random.shuffle(remaining)
                        new_winners = remaining[:draw_count]
                        winner_lines = []
                        for w in new_winners:
                            nick = participants[w]
                            winner_lines.append(f"🏆 {nick}({w})")
                            winners.append(w)

                        save_db()
                        lot["auto_drawn"] = True
                        save_db()

                        await send_group_text(
                            group_id,
                            "🎉 **定时开奖！**\n\n" +
                            "\n".join(winner_lines) +
                            f"\n\n恭喜以上 {draw_count} 位中奖者！\n"
                            f"请找 Owner({lot['created_by']}) 兑奖 🎁"
                        )
                        print(f"[定时开奖] 群 {gid} 已开奖，中奖 {draw_count} 人")
                    else:
                        # 没有剩余参与者
                        lot["auto_drawn"] = True
                        save_db()
                        await send_group_text(
                            group_id,
                            "⏰ 抽奖时间到！但没有可抽取的参与者。"
                        )
                else:
                    lot["auto_drawn"] = True
                    save_db()
                    await send_group_text(
                        group_id,
                        "⏰ 抽奖时间到！但没有人参与……"
                    )

            # 2) 长周期任务（续期 + 清理），按 reapply_interval 间隔执行
            if tick * 60 >= long_interval:
                tick = 0
                # 给所有"永久禁言"重新上 30 天禁言
                for key, v in list(DB["mutes"].items()):
                    if v["expire"] == 0:
                        res = await call_api("set_group_ban", {
                            "group_id": v["group_id"], "user_id": v["user_id"],
                            "duration": CONFIG["mute_max_seconds"],
                        })
                        if api_ok(res):
                            print(f"[续期] 永久禁言 {v['user_id']} @ 群{v['group_id']} 已续期")
                # 清理已过期的限时封禁/禁言记录
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


async def auto_sync_groups():
    """循环同步群状态(allowed_groups 非空时生效；为空=对所有群生效，不处理)：
    ① 机器人在某群、但该群不在生效列表 → 自动退群；
    ② 生效列表里有某群、但机器人已不在该群 → 自动从生效列表移除。
    间隔由 config 的 auto_leave_check_interval 控制(默认 300 秒)。
    """
    interval = max(60, CONFIG.get("auto_leave_check_interval", 300))
    await asyncio.sleep(20)  # 启动后先等一会，确保 WS 已连上
    while True:
        try:
            allowed = CONFIG.get("allowed_groups", [])
            if allowed:  # 空列表=全部群生效，不处理
                res = await call_api("get_group_list", timeout=15)
                if api_ok(res):
                    groups = (res.get("data") or []) if isinstance(res, dict) else []
                    in_groups = {g.get("group_id") for g in groups
                                 if isinstance(g, dict) and g.get("group_id") is not None}
                    # ① 机器人在群但不在生效列表 → 退群
                    for g in groups:
                        if not isinstance(g, dict):
                            continue
                        gid = g.get("group_id")
                        if gid is None or gid in allowed:
                            continue
                        name = g.get("group_name") or ""
                        lr = await call_api("set_group_leave", {"group_id": gid}, timeout=10)
                        if api_ok(lr):
                            print(f"[自动退群] 群 {gid}({name}) 不在生效列表，已退出")
                        else:
                            print(f"[自动退群] 退出群 {gid}({name}) 失败: {lr}")
                    # ② 生效列表里有但机器人不在 → 移出生效列表
                    stale = [g for g in allowed if g not in in_groups]
                    if stale:
                        for g in stale:
                            print(f"[生效清理] 群 {g} 在生效列表但机器人不在，已移除")
                        CONFIG["allowed_groups"] = [g for g in allowed if g not in stale]
                        save_config()
        except Exception as e:
            print(f"[自动同步异常] {e}")
        await asyncio.sleep(interval)


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
    global WS, BOT_QQ
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
    asyncio.create_task(auto_sync_groups())  # 定时同步：不在生效列表的群自动退、机器人不在的生效群自动移除
    threading.Thread(target=stdin_reloader_loop, daemon=True).start()

    while True:
        try:
            async with websockets.connect(
                url, ping_interval=20, ping_timeout=60, close_timeout=5
            ) as ws:
                WS = ws
                print("[连接] 已连接到 NapCat ✓  等待消息...")
                # 获取登录信息，缓存机器人QQ
                login = await call_api("get_login_info", timeout=8)
                if api_ok(login):
                    d = login.get("data", {}) or {}
                    BOT_QQ = d.get("user_id")
                    print(f"[登录] 机器人账号: {d.get('nickname')} ({BOT_QQ})")

                # 设置 QQ 资料（官方感）
                profile = {}
                sig = CONFIG.get("bot_signature", "")
                nick = CONFIG.get("bot_nickname", "")
                if sig: profile["personal_note"] = sig
                if nick: profile["nickname"] = nick
                if profile:
                    res = await call_api("set_qq_profile", profile, timeout=8)
                    if api_ok(res):
                        parts = []
                        if nick: parts.append(f"昵称={nick}")
                        if sig: parts.append(f"签名={sig}")
                        print(f"[资料] 已设置: {', '.join(parts)}")
                    else:
                        print(f"[资料] 设置失败: {(res or {}).get('msg', res)}")

                # 设置头像
                avatar = CONFIG.get("bot_avatar_path", "")
                if avatar and os.path.exists(avatar):
                    img_url = "file:///" + avatar.replace("\\", "/")
                    res = await call_api("set_qq_avatar", {"file": img_url}, timeout=15)
                    if api_ok(res):
                        print(f"[头像] 已设置")
                    else:
                        print(f"[头像] 失败: {(res or {}).get('msg', res)}")
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
