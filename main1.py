# -*- coding: utf8 -*-
import math
import traceback
from datetime import datetime
import pytz
import uuid

import json
import random
import re
import time
import os

import requests
from util.aes_help import encrypt_data, decrypt_data
import util.zepp_helper as zeppHelper

from flask import Flask, request, jsonify

# Flask 应用初始化
app = Flask(__name__)

# ====================== 全局变量初始化（必须放在最前面）======================
time_bj = get_beijing_time() if 'get_beijing_time' in globals() else None
encrypt_support = False
user_tokens = dict()
aes_key = b''
config = {}

# 默认配置（API 模式必须有）
PUSH_PLUS_TOKEN = None
PUSH_PLUS_HOUR = None
PUSH_PLUS_MAX = 30
sleep_seconds = 5.0
use_concurrent = False

# ============================== 工具函数 ==============================
def get_int_value_default(_config: dict, _key, default):
    _config.setdefault(_key, default)
    return int(_config.get(_key))

def get_min_max_by_time(hour=None, minute=None):
    if hour is None:
        hour = time_bj.hour
    if minute is None:
        minute = time_bj.minute
    time_rate = min((hour * 60 + minute) / (22 * 60), 1)
    min_step = get_int_value_default(config, 'MIN_STEP', 18000)
    max_step = get_int_value_default(config, 'MAX_STEP', 25000)
    return int(time_rate * min_step), int(time_rate * max_step)

def fake_ip():
    return f"{223}.{random.randint(64, 117)}.{random.randint(0, 255)}.{random.randint(0, 255)}"

def desensitize_user_name(user):
    user = str(user)
    if len(user) <= 8:
        ln = max(math.floor(len(user) / 3), 1)
        return f'{user[:ln]}***{user[-ln:]}'
    return f'{user[:3]}****{user[-4:]}'

def get_beijing_time():
    target_timezone = pytz.timezone('Asia/Shanghai')
    return datetime.now().astimezone(target_timezone)

def format_now():
    return get_beijing_time().strftime("%Y-%m-%d %H:%M:%S")

def get_time():
    current_time = get_beijing_time()
    return "%.0f" % (current_time.timestamp() * 1000)

def get_access_token(location):
    code_pattern = re.compile("(?<=access=).*?(?=&)")
    result = code_pattern.findall(location)
    return result[0] if result else None

def get_error_code(location):
    code_pattern = re.compile("(?<=error=).*?(?=&)")
    result = code_pattern.findall(location)
    return result[0] if result else None

def push_plus(title, content):
    if not PUSH_PLUS_TOKEN:
        return
    try:
        requests.post("http://www.pushplus.plus/send", data={
            "token": PUSH_PLUS_TOKEN,
            "title": title,
            "content": content,
            "template": "html",
            "channel": "wechat"
        }, timeout=10)
    except:
        pass

# ============================== 核心类 ==============================
class MiMotionRunner:
    def __init__(self, _user, _passwd):
        self.user_id = None
        self.device_id = str(uuid.uuid4())
        self.user = str(_user).strip()
        self.password = str(_passwd).strip()
        self.invalid = False
        self.log_str = ""
        self.is_phone = False

        if not self.user or not self.password:
            self.error = "用户名或密码为空"
            self.invalid = True
            return

        if self.user.startswith("+86") or "@" in self.user:
            pass
        else:
            self.user = "+86" + self.user

        self.is_phone = self.user.startswith("+86")

    def login(self):
        try:
            access_token, msg = zeppHelper.login_access_token(self.user, self.password)
            if not access_token:
                self.log_str += f"登录失败：{msg}"
                return None

            login_token, app_token, user_id, msg = zeppHelper.grant_login_tokens(
                access_token, self.device_id, self.is_phone
            )
            if not app_token:
                self.log_str += f"获取token失败：{msg}"
                return None

            self.user_id = user_id
            return app_token
        except:
            self.log_str += f"登录异常：{traceback.format_exc()}"
            return None

    def login_and_post_steps(self, step):
        if self.invalid:
            return "账号密码错误", False

        app_token = self.login()
        if not app_token:
            return "登录失败", False

        try:
            ok, msg = zeppHelper.post_fake_brand_data(str(step), app_token, self.user_id)
            return f"修改步数 {step} → {msg}", ok
        except:
            return f"提交异常：{traceback.format_exc()}", False

# ============================== 执行逻辑（给API调用）======================
def run_single_api(account, password, step):
    log_str = f"[{format_now()}] 账号：{desensitize_user_name(account)}\n"
    try:
        runner = MiMotionRunner(account, password)
        msg, success = runner.login_and_post_steps(step)
        log_str += runner.log_str + msg
        print(log_str)
        return {"success": success, "message": msg, "account": desensitize_user_name(account)}
    except Exception as e:
        err = f"异常：{str(e)}"
        print(log_str + err)
        return {"success": False, "message": err, "account": desensitize_user_name(account)}

# ============================== API 接口 ==============================
@app.route('/api/brush', methods=['POST'])
def api_brush():
    try:
        data = request.json
        account = data.get("account")
        password = data.get("password")
        step = data.get("step")

        if not all([account, password, step]):
            return jsonify({"success": False, "message": "缺少参数：account/password/step"}), 400

        if not isinstance(step, int) or step <= 0 or step > 99999:
            return jsonify({"success": False, "message": "步数必须是 1~99999 之间的整数"}), 400

        # 执行刷步
        result = run_single_api(account, password, step)
        return jsonify(result)

    except Exception as e:
        return jsonify({"success": False, "message": f"服务器错误：{str(e)}"}), 500

# ============================== 启动服务 ==============================
if __name__ == "__main__":
    # 最后再启动！！！
    app.run(host="0.0.0.0", port=3002, debug=False)
