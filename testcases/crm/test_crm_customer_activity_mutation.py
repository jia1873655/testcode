# -*- coding: utf-8 -*-
# @Time: 2026/9/21
# @Author: AutoTest
# @Description: CRM 客户动态记录
# 来源：客户动态.json（create/update/delete/list/get_by_id）
#
# - 只读：list / get_by_id 进日常
# - 写链路 mutation：增 → 详情 → 列表 → 改 → 详情 → 删 → 详情/列表确认；默认 skip
import copy
import json
import time
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
    with _DATA_FILE.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _attach(res):
    try:
        allure.attach(
            json.dumps(res.json(), ensure_ascii=False, indent=2),
            name="响应报文",
            attachment_type=allure.attachment_type.JSON,
        )
    except Exception:
        allure.attach(res.text or "", name="响应报文(TEXT)", attachment_type=allure.attachment_type.TEXT)


def _parse_json(res) -> Optional[Dict[str, Any]]:
    try:
        payload = res.json()
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _unwrap_data(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    return data if isinstance(data, dict) else {}


def _normalize_list(value: Any) -> List[Any]:
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


def _success_codes(section: Dict[str, Any]) -> list:
    return list(section.get("success_codes") or [0, 200])


def _is_business_error(payload: Optional[Dict[str, Any]], success_codes: list) -> bool:
    if not isinstance(payload, dict):
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


def _activity_customer_id(crm_config, section: Dict[str, Any]) -> str:
    raw = crm_config.get("activity_record", "customer_id", fallback="") or ""
    if str(raw).strip():
        return str(raw).strip()
    create = section.get("create") or {}
    return str(create.get("customer_id") or "").strip()


def _activity_source(crm_config, section: Dict[str, Any]) -> int:
    raw = crm_config.get("activity_record", "source", fallback="") or ""
    if str(raw).strip():
        return int(raw)
    create = section.get("create") or {}
    return int(create.get("source") or 2)


def _assert_biz_ok(res, section: Dict[str, Any], label: str) -> Dict[str, Any]:
    expected_http = int(section.get("expected_http_status") or 200)
    success_codes = _success_codes(section)
    pytest.assume(
        res.status_code == expected_http,
        f"{label} HTTP 期望 {expected_http}, 实际 {res.status_code}",
    )
    payload = _parse_json(res)
    pytest.assume(isinstance(payload, dict), f"{label} 响应应为 JSON 对象")
    if isinstance(payload, dict) and "code" in payload:
        pytest.assume(
            payload.get("code") in success_codes,
            f"{label} 业务 code 应为 {success_codes}, 实际 {payload.get('code')}",
        )
    return payload if isinstance(payload, dict) else {}


def _list_contains_id(items: List[Any], record_id: int) -> bool:
    for item in items:
        if isinstance(item, dict) and item.get("id") == record_id:
            return True
    return False


@pytest.fixture(scope="module")
def api():
    return CrmApi()


@pytest.fixture(scope="module")
def crm_config():
    return get_project_config("crm", get_env())


@pytest.fixture(scope="module")
def crmdata() -> Dict[str, Any]:
    return _load_crmdata()


@allure.feature("CRM")
@allure.story("CustomerActivityRecord 只读")
class TestCustomerActivityRecordReadonly:
    """GET list / POST get_by_id，进日常。"""

    @pytest.mark.smoke
    @pytest.mark.p0
    @allure.title("客户动态列表 - 按客户查询")
    def test_list_activity_records(self, api, crm_config, crmdata):
        _require_host(api)
        _require_token(api)
        section = crmdata.get("activity_record") or {}
        list_cfg = section.get("list") or {}
        customer_id = _activity_customer_id(crm_config, section)
        if not customer_id:
            pytest.skip("未配置 activity_record.customer_id")
        page = int(list_cfg.get("page") or 1)
        page_size = int(list_cfg.get("page_size") or 20)
        res = api.list_customer_activity_records(customer_id, page=page, page_size=page_size)
        _attach(res)
        payload = _assert_biz_ok(res, section, "列表")
        data = _unwrap_data(payload)
        for field in list_cfg.get("response_fields") or []:
            pytest.assume(field in data, f"列表结果应包含字段: {field}")
        items = data.get("list")
        pytest.assume(items is None or isinstance(items, list), "list 应为数组或 null")
        pytest.assume(_is_int(data.get("total")), f"total 应为整数, 实际 {data.get('total')!r}")
        pytest.assume(data.get("page") == page, f"page 应回显 {page}")
        pytest.assume(data.get("page_size") == page_size, f"page_size 应回显 {page_size}")
        logger.info(f"activity list customer_id={customer_id} total={data.get('total')}")

    @pytest.mark.p1
    @allure.title("客户动态列表 - 缺少 customer_id")
    def test_list_activity_records_missing_customer_id(self, api, crmdata):
        _require_host(api)
        _require_token(api)
        section = crmdata.get("activity_record") or {}
        res = api.list_customer_activity_records()
        _attach(res)
        payload = _parse_json(res)
        pytest.assume(
            res.status_code in (400, 500) or _is_business_error(payload, _success_codes(section)),
            f"缺少 customer_id 应校验失败, 实际 HTTP {res.status_code}, body={payload}",
        )

    @pytest.mark.p1
    @allure.title("客户动态列表 - 列表项字段类型")
    def test_list_activity_records_schema(self, api, crm_config, crmdata):
        _require_host(api)
        _require_token(api)
        section = crmdata.get("activity_record") or {}
        list_cfg = section.get("list") or {}
        customer_id = _activity_customer_id(crm_config, section)
        if not customer_id:
            pytest.skip("未配置 activity_record.customer_id")
        res = api.list_customer_activity_records(
            customer_id,
            page=int(list_cfg.get("page") or 1),
            page_size=int(list_cfg.get("page_size") or 20),
        )
        _attach(res)
        data = _unwrap_data(_assert_biz_ok(res, section, "列表"))
        items = _normalize_list(data.get("list"))
        if not items:
            pytest.skip("当前客户无动态记录，跳过字段类型校验")
        first = items[0]
        for field, expected_type in (list_cfg.get("list_item_field_types") or {}).items():
            if field not in first or first.get(field) is None:
                continue
            value = first.get(field)
            pytest.assume(
                _type_ok(value, expected_type),
                f"list[0].{field} 类型应为 {expected_type}, 实际 {type(value).__name__}={value!r}",
            )

    @pytest.mark.p1
    @allure.title("客户动态详情 - 不存在的 id")
    def test_get_activity_record_not_found(self, api, crmdata):
        _require_host(api)
        _require_token(api)
        section = crmdata.get("activity_record") or {}
        not_found_id = int((section.get("get_by_id") or {}).get("not_found_id") or 999999999)
        res = api.get_customer_activity_record_by_id(id=not_found_id)
        _attach(res)
        payload = _parse_json(res)
        pytest.assume(
            res.status_code in (400, 404, 500) or _is_business_error(payload, _success_codes(section)),
            f"不存在 id 应报错, 实际 HTTP {res.status_code}, body={payload}",
        )


@allure.feature("CRM")
@allure.story("CustomerActivityRecord 写链路")
class TestCustomerActivityRecordMutation:
    """create → detail → list → update → detail → delete → confirm。"""

    @pytest.mark.mutation
    @pytest.mark.p1
    @allure.title("客户动态：新增→详情/列表→编辑→删除完整链路")
    def test_activity_record_full_chain(self, api, crm_config, crmdata):
        _require_host(api)
        _require_token(api)
        section = crmdata.get("activity_record") or {}
        create_cfg = section.get("create") or {}
        update_cfg = section.get("update") or {}
        delete_cfg = section.get("delete") or {}
        list_cfg = section.get("list") or {}
        detail_cfg = section.get("get_by_id") or {}
        success_codes = _success_codes(section)

        customer_id = _activity_customer_id(crm_config, section)
        if not customer_id:
            pytest.skip("未配置 activity_record.customer_id（全量客户 ID / merchant_id）")
        source = _activity_source(crm_config, section)
        stamp = int(time.time())
        content = f"{create_cfg.get('content_prefix') or 'autotest-activity'}-{stamp}"
        tags = list(create_cfg.get("tags") or ["自动化"])
        page = int(list_cfg.get("page") or 1)
        page_size = int(list_cfg.get("page_size") or 20)

        record_id = None
        try:
            with allure.step("1. 新增客户动态"):
                create_body = {
                    "customer_id": customer_id,
                    "source": source,
                    "content": content,
                    "tags": tags,
                }
                res = api.create_customer_activity_record(create_body)
                _attach(res)
                data = _unwrap_data(_assert_biz_ok(res, section, "创建"))
                for field in create_cfg.get("response_fields") or ["id"]:
                    pytest.assume(field in data, f"创建结果应包含字段: {field}")
                record_id = data.get("id")
                pytest.assume(isinstance(record_id, int) and record_id > 0, f"创建 id 非法: {record_id!r}")
                logger.info(f"created activity record id={record_id}")

            with allure.step("2. 详情核对新增内容"):
                res = api.get_customer_activity_record_by_id(id=record_id)
                _attach(res)
                detail = _unwrap_data(_assert_biz_ok(res, section, "详情"))
                for field in detail_cfg.get("response_fields") or []:
                    pytest.assume(field in detail, f"详情应包含字段: {field}")
                pytest.assume(detail.get("id") == record_id, "详情 id 应匹配")
                pytest.assume(detail.get("customer_id") == customer_id, "详情 customer_id 应匹配")
                pytest.assume(detail.get("content") == content, f"详情 content 应为 {content!r}")
                pytest.assume(detail.get("tags") == tags, f"详情 tags 应为 {tags!r}")
                pytest.assume(detail.get("source") == source, f"详情 source 应为 {source}")

            with allure.step("3. 列表应包含新建记录"):
                res = api.list_customer_activity_records(customer_id, page=page, page_size=page_size)
                _attach(res)
                page_data = _unwrap_data(_assert_biz_ok(res, section, "列表"))
                items = _normalize_list(page_data.get("list"))
                pytest.assume(
                    _list_contains_id(items, record_id),
                    f"列表应包含 id={record_id}, 实际 ids={[i.get('id') for i in items if isinstance(i, dict)]}",
                )

            with allure.step("4. 编辑客户动态"):
                updated_content = f"{content}{update_cfg.get('content_suffix') or '-updated'}"
                update_tags = list(update_cfg.get("tags") or ["重点"])
                res = api.update_customer_activity_record(
                    id=record_id, content=updated_content, tags=update_tags
                )
                _attach(res)
                data = _unwrap_data(_assert_biz_ok(res, section, "编辑"))
                for field in update_cfg.get("response_fields") or ["id"]:
                    pytest.assume(field in data, f"编辑结果应包含字段: {field}")
                pytest.assume(data.get("id") == record_id, "编辑回显 id 应匹配")

            with allure.step("5. 详情核对编辑结果"):
                res = api.get_customer_activity_record_by_id(id=record_id)
                _attach(res)
                detail = _unwrap_data(_assert_biz_ok(res, section, "编辑后详情"))
                pytest.assume(
                    detail.get("content") == updated_content,
                    f"编辑后 content 应为 {updated_content!r}, 实际 {detail.get('content')!r}",
                )
                pytest.assume(
                    detail.get("tags") == update_tags,
                    f"编辑后 tags 应为 {update_tags!r}, 实际 {detail.get('tags')!r}",
                )

            with allure.step("6. 删除客户动态"):
                res = api.delete_customer_activity_record(id=record_id)
                _attach(res)
                data = _unwrap_data(_assert_biz_ok(res, section, "删除"))
                for field in delete_cfg.get("response_fields") or ["id"]:
                    pytest.assume(field in data, f"删除结果应包含字段: {field}")
                deleted_id = record_id
                record_id = None

            with allure.step("7. 删除后详情应不存在"):
                res = api.get_customer_activity_record_by_id(id=deleted_id)
                _attach(res)
                payload = _parse_json(res)
                pytest.assume(
                    res.status_code in (400, 404, 500) or _is_business_error(payload, success_codes),
                    f"删除后详情应失败, 实际 HTTP {res.status_code}, body={payload}",
                )

            with allure.step("8. 删除后列表不应再包含该记录"):
                res = api.list_customer_activity_records(customer_id, page=page, page_size=page_size)
                _attach(res)
                page_data = _unwrap_data(_assert_biz_ok(res, section, "删除后列表"))
                items = _normalize_list(page_data.get("list"))
                pytest.assume(
                    not _list_contains_id(items, deleted_id),
                    f"删除后列表不应包含 id={deleted_id}",
                )
        finally:
            if record_id:
                cleanup = api.delete_customer_activity_record(id=record_id)
                logger.info(
                    f"cleanup delete id={record_id} HTTP={cleanup.status_code} body={cleanup.text[:200]}"
                )

    @pytest.mark.mutation
    @pytest.mark.p1
    @allure.title("客户动态：新增缺少 customer_id")
    def test_activity_record_create_missing_customer_id(self, api, crmdata):
        _require_host(api)
        _require_token(api)
        section = crmdata.get("activity_record") or {}
        body = copy.deepcopy(section.get("missing_customer_id") or {})
        res = api.create_customer_activity_record(body)
        _attach(res)
        payload = _parse_json(res)
        pytest.assume(
            res.status_code in (400, 500) or _is_business_error(payload, _success_codes(section)),
            f"缺少 customer_id 应校验失败, 实际 HTTP {res.status_code}, body={payload}",
        )
