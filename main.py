# -*- coding: utf8 -*-
import math
from datetime import datetime
import pytz
import uuid

import json
import random
import time
import os
import sys
import tempfile
from pathlib import Path

from util.aes_help import encrypt_token_data, decrypt_token_data
import util.zepp_helper as zeppHelper
import util.push_util as push_util
from util.http_util import RequestFailure
from util.privacy import desensitize_user_name
from util.token_cache import cache_lock, TokenCacheBusy

TOKEN_DATA_PATH = Path(__file__).with_name("encrypted_tokens.data")

try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass

# 获取默认值转int
def get_int_value_default(_config: dict, _key, default):
    _config.setdefault(_key, default)
    return int(_config.get(_key))


# 获取当前时间对应的最大和最小步数
def get_min_max_by_time(hour=None, minute=None):
    if hour is None:
        hour = time_bj.hour
    if minute is None:
        minute = time_bj.minute
    time_rate = min((hour * 60 + minute) / (22 * 60), 1)
    min_step = get_int_value_default(config, 'MIN_STEP', 18000)
    max_step = get_int_value_default(config, 'MAX_STEP', 25000)
    return int(time_rate * min_step), int(time_rate * max_step)


# 获取北京时间
def get_beijing_time():
    target_timezone = pytz.timezone('Asia/Shanghai')
    # 获取当前时间
    return datetime.now().astimezone(target_timezone)


# 格式化时间
def format_now():
    return get_beijing_time().strftime("%Y-%m-%d %H:%M:%S")


# 获取时间戳
def get_time():
    current_time = get_beijing_time()
    return "%.0f" % (current_time.timestamp() * 1000)


class MiMotionRunner:
    def __init__(self, _user, _passwd):
        self.user_id = None
        self.device_id = str(uuid.uuid4())
        user = str(_user)
        password = str(_passwd)
        self.invalid = False
        self.log_str = ""
        if user == '' or password == '':
            self.error = "用户名或密码填写有误！"
            self.invalid = True
        self.password = password
        if (user.startswith("+86")) or "@" in user:
            user = user
        else:
            user = "+86" + user
        if user.startswith("+86"):
            self.is_phone = True
        else:
            self.is_phone = False
        self.user = user

    # 登录
    def login(self):
        user_token_info = user_tokens.get(self.user)
        if user_token_info is not None:
            access_token = user_token_info.get("access_token")
            login_token = user_token_info.get("login_token")
            app_token = user_token_info.get("app_token")
            self.device_id = user_token_info.get("device_id")
            self.user_id = user_token_info.get("user_id")
            if self.device_id is None:
                self.device_id = str(uuid.uuid4())
                user_token_info["device_id"] = self.device_id
            ok, msg = zeppHelper.check_app_token(app_token, self.user_id)
            if ok:
                self.log_str += "使用加密保存的app_token\n"
                return app_token
            else:
                self.log_str += f"app_token失效 重新获取 last grant time: {user_token_info.get('app_token_time')}\n"
                # 检查login_token是否可用
                app_token, msg = (zeppHelper.grant_app_token(login_token)
                                  if self.user_id and login_token else (None, "缓存认证信息不完整"))
                if app_token is None:
                    self.log_str += f"login_token 失效 重新获取 last grant time: {user_token_info.get('login_token_time')}\n"
                    login_token, app_token, user_id, msg = zeppHelper.grant_login_tokens(access_token, self.device_id,
                                                                                         self.is_phone)
                    if login_token is None:
                        self.log_str += f"access_token 已失效：{msg} last grant time:{user_token_info.get('access_token_time')}\n"
                    else:
                        user_token_info["login_token"] = login_token
                        user_token_info["app_token"] = app_token
                        user_token_info["user_id"] = user_id
                        user_token_info["login_token_time"] = get_time()
                        user_token_info["app_token_time"] = get_time()
                        self.user_id = user_id
                        return app_token
                else:
                    self.log_str += "重新获取app_token成功\n"
                    user_token_info["app_token"] = app_token
                    user_token_info["app_token_time"] = get_time()
                    return app_token

        # access_token 失效 或者没有保存加密数据
        access_token, msg = zeppHelper.login_access_token(self.user, self.password)
        if access_token is None:
            self.log_str += "登录获取accessToken失败：%s" % msg
            return None
        login_token, app_token, user_id, msg = zeppHelper.grant_login_tokens(access_token, self.device_id,
                                                                             self.is_phone)
        if login_token is None:
            self.log_str += f"登录提取的 access_token 无效：{msg}"
            return None

        self.user_id = user_id
        user_token_info = dict()
        user_token_info["access_token"] = access_token
        user_token_info["login_token"] = login_token
        user_token_info["app_token"] = app_token
        user_token_info["user_id"] = user_id
        # 记录token获取时间
        user_token_info["access_token_time"] = get_time()
        user_token_info["login_token_time"] = get_time()
        user_token_info["app_token_time"] = get_time()
        if self.device_id is None:
            self.device_id = str(uuid.uuid4())
        user_token_info["device_id"] = self.device_id
        user_tokens[self.user] = user_token_info
        return app_token

    # 主函数
    def login_and_post_step(self, min_step, max_step):
        if self.invalid:
            return "账号或密码配置有误", False
        app_token = self.login()
        if app_token is None:
            return "登陆失败！", False
        if not self.user_id:
            return "登录未返回有效用户ID，已停止上传步数", False

        step = str(random.randint(min_step, max_step))
        self.log_str += f"已设置为随机步数范围({min_step}~{max_step}) 随机值:{step}\n"

        user_token_info = user_tokens.get(self.user, {})
        # 每次确认云端绑定关系；失败时停止本账号，避免把查询故障当作未绑定。
        bound_device_id = zeppHelper.get_user_device_id(app_token, self.user_id, strict=True)
        if bound_device_id:
            user_token_info["bound_device_id"] = bound_device_id
            self.log_str += "查找到已绑定设备ID\n"
        else:
            user_token_info.pop("bound_device_id", None)
            self.log_str += "未查询到绑定设备，回退到默认设备ID；华米上传成功不代表微信同步成功\n"
        user_tokens[self.user] = user_token_info

        ok, msg = zeppHelper.post_fake_brand_data(step, app_token, self.user_id, device_id=bound_device_id)
        return f"修改步数（{step}）[" + msg + "]", ok


