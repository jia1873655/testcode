"""CRM 项目接口封装。"""

from services.crm.crm_api import CrmApi, get_crm_access_token

__all__ = ["CrmApi", "get_crm_access_token"]
