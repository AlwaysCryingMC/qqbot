#!/usr/bin/env python3
"""
QQ 群管理机器人 (QQ 官方 Bot API + NapCat 兼容层)
==================================================
底层用 QQ 官方 WebSocket 网关 + HTTP API，
命令系统保留 NapCat 版的全部逻辑。

配置: config_official.json
"""
import asyncio
import json
import os
import random
import re
import sys
import threading
import time
from datetime import datetime

# UTF-8
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except: pass

try:
    import aiohttp
except ImportError:
    print("[错误] pip install aiohttp")
    sys.exit(1)

# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config_official.json")
DB_PATH = os.path.join(BASE_DIR, "data_official.json")

DEFAULT_CONFIG = {
    "appid": "1904952605",
    "client_secret": "",
    "super_admins_openid": [],
    "admins_openid": [],
    "banned_users_openid": [],
    "allowed_groups_openid": [],
    "command_prefix": "/",
    "reapply_interval": 86400,
    "mute_max_seconds": 2592000,
    "welcome_message": "你好！{nick}！你是本群的第 {member_count} 位成员 🎉",
    "leave_message": "哔哔哔！群友 {nick} 退群了！",
    "notify_dm": True,
}

HELP_SHORT = (
    "🤖 QQ群管理机器人 (官方API)\n"
    "——————————————————\n"
    "🔒 管理: /ban /unban /mute /unmute /list\n"
    "📝 内容: /say\n"
    "🛡️ 白名单: /whitelist add|remove|on|off\n"
    "🚫 黑名单: /black /unblack (仅Owner)\n"
    "🔍 查询: /sid /pending\n"
    "👑 Admin: /admin add|remove|list (仅Owner私聊)\n"
    "🔄 /reload — 热重载配置\n"
    "💬 /welcome — 自定义欢迎/退群消息\n"
    "🎰 /joinroll — 参与本群抽奖\n"
    "🎲 /roll — 抽奖管理\n"
    "❤️ 赞我 — 给发送者点赞(每日20次)\n"
    "——————————————————\n"
    "ⓘ 群聊需 @bot 使用命令（官方平台限制）\n"
    "发送 /help full 查看完整命令列表"
)

HELP_FULL = (
    "🤖 QQ群管理机器人 完整命令列表\n"
    "——————————————————\n"
    "【群主/管理员 及 Bot Admin 可用】\n"
    "/ban <ID> <时长> <原因>   封禁(踢出)\n"
    "/unban <ID>               解封\n"
    "/mute <ID> <时长> <原因>  禁言\n"
    "/unmute <ID>              解禁\n"
    "/whitelist add <ID>       添加白名单\n"
    "/whitelist remove <ID>    移除白名单\n"
    "/whitelist on|off         启用/关闭白名单模式\n"
    "/list                     查看封禁/禁言名单\n"
    "/say <内容>               让机器人说一句话\n"
    "/welcome                  自定义欢迎/退群消息\n"
    "/reload                   刷新配置(免重启)\n"
    "/sid                       查看会话信息\n"
    "/pending                   查看待审批请求\n"
    "/yes|no <ID>              同意/拒绝请求\n"
    "——————————————————\n"
    "【仅 Owner 可用】\n"
    "/admin <add|remove> <ID>  管理Bot Admin(私聊)\n"
    "/black <ID>               拉黑用户\n"
    "/unblack <ID>             取消拉黑\n"
    "/roll create <群ID> <人数>  创建抽奖\n"
    "/roll draw <群ID>          手动开奖\n"
    "/roll cancel <群ID>        取消抽奖\n"
    "——————————————————\n"
    "【任意成员可用】\n"
    "赞我                         给发送者点赞(每日20次)\n"
    "/joinroll                    参与本群抽奖\n"
    "/joinroll list               查看参与名单\n"
    "——————————————————\n"
    "ⓘ 群聊需 @bot（官方平台限制），私聊无需 @\n"
    "时长：纯数字=分钟，或 30s/10m/2h/1d/3w，0=永久"
)

# ============================================================
#  配置 & 数据
# ============================================================
def load_config():
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    cfg = {k: v for k, v in cfg.items() if not k.startswith("_")}
    m = dict(DEFAULT_CONFIG); m.update(cfg)
    return m

_save_lock = threading.Lock()

def save_config(cfg):
    with _save_lock:
        o = {}
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                o = json.load(f)
        for k, v in cfg.items(): o[k] = v
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(o, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CONFIG_PATH)

def load_db():
    if not os.path.exists(DB_PATH):
        return _empty_db()
    try:
        with open(DB_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
        for k, v in _empty_db().items(): d.setdefault(k, v)
        return d
    except: return _empty_db()

def save_db(db):
    with _save_lock:
        tmp = DB_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=2)
        os.replace(tmp, DB_PATH)

def _empty_db():
    return {"bans": {}, "mutes": {}, "whitelist": {}, "whitelist_enabled": [],
            "welcome_msgs": {}, "leave_msgs": {}, "lottery": {}}

CONFIG = load_config()
DB = load_db()

API_BASE = "https://api.sgroup.qq.com"
TOKEN_URL = "https://bots.qq.com/app/getAppAccessToken"

# ============================================================
#  Token 管理
# ============================================================
_token = None
_token_expiry = 0

async def get_token():
    global _token, _token_expiry
    if _token and time.time() < _token_expiry - 60:
        return _token
    async with aiohttp.ClientSession() as s:
        async with s.post(TOKEN_URL, json={
            "appId": CONFIG["appid"],
            "clientSecret": CONFIG["client_secret"],
        }) as r:
            d = await r.json()
    _token = d.get("access_token", "")
    _token_expiry = time.time() + int(d.get("expires_in", 7200))
    if not _token: raise RuntimeError(f"Token 获取失败: {d}")
    return _token

