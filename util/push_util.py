from datetime import datetime
from html import escape
import re

import pytz

from util.http_util import request, response_json, require_success_status
from util.privacy import desensitize_user_name


def get_beijing_time():
    return datetime.now().astimezone(pytz.timezone('Asia/Shanghai'))


def format_now():
    return get_beijing_time().strftime("%Y-%m-%d %H:%M:%S")


class PushConfig:
    def __init__(self, push_plus_token=None, push_plus_hour=None, push_plus_max=30,
                 push_wechat_webhook_key=None, telegram_bot_token=None, telegram_chat_id=None):
        self.push_plus_token = push_plus_token
        self.push_plus_hour = str(push_plus_hour).strip() if push_plus_hour is not None else ''
        self.push_plus_max = int(push_plus_max)
        if self.push_plus_max < 1:
            raise ValueError('PUSH_PLUS_MAX 必须为正整数')
        self.push_wechat_webhook_key = push_wechat_webhook_key
        self.telegram_bot_token = telegram_bot_token
        self.telegram_chat_id = telegram_chat_id


def push_plus(token, title, content):
    data = {'token': token, 'title': title, 'content': content,
            'template': 'html', 'channel': 'wechat'}
    try:
        response = request('POST', 'https://www.pushplus.plus/send', data=data)
        require_success_status(response)
        payload = response_json(response)
        success = payload.get('code') == 200
        print('pushplus推送完毕' if success else 'pushplus推送失败：接口拒绝')
        return success
    except Exception as error:
        # 异常文本可能包含带凭据的 URL，不打印原始错误或响应正文。
        print(f'pushplus推送异常：{type(error).__name__}')
        return False


def push_wechat_webhook(key, title, content):
    payload = {'msgtype': 'markdown_v2',
               'markdown_v2': {'content': buildWeChatContent(title, content)}}
    try:
        response = request('POST', 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send',
                           params={'key': key}, json=payload)
        require_success_status(response)
        success = response_json(response).get('errcode') == 0
        print('企业微信推送完毕' if success else '企业微信推送失败：接口拒绝')
        return success
    except Exception as error:
        print(f'企业微信推送异常：{type(error).__name__}')
        return False


def buildWeChatContent(title, content):
    return f'# {title}\n{content}'


def push_telegram_bot(bot_token, chat_id, content):
    try:
        chat_id = str(chat_id).strip()
        if not chat_id:
            raise ValueError('缺少 chat_id')
        payload = {'chat_id': int(chat_id) if chat_id.lstrip('-').isdigit() else chat_id,
                   'text': content, 'parse_mode': 'HTML'}
        response = request('POST', f'https://api.telegram.org/bot{bot_token}/sendMessage', json=payload)
        require_success_status(response)
        success = response_json(response).get('ok') is True
        print('telegram bot推送完毕' if success else 'telegram bot推送失败：接口拒绝')
        return success
    except Exception as error:
        print(f'telegram bot推送异常：{type(error).__name__}')
        return False


def push_results(exec_results, summary, config):
    # PUSH_PLUS_HOUR 仅控制 PushPlus，其他渠道不受它限制。
    if not not_in_push_time_range(config):
        push_to_push_plus(exec_results, summary, config)
    push_to_wechat_webhook(exec_results, summary, config)
    push_to_telegram_bot(exec_results, summary, config)


def not_in_push_time_range(config):
    hour = config.push_plus_hour
    if not hour or not hour.isdigit() or not 0 <= int(hour) <= 23:
        return False
    time_bj = get_beijing_time()
    if time_bj.hour == int(hour):
        return False
    # 兼容 Actions 延迟：读取随机调度记录的预定整点。
    try:
        with open('cron_change_time', encoding='utf-8') as file:
            lines = file.readlines()
        if lines:
            match = re.search(r'北京时间\((\d+):\d+\)', lines[-1])
            if match and int(match.group(1)) == int(hour):
                return False
    except (OSError, UnicodeError):
        pass
    print(f'当前北京时间整点为 {time_bj.hour}，不执行 PushPlus 推送')
    return True


def _result_text(result):
    user = desensitize_user_name(result['user'])
    status = '成功' if result['success'] is True else '失败'
    return f'账号：{user} 刷步数{status}，接口返回：{result["msg"]}'


def _configured(value):
    return bool(value) and value != 'NO'


def push_to_push_plus(exec_results, summary, config):
    if not _configured(config.push_plus_token):
        print('未配置 PUSH_PLUS_TOKEN 跳过PUSHPLUS推送')
        return
    content = f'<div>{escape(summary)}</div>'
    if len(exec_results) > config.push_plus_max:
        content += '<div>账号数量过多，详细情况请前往github actions中查看</div>'
    else:
        content += '<ul>' + ''.join(f'<li>{escape(_result_text(result))}</li>' for result in exec_results) + '</ul>'
    push_plus(config.push_plus_token, f'{format_now()} 刷步数通知', content)


def push_to_wechat_webhook(exec_results, summary, config):
    if not _configured(config.push_wechat_webhook_key):
        print('未配置 WECHAT_WEBHOOK_KEY 跳过微信推送')
        return
    content = f'## {summary}'
    if len(exec_results) > config.push_plus_max:
        content += '\n- 账号数量过多，详细情况请前往github actions中查看'
    else:
        content += ''.join(f'\n- {_result_text(result)}' for result in exec_results)
    push_wechat_webhook(config.push_wechat_webhook_key, f'{format_now()} 刷步数通知', content)


def push_to_telegram_bot(exec_results, summary, config):
    if not _configured(config.telegram_bot_token) or not config.telegram_chat_id:
        print('未配置 TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID 跳过telegram推送')
        return
    content = f'<b>{escape(summary)}</b>'
    if len(exec_results) > config.push_plus_max:
        content += '<blockquote>账号数量过多，详细情况请前往github actions中查看</blockquote>'
    else:
        content += ''.join(f'\n<pre>{escape(_result_text(result))}</pre>' for result in exec_results)
    push_telegram_bot(config.telegram_bot_token, config.telegram_chat_id, content)
