# -*- coding: utf-8 -*-
# @Time: 2026/9/8
# @Author: AutoTest
# @Description: CRM 客户接口测试用例
# 来源：crm.openapi.json / 分页查询.openapi.json / 四个接口.json / 最后2个.json
#
# 安全约定：当前用例只覆盖只读查询与校验类接口，不调用新增 / 编辑 / 导出 / 永久删除。
import copy
import json
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import allure
import pytest
import yaml

from lib.common.config import get_env, get_project_config
from lib.common.logger import get_logger
from services.crm.crm_api import CrmApi

logger = get_logger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DATA_FILE = _PROJECT_ROOT / "data" / "crmdata" / "crmdata.yaml"


def _load_crmdata() -> Dict[str, Any]:
    """读取 data/crmdata/crmdata.yaml。"""
    with _DATA_FILE.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _attach(res):
    """统一记录响应报文到 Allure（JSON 优先，异常回退 TEXT）。"""
    try:
        allure.attach(
            json.dumps(res.json(), ensure_ascii=False, indent=2),
            name="响应报文",
            attachment_type=allure.attachment_type.JSON,
        )
    except Exception:
        allure.attach(res.text or "", name="响应报文(TEXT)", attachment_type=allure.attachment_type.TEXT)


def _parse_json(res) -> Optional[Dict[str, Any]]:
    """解析 JSON 对象响应；非法 JSON 返回 None。"""
    try:
        payload = res.json()
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _unwrap_customer(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """兼容根对象直出与 {data: {...}} 两种响应。"""
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    if isinstance(data, dict) and (
        "id" in data or "customer_name" in data or "referrer_commission_basis" in data
    ):
        return data
    return payload


def _unwrap_page(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """兼容分页结果根对象直出与 {data: {list,total,...}}。"""
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    if isinstance(data, dict) and ("list" in data or "total" in data):
        return data
    if "list" in payload or "total" in payload:
        return payload
    return data if isinstance(data, dict) else {}


def _unwrap_status_log(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """兼容状态日志根对象直出与 {data: {customer_id,list,...}}。"""
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    if isinstance(data, dict) and ("customer_id" in data or "list" in data):
        return data
    if "customer_id" in payload or ("list" in payload and "customer_name" in payload):
        return payload
    return data if isinstance(data, dict) else {}


def _unwrap_duplicate(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """兼容重复检查根对象直出与 {data: {is_duplicated}}。"""
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    if isinstance(data, dict) and "is_duplicated" in data:
        return data
    if "is_duplicated" in payload:
        return payload
    return data if isinstance(data, dict) else {}


def _unwrap_badge(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """兼容待办角标根对象直出与 {data: {pending_link_count,...}}。"""
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    if isinstance(data, dict) and "pending_link_count" in data:
        return data
    if "pending_link_count" in payload:
        return payload
    return data if isinstance(data, dict) else {}


def _normalize_list(value: Any) -> List[Any]:
    """将 list / null 归一为列表。"""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return []


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _type_ok(value: Any, expected: str) -> bool:
    if expected == "int":
        return _is_int(value)
    if expected == "str":
        return isinstance(value, str)
    if expected == "list":
        return isinstance(value, list)
    if expected == "bool":
        return isinstance(value, bool)
    return True


def _as_status_list(value: Any) -> List[int]:
    if isinstance(value, list):
        return [int(item) for item in value]
    return [int(value)]


def _success_codes(case: Dict[str, Any]) -> List[Any]:
    codes = case.get("success_codes") or [0, 200]
    return list(codes)


def _is_business_error(payload: Optional[Dict[str, Any]], success_codes: List[Any]) -> bool:
    if not isinstance(payload, dict):
        return True
    if payload.get("success") is False:
        return True
    if payload.get("error") not in (None, "", False):
        return True
    if "code" in payload and payload.get("code") not in success_codes:
        return True
    return False


def _require_token(api: CrmApi):
    if not api.token:
        pytest.skip("未配置 CRM token：请设置 CRM_TOKEN 或 config/conf_crm_test.ini [env] token")


def _require_host(api: CrmApi):
    if not api.host:
        pytest.skip("未配置 CRM host：请设置 CRM_HOST 或 config/conf_crm_test.ini [env] host")


def _valid_customer_id(crm_config, case: Dict[str, Any]) -> int:
    raw = crm_config.get("customer", "id", fallback="") or ""
    if str(raw).strip():
        return int(raw)
    return int(case.get("id"))


def _invalid_id_cases():
    data = _load_crmdata().get("get_by_id") or {}
    cases = data.get("invalid_ids") or []
    return [
        pytest.param(item.get("id"), item.get("expected_http_status"), id=item.get("title") or str(item.get("id")))
        for item in cases
    ]


def _page_query_body(crm_config, crmdata: Dict[str, Any], case_key: str = "valid") -> Dict[str, Any]:
    """组装分页查询请求体：数据文件为底，配置覆盖关键字段。"""
    section = crmdata.get("page_query") or {}
    body = copy.deepcopy(section.get(case_key) or {})
    scene = crm_config.get("page_query", "scene", fallback="")
    page = crm_config.get("page_query", "page", fallback="")
    page_size = crm_config.get("page_query", "page_size", fallback="")
    start = crm_config.get("page_query", "create_time_start", fallback="")
    end = crm_config.get("page_query", "create_time_end", fallback="")
    if str(scene).strip():
        body["scene"] = int(scene)
    if str(page).strip():
        body["page"] = int(page)
    if str(page_size).strip() and case_key != "invalid_page_size":
        body["page_size"] = int(page_size)
    if str(start).strip() or str(end).strip():
        time_range = dict(body.get("create_time_range") or {})
        if str(start).strip():
            time_range["start"] = start
        if str(end).strip():
            time_range["end"] = end
        body["create_time_range"] = time_range
    return body


def _pending_link_body(crm_config, crmdata: Dict[str, Any], case_key: str) -> Dict[str, Any]:
    """组装待关联/官网待审任务分页请求体。"""
    section = crmdata.get("pending_link_task") or {}
    body = copy.deepcopy(section.get(case_key) or {})
    scope = crm_config.get("pending_link_task", "scope", fallback="")
    source = crm_config.get("pending_link_task", "source", fallback="")
    page = crm_config.get("pending_link_task", "page", fallback="")
    page_size = crm_config.get("pending_link_task", "page_size", fallback="")
    if case_key.startswith("valid_") and str(scope).strip() and "scope" in body:
        # 仅覆盖 valid_all_* 的 scope/source；valid_mine 保持 mine
        if body.get("scope") == "all" and scope == "all":
            body["scope"] = scope
            if str(source).strip() and case_key == "valid_all_link":
                body["source"] = int(source)
    if str(page).strip() and "page" in body:
        body["page"] = int(page)
    if str(page_size).strip() and "page_size" in body:
        body["page_size"] = int(page_size)
    return body


def _pending_store_body(crm_config, crmdata: Dict[str, Any], case_key: str = "valid") -> Dict[str, Any]:
    """组装绑店待确认任务分页请求体。"""
    section = crmdata.get("pending_store_task") or {}
    body = copy.deepcopy(section.get(case_key) or {})
    page = crm_config.get("pending_store_task", "page", fallback="")
    page_size = crm_config.get("pending_store_task", "page_size", fallback="")
    if str(page).strip() and "page" in body:
        body["page"] = int(page)
    if str(page_size).strip() and "page_size" in body:
        body["page_size"] = int(page_size)
    return body


def _link_search_body(crm_config, crmdata: Dict[str, Any], case_key: str) -> Dict[str, Any]:
    """组装关联已有线索检索请求体。"""
    section = crmdata.get("link_search") or {}
    body = copy.deepcopy(section.get(case_key) or {})
    scope = crm_config.get("link_search", "scope", fallback="")
    page = crm_config.get("link_search", "page", fallback="")
    page_size = crm_config.get("link_search", "page_size", fallback="")
    name = crm_config.get("link_search", "customer_name", fallback="")
    empty_name = crm_config.get("link_search", "empty_customer_name", fallback="")
    if case_key == "valid_all" and str(scope).strip():
        body["scope"] = scope
    if str(page).strip() and "page" in body:
        body["page"] = int(page)
    if str(page_size).strip() and "page_size" in body:
        body["page_size"] = int(page_size)
    if case_key == "valid_all" and str(name).strip():
        body["customer_name"] = name
    if case_key == "empty_result" and str(empty_name).strip():
        body["customer_name"] = empty_name
    return body


def _assert_page_success(res, section: Dict[str, Any], expected_page: Any = None, expected_page_size: Any = None):
    """分页类接口公共断言：HTTP / code / list/total/page/page_size。"""
    expected_status = int(section.get("expected_http_status") or 200)
    success_codes = _success_codes(section)
    pytest.assume(
        res.status_code == expected_status,
        f"HTTP 状态码不匹配: 期望 {expected_status}, 实际 {res.status_code}",
    )
    payload = _parse_json(res)
    pytest.assume(isinstance(payload, dict), "响应应为 JSON 对象")
    if not isinstance(payload, dict):
        return {}, {}
    if "code" in payload:
        pytest.assume(
            payload.get("code") in success_codes,
            f"业务 code 应为 {success_codes}, 实际 {payload.get('code')}",
        )
    page_data = _unwrap_page(payload)
    for field in section.get("response_fields") or []:
        pytest.assume(field in page_data, f"分页结果应包含字段: {field}")
    items = page_data.get("list")
    pytest.assume(items is None or isinstance(items, list), "data.list 应为列表或 null")
    pytest.assume(_is_int(page_data.get("total")), f"total 应为整数, 实际 {page_data.get('total')!r}")
    if expected_page is not None:
        pytest.assume(page_data.get("page") == expected_page, f"page 应回显 {expected_page}")
    if expected_page_size is not None:
        pytest.assume(
            page_data.get("page_size") == expected_page_size,
            f"page_size 应回显 {expected_page_size}",
        )
    return payload, page_data


def _unwrap_attachment_list(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """兼容附件待绑定列表根对象直出与 {data: {list}}。"""
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    if isinstance(data, dict) and "list" in data:
        return data
    if "list" in payload and "page" not in payload and "total" not in payload:
        return payload
    return data if isinstance(data, dict) else {}


@pytest.fixture(scope="module")
def api():
    """CRM API 客户端。"""
    return CrmApi()


@pytest.fixture(scope="module")
def crm_config():
    """CRM 项目配置。"""
    return get_project_config("crm", get_env())


@pytest.fixture(scope="module")
def crmdata() -> Dict[str, Any]:
    """CRM 数据文件。"""
    return _load_crmdata()


@allure.feature("CRM")
@allure.story("Customer 客户详情")
class TestCustomerGetById:
    """GET /customer/get_by_id。"""

    @pytest.mark.smoke
    @pytest.mark.p0
    @allure.title("根据 ID 获取客户详情")
    def test_get_customer_by_id(self, api, crm_config, crmdata):
        _require_host(api)
        _require_token(api)
        case = (crmdata.get("get_by_id") or {}).get("valid") or {}
        customer_id = _valid_customer_id(crm_config, case)
        expected_status = int(case.get("expected_http_status") or 200)
        success_codes = _success_codes(case)

        res = api.get_customer_by_id(customer_id)
        _attach(res)
        pytest.assume(
            res.status_code == expected_status,
            f"HTTP 状态码不匹配: 期望 {expected_status}, 实际 {res.status_code}",
        )
        payload = _parse_json(res)
        pytest.assume(isinstance(payload, dict), "响应应为 JSON 对象")
        if not isinstance(payload, dict):
            return
        if "code" in payload:
            pytest.assume(
                payload.get("code") in success_codes,
                f"业务 code 应为 {success_codes}, 实际 {payload.get('code')}",
            )
        customer = _unwrap_customer(payload)
        pytest.assume(isinstance(customer, dict), "客户详情应为对象")
        pytest.assume(
            customer.get("id") == customer_id,
            f"返回 id 应为 {customer_id}, 实际 {customer.get('id')}",
        )
        for field in case.get("required_fields") or []:
            pytest.assume(field in customer, f"详情应包含字段: {field}")
        logger.info(f"客户详情 id={customer.get('id')}, name={customer.get('customer_name')}")

    @pytest.mark.p1
    @allure.title("客户详情字段类型与必填项")
    def test_get_customer_by_id_schema(self, api, crm_config, crmdata):
        _require_host(api)
        _require_token(api)
        case = (crmdata.get("get_by_id") or {}).get("valid") or {}
        customer_id = _valid_customer_id(crm_config, case)
        res = api.get_customer_by_id(customer_id)
        _attach(res)
        pytest.assume(res.status_code == 200, f"HTTP 状态码不匹配: 期望 200, 实际 {res.status_code}")
        payload = _parse_json(res)
        pytest.assume(isinstance(payload, dict), "响应应为 JSON 对象")
        customer = _unwrap_customer(payload)
        field_types = case.get("field_types") or {}
        for field, expected_type in field_types.items():
            if field not in customer or customer.get(field) is None:
                continue
            value = customer.get(field)
            pytest.assume(
                _type_ok(value, expected_type),
                f"{field} 类型应为 {expected_type}, 实际 {type(value).__name__}={value!r}",
            )
        attachments = customer.get("attachments")
        if isinstance(attachments, list) and attachments:
            item_types = case.get("attachment_item_types") or {}
            first = attachments[0]
            pytest.assume(isinstance(first, dict), "attachments[0] 应为对象")
            for field, expected_type in item_types.items():
                if not isinstance(first, dict) or field not in first or first.get(field) is None:
                    continue
                value = first.get(field)
                pytest.assume(
                    _type_ok(value, expected_type),
                    f"attachments[0].{field} 类型应为 {expected_type}, 实际 {type(value).__name__}",
                )

    @pytest.mark.p1
    @allure.title("客户详情 - 不存在的 ID")
    def test_get_customer_by_id_not_found(self, api, crmdata):
        _require_host(api)
        _require_token(api)
        case = (crmdata.get("get_by_id") or {}).get("not_found") or {}
        valid = (crmdata.get("get_by_id") or {}).get("valid") or {}
        customer_id = case.get("id")
        expected_status = _as_status_list(case.get("expected_http_status") or [400, 404, 500])
        res = api.get_customer_by_id(customer_id)
        _attach(res)
        payload = _parse_json(res)
        customer = _unwrap_customer(payload)
        not_found = (
            res.status_code in expected_status
            or _is_business_error(payload, _success_codes(valid))
            or customer.get("id") != customer_id
        )
        pytest.assume(
            not_found,
            f"不存在的 id 应返回错误, 实际 HTTP {res.status_code}, body={payload}",
        )
        logger.info(f"客户不存在 HTTP {res.status_code}: {(payload or {}).get('message') or (payload or {}).get('msg')}")

    @pytest.mark.p1
    @allure.title("客户详情 - 缺少必填参数 id")
    def test_get_customer_by_id_missing_id(self, api, crmdata):
        _require_host(api)
        _require_token(api)
        case = (crmdata.get("get_by_id") or {}).get("missing_id") or {}
        valid = (crmdata.get("get_by_id") or {}).get("valid") or {}
        expected_status = _as_status_list(case.get("expected_http_status") or [400, 500])
        res = api.get_customer_by_id()
        _attach(res)
        payload = _parse_json(res)
        pytest.assume(
            res.status_code in expected_status or _is_business_error(payload, _success_codes(valid)),
            f"缺少 id 应校验失败, 实际 HTTP {res.status_code}, body={payload}",
        )

    @pytest.mark.p1
    @pytest.mark.parametrize("invalid_id, expected_http_status", _invalid_id_cases())
    def test_get_customer_by_id_invalid_id(self, api, crmdata, invalid_id, expected_http_status):
        allure.dynamic.title(f"客户详情 - 非法 id={invalid_id!r}")
        _require_host(api)
        _require_token(api)
        valid = (crmdata.get("get_by_id") or {}).get("valid") or {}
        expected_status = _as_status_list(expected_http_status or [400, 500])
        res = api.get_customer_by_id(invalid_id)
        _attach(res)
        payload = _parse_json(res)
        pytest.assume(
            res.status_code in expected_status or _is_business_error(payload, _success_codes(valid)),
            f"非法 id={invalid_id!r} 应校验失败, 实际 HTTP {res.status_code}, body={payload}",
        )


@allure.feature("CRM")
@allure.story("Customer 客户分页查询")
class TestCustomerPageQuery:
    """POST /customer/page_query。"""

    @pytest.mark.smoke
    @pytest.mark.p0
    @allure.title("客户分页查询 - 全部客户首屏")
    def test_page_query_customers(self, api, crm_config, crmdata):
        _require_host(api)
        _require_token(api)
        section = crmdata.get("page_query") or {}
        body = _page_query_body(crm_config, crmdata, "valid")
        expected_status = int(section.get("expected_http_status") or 200)
        success_codes = _success_codes(section)

        res = api.page_query_customers(body)
        _attach(res)
        pytest.assume(
            res.status_code == expected_status,
            f"HTTP 状态码不匹配: 期望 {expected_status}, 实际 {res.status_code}",
        )
        payload = _parse_json(res)
        pytest.assume(isinstance(payload, dict), "响应应为 JSON 对象")
        if not isinstance(payload, dict):
            return
        if "code" in payload:
            pytest.assume(
                payload.get("code") in success_codes,
                f"业务 code 应为 {success_codes}, 实际 {payload.get('code')}",
            )
        page_data = _unwrap_page(payload)
        for field in section.get("response_fields") or []:
            pytest.assume(field in page_data, f"分页结果应包含字段: {field}")
        items = page_data.get("list")
        pytest.assume(isinstance(items, list), "data.list 应为列表")
        pytest.assume(_is_int(page_data.get("total")), f"total 应为整数, 实际 {page_data.get('total')!r}")
        pytest.assume(page_data.get("page") == body.get("page"), f"page 应回显 {body.get('page')}")
        pytest.assume(
            page_data.get("page_size") == body.get("page_size"),
            f"page_size 应回显 {body.get('page_size')}",
        )
        logger.info(f"分页查询 total={page_data.get('total')}, 本页={len(items or [])}")

    @pytest.mark.p1
    @allure.title("客户分页查询 - 列表项字段类型")
    def test_page_query_list_item_schema(self, api, crm_config, crmdata):
        _require_host(api)
        _require_token(api)
        section = crmdata.get("page_query") or {}
        body = _page_query_body(crm_config, crmdata, "valid")
        res = api.page_query_customers(body)
        _attach(res)
        pytest.assume(res.status_code == 200, f"HTTP 状态码不匹配: 期望 200, 实际 {res.status_code}")
        page_data = _unwrap_page(_parse_json(res))
        items = page_data.get("list") or []
        if not items:
            pytest.skip("当前筛选条件下列表为空，跳过字段类型校验")
        first = items[0]
        pytest.assume(isinstance(first, dict), "list[0] 应为对象")
        for field in section.get("list_item_required_fields") or []:
            pytest.assume(field in first, f"list[0] 应包含字段: {field}")
        for field, expected_type in (section.get("list_item_field_types") or {}).items():
            if field not in first or first.get(field) is None:
                continue
            value = first.get(field)
            pytest.assume(
                _type_ok(value, expected_type),
                f"list[0].{field} 类型应为 {expected_type}, 实际 {type(value).__name__}={value!r}",
            )

    @pytest.mark.p1
    @allure.title("客户分页查询 - 按客户名模糊筛选")
    def test_page_query_filter_by_customer_name(self, api, crm_config, crmdata):
        _require_host(api)
        _require_token(api)
        section = crmdata.get("page_query") or {}
        keyword = (
            crm_config.get("page_query", "customer_name", fallback="")
            or "测试090103"
        ).strip()
        body = _page_query_body(crm_config, crmdata, "filter_by_name")
        body["customer_name"] = keyword
        res = api.page_query_customers(body)
        _attach(res)
        pytest.assume(res.status_code == 200, f"HTTP 状态码不匹配: 期望 200, 实际 {res.status_code}")
        payload = _parse_json(res)
        if "code" in (payload or {}):
            pytest.assume(
                payload.get("code") in _success_codes(section),
                f"业务 code 应为 {_success_codes(section)}, 实际 {payload.get('code')}",
            )
        page_data = _unwrap_page(payload)
        items = page_data.get("list") or []
        pytest.assume(isinstance(items, list), "data.list 应为列表")
        pytest.assume(len(items) > 0, f"按客户名 '{keyword}' 筛选结果不应为空")
        for idx, item in enumerate(items):
            name = item.get("customer_name") or ""
            pytest.assume(
                keyword in name,
                f"[idx={idx}] customer_name 应包含 '{keyword}', 实际 '{name}'",
            )

    @pytest.mark.p1
    @allure.title("客户分页查询 - 空结果")
    def test_page_query_empty_result(self, api, crm_config, crmdata):
        _require_host(api)
        _require_token(api)
        section = crmdata.get("page_query") or {}
        empty_name = (
            crm_config.get("page_query", "empty_customer_name", fallback="")
            or "__autotest_no_such_customer_xyz__"
        ).strip()
        body = _page_query_body(crm_config, crmdata, "empty_result")
        body["customer_name"] = empty_name
        res = api.page_query_customers(body)
        _attach(res)
        pytest.assume(res.status_code == 200, f"HTTP 状态码不匹配: 期望 200, 实际 {res.status_code}")
        payload = _parse_json(res)
        if "code" in (payload or {}):
            pytest.assume(
                payload.get("code") in _success_codes(section),
                f"业务 code 应为 {_success_codes(section)}, 实际 {payload.get('code')}",
            )
        page_data = _unwrap_page(payload)
        items = page_data.get("list")
        total = page_data.get("total")
        # 后端空结果可能返回 list=null 或 []
        empty_list = items is None or items == []
        pytest.assume(empty_list, f"空结果 list 应为 null/[] , 实际 {items!r}")
        pytest.assume(total == 0, f"空结果 total 应为 0, 实际 {total}")

    @pytest.mark.p1
    @allure.title("客户分页查询 - 缺少 scene")
    def test_page_query_missing_scene(self, api, crmdata):
        _require_host(api)
        _require_token(api)
        section = crmdata.get("page_query") or {}
        body = copy.deepcopy((section.get("missing_scene") or {}))
        res = api.page_query_customers(body)
        _attach(res)
        payload = _parse_json(res)
        pytest.assume(
            res.status_code in (400, 500) or _is_business_error(payload, _success_codes(section)),
            f"缺少 scene 应校验失败, 实际 HTTP {res.status_code}, body={payload}",
        )

    @pytest.mark.p1
    @allure.title("客户分页查询 - page_size 为 0 回落到默认值")
    def test_page_query_invalid_page_size(self, api, crm_config, crmdata):
        _require_host(api)
        _require_token(api)
        section = crmdata.get("page_query") or {}
        body = _page_query_body(crm_config, crmdata, "invalid_page_size")
        body["page_size"] = 0
        res = api.page_query_customers(body)
        _attach(res)
        payload = _parse_json(res)
        page_data = _unwrap_page(payload)
        # 实测：page_size=0 时业务成功，并回落到默认 20
        if "code" in (payload or {}):
            pytest.assume(
                payload.get("code") in _success_codes(section),
                f"业务 code 应为 {_success_codes(section)}, 实际 {payload.get('code')}",
            )
        pytest.assume(
            page_data.get("page_size") == 20,
            f"page_size=0 应回落到默认 20, 实际 {page_data.get('page_size')}",
        )
        logger.info(
            f"page_size=0 响应 HTTP {res.status_code}, page_size={page_data.get('page_size')}, "
            f"code={(payload or {}).get('code')}"
        )


@allure.feature("CRM")
@allure.story("Customer 业务状态变更日志")
class TestCustomerBusinessStatusLog:
    """GET /customer/business_status_log/list。"""

    @pytest.mark.smoke
    @pytest.mark.p0
    @allure.title("查询业务状态变更日志")
    def test_list_business_status_log(self, api, crm_config, crmdata):
        _require_host(api)
        _require_token(api)
        section = crmdata.get("business_status_log") or {}
        customer_id = _valid_customer_id(crm_config, {"id": 1516})
        expected_status = int(section.get("expected_http_status") or 200)
        success_codes = _success_codes(section)

        res = api.list_business_status_log(customer_id)
        _attach(res)
        pytest.assume(
            res.status_code == expected_status,
            f"HTTP 状态码不匹配: 期望 {expected_status}, 实际 {res.status_code}",
        )
        payload = _parse_json(res)
        pytest.assume(isinstance(payload, dict), "响应应为 JSON 对象")
        if not isinstance(payload, dict):
            return
        if "code" in payload:
            pytest.assume(
                payload.get("code") in success_codes,
                f"业务 code 应为 {success_codes}, 实际 {payload.get('code')}",
            )
        data = _unwrap_status_log(payload)
        for field in section.get("response_fields") or []:
            pytest.assume(field in data, f"结果应包含字段: {field}")
        pytest.assume(
            data.get("customer_id") == customer_id,
            f"customer_id 应为 {customer_id}, 实际 {data.get('customer_id')}",
        )
        items = data.get("list")
        pytest.assume(items is None or isinstance(items, list), "list 应为数组或 null")
        logger.info(
            f"业务状态日志 customer_id={data.get('customer_id')}, "
            f"条数={len(_normalize_list(items))}"
        )

    @pytest.mark.p1
    @allure.title("业务状态变更日志 - 列表项字段类型")
    def test_list_business_status_log_schema(self, api, crm_config, crmdata):
        _require_host(api)
        _require_token(api)
        section = crmdata.get("business_status_log") or {}
        customer_id = _valid_customer_id(crm_config, {"id": 1516})
        res = api.list_business_status_log(customer_id)
        _attach(res)
        pytest.assume(res.status_code == 200, f"HTTP 状态码不匹配: 期望 200, 实际 {res.status_code}")
        data = _unwrap_status_log(_parse_json(res))
        items = _normalize_list(data.get("list"))
        if not items:
            pytest.skip("当前客户无业务状态日志，跳过字段类型校验")
        first = items[0]
        pytest.assume(isinstance(first, dict), "list[0] 应为对象")
        for field, expected_type in (section.get("list_item_field_types") or {}).items():
            if field not in first or first.get(field) is None:
                continue
            value = first.get(field)
            pytest.assume(
                _type_ok(value, expected_type),
                f"list[0].{field} 类型应为 {expected_type}, 实际 {type(value).__name__}={value!r}",
            )

    @pytest.mark.p1
    @allure.title("业务状态变更日志 - 不存在的客户 ID")
    def test_list_business_status_log_not_found(self, api, crm_config, crmdata):
        _require_host(api)
        _require_token(api)
        section = crmdata.get("business_status_log") or {}
        not_found_id = int(
            crm_config.get("customer", "not_found_id", fallback="")
            or (section.get("not_found") or {}).get("id")
            or 999999999
        )
        res = api.list_business_status_log(not_found_id)
        _attach(res)
        payload = _parse_json(res)
        data = _unwrap_status_log(payload)
        items = _normalize_list(data.get("list"))
        not_found = (
            res.status_code in (400, 404, 500)
            or _is_business_error(payload, _success_codes(section))
            or data.get("customer_id") not in (not_found_id, None)
            or len(items) == 0
        )
        # 允许：业务错误，或返回空日志且无有效客户匹配
        empty_ok = (
            payload
            and payload.get("code") in _success_codes(section)
            and (data.get("customer_id") in (0, None, not_found_id) or "customer_id" not in data)
            and len(items) == 0
        )
        pytest.assume(
            not_found or empty_ok,
            f"不存在客户应报错或空日志, 实际 HTTP {res.status_code}, body={payload}",
        )

    @pytest.mark.p1
    @allure.title("业务状态变更日志 - 缺少必填参数 id")
    def test_list_business_status_log_missing_id(self, api, crmdata):
        _require_host(api)
        _require_token(api)
        section = crmdata.get("business_status_log") or {}
        res = api.list_business_status_log()
        _attach(res)
        payload = _parse_json(res)
        pytest.assume(
            res.status_code in (400, 500) or _is_business_error(payload, _success_codes(section)),
            f"缺少 id 应校验失败, 实际 HTTP {res.status_code}, body={payload}",
        )


@allure.feature("CRM")
@allure.story("Customer 归属状态变更日志")
class TestCustomerOwnershipStatusLog:
    """GET /customer/ownership_status_log/list。"""

    @pytest.mark.smoke
    @pytest.mark.p0
    @allure.title("查询归属状态变更日志")
    def test_list_ownership_status_log(self, api, crm_config, crmdata):
        _require_host(api)
        _require_token(api)
        section = crmdata.get("ownership_status_log") or {}
        customer_id = _valid_customer_id(crm_config, {"id": 1516})
        expected_status = int(section.get("expected_http_status") or 200)
        success_codes = _success_codes(section)

        res = api.list_ownership_status_log(customer_id)
        _attach(res)
        pytest.assume(
            res.status_code == expected_status,
            f"HTTP 状态码不匹配: 期望 {expected_status}, 实际 {res.status_code}",
        )
        payload = _parse_json(res)
        pytest.assume(isinstance(payload, dict), "响应应为 JSON 对象")
        if not isinstance(payload, dict):
            return
        if "code" in payload:
            pytest.assume(
                payload.get("code") in success_codes,
                f"业务 code 应为 {success_codes}, 实际 {payload.get('code')}",
            )
        data = _unwrap_status_log(payload)
        for field in section.get("response_fields") or []:
            pytest.assume(field in data, f"结果应包含字段: {field}")
        pytest.assume(
            data.get("customer_id") == customer_id,
            f"customer_id 应为 {customer_id}, 实际 {data.get('customer_id')}",
        )
        items = data.get("list")
        pytest.assume(items is None or isinstance(items, list), "list 应为数组或 null")
        logger.info(
            f"归属状态日志 customer_id={data.get('customer_id')}, "
            f"条数={len(_normalize_list(items))}"
        )

    @pytest.mark.p1
    @allure.title("归属状态变更日志 - 列表项字段类型")
    def test_list_ownership_status_log_schema(self, api, crm_config, crmdata):
        _require_host(api)
        _require_token(api)
        section = crmdata.get("ownership_status_log") or {}
        customer_id = _valid_customer_id(crm_config, {"id": 1516})
        res = api.list_ownership_status_log(customer_id)
        _attach(res)
        pytest.assume(res.status_code == 200, f"HTTP 状态码不匹配: 期望 200, 实际 {res.status_code}")
        data = _unwrap_status_log(_parse_json(res))
        items = _normalize_list(data.get("list"))
        if not items:
            pytest.skip("当前客户无归属状态日志，跳过字段类型校验")
        first = items[0]
        pytest.assume(isinstance(first, dict), "list[0] 应为对象")
        for field, expected_type in (section.get("list_item_field_types") or {}).items():
            if field not in first or first.get(field) is None:
                continue
            value = first.get(field)
            pytest.assume(
                _type_ok(value, expected_type),
                f"list[0].{field} 类型应为 {expected_type}, 实际 {type(value).__name__}={value!r}",
            )

    @pytest.mark.p1
    @allure.title("归属状态变更日志 - 不存在的客户 ID")
    def test_list_ownership_status_log_not_found(self, api, crm_config, crmdata):
        _require_host(api)
        _require_token(api)
        section = crmdata.get("ownership_status_log") or {}
        not_found_id = int(
            crm_config.get("customer", "not_found_id", fallback="")
            or (section.get("not_found") or {}).get("id")
            or 999999999
        )
        res = api.list_ownership_status_log(not_found_id)
        _attach(res)
        payload = _parse_json(res)
        data = _unwrap_status_log(payload)
        items = _normalize_list(data.get("list"))
        not_found = (
            res.status_code in (400, 404, 500)
            or _is_business_error(payload, _success_codes(section))
            or data.get("customer_id") not in (not_found_id, None)
            or len(items) == 0
        )
        empty_ok = (
            payload
            and payload.get("code") in _success_codes(section)
            and (data.get("customer_id") in (0, None, not_found_id) or "customer_id" not in data)
            and len(items) == 0
        )
        pytest.assume(
            not_found or empty_ok,
            f"不存在客户应报错或空日志, 实际 HTTP {res.status_code}, body={payload}",
        )

    @pytest.mark.p1
    @allure.title("归属状态变更日志 - 缺少必填参数 id")
    def test_list_ownership_status_log_missing_id(self, api, crmdata):
        _require_host(api)
        _require_token(api)
        section = crmdata.get("ownership_status_log") or {}
        res = api.list_ownership_status_log()
        _attach(res)
        payload = _parse_json(res)
        pytest.assume(
            res.status_code in (400, 500) or _is_business_error(payload, _success_codes(section)),
            f"缺少 id 应校验失败, 实际 HTTP {res.status_code}, body={payload}",
        )


@allure.feature("CRM")
@allure.story("Customer 手机号/邮箱重复检查")
class TestCustomerDuplicateCheck:
    """POST /customer/duplicate_check。"""

    @pytest.mark.smoke
    @pytest.mark.p0
    @allure.title("重复检查 - value 为空返回未重复")
    def test_duplicate_check_empty_value(self, api, crmdata):
        _require_host(api)
        _require_token(api)
        section = crmdata.get("duplicate_check") or {}
        body = copy.deepcopy(section.get("empty_value") or {})
        res = api.duplicate_check_customer(body)
        _attach(res)
        pytest.assume(res.status_code == 200, f"HTTP 状态码不匹配: 期望 200, 实际 {res.status_code}")
        payload = _parse_json(res)
        if "code" in (payload or {}):
            pytest.assume(
                payload.get("code") in _success_codes(section),
                f"业务 code 应为 {_success_codes(section)}, 实际 {payload.get('code')}",
            )
        data = _unwrap_duplicate(payload)
        for field in section.get("response_fields") or []:
            pytest.assume(field in data, f"结果应包含字段: {field}")
        pytest.assume(
            data.get("is_duplicated") is False,
            f"空 value 时 is_duplicated 应为 False, 实际 {data.get('is_duplicated')!r}",
        )

    @pytest.mark.p0
    @allure.title("重复检查 - 唯一手机号未重复")
    def test_duplicate_check_unique_phone(self, api, crmdata):
        _require_host(api)
        _require_token(api)
        section = crmdata.get("duplicate_check") or {}
        body = copy.deepcopy(section.get("unique_phone") or {})
        # 避免与历史数据碰撞
        body["value"] = f"199{uuid.uuid4().hex[:8]}"
        res = api.duplicate_check_customer(body)
        _attach(res)
        pytest.assume(res.status_code == 200, f"HTTP 状态码不匹配: 期望 200, 实际 {res.status_code}")
        payload = _parse_json(res)
        if "code" in (payload or {}):
            pytest.assume(
                payload.get("code") in _success_codes(section),
                f"业务 code 应为 {_success_codes(section)}, 实际 {payload.get('code')}",
            )
        data = _unwrap_duplicate(payload)
        pytest.assume(
            data.get("is_duplicated") is False,
            f"唯一手机号 is_duplicated 应为 False, 实际 {data.get('is_duplicated')!r}",
        )

    @pytest.mark.p1
    @allure.title("重复检查 - 唯一邮箱未重复")
    def test_duplicate_check_unique_email(self, api, crmdata):
        _require_host(api)
        _require_token(api)
        section = crmdata.get("duplicate_check") or {}
        body = copy.deepcopy(section.get("unique_email") or {})
        body["value"] = f"__autotest_{uuid.uuid4().hex}@example.com"
        res = api.duplicate_check_customer(body)
        _attach(res)
        pytest.assume(res.status_code == 200, f"HTTP 状态码不匹配: 期望 200, 实际 {res.status_code}")
        data = _unwrap_duplicate(_parse_json(res))
        pytest.assume(
            data.get("is_duplicated") is False,
            f"唯一邮箱 is_duplicated 应为 False, 实际 {data.get('is_duplicated')!r}",
        )

    @pytest.mark.p0
    @allure.title("重复检查 - 已有客户邮箱判定为重复")
    def test_duplicate_check_existing_email(self, api, crm_config, crmdata):
        _require_host(api)
        _require_token(api)
        section = crmdata.get("duplicate_check") or {}
        customer_id = _valid_customer_id(crm_config, {"id": 1516})
        detail_res = api.get_customer_by_id(customer_id)
        _attach(detail_res)
        customer = _unwrap_customer(_parse_json(detail_res))
        email = (customer.get("email") or "").strip()
        if not email or email in {"/", "-"}:
            pytest.skip(f"客户 {customer_id} 无有效邮箱，跳过重复正例")
        check_type = int((section.get("from_existing_customer") or {}).get("check_type_email") or 2)
        res = api.duplicate_check_customer(check_type=check_type, value=email)
        _attach(res)
        pytest.assume(res.status_code == 200, f"HTTP 状态码不匹配: 期望 200, 实际 {res.status_code}")
        payload = _parse_json(res)
        if "code" in (payload or {}):
            pytest.assume(
                payload.get("code") in _success_codes(section),
                f"业务 code 应为 {_success_codes(section)}, 实际 {payload.get('code')}",
            )
        data = _unwrap_duplicate(payload)
        pytest.assume(isinstance(data.get("is_duplicated"), bool), "is_duplicated 应为布尔值")
        pytest.assume(
            data.get("is_duplicated") is True,
            f"已有邮箱 '{email}' 应判定重复, 实际 {data.get('is_duplicated')!r}",
        )


@allure.feature("CRM")
@allure.story("Customer 待办 Tab 角标统计")
class TestCustomerPendingTaskBadge:
    """GET /customer/pending_task_badge。"""

    @pytest.mark.smoke
    @pytest.mark.p0
    @allure.title("待办角标 - scope=mine")
    def test_pending_task_badge_mine(self, api, crm_config, crmdata):
        _require_host(api)
        _require_token(api)
        section = crmdata.get("pending_task_badge") or {}
        scope = (
            crm_config.get("pending_task_badge", "scope_mine", fallback="") or "mine"
        ).strip()
        res = api.get_pending_task_badge(scope)
        _attach(res)
        pytest.assume(res.status_code == 200, f"HTTP 状态码不匹配: 期望 200, 实际 {res.status_code}")
        payload = _parse_json(res)
        if "code" in (payload or {}):
            pytest.assume(
                payload.get("code") in _success_codes(section),
                f"业务 code 应为 {_success_codes(section)}, 实际 {payload.get('code')}",
            )
        data = _unwrap_badge(payload)
        for field in section.get("response_fields") or []:
            pytest.assume(field in data, f"结果应包含字段: {field}")
        for field, expected_type in (section.get("field_types") or {}).items():
            value = data.get(field)
            pytest.assume(
                _type_ok(value, expected_type),
                f"{field} 类型应为 {expected_type}, 实际 {type(value).__name__}={value!r}",
            )
        for field in section.get("mine_fixed_zero_fields") or []:
            pytest.assume(
                data.get(field) == 0,
                f"scope=mine 时 {field} 应为 0, 实际 {data.get(field)!r}",
            )
        logger.info(
            f"badge mine link={data.get('pending_link_count')} "
            f"website={data.get('pending_website_count')} store={data.get('pending_store_count')}"
        )

    @pytest.mark.p0
    @allure.title("待办角标 - scope=all")
    def test_pending_task_badge_all(self, api, crm_config, crmdata):
        _require_host(api)
        _require_token(api)
        section = crmdata.get("pending_task_badge") or {}
        scope = (
            crm_config.get("pending_task_badge", "scope_all", fallback="") or "all"
        ).strip()
        res = api.get_pending_task_badge(scope)
        _attach(res)
        pytest.assume(res.status_code == 200, f"HTTP 状态码不匹配: 期望 200, 实际 {res.status_code}")
        payload = _parse_json(res)
        if "code" in (payload or {}):
            pytest.assume(
                payload.get("code") in _success_codes(section),
                f"业务 code 应为 {_success_codes(section)}, 实际 {payload.get('code')}",
            )
        data = _unwrap_badge(payload)
        for field in section.get("response_fields") or []:
            pytest.assume(field in data, f"结果应包含字段: {field}")
            pytest.assume(
                _is_int(data.get(field)) and data.get(field) >= 0,
                f"{field} 应为非负整数, 实际 {data.get(field)!r}",
            )

    @pytest.mark.p1
    @allure.title("待办角标 - 缺少 scope")
    def test_pending_task_badge_missing_scope(self, api, crmdata):
        _require_host(api)
        _require_token(api)
        section = crmdata.get("pending_task_badge") or {}
        res = api.get_pending_task_badge()
        _attach(res)
        payload = _parse_json(res)
        pytest.assume(
            res.status_code in (400, 500) or _is_business_error(payload, _success_codes(section)),
            f"缺少 scope 应校验失败, 实际 HTTP {res.status_code}, body={payload}",
        )

    @pytest.mark.p1
    @allure.title("待办角标 - 非法 scope")
    def test_pending_task_badge_invalid_scope(self, api, crmdata):
        _require_host(api)
        _require_token(api)
        section = crmdata.get("pending_task_badge") or {}
        bad_scope = section.get("invalid_scope") or "__invalid_scope__"
        res = api.get_pending_task_badge(bad_scope)
        _attach(res)
        payload = _parse_json(res)
        pytest.assume(
            res.status_code in (400, 500) or _is_business_error(payload, _success_codes(section)),
            f"非法 scope 应校验失败, 实际 HTTP {res.status_code}, body={payload}",
        )


@allure.feature("CRM")
@allure.story("Customer 待关联/官网待审任务分页")
class TestPendingLinkTaskPageQuery:
    """POST /pending_link_task/page_query。"""

    @pytest.mark.smoke
    @pytest.mark.p0
    @allure.title("待关联任务分页 - scope=all source=1")
    def test_pending_link_task_page_query_all(self, api, crm_config, crmdata):
        _require_host(api)
        _require_token(api)
        section = crmdata.get("pending_link_task") or {}
        body = _pending_link_body(crm_config, crmdata, "valid_all_link")
        res = api.page_query_pending_link_task(body)
        _attach(res)
        _, page_data = _assert_page_success(
            res, section, expected_page=body.get("page"), expected_page_size=body.get("page_size")
        )
        logger.info(f"pending_link total={page_data.get('total')}")

    @pytest.mark.p1
    @allure.title("官网待审任务分页 - scope=all source=2")
    def test_pending_link_task_page_query_website(self, api, crm_config, crmdata):
        _require_host(api)
        _require_token(api)
        section = crmdata.get("pending_link_task") or {}
        body = _pending_link_body(crm_config, crmdata, "valid_all_website")
        res = api.page_query_pending_link_task(body)
        _attach(res)
        _assert_page_success(
            res, section, expected_page=body.get("page"), expected_page_size=body.get("page_size")
        )

    @pytest.mark.p1
    @allure.title("待关联任务分页 - scope=mine")
    def test_pending_link_task_page_query_mine(self, api, crm_config, crmdata):
        _require_host(api)
        _require_token(api)
        section = crmdata.get("pending_link_task") or {}
        body = _pending_link_body(crm_config, crmdata, "valid_mine")
        res = api.page_query_pending_link_task(body)
        _attach(res)
        _assert_page_success(
            res, section, expected_page=body.get("page"), expected_page_size=body.get("page_size")
        )

    @pytest.mark.p1
    @allure.title("待关联任务分页 - 列表项字段类型")
    def test_pending_link_task_list_item_schema(self, api, crm_config, crmdata):
        _require_host(api)
        _require_token(api)
        section = crmdata.get("pending_link_task") or {}
        body = _pending_link_body(crm_config, crmdata, "valid_all_link")
        res = api.page_query_pending_link_task(body)
        _attach(res)
        _, page_data = _assert_page_success(res, section)
        items = _normalize_list(page_data.get("list"))
        if not items:
            pytest.skip("当前筛选条件下列表为空，跳过字段类型校验")
        first = items[0]
        pytest.assume(isinstance(first, dict), "list[0] 应为对象")
        for field in section.get("list_item_required_fields") or []:
            pytest.assume(field in first, f"list[0] 应包含字段: {field}")
        for field, expected_type in (section.get("list_item_field_types") or {}).items():
            if field not in first or first.get(field) is None:
                continue
            value = first.get(field)
            pytest.assume(
                _type_ok(value, expected_type),
                f"list[0].{field} 类型应为 {expected_type}, 实际 {type(value).__name__}={value!r}",
            )

    @pytest.mark.p1
    @allure.title("待关联任务分页 - 缺少 scope")
    def test_pending_link_task_missing_scope(self, api, crmdata):
        _require_host(api)
        _require_token(api)
        section = crmdata.get("pending_link_task") or {}
        body = copy.deepcopy(section.get("missing_scope") or {})
        res = api.page_query_pending_link_task(body)
        _attach(res)
        payload = _parse_json(res)
        pytest.assume(
            res.status_code in (400, 500) or _is_business_error(payload, _success_codes(section)),
            f"缺少 scope 应校验失败, 实际 HTTP {res.status_code}, body={payload}",
        )

    @pytest.mark.p1
    @allure.title("待关联任务分页 - scope=all 缺少 source")
    def test_pending_link_task_all_missing_source(self, api, crmdata):
        _require_host(api)
        _require_token(api)
        section = crmdata.get("pending_link_task") or {}
        body = copy.deepcopy(section.get("all_missing_source") or {})
        res = api.page_query_pending_link_task(body)
        _attach(res)
        payload = _parse_json(res)
        pytest.assume(
            res.status_code in (400, 500) or _is_business_error(payload, _success_codes(section)),
            f"scope=all 缺少 source 应校验失败, 实际 HTTP {res.status_code}, body={payload}",
        )


@allure.feature("CRM")
@allure.story("Customer 绑店待确认任务分页")
class TestPendingStoreTaskPageQuery:
    """POST /pending_store_task/page_query。"""

    @pytest.mark.smoke
    @pytest.mark.p0
    @allure.title("绑店待确认任务分页 - 首屏")
    def test_pending_store_task_page_query(self, api, crm_config, crmdata):
        _require_host(api)
        _require_token(api)
        section = crmdata.get("pending_store_task") or {}
        body = _pending_store_body(crm_config, crmdata, "valid")
        res = api.page_query_pending_store_task(body)
        _attach(res)
        _, page_data = _assert_page_success(
            res, section, expected_page=body.get("page"), expected_page_size=body.get("page_size")
        )
        logger.info(f"pending_store total={page_data.get('total')}")

    @pytest.mark.p1
    @allure.title("绑店待确认任务分页 - 列表项字段类型")
    def test_pending_store_task_list_item_schema(self, api, crm_config, crmdata):
        _require_host(api)
        _require_token(api)
        section = crmdata.get("pending_store_task") or {}
        body = _pending_store_body(crm_config, crmdata, "valid")
        res = api.page_query_pending_store_task(body)
        _attach(res)
        _, page_data = _assert_page_success(res, section)
        items = _normalize_list(page_data.get("list"))
        if not items:
            pytest.skip("当前列表为空，跳过字段类型校验")
        first = items[0]
        pytest.assume(isinstance(first, dict), "list[0] 应为对象")
        for field in section.get("list_item_required_fields") or []:
            pytest.assume(field in first, f"list[0] 应包含字段: {field}")
        for field, expected_type in (section.get("list_item_field_types") or {}).items():
            if field not in first or first.get(field) is None:
                continue
            value = first.get(field)
            pytest.assume(
                _type_ok(value, expected_type),
                f"list[0].{field} 类型应为 {expected_type}, 实际 {type(value).__name__}={value!r}",
            )

    @pytest.mark.p1
    @allure.title("绑店待确认任务分页 - 空结果")
    def test_pending_store_task_empty_result(self, api, crm_config, crmdata):
        _require_host(api)
        _require_token(api)
        section = crmdata.get("pending_store_task") or {}
        body = _pending_store_body(crm_config, crmdata, "empty_result")
        res = api.page_query_pending_store_task(body)
        _attach(res)
        payload = _parse_json(res)
        if "code" in (payload or {}):
            pytest.assume(
                payload.get("code") in _success_codes(section),
                f"业务 code 应为 {_success_codes(section)}, 实际 {payload.get('code')}",
            )
        page_data = _unwrap_page(payload)
        items = page_data.get("list")
        empty_list = items is None or items == []
        pytest.assume(empty_list, f"空结果 list 应为 null/[] , 实际 {items!r}")
        pytest.assume(page_data.get("total") == 0, f"空结果 total 应为 0, 实际 {page_data.get('total')}")

    @pytest.mark.p1
    @allure.title("绑店待确认任务分页 - 非法 status")
    def test_pending_store_task_invalid_status(self, api, crmdata):
        _require_host(api)
        _require_token(api)
        section = crmdata.get("pending_store_task") or {}
        body = copy.deepcopy(section.get("invalid_status") or {})
        res = api.page_query_pending_store_task(body)
        _attach(res)
        payload = _parse_json(res)
        pytest.assume(
            res.status_code in (400, 500) or _is_business_error(payload, _success_codes(section)),
            f"非法 status 应校验失败, 实际 HTTP {res.status_code}, body={payload}",
        )


@allure.feature("CRM")
@allure.story("Customer 关联已有线索检索")
class TestCustomerLinkSearch:
    """POST /customer/link_search。"""

    @pytest.mark.smoke
    @pytest.mark.p0
    @allure.title("关联线索检索 - scope=all 按客户名")
    def test_link_search_by_customer_name(self, api, crm_config, crmdata):
        _require_host(api)
        _require_token(api)
        section = crmdata.get("link_search") or {}
        body = _link_search_body(crm_config, crmdata, "valid_all")
        res = api.link_search_customers(body)
        _attach(res)
        _, page_data = _assert_page_success(
            res, section, expected_page=body.get("page"), expected_page_size=body.get("page_size")
        )
        items = _normalize_list(page_data.get("list"))
        keyword = body.get("customer_name") or ""
        pytest.assume(len(items) > 0, f"按客户名 '{keyword}' 检索结果不应为空")
        for idx, item in enumerate(items):
            name = item.get("customer_name") or ""
            pytest.assume(
                keyword in name,
                f"[idx={idx}] customer_name 应包含 '{keyword}', 实际 '{name}'",
            )
        logger.info(f"link_search total={page_data.get('total')}")

    @pytest.mark.p1
    @allure.title("关联线索检索 - scope=mine")
    def test_link_search_mine(self, api, crm_config, crmdata):
        _require_host(api)
        _require_token(api)
        section = crmdata.get("link_search") or {}
        body = _link_search_body(crm_config, crmdata, "valid_mine")
        res = api.link_search_customers(body)
        _attach(res)
        _assert_page_success(
            res, section, expected_page=body.get("page"), expected_page_size=body.get("page_size")
        )

    @pytest.mark.p1
    @allure.title("关联线索检索 - 列表项字段类型")
    def test_link_search_list_item_schema(self, api, crm_config, crmdata):
        _require_host(api)
        _require_token(api)
        section = crmdata.get("link_search") or {}
        body = _link_search_body(crm_config, crmdata, "valid_all")
        res = api.link_search_customers(body)
        _attach(res)
        _, page_data = _assert_page_success(res, section)
        items = _normalize_list(page_data.get("list"))
        if not items:
            pytest.skip("当前检索结果为空，跳过字段类型校验")
        first = items[0]
        pytest.assume(isinstance(first, dict), "list[0] 应为对象")
        for field in section.get("list_item_required_fields") or []:
            pytest.assume(field in first, f"list[0] 应包含字段: {field}")
        for field, expected_type in (section.get("list_item_field_types") or {}).items():
            if field not in first or first.get(field) is None:
                continue
            value = first.get(field)
            pytest.assume(
                _type_ok(value, expected_type),
                f"list[0].{field} 类型应为 {expected_type}, 实际 {type(value).__name__}={value!r}",
            )

    @pytest.mark.p1
    @allure.title("关联线索检索 - 空结果")
    def test_link_search_empty_result(self, api, crm_config, crmdata):
        _require_host(api)
        _require_token(api)
        section = crmdata.get("link_search") or {}
        body = _link_search_body(crm_config, crmdata, "empty_result")
        res = api.link_search_customers(body)
        _attach(res)
        payload = _parse_json(res)
        if "code" in (payload or {}):
            pytest.assume(
                payload.get("code") in _success_codes(section),
                f"业务 code 应为 {_success_codes(section)}, 实际 {payload.get('code')}",
            )
        page_data = _unwrap_page(payload)
        items = page_data.get("list")
        empty_list = items is None or items == []
        pytest.assume(empty_list, f"空结果 list 应为 null/[] , 实际 {items!r}")
        pytest.assume(page_data.get("total") == 0, f"空结果 total 应为 0, 实际 {page_data.get('total')}")

    @pytest.mark.p1
    @allure.title("关联线索检索 - 缺少筛选条件")
    def test_link_search_missing_filter(self, api, crmdata):
        _require_host(api)
        _require_token(api)
        section = crmdata.get("link_search") or {}
        body = copy.deepcopy(section.get("missing_filter") or {})
        res = api.link_search_customers(body)
        _attach(res)
        payload = _parse_json(res)
        pytest.assume(
            res.status_code in (400, 500) or _is_business_error(payload, _success_codes(section)),
            f"缺少筛选条件应校验失败, 实际 HTTP {res.status_code}, body={payload}",
        )

    @pytest.mark.p1
    @allure.title("关联线索检索 - 缺少 scope")
    def test_link_search_missing_scope(self, api, crmdata):
        _require_host(api)
        _require_token(api)
        section = crmdata.get("link_search") or {}
        body = copy.deepcopy(section.get("missing_scope") or {})
        res = api.link_search_customers(body)
        _attach(res)
        payload = _parse_json(res)
        pytest.assume(
            res.status_code in (400, 500) or _is_business_error(payload, _success_codes(section)),
            f"缺少 scope 应校验失败, 实际 HTTP {res.status_code}, body={payload}",
        )

    @pytest.mark.p1
    @allure.title("关联线索检索 - 非法 scope")
    def test_link_search_invalid_scope(self, api, crmdata):
        _require_host(api)
        _require_token(api)
        section = crmdata.get("link_search") or {}
        body = copy.deepcopy(section.get("invalid_scope") or {})
        res = api.link_search_customers(body)
        _attach(res)
        payload = _parse_json(res)
        pytest.assume(
            res.status_code in (400, 500) or _is_business_error(payload, _success_codes(section)),
            f"非法 scope 应校验失败, 实际 HTTP {res.status_code}, body={payload}",
        )


@allure.feature("CRM")
@allure.story("Customer 附件待绑定列表")
class TestCustomerAttachmentListPending:
    """GET /customer/attachment/list_pending。"""

    @pytest.mark.smoke
    @pytest.mark.p0
    @allure.title("附件待绑定列表 - 按 draft_id 查询")
    def test_list_pending_attachments(self, api, crm_config, crmdata):
        _require_host(api)
        _require_token(api)
        section = crmdata.get("attachment_list_pending") or {}
        draft_id = (
            crm_config.get("attachment", "draft_id", fallback="")
            or (section.get("valid") or {}).get("draft_id")
            or f"autotest-{uuid.uuid4().hex[:12]}"
        ).strip()
        res = api.list_pending_attachments(draft_id)
        _attach(res)
        pytest.assume(res.status_code == 200, f"HTTP 状态码不匹配: 期望 200, 实际 {res.status_code}")
        payload = _parse_json(res)
        if "code" in (payload or {}):
            pytest.assume(
                payload.get("code") in _success_codes(section),
                f"业务 code 应为 {_success_codes(section)}, 实际 {payload.get('code')}",
            )
        data = _unwrap_attachment_list(payload)
        for field in section.get("response_fields") or []:
            pytest.assume(field in data, f"结果应包含字段: {field}")
        items = data.get("list")
        pytest.assume(items is None or isinstance(items, list), "list 应为数组或 null")
        logger.info(f"pending attachments draft_id={draft_id}, count={len(_normalize_list(items))}")

    @pytest.mark.p1
    @allure.title("附件待绑定列表 - 列表项字段类型")
    def test_list_pending_attachments_schema(self, api, crm_config, crmdata):
        _require_host(api)
        _require_token(api)
        section = crmdata.get("attachment_list_pending") or {}
        draft_id = (
            crm_config.get("attachment", "draft_id", fallback="")
            or (section.get("valid") or {}).get("draft_id")
            or f"autotest-{uuid.uuid4().hex[:12]}"
        ).strip()
        res = api.list_pending_attachments(draft_id)
        _attach(res)
        pytest.assume(res.status_code == 200, f"HTTP 状态码不匹配: 期望 200, 实际 {res.status_code}")
        data = _unwrap_attachment_list(_parse_json(res))
        items = _normalize_list(data.get("list"))
        if not items:
            pytest.skip("当前 draft_id 无暂存附件，跳过字段类型校验")
        first = items[0]
        pytest.assume(isinstance(first, dict), "list[0] 应为对象")
        for field, expected_type in (section.get("list_item_field_types") or {}).items():
            if field not in first or first.get(field) is None:
                continue
            value = first.get(field)
            pytest.assume(
                _type_ok(value, expected_type),
                f"list[0].{field} 类型应为 {expected_type}, 实际 {type(value).__name__}={value!r}",
            )

    @pytest.mark.p1
    @allure.title("附件待绑定列表 - 缺少 draft_id")
    def test_list_pending_attachments_missing_draft_id(self, api, crmdata):
        _require_host(api)
        _require_token(api)
        section = crmdata.get("attachment_list_pending") or {}
        res = api.list_pending_attachments()
        _attach(res)
        payload = _parse_json(res)
        pytest.assume(
            res.status_code in (400, 500) or _is_business_error(payload, _success_codes(section)),
            f"缺少 draft_id 应校验失败, 实际 HTTP {res.status_code}, body={payload}",
        )