def run_single_account(total, idx, user_mi, passwd_mi):
    idx_info = ""
    if idx is not None:
        idx_info = f"[{idx + 1}/{total}]"
    log_str = f"[{format_now()}]\n{idx_info}账号：{desensitize_user_name(user_mi)}\n"
    try:
        runner = MiMotionRunner(user_mi, passwd_mi)
        exec_msg, success = runner.login_and_post_step(min_step, max_step)
        log_str += runner.log_str
        log_str += f'{exec_msg}\n'
        exec_result = {"user": user_mi, "success": success,
                       "msg": exec_msg}
    except Exception as error:
        message = str(error) if isinstance(error, RequestFailure) else type(error).__name__
        log_str += f"执行异常：{message}\n"
        exec_result = {"user": user_mi, "success": False, "msg": f"执行异常：{message}"}
    print(log_str)
    return exec_result


def execute():
    user_list = users.split('#')
    passwd_list = passwords.split('#')
    exec_results = []
    if len(user_list) == len(passwd_list):
        idx, total = 0, len(user_list)
        if use_concurrent:
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                exec_results = executor.map(lambda x: run_single_account(total, x[0], *x[1]),
                                            enumerate(zip(user_list, passwd_list)))
        else:
            for user_mi, passwd_mi in zip(user_list, passwd_list):
                exec_results.append(run_single_account(total, idx, user_mi, passwd_mi))
                idx += 1
                if idx < total:
                    # 每个账号之间间隔一定时间请求一次，避免接口请求过于频繁导致异常
                    time.sleep(sleep_seconds)
        if encrypt_support:
            persist_user_tokens()
        success_count = 0
        push_results = []
        for result in exec_results:
            push_results.append(result)
            if result['success'] is True:
                success_count += 1
        summary = f"\n执行账号总数{total}，成功：{success_count}，失败：{total - success_count}"
        print(summary)
        push_util.push_results(push_results, summary, push_config)
        return 0 if success_count == total else 1
    else:
        print(f"账号数长度[{len(user_list)}]和密码数长度[{len(passwd_list)}]不匹配，跳过执行")
        return 1


def prepare_user_tokens() -> dict:
    if not TOKEN_DATA_PATH.exists():
        return {}
    try:
        decrypted = decrypt_token_data(TOKEN_DATA_PATH.read_bytes(), aes_key)
        data = json.loads(decrypted.decode('utf-8'))
        if not isinstance(data, dict) or any(not isinstance(value, dict) for value in data.values()):
            raise ValueError("缓存格式异常")
        return data
    except (ValueError, TypeError, UnicodeError):
        print("密钥不正确或者加密内容损坏 放弃token")
        return {}


