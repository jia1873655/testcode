# -*- coding: utf-8 -*-
# @Time: 2026/9/8
# @Author: AutoTest
# @Description: CRM 接口封装
# 来源：crm.openapi.json / 分页查询.openapi.json / 状态变更日志 / 四个接口.json
#
# 认证：HTTP Authorization（OpenAPI {{token}}）。
# 仅负责构造请求并返回原始 requests.Response，不包含断言。
import json
import os
from typing import Any, Mapping, Optional

import allure

from lib.common.config import get_env, get_project_config
from lib.common.http_client import HttpClient
from lib.common.logger import get_logger

logger = get_logger(__name__)


def _get_crm_config():
    """获取 CRM 项目配置（延迟初始化，避免循环导入）。"""
    return get_project_config("crm", get_env())


def _normalize_base_url(host: str, path_prefix: str = "") -> str:
    """将 host 与 path_prefix 拼成可用的 base URL。"""
    host = (host or "").strip().rstrip("/")
    if not host:
        return ""
    if not host.startswith(("http://", "https://")):
        host = f"https://{host}"
    prefix = (path_prefix or "").strip()
    if not prefix:
        return host
    if not prefix.startswith("/"):
        prefix = f"/{prefix}"
    prefix = prefix.rstrip("/")
    if host.endswith(prefix):
        return host
    return f"{host}{prefix}"


def _format_authorization(token: str) -> str:
    """将配置中的 token 转成 Authorization 头值。"""
    value = _strip_token(token)
    if not value:
        return ""
    if value.lower().startswith("bearer "):
        return value
    return f"Bearer {value}"


def _strip_token(token: str) -> str:
    """去掉首尾空白和 ini 里误加的引号。"""
    value = (token or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1].strip()
    return value


def get_crm_access_token() -> str:
    """
    读取 CRM 访问 token。

    优先级：
    1. 环境变量 CRM_TOKEN
    2. config/conf_crm_{env}.ini 的 [env] token
    """
    config = _get_crm_config()
    return _strip_token(os.environ.get("CRM_TOKEN") or config.get("env", "token", fallback="") or "")