# ============================================================
#  HTTP API
# ============================================================
async def api_req(method, path, **kw):
    token = await get_token()
    h = {"Authorization": f"QQBot {token}", "Content-Type": "application/json"}
    h.update(kw.pop("headers", {}))
    async with aiohttp.ClientSession() as s:
        async with s.request(method, f"{API_BASE}{path}", headers=h, **kw) as r:
            t = await r.text()
            try: d = json.loads(t) if t else {}
            except: d = {"_raw": t}
            return {"ok": r.ok, "code": d.get("code", r.status), "data": d}

def ok(r): return r and r.get("ok")

async def send_group_msg(gid, text, msg_id=None):
    body = {"content": text, "msg_type": 0}
    if msg_id: body["msg_id"] = msg_id
    return await api_req("POST", f"/v2/groups/{gid}/messages", json=body)

async def send_c2c_msg(uid, text):
    return await api_req("POST", f"/v2/users/{uid}/messages",
                         json={"content": text, "msg_type": 0})

async def mute_member(gid, uid, sec):
    return await api_req("PATCH", f"/v2/groups/{gid}/members/{uid}",
                         json={"mute_seconds": str(sec)})

async def kick_member(gid, uid):
    return await api_req("DELETE", f"/v2/groups/{gid}/members/{uid}",
                         params={"add_blacklist": "false"})

async def get_member(gid, uid):
    return await api_req("GET", f"/v2/groups/{gid}/members/{uid}")

async def get_group(gid):
    return await api_req("GET", f"/v2/groups/{gid}")

# ============================================================
#  工具
# ============================================================
_PERM = {"0", "永久", "perm", "permanent", "forever"}
_UNIT = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}

def parse_duration(s):
    s = str(s).strip().lower()
    if s in _PERM: return 0
    m = re.fullmatch(r"(\d+)\s*([smhdw]?)", s)
    if not m: return None
    return int(m.group(1)) * _UNIT.get(m.group(2) or "m", 60)

def fmt_duration(sec):
    if sec <= 0: return "永久"
    for n, v in [("周", 604800), ("天", 86400), ("小时", 3600), ("分钟", 60), ("秒", 1)]:
        if sec >= v: q, sec = divmod(sec, v)
        else: q = 0
        if q: return f"{q}{n}" + (fmt_duration(sec) if sec else "")
    return "0秒"

def format_msg(t, **kw):
    if not t or not t.strip(): return None
    for k, v in kw.items(): t = t.replace("{" + k + "}", str(v))
    return t

def parse_single_id(rest):
    rest = rest.strip()
    if not rest: return None
    p = rest.split(None, 1)[0]
    return p if re.fullmatch(r"[A-Fa-f0-9]+", p) and len(p) >= 8 else None

def parse_target_and_duration(rest):
    p = rest.split(None, 2)
    if len(p) < 2: return None, None, None
    uid, ts = p[0], p[1]
    reason = p[2].strip() if len(p) > 2 else "未说明"
    if not re.fullmatch(r"[A-Fa-f0-9]+", uid) or len(uid) < 8: return None, None, None
    dur = parse_duration(ts)
    if dur is None: return None, None, None
    return uid, dur, reason

def is_owner(uid):
    return uid in CONFIG.get("super_admins_openid", [])
def is_bot_admin(uid):
    return is_owner(uid) or uid in CONFIG.get("admins_openid", [])
def is_banned(uid):
    return uid in CONFIG.get("banned_users_openid", [])
def group_allowed(gid):
    al = CONFIG.get("allowed_groups_openid", [])
    return (not al) or (gid in al)

def u(event):
    """从 QQ 事件中提取用户 openid"""
    return (event.get("author") or {}).get("id", "")
def g(event):
    """从 QQ 事件中提取群 openid"""
    return event.get("group_openid", "")

async def get_nick(gid, uid):
    r = await get_member(gid, uid)
    if ok(r):
        d = r.get("data", {}) or {}
        return d.get("nick") or d.get("user", {}).get("username", "") or uid[:12] + "…"
    return uid[:12] + "…"

async def get_member_count(gid):
    r = await get_group(gid)
    if ok(r): return str((r.get("data", {}) or {}).get("member_count", "?"))
    return "?"

def _reply(event):
    is_grp = bool(g(event))
    target = g(event) or u(event)
    msg_id = event.get("msg_id") or event.get("id", "")

    async def _do(text):
        if is_grp: await send_group_msg(target, text, msg_id=msg_id)
        else: await send_c2c_msg(target, text)
    return _do

async def _dm_owners(text):
    for oid in CONFIG.get("super_admins_openid", []):
        try: await send_c2c_msg(oid, text)
        except: pass

def _strip_at(content):
    """去掉 @bot 前缀"""
    c = content.strip()
    c = re.sub(r'<@!\w+>\s*', '', c)
    c = re.sub(r'@\S+\s*', '', c, count=1)
    return c.strip()

# ============================================================
#  命令实现
# ============================================================
async def cmd_ban(event, rest):
    gid = g(event); target, duration, reason = parse_target_and_duration(rest)
    if not target:
        await send_group_msg(gid, "❌ 格式: /ban <ID> <时长> <原因>")
        return
    if target == u(event): await send_group_msg(gid, "❌ 不能封禁自己。"); return
    if is_owner(target): await send_group_msg(gid, "❌ 不能封禁Owner。"); return

    nick = await get_nick(gid, target)
    await kick_member(gid, target)
    now = time.time(); expire = 0 if duration == 0 else now + duration
    key = f"{gid}_{target}"
    DB["bans"][key] = {"group_id": gid, "user_id": target, "reason": reason,
                       "expire": expire, "set_at": now, "set_by": u(event)}
    save_db(DB)
    ds = "永久" if duration == 0 else fmt_duration(duration)
    await send_group_msg(gid, f"✅ 已封禁 {nick}\n时长: {ds}\n原因: {reason}")

