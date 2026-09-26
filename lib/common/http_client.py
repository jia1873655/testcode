"""
HTTP客户端封装 - 统一的HTTP请求工具
"""
import json
import threading
from typing import Dict, Optional, Any, Union

import requests
import urllib3
from lib.common.logger import get_logger

logger = get_logger(__name__)

# 接口自动化不校验对端 HTTPS 证书（过期/自签域名均放行，避免干扰用例结果）
SSL_VERIFY = False
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def apply_no_ssl_verify(session: requests.Session) -> None:
    """为 requests.Session 关闭 TLS 证书校验。"""
    session.verify = SSL_VERIFY


_thread_local = threading.local()


def _truncate(value: Any, max_len: int = 0) -> str:
    """max_len<=0 时不截断（默认完整输出）。"""
    if value is None:
        return ""
    s = str(value)
    if max_len is not None and max_len <= 0:
        return s
    if len(s) <= max_len:
        return s
    return s[:max_len] + f"...(truncated, total={len(s)})"


def _safe_json_dumps(obj: Any, max_len: int = 0) -> str:
    try:
        s = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        s = str(obj)
    return _truncate(s, max_len=max_len)


def get_last_http_call() -> Optional[Dict[str, Any]]:
    """获取当前线程最近一次HTTP调用摘要（供pytest hook等使用）。"""
    return getattr(_thread_local, "last_http_call", None)


def clear_last_http_call() -> None:
    """清理当前线程最近一次HTTP调用摘要。"""
    if hasattr(_thread_local, "last_http_call"):
        delattr(_thread_local, "last_http_call")


def _headers_for_log(headers: Optional[Dict]) -> Dict:
    if not headers:
        return {}
    return dict(headers)