def persist_user_tokens():
    plain = json.dumps(user_tokens, ensure_ascii=False).encode('utf-8')
    cipher = encrypt_token_data(plain, aes_key)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=TOKEN_DATA_PATH.parent, prefix='.tokens-', delete=False) as file:
            temporary_path = Path(file.name)
            file.write(cipher)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_path, TOKEN_DATA_PATH)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def validate_config(config):
    if not isinstance(config, dict):
        raise ValueError("CONFIG 必须为 JSON 对象")
    for field in ('USER', 'PWD'):
        if not isinstance(config.get(field), str) or any(not value for value in config[field].split('#')):
            raise ValueError(f"{field} 必须为非空字符串，各账号配置不能留空")
    if len(config['USER'].split('#')) != len(config['PWD'].split('#')):
        raise ValueError("账号和密码数量不匹配")
    for field, default in (('MIN_STEP', 18000), ('MAX_STEP', 25000), ('PUSH_PLUS_MAX', 30)):
        try:
            value = config.get(field, default)
            config[field] = int(str(value))
        except (TypeError, ValueError):
            raise ValueError(f"{field} 必须为整数") from None
    if not 0 <= config['MIN_STEP'] <= config['MAX_STEP']:
        raise ValueError("步数范围必须满足 0 <= MIN_STEP <= MAX_STEP")
    if config['PUSH_PLUS_MAX'] < 1:
        raise ValueError("PUSH_PLUS_MAX 必须为正整数")
    try:
        sleep_gap = config.get('SLEEP_GAP', 5)
        config['SLEEP_GAP'] = float(5 if sleep_gap is None or sleep_gap == '' else sleep_gap)
    except (TypeError, ValueError):
        raise ValueError("SLEEP_GAP 必须为非负数") from None
    if not math.isfinite(config['SLEEP_GAP']) or config['SLEEP_GAP'] < 0:
        raise ValueError("SLEEP_GAP 必须为有限非负数")
    concurrent = config.get('USE_CONCURRENT', False)
    if isinstance(concurrent, bool):
        config['USE_CONCURRENT'] = concurrent
    elif isinstance(concurrent, str) and concurrent.lower() in ('true', 'false', ''):
        config['USE_CONCURRENT'] = concurrent.lower() == 'true'
    else:
        raise ValueError("USE_CONCURRENT 必须为布尔值或 True/False 字符串")
    return config


def main():
    global time_bj, encrypt_support, user_tokens, aes_key, config
    global push_config, sleep_seconds, users, passwords, min_step, max_step, use_concurrent
    time_bj = get_beijing_time()
    aes_key = os.environ.get('AES_KEY', '').encode('utf-8')
    encrypt_support = len(aes_key) == 16
    user_tokens = {}
    if aes_key and not encrypt_support:
        print("AES_KEY 无效，无法使用加密保存功能")
    try:
        if 'CONFIG' in os.environ:
            config = json.loads(os.environ['CONFIG'])
        elif 'USER' in os.environ and 'PWD' in os.environ:
            defaults = {'MIN_STEP': '18000', 'MAX_STEP': '25000', 'PUSH_PLUS_MAX': '30',
                        'SLEEP_GAP': '5', 'USE_CONCURRENT': 'False'}
            fields = ('USER', 'PWD', 'MIN_STEP', 'MAX_STEP', 'PUSH_PLUS_TOKEN', 'PUSH_PLUS_HOUR',
                      'PUSH_PLUS_MAX', 'PUSH_WECHAT_WEBHOOK_KEY', 'TELEGRAM_BOT_TOKEN',
                      'TELEGRAM_CHAT_ID', 'SLEEP_GAP', 'USE_CONCURRENT')
            config = {field: os.environ.get(field, defaults.get(field, '')) for field in fields}
        else:
            print("未配置CONFIG或USER/PWD环境变量，无法执行")
            return 1
        config = validate_config(config)
    except json.JSONDecodeError:
        print("CONFIG 格式不正确，请检查 JSON 语法")
        return 1
    except ValueError as error:
        print(f"配置错误：{error}")
        return 1
    push_config = push_util.PushConfig(
        push_plus_token=config.get('PUSH_PLUS_TOKEN'),
        push_plus_hour=config.get('PUSH_PLUS_HOUR'),
        push_plus_max=config['PUSH_PLUS_MAX'],
        push_wechat_webhook_key=config.get('PUSH_WECHAT_WEBHOOK_KEY'),
        telegram_bot_token=config.get('TELEGRAM_BOT_TOKEN'),
        telegram_chat_id=config.get('TELEGRAM_CHAT_ID'))
    sleep_seconds = config['SLEEP_GAP']
    users, passwords = config['USER'], config['PWD']
    min_step, max_step = get_min_max_by_time()
    use_concurrent = config['USE_CONCURRENT']
    if not use_concurrent:
        print(f"多账号执行间隔：{sleep_seconds}")
    if encrypt_support:
        with cache_lock(TOKEN_DATA_PATH):
            user_tokens = prepare_user_tokens()
            return execute()
    return execute()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except TokenCacheBusy as error:
        print(str(error))
        sys.exit(1)
    except Exception as error:
        print(f"运行失败：{type(error).__name__}")
        sys.exit(1)