async def cmd_unban(event, rest):
    gid = g(event); target = parse_single_id(rest)
    if not target: await send_group_msg(gid, "❌ 格式: /unban <ID>"); return
    key = f"{gid}_{target}"
    if key in DB["bans"]: del DB["bans"][key]; save_db(DB); await send_group_msg(gid, f"✅ 已解封 {target[:12]}…")
    else: await send_group_msg(gid, f"ℹ️ 不在封禁名单中。")

async def cmd_mute(event, rest):
    gid = g(event); target, duration, reason = parse_target_and_duration(rest)
    if not target: await send_group_msg(gid, "❌ 格式: /mute <ID> <时长> <原因>"); return
    if target == u(event): await send_group_msg(gid, "❌ 不能禁言自己。"); return
    if is_owner(target): await send_group_msg(gid, "❌ 不能禁言Owner。"); return

    nick = await get_nick(gid, target)
    now = time.time(); is_perm = (duration == 0)
    mx = CONFIG.get("mute_max_seconds", 2592000)
    await mute_member(gid, target, mx if is_perm else min(duration, mx))
    expire = 0 if is_perm else now + duration
    key = f"{gid}_{target}"
    DB["mutes"][key] = {"group_id": gid, "user_id": target, "reason": reason,
                        "expire": expire, "set_at": now, "set_by": u(event)}
    save_db(DB)
    ds = "永久(自动续期)" if is_perm else fmt_duration(duration)
    await send_group_msg(gid, f"✅ 已禁言 {nick}\n时长: {ds}\n原因: {reason}")

async def cmd_unmute(event, rest):
    gid = g(event); target = parse_single_id(rest)
    if not target: await send_group_msg(gid, "❌ 格式: /unmute <ID>"); return
    await mute_member(gid, target, 0)
    key = f"{gid}_{target}"
    if key in DB["mutes"]: del DB["mutes"][key]; save_db(DB)
    await send_group_msg(gid, f"✅ 已解除禁言。")

async def cmd_list(event, rest):
    gid = g(event); now = time.time()
    bans = [v for v in DB["bans"].values() if v["group_id"] == gid and (v["expire"] == 0 or v["expire"] > now)]
    mutes = [v for v in DB["mutes"].values() if v["group_id"] == gid and (v["expire"] == 0 or v["expire"] > now)]
    out = [f"📋 管理名单"]
    for label, items, icon in [("封禁", bans, "🔒"), ("禁言", mutes, "🤐")]:
        out.append(f"\n{icon} {label} ({len(items)}):")
        if items:
            for v in items:
                t = "永久" if v["expire"] == 0 else f"剩{fmt_duration(int(v['expire'] - now))}"
                out.append(f"  · {v['user_id'][:12]}… [{t}] {v['reason']}")
        else: out.append("  (无)")
    await send_group_msg(gid, "\n".join(out))

async def cmd_say(event, rest):
    if not rest.strip(): await send_group_msg(g(event), "❌ 内容不能为空。"); return
    await send_group_msg(g(event), rest.strip())

async def cmd_sid(event, rest=""):
    gid = g(event); uid = u(event)
    await _reply(event)(f"群 OpenID: {gid or 'N/A'}\n你的 OpenID: {uid}\nBot AppID: {CONFIG.get('appid', '?')}")

async def cmd_reload(event, rest):
    global CONFIG
    try: CONFIG = load_config()
    except Exception as e: await _reply(event)(f"❌ 刷新失败: {e}"); return
    await _reply(event)(f"✅ 配置已刷新")

async def cmd_group(event, rest):
    reply = _reply(event); parts = rest.strip().split(None, 1); sub = parts[0].lower() if parts else "list"
    if sub in ("list", "ls", "列表"):
        gs = CONFIG.get("allowed_groups_openid", [])
        if gs: await reply("📋 生效群 ({} 个):\n{}".format(len(gs), "\n".join(f"  · {x[:16]}…" for x in gs)))
        else: await reply("📋 生效群：全部")
    elif sub in ("del", "remove", "rm", "删除"):
        gid = parse_single_id(parts[1]) if len(parts) > 1 else None
        if not gid: await reply("❌ 用法: /group del <群openid>"); return
        gs = CONFIG.get("allowed_groups_openid", [])
        if gid in gs: gs.remove(gid); save_config(CONFIG); await reply("✅ 已移除。")
        else: await reply("ℹ️ 不在列表中。")
    else:
        gid = parse_single_id(parts[0])
        if not gid: await reply("❌ 用法: /group <群openid>"); return
        gs = CONFIG.setdefault("allowed_groups_openid", [])
        if gid not in gs: gs.append(gid); save_config(CONFIG); await reply("✅ 已激活。")
        else: await reply("ℹ️ 已在列表中。")

async def cmd_black(event, rest):
    gid = g(event); target = parse_single_id(rest)
    if not target: await send_group_msg(gid, "❌ 格式: /black <ID>"); return
    if is_owner(target): await send_group_msg(gid, "❌ 不能拉黑Owner。"); return
    bl = CONFIG.setdefault("banned_users_openid", [])
    if target not in bl: bl.append(target); save_config(CONFIG)
    await send_group_msg(gid, f"✅ 已拉黑 {target[:12]}…")