class CrmApi(HttpClient):
    """CRM 项目接口封装。

    仅负责构造请求并返回原始 requests.Response，不包含任何断言 / 测试逻辑。
    """

    def __init__(self):
        """初始化 CRM API 客户端（从配置读取 host / token）。"""
        self.headers = {}
        config = _get_crm_config()
        host = os.environ.get("CRM_HOST") or config.get("env", "host") or config.get("env", "HOST") or ""
        path_prefix = config.get("env", "path_prefix", fallback="/api/v1") or "/api/v1"
        base_url = _normalize_base_url(host, path_prefix)
        super().__init__(base_url=base_url)
        self.host = base_url
        self.token = get_crm_access_token()

    def common_request(
        self,
        method: str = "GET",
        url: str = "",
        req_json: Any = None,
        params: Optional[Mapping[str, Any]] = None,
        extra_headers: Optional[Mapping[str, str]] = None,
    ):
        """通用请求方法，自动携带 Authorization。

        Args:
            method: HTTP 方法（GET/POST/...）。
            url: 接口路径（以 / 开头，相对 host）。
            req_json: JSON 请求体。
            params: Query 参数字典。
            extra_headers: 附加请求头。

        Returns:
            requests.Response 原始响应，由调用方 / 用例判断状态码。
        """
        if str(url).startswith("http"):
            self.url = str(url)
        else:
            self.url = self.host + url if url.startswith("/") else f"{self.host}/{url}"

        self.method = method.upper()
        self.json = req_json
        self.params = dict(params) if params else None

        authorization = _format_authorization(self.token)
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if authorization:
            self.headers["Authorization"] = authorization
        if extra_headers:
            self.headers.update(extra_headers)

        allure.attach(self.url, name="请求URL", attachment_type=allure.attachment_type.TEXT, extension="txt")
        allure.attach(self.method, name="请求方法", attachment_type=allure.attachment_type.TEXT, extension="txt")
        if self.params:
            allure.attach(
                json.dumps(self.params, ensure_ascii=False),
                name="Query参数",
                attachment_type=allure.attachment_type.JSON,
                extension="json",
            )
        if self.json is not None:
            allure.attach(
                json.dumps(self.json, ensure_ascii=False),
                name="请求报文",
                attachment_type=allure.attachment_type.JSON,
                extension="json",
            )
        return self.send()

    def get_customer_by_id(self, customer_id: Any = None, **query):
        """GET /customer/get_by_id — 根据客户主键查询详情。

        Args:
            customer_id: 客户主键（OpenAPI Query 参数 id，必填）。不传则不带 id，用于缺参校验。
            **query: 额外 Query 参数。
        """
        params = {k: v for k, v in query.items() if v is not None}
        if customer_id is not None:
            params["id"] = customer_id
        return self.common_request(url="/customer/get_by_id", method="GET", params=params or None)

    def page_query_customers(self, body: Optional[Mapping[str, Any]] = None, **fields):
        """POST /customer/page_query — 按筛选条件分页查询客户列表。

        Args:
            body: 完整请求体；与 **fields 合并，fields 覆盖同名字段。
            **fields: scene / page / page_size / customer_name / create_time_range 等。
        """
        payload: dict = dict(body or {})
        payload.update({k: v for k, v in fields.items() if v is not None})
        return self.common_request(url="/customer/page_query", method="POST", req_json=payload)

    def list_business_status_log(self, customer_id: Any = None, **query):
        """GET /customer/business_status_log/list — 按客户 id 查询业务状态变更日志。

        Args:
            customer_id: 客户主键（Query 参数 id，必填）。不传则不带 id，用于缺参校验。
            **query: 额外 Query 参数。
        """
        params = {k: v for k, v in query.items() if v is not None}
        if customer_id is not None:
            params["id"] = customer_id
        return self.common_request(
            url="/customer/business_status_log/list", method="GET", params=params or None
        )

    def list_ownership_status_log(self, customer_id: Any = None, **query):
        """GET /customer/ownership_status_log/list — 按客户 id 查询归属状态变更日志。

        Args:
            customer_id: 客户主键（Query 参数 id，必填）。不传则不带 id，用于缺参校验。
            **query: 额外 Query 参数。
        """
        params = {k: v for k, v in query.items() if v is not None}
        if customer_id is not None:
            params["id"] = customer_id
        return self.common_request(
            url="/customer/ownership_status_log/list", method="GET", params=params or None
        )

    def duplicate_check_customer(self, body: Optional[Mapping[str, Any]] = None, **fields):
        """POST /customer/duplicate_check — 客户手机号/邮箱重复检查。

        Args:
            body: 完整请求体；与 **fields 合并，fields 覆盖同名字段。
            **fields: check_type / value / customer_id 等。
        """
        payload: dict = dict(body or {})
        payload.update({k: v for k, v in fields.items() if v is not None})
        return self.common_request(url="/customer/duplicate_check", method="POST", req_json=payload)

    def get_pending_task_badge(self, scope: Any = None, **query):
        """GET /customer/pending_task_badge — 待办 Tab 角标统计。

        Args:
            scope: 数据范围 mine / all（必填）。不传则不带 scope，用于缺参校验。
            **query: 额外 Query 参数。
        """
        params = {k: v for k, v in query.items() if v is not None}
        if scope is not None:
            params["scope"] = scope
        return self.common_request(
            url="/customer/pending_task_badge", method="GET", params=params or None
        )

    def page_query_pending_link_task(self, body: Optional[Mapping[str, Any]] = None, **fields):
        """POST /pending_link_task/page_query — 待关联/官网待审任务分页查询。

        Args:
            body: 完整请求体；与 **fields 合并，fields 覆盖同名字段。
            **fields: scope / source / page / page_size 等。
        """
        payload: dict = dict(body or {})
        payload.update({k: v for k, v in fields.items() if v is not None})
        return self.common_request(url="/pending_link_task/page_query", method="POST", req_json=payload)

    def page_query_pending_store_task(self, body: Optional[Mapping[str, Any]] = None, **fields):
        """POST /pending_store_task/page_query — 绑店待确认任务分页查询。

        Args:
            body: 完整请求体；与 **fields 合并，fields 覆盖同名字段。
            **fields: page / page_size / shop_name / status 等。
        """
        payload: dict = dict(body or {})
        payload.update({k: v for k, v in fields.items() if v is not None})
        return self.common_request(url="/pending_store_task/page_query", method="POST", req_json=payload)

    def link_search_customers(self, body: Optional[Mapping[str, Any]] = None, **fields):
        """POST /customer/link_search — 关联已有线索检索。

        Args:
            body: 完整请求体；与 **fields 合并，fields 覆盖同名字段。
            **fields: scope / customer_name / email / page / page_size 等。
        """
        payload: dict = dict(body or {})
        payload.update({k: v for k, v in fields.items() if v is not None})
        return self.common_request(url="/customer/link_search", method="POST", req_json=payload)

    def list_pending_attachments(self, draft_id: Any = None, **query):
        """GET /customer/attachment/list_pending — 附件待绑定列表。

        Args:
            draft_id: 表单会话 ID（Query 必填）。不传则不带 draft_id，用于缺参校验。
            **query: 额外 Query 参数。
        """
        params = {k: v for k, v in query.items() if v is not None}
        if draft_id is not None:
            params["draft_id"] = draft_id
        return self.common_request(
            url="/customer/attachment/list_pending", method="GET", params=params or None
        )

    def create_customer_activity_record(self, body: Optional[Mapping[str, Any]] = None, **fields):
        """POST /customer_activity_record/create — 新增客户动态记录。

        Args:
            body: 完整请求体；与 **fields 合并，fields 覆盖同名字段。
            **fields: customer_id / source / content / tags 等。
        """
        payload: dict = dict(body or {})
        payload.update({k: v for k, v in fields.items() if v is not None})
        return self.common_request(
            url="/customer_activity_record/create", method="POST", req_json=payload
        )

    def update_customer_activity_record(self, body: Optional[Mapping[str, Any]] = None, **fields):
        """POST /customer_activity_record/update — 编辑客户动态记录。

        Args:
            body: 完整请求体；与 **fields 合并，fields 覆盖同名字段。
            **fields: id / content / tags 等。
        """
        payload: dict = dict(body or {})
        payload.update({k: v for k, v in fields.items() if v is not None})
        return self.common_request(
            url="/customer_activity_record/update", method="POST", req_json=payload
        )

    def delete_customer_activity_record(self, body: Optional[Mapping[str, Any]] = None, **fields):
        """POST /customer_activity_record/delete — 软删除客户动态记录。

        Args:
            body: 完整请求体；与 **fields 合并，fields 覆盖同名字段。
            **fields: id 等。
        """
        payload: dict = dict(body or {})
        payload.update({k: v for k, v in fields.items() if v is not None})
        return self.common_request(
            url="/customer_activity_record/delete", method="POST", req_json=payload
        )

    def list_customer_activity_records(self, customer_id: Any = None, **query):
        """GET /customer_activity_record/list — 客户动态记录列表。

        Args:
            customer_id: 全量客户 ID（Query 必填）。不传则不带，用于缺参校验。
            **query: page / page_size 等额外 Query。
        """
        params = {k: v for k, v in query.items() if v is not None}
        if customer_id is not None:
            params["customer_id"] = customer_id
        return self.common_request(
            url="/customer_activity_record/list", method="GET", params=params or None
        )

    def get_customer_activity_record_by_id(self, body: Optional[Mapping[str, Any]] = None, **fields):
        """POST /customer_activity_record/get_by_id — 客户动态记录详情。

        Args:
            body: 完整请求体；与 **fields 合并，fields 覆盖同名字段。
            **fields: id 等。
        """
        payload: dict = dict(body or {})
        payload.update({k: v for k, v in fields.items() if v is not None})
        return self.common_request(
            url="/customer_activity_record/get_by_id", method="POST", req_json=payload
        )
