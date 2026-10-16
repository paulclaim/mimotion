"""有界网络请求及不包含 URL、凭据和响应正文的错误。"""

import time

import requests

REQUEST_TIMEOUT = (5, 20)  # 连接超时、读取超时（秒）
DEFAULT_ATTEMPTS = 3  # 含首次请求在内的总尝试次数
RETRY_BACKOFF = (2, 5)  # 每次重试前的等待秒数，超出则复用最后一档

# 仅"没拿到可用响应"的链路故障才重试；接口返回的状态码和业务错误不在这里。
TRANSIENT_ERRORS = (
    requests.exceptions.Timeout,
    requests.exceptions.ConnectionError,
    requests.exceptions.ChunkedEncodingError,
)


class RequestFailure(RuntimeError):
    pass


def request(method, url, *, attempts=DEFAULT_ATTEMPTS, **kwargs):
    kwargs.setdefault("timeout", REQUEST_TIMEOUT)
    # 带认证的请求不自动跟随跳转，避免向其他地址转发凭据。
    kwargs.setdefault("allow_redirects", False)
    attempts = max(1, int(attempts))
    error = None
    for index in range(attempts):
        try:
            return requests.request(method, url, **kwargs)
        except TRANSIENT_ERRORS as transient:
            error = transient
            if index + 1 >= attempts:
                break
            wait = RETRY_BACKOFF[min(index, len(RETRY_BACKOFF) - 1)]
            print(f"网络瞬时故障（{type(error).__name__}），等待 {wait} 秒后重试 {index + 1}/{attempts - 1}")
            time.sleep(wait)
        except requests.RequestException as failure:
            raise RequestFailure(f"网络请求失败（{type(failure).__name__}）") from None
    raise RequestFailure(f"网络请求失败（{type(error).__name__}）") from None


def response_json(response):
    try:
        payload = response.json()
    except ValueError:
        raise RequestFailure("接口返回无效 JSON") from None
    if not isinstance(payload, dict):
        raise RequestFailure("接口返回的数据格式异常")
    return payload


def require_success_status(response):
    if response.status_code != 200:
        raise RequestFailure(f"接口请求失败（HTTP {response.status_code}）")