class HttpClient:
    """HTTP客户端"""
    
    def __init__(self, base_url: str = '', timeout: int = 60, default_headers: Optional[Dict] = None):
        """
        初始化HTTP客户端
        
        Args:
            base_url: 基础URL（可选，如果为空则send()方法需要完整URL）
            timeout: 超时时间（秒）
            default_headers: 默认请求头
        """
        self.base_url = base_url.rstrip('/') if base_url else ''
        self.timeout = timeout
        self.session = requests.Session()
        apply_no_ssl_verify(self.session)
        # 保存默认headers，用于send()方法重置
        self._default_headers = dict(default_headers) if default_headers else {}
        if default_headers:
            self.session.headers.update(default_headers)
    
    def _build_url(self, endpoint: str) -> str:
        """构建完整 URL；域名末尾 / 与路径开头 / 可任意组合，不会出现双斜杠。"""
        if endpoint.startswith('http'):
            return endpoint
        if self.base_url:
            base = self.base_url.rstrip('/')
            path = (endpoint or '').lstrip('/')
            return f'{base}/{path}' if path else base
        return endpoint
    
    def request(self, method: str, url: str, return_response: bool = False, **kwargs) -> Union[Dict, requests.Response]:
        """
        统一请求方法
        
        Args:
            method: HTTP方法（GET/POST/PUT/DELETE等）
            url: 请求URL（可以是完整URL或相对路径）
            return_response: 是否返回原始Response对象，默认False返回字典格式
            **kwargs: 其他requests参数（headers, json, params等）
        
        Returns:
            如果return_response=True，返回requests.Response对象
            否则返回统一格式的字典：{'status_code': ..., 'headers': ..., 'json': ..., 'text': ...}
        """
        url = self._build_url(url)
        method_u = method.upper()
        
        try:
            # 记录请求详情用于错误日志
            request_info = {
                'method': method_u,
                'url': url,
                'params': kwargs.get('params'),
                'json': kwargs.get('json'),
                'data': kwargs.get('data'),
                'headers': kwargs.get('headers')
            }
            
            kwargs["verify"] = SSL_VERIFY
            merged_headers = dict(self.session.headers)
            extra = kwargs.get("headers")
            if isinstance(extra, dict):
                merged_headers.update(extra)
            if merged_headers:
                logger.info(
                    f"Request Headers: {_safe_json_dumps(_headers_for_log(merged_headers))}"
                )
            response = self.session.request(method_u, url, timeout=self.timeout, **kwargs)
            # 1) 请求行：方法 + 完整URL + HTTP状态码
            logger.info(f"{method_u} {url} - Status: {response.status_code}")
            # 2) 请求参数（截断，避免刷屏）
            if request_info.get("params") is not None:
                logger.info(f"Request Params: {_safe_json_dumps(request_info.get('params'))}")
            if request_info.get("json") is not None:
                logger.info(f"Request JSON: {_safe_json_dumps(request_info.get('json'))}")
            elif request_info.get("data") is not None:
                logger.info(f"Request Data: {_truncate(request_info.get('data'))}")

            # 3) 响应体：默认完整输出（与平台探针/调试 SSE 一致）
            resp_json = None
            try:
                resp_json = response.json() if response.content else None
            except Exception:
                resp_json = None
            if resp_json is not None:
                logger.info(f"Response JSON: {_safe_json_dumps(resp_json)}")
            else:
                logger.info(f"Response Text: {_truncate(response.text)}")
            
            # 如果需要返回原始Response对象（用于send()方法兼容）
            if return_response:
                return response
            
            # 默认返回统一格式的字典
            response.raise_for_status()
            return {
                'status_code': response.status_code,
                'headers': dict(response.headers),
                'json': response.json() if response.content else {},
                'text': response.text
            }
        except requests.exceptions.RequestException as e:
            # 记录详细的错误信息
            error_msg = (
                f"{method.upper()}请求失败: {str(e)}\n"
                f"URL: {url}\n"
                f"参数: {request_info.get('params')}\n"
                f"JSON: {request_info.get('json')}\n"
                f"Data: {request_info.get('data')}\n"
                f"Headers: {request_info.get('headers')}"
            )
            logger.error(error_msg)
            raise
    
    def get(self, endpoint: str, **kwargs) -> Dict:
        """GET请求"""
        return self.request('GET', endpoint, **kwargs)
    
    def post(self, endpoint: str, **kwargs) -> Dict:
        """POST请求"""
        return self.request('POST', endpoint, **kwargs)
    
    def put(self, endpoint: str, **kwargs) -> Dict:
        """PUT请求"""
        return self.request('PUT', endpoint, **kwargs)
    
    def delete(self, endpoint: str, **kwargs) -> Dict:
        """DELETE请求"""
        return self.request('DELETE', endpoint, **kwargs)
    
    def send(self) -> requests.Response:
        """
        发送请求 - 使用实例属性（兼容数据驱动场景）
        通过设置 self.url, self.method, self.headers, self.json 等属性来发送请求
        
        Returns:
            requests.Response 对象（原始响应，便于灵活处理）
        
        示例:
            client = HttpClient(base_url='https://api.example.com')
            client.url = '/api/users'
            client.method = 'POST'
            client.json = {'name': 'test'}
            response = client.send()
        """
        method = getattr(self, 'method', 'GET').upper()
        url = getattr(self, 'url', '')
        headers = getattr(self, 'headers', {})
        json_data = getattr(self, 'json', None)
        params = getattr(self, 'params', None)
        data = getattr(self, 'data', None)
        
        # URL验证
        if not url or not url.strip():
            raise ValueError("URL不能为空，请设置 self.url 属性")
        
        # 重置session的headers为默认值，避免headers累积
        self.session.headers.clear()
        if self._default_headers:
            self.session.headers.update(self._default_headers)
        
        # 如果设置了headers属性，更新session的headers
        if headers:
            self.set_headers(headers)
            logger.debug(f"设置请求头: {list(headers.keys())}")
        else:
            logger.debug("未设置请求头，self.headers为空")
        
        # 记录最终session的headers（用于调试）
        logger.debug(f"Session headers: {dict(self.session.headers)}")
        
        # 构建请求参数
        request_kwargs = {}
        if json_data is not None:
            request_kwargs['json'] = json_data
        if params is not None:
            request_kwargs['params'] = params
        if data is not None:
            request_kwargs['data'] = data
        
        # 返回原始Response对象（不自动处理状态码，让调用者决定）
        return self.request(method, url, return_response=True, **request_kwargs)
    
    def set_header(self, key: str, value: str):
        """设置请求头"""
        self.session.headers[key] = value
    
    def set_headers(self, headers: Dict):
        """批量设置请求头"""
        self.session.headers.update(headers)