async def cmd_unblack(event, rest):
    gid = g(event); target = parse_single_id(rest)
    if not target: await send_group_msg(gid, "❌ 格式: /unblack <ID>"); return
    bl = CONFIG.get("banned_users_openid", [])
    if target in bl: bl.remove(target); save_config(CONFIG); await send_group_msg(gid, f"✅ 已移出黑名单。")
    else: await send_group_msg(gid, f"ℹ️ 不在黑名单中。")

async def cmd_blacklist(event, rest):
    bl = CONFIG.get("banned_users_openid", [])
    if bl: await send_group_msg(g(event), f"📋 黑名单 ({len(bl)} 人):\n" + "\n".join(f"  · {x[:16]}…" for x in bl))
    else: await send_group_msg(g(event), "📋 黑名单: (空)")

async def cmd_whitelist(event, rest):
    gid = g(event); gid_s = str(gid); parts = rest.strip().split(None, 1); sub = parts[0].lower() if parts else "list"
    if sub in ("add", "添加", "+"):
        t = parse_single_id(parts[1]) if len(parts) > 1 else None
        if not t: await send_group_msg(gid, "❌ 格式: /whitelist add <ID>"); return
        wl = DB["whitelist"].setdefault(gid_s, [])
        if t not in wl: wl.append(t); save_db(DB); await send_group_msg(gid, f"✅ 已添加。")
        else: await send_group_msg(gid, "ℹ️ 已在白名单中。")
    elif sub in ("remove", "del", "删除", "-"):
        t = parse_single_id(parts[1]) if len(parts) > 1 else None
        if not t: await send_group_msg(gid, "❌ 格式: /whitelist remove <ID>"); return
        wl = DB["whitelist"].get(gid_s, [])
        if t in wl: wl.remove(t); save_db(DB); await send_group_msg(gid, "✅ 已移除。")
        else: await send_group_msg(gid, "ℹ️ 不在白名单中。")
    elif sub in ("on", "enable", "启用"):
        en = DB.setdefault("whitelist_enabled", [])
        if gid not in en: en.append(gid); save_db(DB); await send_group_msg(gid, "🛡️ 白名单模式已启用。")
        else: await send_group_msg(gid, "ℹ️ 已启用。")
    elif sub in ("off", "disable", "禁用"):
        en = DB.setdefault("whitelist_enabled", [])
        if gid in en: en.remove(gid); save_db(DB); await send_group_msg(gid, "🔓 白名单模式已关闭。")
        else: await send_group_msg(gid, "ℹ️ 未启用。")
    else:
        wl = DB["whitelist"].get(gid_s, []); en = DB.get("whitelist_enabled", [])
        st = "🟢 启用" if gid in en else "⚪ 关闭"
        await send_group_msg(gid, f"📋 白名单 ({st}) — {len(wl)} 人")

async def cmd_welcome(event, rest):
    gid = g(event); gid_s = str(gid); parts = rest.strip().split(None, 1); sub = parts[0].lower() if parts else ""
    if sub in ("leave", "退群"):
        c = parts[1].strip() if len(parts) > 1 else ""
        if not c:
            cur = DB.get("leave_msgs", {}).get(gid_s); df = CONFIG.get("leave_message", "")
            await send_group_msg(gid, f"退群消息: {cur if cur is not None else df}\n设置: /welcome leave <消息>  |  关闭: /welcome leave off")
            return
        if c.lower() in ("off", "关闭"): DB.setdefault("leave_msgs", {}).pop(gid_s, None); save_db(DB); await send_group_msg(gid, "✅ 已恢复默认。")
        else: DB.setdefault("leave_msgs", {})[gid_s] = c; save_db(DB); await send_group_msg(gid, f"✅ 退群消息已更新。")
    elif sub in ("off", "关闭"):
        DB.setdefault("welcome_msgs", {}).pop(gid_s, None); save_db(DB); await send_group_msg(gid, "✅ 已恢复默认。")
    elif not sub or sub in ("show", "查看"):
        wc = DB.get("welcome_msgs", {}).get(gid_s); lc = DB.get("leave_msgs", {}).get(gid_s)
        await send_group_msg(gid, f"欢迎: {wc if wc is not None else CONFIG.get('welcome_message','')}\n退群: {lc if lc is not None else CONFIG.get('leave_message','')}")
    else:
        DB.setdefault("welcome_msgs", {})[gid_s] = rest.strip(); save_db(DB); await send_group_msg(gid, "✅ 欢迎消息已更新。")

async def cmd_admin(event, rest) -> str:
    parts = rest.strip().split(); sub = parts[0].lower() if parts else "list"
    if sub in ("add", "添加", "+"):
        targets = [p for p in parts[1:] if re.fullmatch(r"[A-Fa-f0-9]{8,}", p)]
        if not targets: return "❌ 格式: /admin add <openid>"
        added = []; cur = CONFIG.setdefault("admins_openid", [])
        for t in targets:
            if t not in cur: cur.append(t); added.append(t[:12] + "…")
        if added: save_config(CONFIG); return f"✅ 已添加: {', '.join(added)}"
        return "ℹ️ 已在列表中。"
    elif sub in ("remove", "del", "删除", "-"):
        targets = [p for p in parts[1:] if re.fullmatch(r"[A-Fa-f0-9]{8,}", p)]
        if not targets: return "❌ 格式: /admin remove <openid>"
        cur = CONFIG.get("admins_openid", []); removed = []
        for t in targets:
            if t in cur: cur.remove(t); removed.append(t[:12] + "…")
        if removed: save_config(CONFIG); return f"✅ 已移除: {', '.join(removed)}"
        return "ℹ️ 不在列表中。"
    else:
        ad = CONFIG.get("admins_openid", [])
        return f"📋 Bot Admin ({len(ad)} 人):\n" + "\n".join(f"  · {x[:16]}…" for x in ad) if ad else "📋 (空)"

