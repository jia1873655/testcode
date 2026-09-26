"""CRM Allure 分组与 mutation 门禁。

写操作用例默认跳过，避免日常全量误改数据。
显式设置 ``CRM_ALLOW_MUTATIONS=1`` 后才会执行 ``@pytest.mark.mutation``。
"""
from __future__ import annotations

import os

import allure
import pytest

CRM_GROUP = "CRM"


def _env_enabled(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


@pytest.fixture(autouse=True)
def _crm_allure_labels():
    allure.dynamic.parent_suite(CRM_GROUP)


def pytest_collection_modifyitems(config, items):
    """仅对本目录生效：未开 CRM_ALLOW_MUTATIONS 时跳过 mutation。"""
    del config
    mutations_enabled = _env_enabled("CRM_ALLOW_MUTATIONS")
    crm_root = os.path.abspath(os.path.dirname(__file__))
    skip_mutation = pytest.mark.skip(
        reason="设置 CRM_ALLOW_MUTATIONS=1 才执行 CRM 写操作用例"
    )
    for item in items:
        item_path = os.path.abspath(str(getattr(item, "fspath", "")))
        try:
            in_crm = os.path.commonpath([crm_root, item_path]) == crm_root
        except ValueError:
            in_crm = False
        if not in_crm:
            continue
        if "mutation" in item.keywords and not mutations_enabled:
            item.add_marker(skip_mutation)
