"""有界网络请求及不包含 URL、凭据和响应正文的错误。"""

import requests

REQUEST_TIMEOUT = (5, 20)  # 连接超时、读取超时（秒）


class RequestFailure(RuntimeError):
    pass


def request(method, url, **kwargs):
    kwargs.setdefault("timeout", REQUEST_TIMEOUT)
    # 带认证的请求不自动跟随跳转，避免向其他地址转发凭据。
    kwargs.setdefault("allow_redirects", False)
    try:
        return requests.request(method, url, **kwargs)
    except requests.RequestException as error:
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