# ---- 点赞 ----
_LIKE = {}; _LIKE_MAX = 20; _LIKE_FAIL = {}; _LIKE_CD = 60

async def cmd_like(event):
    uid = u(event); gid = g(event); reply = _reply(event)
    today = time.strftime("%Y%m%d"); ck = f"{today}_{uid}"
    cur = _LIKE.get(ck, 0); now = time.time()
    if cur >= _LIKE_MAX: await reply("❌ 今日已达上限")
    elif now - _LIKE_FAIL.get(uid, 0) < _LIKE_CD: await reply("❌ 稍后再试")
    else:
        # QQ官方API没有点赞接口，模拟回复
        _LIKE[ck] = cur + 1
        await reply(f"❤️ 点赞成功！今日剩余 {_LIKE_MAX - _LIKE[ck]} 赞～")

# ---- 抽奖 ----
_PENDING = {}; _REQ_CTR = [0]

def add_pending_req(uid, flag, kind, gid=None, comment=""):
    _REQ_CTR[0] += 1; rid = _REQ_CTR[0]
    _PENDING[rid] = {"flag": flag, "user_id": uid, "group_id": gid, "kind": kind,
                     "comment": comment, "timestamp": time.time()}
    return rid

async def cmd_pending(event, rest=""):
    reply = _reply(event); now = time.time()
    for rid in [r for r, v in _PENDING.items() if now - v["timestamp"] > 600]: del _PENDING[rid]
    if not _PENDING: await reply("✅ 无待处理请求。"); return
    lines = ["📋 待处理:"]
    for rid in sorted(_PENDING): r = _PENDING[rid]; lines.append(f"  #{rid} {r['user_id'][:12]}…")
    await reply("\n".join(lines))

async def cmd_approve(event, rest, approve):
    reply = _reply(event)
    try: rid = int(rest.strip()) if rest.strip() else max(_PENDING.keys()) if _PENDING else None
    except: await reply("❌ 无效ID"); return
    if rid not in _PENDING: await reply("❌ 不存在"); return
    r = _PENDING.pop(rid)
    await reply(f"{'✅ 已同意' if approve else '❌ 已拒绝'} #{rid}")

async def cmd_joinroll(event, rest):
    gid = g(event); uid = u(event); gid_s = str(gid)
    lot = DB.get("lottery", {}).get(gid_s)
    if not lot or not lot.get("active"): await send_group_msg(gid, "ℹ️ 本群没有进行中的抽奖。"); return
    participants = lot.setdefault("participants", {})
    if rest.strip().lower() in ("list", "名单"):
        total = len(participants); slots = lot["num_winners"]; won = len(lot.get("winners", []))
        await send_group_msg(gid, f"📋 抽奖名单 ({slots}名额, 已开{won}, 共{total}人):\n" +
            "\n".join(f"  · {n}" for n in participants.values()) if participants else "  暂无人参与。")
        return
    uid_key = str(uid)
    if uid_key in participants: await send_group_msg(gid, "ℹ️ 你已经参与过了！"); return
    nick = await get_nick(gid, uid); participants[uid_key] = nick; save_db(DB)
    await send_group_msg(gid, f"✅ {nick} 已加入抽奖！当前 {len(participants)} 人参与。")

async def cmd_roll_create(event, rest):
    reply = _reply(event); parts = rest.strip().split()
    if len(parts) < 2: await reply("❌ 格式: /roll create <群openid> <中奖人数> [开奖时间]"); return
    gid, num_str = parts[0], parts[1]
    if not num_str.isdigit(): await reply("❌ 人数必须是数字"); return
    num = int(num_str)
    gid_s = str(gid)
    DB.setdefault("lottery", {})[gid_s] = {"active": True, "num_winners": num,
        "participants": {}, "winners": [], "created_by": u(event),
        "draw_at": None, "auto_drawn": False}
    save_db(DB)
    await send_group_msg(gid, f"🎉 抽奖已开启！{num} 个中奖名额。\n参与方式: /joinroll")
    await reply(f"✅ 已在群创建抽奖（{num} 人中奖）")

async def cmd_roll_draw(event, rest):
    reply = _reply(event); parts = rest.strip().split()
    if not parts: await reply("❌ 格式: /roll draw <群openid>"); return
    gid = parts[0]; gid_s = str(gid)
    lot = DB.get("lottery", {}).get(gid_s)
    if not lot or not lot.get("active"): await reply("ℹ️ 没有进行中的抽奖。"); return
    participants = lot.get("participants", {})
    if not participants: await reply("无人参与，无法抽奖。"); return
    remaining = [k for k in participants if k not in [str(w) for w in lot.get("winners", [])]]
    if not remaining: await reply("所有人都已中奖！"); return
    import random
    winners = lot.setdefault("winners", [])
    slots = lot["num_winners"] - len(winners)
    draw_n = min(slots, len(remaining)) if slots > 0 else 1
    picked_ids = random.sample(remaining, min(draw_n, len(remaining)))
    picked_names = [participants[pid] for pid in picked_ids]
    winners.extend(picked_ids)
    lot["auto_drawn"] = True; save_db(DB)
    await send_group_msg(gid, f"🎉 开奖了！\n\n恭喜: {', '.join(picked_names)}\n\n中奖者请联系群管！")
    await reply(f"✅ 已开奖，{len(picked_names)} 人中奖")

async def cmd_roll_cancel(event, rest):
    reply = _reply(event); parts = rest.strip().split()
    if not parts: await reply("❌ 格式: /roll cancel <群openid>"); return
    gid = parts[0]; gid_s = str(gid); lot = DB.get("lottery", {}).get(gid_s)
    if not lot: await reply("ℹ️ 没有进行中的抽奖。"); return
    cnt = len(lot.get("participants", {})); del DB["lottery"][gid_s]; save_db(DB)
    await send_group_msg(gid, "🚫 抽奖已被取消。")
    await reply(f"✅ 已取消（参与人数: {cnt}）")

