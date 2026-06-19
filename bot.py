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
    "allow_owner": True,
    "allow_admin": True,
    "allowed_groups": [],
    "command_prefix": "/",
    "reconnect_delay": 5,
    "reapply_interval": 86400,
    "mute_max_seconds": 2592000,  # QQ 单次禁言上限 = 30 天
}

HELP_TEXT = (
    "🤖 QQ群管理机器人 命令列表\n"
    "——————————————————\n"
    "【群主/管理员可用】\n"
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
    "/reload                     刷新配置(免重启)\n"
    "/blacklist                  查看黑名单\n"
    "——————————————————\n"
    "【仅 Owner 可用】\n"
    "/black <QQ号>               拉黑用户(禁止使用命令)\n"
    "/unblack <QQ号>             取消拉黑\n"
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
#  本地数据库 (data.json)：记录封禁/禁言
# ============================================================
# 结构:
#   bans : { "群号_QQ号": {"group_id","user_id","reason","expire"(0=永久),"set_at","set_by"} }
#   mutes: 同上
#   whitelist : { 群号: [QQ号, ...] }
#   whitelist_enabled : [群号, ...]


def load_db():
    if not os.path.exists(DB_PATH):
        return {"bans": {}, "mutes": {}, "whitelist": {}, "whitelist_enabled": []}
    try:
        with open(DB_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("bans", {})
        data.setdefault("mutes", {})
        data.setdefault("whitelist", {})
        data.setdefault("whitelist_enabled", [])
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
    """将用户加入黑名单(仅Owner可用)。"""
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
    CONFIG.setdefault("banned_users", []).append(target)
    save_config()
    await send_group_text(group_id, f"✅ 已将 {target} 加入黑名单，该用户无法使用任何命令。")


async def cmd_unblack(event, rest):
    """将用户移出黑名单(仅Owner可用)。"""
    group_id = event["group_id"]
    target = parse_single_qq(rest)
    if target is None:
        await send_group_text(group_id, "❌ 格式错误。用法: /unblack <QQ号>")
        return
    banned = CONFIG.get("banned_users", [])
    if target in banned:
        banned.remove(target)
        save_config()
        await send_group_text(group_id, f"✅ 已将 {target} 移出黑名单。")
    else:
        await send_group_text(group_id, f"ℹ️ {target} 不在黑名单中。")


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
    if event.get("message_type") != "group":
        return
    group_id = event.get("group_id")
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

    # 黑名单拦截
    if event.get("user_id") in CONFIG.get("banned_users", []):
        owner_qq = CONFIG["super_admins"][0] if CONFIG["super_admins"] else "未知"
        await send_group_text(
            group_id,
            f"× 你被加入黑名单了 请寻找Owner({owner_qq})解ban"
        )
        return

    admin = is_admin(event)

    if cmd in ("help", "帮助", "?", "菜单"):
        await send_group_text(group_id, HELP_TEXT)
        return

    if cmd in ("mute", "禁言"):
        if not admin:
            await send_group_text(group_id, "⛔ 仅群主/管理员可使用此命令。")
            return
        await cmd_mute(event, rest)
    elif cmd in ("unmute", "解禁", "解除禁言"):
        if not admin:
            await send_group_text(group_id, "⛔ 仅群主/管理员可使用此命令。")
            return
        await cmd_unmute(event, rest)
    elif cmd in ("ban", "封禁", "封人", "kick", "踢"):
        if not admin:
            await send_group_text(group_id, "⛔ 仅群主/管理员可使用此命令。")
            return
        await cmd_ban(event, rest)
    elif cmd in ("unban", "解封", "解封禁"):
        if not admin:
            await send_group_text(group_id, "⛔ 仅群主/管理员可使用此命令。")
            return
        await cmd_unban(event, rest)
    elif cmd in ("list", "名单", "列表"):
        if not admin:
            await send_group_text(group_id, "⛔ 仅群主/管理员可使用此命令。")
            return
        await cmd_list(event, rest)
    elif cmd in ("say", "说", "发言", "复读"):
        if not admin:
            await send_group_text(group_id, "⛔ 仅群主/管理员可使用此命令。")
            return
        await cmd_say(event, rest)
    elif cmd in ("reload", "刷新", "重载", "重新加载"):
        if not admin:
            await send_group_text(group_id, "⛔ 仅群主/管理员可使用此命令。")
            return
        await cmd_reload(event, rest)
    elif cmd in ("whitelist", "wl", "白名单"):
        if not admin:
            await send_group_text(group_id, "⛔ 仅群主/管理员可使用此命令。")
            return
        await cmd_whitelist(event, rest)
    elif cmd in ("black", "拉黑"):
        if event.get("user_id") not in CONFIG["super_admins"]:
            await send_group_text(group_id, "⛔ 仅Owner可使用此命令。")
            return
        await cmd_black(event, rest)
    elif cmd in ("unblack", "取消拉黑"):
        if event.get("user_id") not in CONFIG["super_admins"]:
            await send_group_text(group_id, "⛔ 仅Owner可使用此命令。")
            return
        await cmd_unblack(event, rest)
    elif cmd in ("blacklist", "黑名单"):
        if not admin:
            await send_group_text(group_id, "⛔ 仅群主/管理员可使用此命令。")
            return
        banned = CONFIG.get("banned_users", [])
        if banned:
            await send_group_text(group_id, f"📋 黑名单 ({len(banned)} 人):\n" + "\n".join(f"  · {u}" for u in banned))
        else:
            await send_group_text(group_id, "📋 黑名单: (空)")


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
        await send_group_text(
            group_id,
            f"你好！{nick}({user_id})！你是本群的第 {member_count} 位成员 🎉"
        )

    # 普通退群 (leave)
    elif notice_type == "group_decrease":
        nick = await get_nick(group_id, user_id)
        await send_group_text(
            group_id,
            f"哔哔哔！群友 {nick}({user_id}) 退群了！"
        )


async def handle_request(event):
    """处理加群请求/邀请：
    - invite(机器人被邀请加群): 仅 super_admins 的邀请才同意，其余一律拒绝
    - add(别人申请加群): 拦截被封禁成员，其余放行(交给群管处理)
    """
    if event.get("request_type") != "group":
        return
    sub_type = event.get("sub_type")
    group_id = event.get("group_id")
    user_id = event.get("user_id")
    flag = event.get("flag")
    if not group_id or not user_id or not flag:
        return

    # ---- 机器人被邀请加群：只接受Owner(你)的邀请 ----
    if sub_type == "invite":
        approve = user_id in CONFIG["super_admins"]
        res = await call_api("set_group_add_request", {
            "flag": flag, "sub_type": "invite", "approve": approve,
            "reason": "" if approve else "仅限管理员邀请入群",
        })
        action = "同意" if approve else "拒绝"
        ok = "成功" if api_ok(res) else "失败"
        print(f"[邀请] {user_id} 邀请机器人进群 {group_id} -> {action}({ok}) resp={res}")
        # 同意后自动注册为生效群(不依赖api_ok，避免NapCat返回格式差异)
        if approve:
            gid = int(group_id) if group_id else 0
            if gid and gid not in CONFIG["allowed_groups"]:
                CONFIG["allowed_groups"].append(gid)
                save_config()
                print(f"[自动注册] 群 {gid} 已添加到生效群列表")
        return

    # ---- 普通加群申请(add)：拦截被封禁成员 + 白名单检查 ----
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
            # 封禁已过期，放行并清理
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