async def cmd_roll_help(event, rest=None):
    reply = _reply(event)
    uid = event.get("author", {}).get("id", "")
    if is_owner(uid) or is_bot_admin(uid):
        await reply("🎲 抽奖管理命令请私聊机器人使用。\n\n群成员命令:\n  /joinroll          参与本群抽奖\n  /joinroll list     查看当前参与名单")
    else:
        await reply("🎰 抽奖系统:\n  /joinroll          参与本群抽奖\n  /joinroll list     查看当前参与名单")

async def cmd_roll_add(event, rest):
    """追加名额"""
    reply = _reply(event); parts = rest.strip().split()
    if len(parts) < 2: await reply("❌ 格式: /roll add <群openid> <追加人数>"); return
    gid, n_str = parts[0], parts[1]
    if not n_str.isdigit(): await reply("❌ 人数必须是数字"); return
    gid_s = str(gid); lot = DB.get("lottery", {}).get(gid_s)
    if not lot or not lot.get("active"): await reply("ℹ️ 没有进行中的抽奖。"); return
    add = int(n_str); lot["num_winners"] += add; save_db(DB)
    await send_group_msg(gid, f"📢 名额追加 +{add}！当前总名额: {lot['num_winners']}")
    await reply(f"✅ 已追加 {add} 个名额")

async def cmd_roll_pick(event, rest):
    """指定某人中奖，自动补抽剩余名额"""
    reply = _reply(event); parts = rest.strip().split()
    if len(parts) < 2: await reply("❌ 格式: /roll pick <群openid> <openid>"); return
    gid, target = parts[0], parts[1]; gid_s = str(gid)
    lot = DB.get("lottery", {}).get(gid_s)
    if not lot or not lot.get("active"): await reply("ℹ️ 没有进行中的抽奖。"); return
    if target not in lot.get("participants", {}): await reply("❌ 该用户未参与抽奖。"); return
    participants = lot["participants"]
    winners = lot.setdefault("winners", [])
    if target in winners: await reply("ℹ️ 该用户已中过奖。"); return
    # 指定中奖
    winners.append(target)
    pick_nick = participants[target]
    num_winners = lot["num_winners"]
    slots_left = num_winners - len(winners)
    # 自动补抽剩余名额
    remaining = [q for q in participants if q not in winners]
    auto_winners = []
    if slots_left > 0 and remaining:
        random.shuffle(remaining)
        auto_winners = remaining[:min(slots_left, len(remaining))]
        for w in auto_winners:
            winners.append(w)
    # 生成中奖名单（不区分指定/随机）
    lines = [f"🏆 {pick_nick}({target})"]
    for w in auto_winners:
        lines.append(f"🏆 {participants[w]}({w})")
    lot["auto_drawn"] = True
    save_db(DB)
    await send_group_msg(gid, "🎉 **中奖了！**\n\n" + "\n".join(lines) + f"\n\n恭喜以上 {len(lines)} 位中奖者！")
    await reply(f"✅ 已指定 {pick_nick} 中奖" + (f"，自动补抽 {len(auto_winners)} 人" if auto_winners else ""))

async def cmd_roll_redraw(event, rest):
    """补抽"""
    await cmd_roll_draw(event, rest)

async def cmd_roll_schedule(event, rest):
    """定时开奖（简化版：接受分钟数）"""
    reply = _reply(event); parts = rest.strip().split()
    if len(parts) < 2: await reply("❌ 格式: /roll time <群openid> <分钟数>"); return
    gid, t_str = parts[0], parts[1]; gid_s = str(gid)
    lot = DB.get("lottery", {}).get(gid_s)
    if not lot or not lot.get("active"): await reply("ℹ️ 没有进行中的抽奖。"); return
    if t_str.lower() in ("off", "取消"):
        lot["draw_at"] = None; lot["auto_drawn"] = False; save_db(DB)
        await reply("✅ 已取消定时开奖。")
        return
    dur = parse_duration(t_str)
    if dur is None: await reply("❌ 格式错误。例如: 30m, 2h"); return
    lot["draw_at"] = time.time() + dur; lot["auto_drawn"] = False; save_db(DB)
    await reply(f"✅ 定时开奖已设置（{fmt_duration(dur)} 后）")

# ============================================================
#  命令表
# ============================================================
_GROUP_CMD = (
    (("mute", "禁言"), cmd_mute, None, None),
    (("unmute", "解禁"), cmd_unmute, None, None),
    (("ban", "封禁", "kick", "踢"), cmd_ban, None, None),
    (("unban", "解封"), cmd_unban, None, None),
    (("list", "名单"), cmd_list, None, None),
    (("say", "说"), cmd_say, None, None),
    (("reload", "刷新"), cmd_reload, None, None),
    (("group", "grp", "生效群"), cmd_group, "botadmin", "⛔ 仅Owner/Bot Admin可用。"),
    (("whitelist", "wl", "白名单"), cmd_whitelist, None, None),
    (("welcome", "欢迎"), cmd_welcome, None, None),
    (("black", "拉黑"), cmd_black, "owner", "⛔ 仅Owner可用。"),
    (("unblack", "取消拉黑"), cmd_unblack, "owner", "⛔ 仅Owner可用。"),
    (("blacklist", "黑名单"), cmd_blacklist, None, None),
    (("sid", "session"), cmd_sid, None, None),
    (("pending", "审批"), cmd_pending, "botadmin", "⛔ 仅Owner/Admin可用。"),
    (("joinroll", "参与抽奖", "jr"), cmd_joinroll, None, None),
)
_GA = {a: (h, t, d) for als, h, t, d in _GROUP_CMD for a in als}

# ============================================================
#  消息处理
# ============================================================
async def handle_group_msg(event):
    """处理群 @消息"""
    d = event.get("d", {}); gid = d.get("group_openid", "")
    author = d.get("author", {}); uid = author.get("id", "")
    msg_id = d.get("id", ""); raw = d.get("content", "").strip()
    if not gid or not uid or not group_allowed(gid): return

    content = _strip_at(raw)
    wrapped = {"group_openid": gid, "author": author, "id": msg_id, "content": content}

    prefix = CONFIG.get("command_prefix", "/")
    if is_banned(uid): await send_group_msg(gid, "× 你被拉黑了。"); return
    if content in ("赞我", "/赞我"): await cmd_like(wrapped); return
    if not content.startswith(prefix): return

    body = content[len(prefix):].strip(); parts = body.split(None, 1)
    cmd = parts[0].lower() if parts else ""; rest = parts[1].strip() if len(parts) > 1 else ""

    if cmd in ("help", "帮助", "?", "菜单"):
        await send_group_msg(gid, HELP_FULL if rest.lower() in ("full", "all", "完整") else HELP_SHORT); return

    # 抽奖参与 任意成员
    if cmd in ("joinroll", "参与抽奖", "jr"): await cmd_joinroll(wrapped, rest); return
    # /roll 帮助 任意成员
    if cmd == "roll" and (not rest or rest.split()[0].lower() in ("help", "帮助", "?")):
        await cmd_roll_help(wrapped)
        return
    # /roll 子命令 仅特权
    if cmd == "roll":
        if not (is_owner(uid) or is_bot_admin(uid)): await send_group_msg(gid, "⛔ 仅群管可用。"); return
        sp = rest.split(None, 1); sc = sp[0].lower() if sp else ""; sr = sp[1].strip() if len(sp) > 1 else ""
        if sc in ("create", "创建"): await cmd_roll_create(wrapped, sr)
        elif sc in ("draw", "roll", "开奖"): await cmd_roll_draw(wrapped, sr)
        elif sc in ("redraw", "重抽", "补抽"): await cmd_roll_redraw(wrapped, sr)
        elif sc in ("add", "追加"): await cmd_roll_add(wrapped, sr)
        elif sc in ("pick", "指定"): await cmd_roll_pick(wrapped, sr)
        elif sc in ("cancel", "取消"): await cmd_roll_cancel(wrapped, sr)
        elif sc in ("time", "schedule", "定时"): await cmd_roll_schedule(wrapped, sr)
        else: await cmd_roll_help(wrapped)
        return

    # 权限闸门
    if not (is_owner(uid) or is_bot_admin(uid)):
        await send_group_msg(gid, "⛔ 仅群主/管理员/Owner可用。"); return

    entry = _GA.get(cmd)
    if not entry: await send_group_msg(gid, f"🤔 未知指令 /{cmd}"); return
    handler, tier, deny = entry
    if tier == "owner" and not is_owner(uid): await send_group_msg(gid, deny); return
    if tier == "botadmin" and not is_bot_admin(uid): await send_group_msg(gid, deny); return
    await handler(wrapped, rest)

async def handle_c2c_msg(event):
    """处理私聊消息"""
    d = event.get("d", {}); author = d.get("author", {}); uid = author.get("id", "")
    raw = d.get("content", "").strip()
    wrapped = {"author": author, "id": d.get("id", ""), "content": raw}

    if raw in ("赞我", "/赞我"): await cmd_like(wrapped); return
    if not is_owner(uid) and not is_bot_admin(uid):
        if CONFIG.get("notify_dm", True):
            for oid in CONFIG.get("super_admins_openid", []):
                await send_c2c_msg(oid, f"📬 {uid[:12]}… 私聊: {raw[:80]}")
        return

    prefix = CONFIG.get("command_prefix", "/")
    if not raw.startswith(prefix): return
    body = raw[len(prefix):].strip(); parts = body.split(None, 1)
    cmd = parts[0].lower() if parts else ""; rest = parts[1].strip() if len(parts) > 1 else ""
    reply = _reply(wrapped)

    if cmd in ("help", "帮助"):
        await reply("私聊命令:\n  /admin add|remove|list\n  /group <群ID>\n  /roll create|draw|cancel <群ID>"); return
    if cmd in ("admin", "admins") and is_owner(uid): await reply(await cmd_admin(wrapped, rest)); return
    if cmd in ("group", "grp") and is_bot_admin(uid): await cmd_group(wrapped, rest); return
    if cmd == "roll" and is_owner(uid):
        sp = rest.split(None, 1); sc = sp[0].lower() if sp else ""; sr = sp[1].strip() if len(sp) > 1 else ""
        if sc in ("create", "创建"): await cmd_roll_create(wrapped, sr)
        elif sc in ("draw", "开奖"): await cmd_roll_draw(wrapped, sr)
        elif sc in ("cancel", "取消"): await cmd_roll_cancel(wrapped, sr)
        elif sc in ("add", "追加"): await cmd_roll_add(wrapped, sr)
        elif sc in ("pick", "指定"): await cmd_roll_pick(wrapped, sr)
        elif sc in ("time", "定时"): await cmd_roll_schedule(wrapped, sr)
        elif sc in ("redraw", "补抽"): await cmd_roll_redraw(wrapped, sr)
        else: await cmd_roll_help(wrapped)
        return

# ============================================================
#  WebSocket 网关
# ============================================================
_SEEN = set(); _MAX_SEEN = 5000

async def ws_connect():
    """连接 QQ 官方 WebSocket 网关"""
    token = await get_token()
    # 获取网关地址
    async with aiohttp.ClientSession() as s:
        async with s.get(f"{API_BASE}/gateway", headers={"Authorization": f"QQBot {token}"}) as r:
            gw = (await r.json()).get("url", "")
    print(f"[网关] {gw}")

    # 连接 WebSocket  intents: C2C(1<<12) | GROUP(1<<25) | GUILD_MESSAGES(1<<9)
    INTENTS = (1 << 12) | (1 << 25) | (1 << 9)
    seq = 0; session_id = None
    auth = f"QQBot {await get_token()}"

    async with aiohttp.ClientSession() as s:
        async with s.ws_connect(gw) as ws:
            hb_task = None

            async def heartbeat(interval_ms):
                while True:
                    await asyncio.sleep(interval_ms / 1000 * 0.8)
                    try: await ws.send_json({"op": 1, "d": seq})
                    except: break

            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    p = json.loads(msg.data); op = p.get("op"); seq = p.get("s", seq)
                    if op == 10:  # Hello
                        hi = p["d"]["heartbeat_interval"]
                        print(f"[网关] Hello, 心跳 {hi}ms")
                        hb_task = asyncio.create_task(heartbeat(hi))
                        await ws.send_json({"op": 2, "d": {"token": auth, "intents": INTENTS, "shard": [0, 1], "properties": {}}})
                        print("[网关] Identify 已发送")
                    elif op == 0:  # Dispatch
                        t = p.get("t", "")
                        mid = (p.get("d", {}) or {}).get("id", "")
                        if mid:
                            if mid in _SEEN: continue
                            _SEEN.add(mid)
                            if len(_SEEN) > _MAX_SEEN: _SEEN.clear()
                        try:
                            if t == "GROUP_AT_MESSAGE_CREATE": await handle_group_msg(p)
                            elif t == "C2C_MESSAGE_CREATE": await handle_c2c_msg(p)
                            elif t in ("GUILD_MEMBER_ADD", "GROUP_ADD_ROBOT"):
                                gid = (p.get("d", {}) or {}).get("group_openid", "") or (p.get("d", {}) or {}).get("guild_id", "")
                                if gid:
                                    al = CONFIG.setdefault("allowed_groups_openid", [])
                                    if gid not in al: al.append(gid); save_config(CONFIG)
                                    print(f"[进群] {gid}")
                            elif t in ("GUILD_MEMBER_REMOVE", "GROUP_DEL_ROBOT"):
                                gid = (p.get("d", {}) or {}).get("group_openid", "") or (p.get("d", {}) or {}).get("guild_id", "")
                                if gid in CONFIG.get("allowed_groups_openid", []):
                                    CONFIG["allowed_groups_openid"].remove(gid); save_config(CONFIG)
                                    print(f"[退群] {gid}")
                        except Exception as e:
                            print(f"[事件异常] {t}: {e}")
                    elif op == 11: pass  # Heartbeat ACK
                    elif op == 7: print("[网关] 要求重连"); break
                    elif op == 9:
                        print("[网关] 会话失效，重新 Identify")
                        await ws.send_json({"op": 2, "d": {"token": auth, "intents": INTENTS, "shard": [0, 1], "properties": {}}})
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break
            if hb_task: hb_task.cancel()

# ============================================================
#  后台任务
# ============================================================
async def bg_tasks():
    interval = max(60, CONFIG.get("reapply_interval", 86400))
    while True:
        await asyncio.sleep(interval)
        try:
            now = time.time()
            for k, v in list(DB["mutes"].items()):
                if v["expire"] == 0:
                    await mute_member(v["group_id"], v["user_id"], CONFIG.get("mute_max_seconds", 2592000))
            changed = False
            for tbl in ("bans", "mutes"):
                for k, v in list(DB[tbl].items()):
                    if v["expire"] != 0 and v["expire"] <= now: del DB[tbl][k]; changed = True
            if changed: save_db(DB)
            # 定时开奖
            for gid_s, lot in list(DB.get("lottery", {}).items()):
                if lot.get("draw_at") and not lot.get("auto_drawn") and lot["draw_at"] <= now:
                    import random
                    ps = lot.get("participants", {})
                    if ps:
                        remaining = [k for k in ps if k not in [str(w) for w in lot.get("winners", [])]]
                        if remaining:
                            n = min(lot["num_winners"] - len(lot.get("winners", [])), len(remaining))
                            picked = random.sample(remaining, max(1, n))
                            lot.setdefault("winners", []).extend(picked)
                    lot["auto_drawn"] = True; save_db(DB)
                    await send_group_msg(int(gid_s), f"🎉 定时开奖！中奖者: {', '.join(ps.get(p, p) for p in lot.get('winners', []))}")
        except Exception as e: print(f"[后台] {e}")

# ============================================================
#  主循环
# ============================================================
async def run():
    print("=" * 56)
    print("  QQ 群管理机器人 (官方 API)")
    print(f"  AppID  : {CONFIG.get('appid')}")
    print(f"  Owners : {len(CONFIG.get('super_admins_openid', []))} 人")
    print("=" * 56)

    asyncio.create_task(bg_tasks())

    while True:
        try: await ws_connect()
        except asyncio.CancelledError: raise
        except KeyboardInterrupt: raise
        except Exception as e: print(f"[断开] {e} — 5秒后重连...")
        await asyncio.sleep(5)

if __name__ == "__main__":
    try: asyncio.run(run())
    except KeyboardInterrupt: print("\n[退出]"); sys.exit(0)
    except Exception as e:
        print(f"[致命] {e}"); import traceback; traceback.print_exc(); time.sleep(5); sys.exit(3)
