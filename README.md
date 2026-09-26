# CRM Autotest（本地独立版）

从 AutoTest 抽出的 **仅 CRM** 接口自动化项目，不含 OMS / 平台服务 / FastAPI。

## 目录

```
config/conf_crm_test.ini     # host / token / 业务参数
data/crmdata/crmdata.yaml    # 断言与用例数据
services/crm/crm_api.py      # 接口封装
testcases/crm/               # pytest 用例
lib/common/                  # config / http_client / logger
```

## PyCharm

1. **Open** 本目录：`/Users/jia/code/crm-autotest`
2. Interpreter：可用 AutoTest 的 `.venv`，或新建 venv 后 `pip install -r requirements.txt`
3. 将项目根目录标为 Sources Root（保证 `from lib...` / `from services...` 可导入）
4. Working directory = 项目根目录

## 运行

```bash
cd /Users/jia/code/crm-autotest
# 可选：复用 AutoTest 虚拟环境
export PYTHONPATH=/Users/jia/code/crm-autotest
/Users/jia/code/AutoTest/.venv/bin/pytest testcases/crm -q
```

Token 可用环境变量覆盖，不必改 ini：

```bash
export CRM_TOKEN='你的JWT'
export CRM_HOST='https://crm-api.bestfulfill.top'
```

写操作用例（create/update/delete）默认跳过：

```bash
CRM_ALLOW_MUTATIONS=1 pytest testcases/crm -m mutation -q
```

## 配置

```bash
cp config/conf_crm_test.ini.example config/conf_crm_test.ini
# 编辑 conf_crm_test.ini，填入有效 token
# 或：export CRM_TOKEN='你的JWT'
```

`config/conf_crm_test.ini` 含密钥，已加入 `.gitignore`，不会提交到 GitHub。

## Allure 报告

```bash
pytest testcases/crm -q
allure generate reports/allure-results -o reports/allure-report --clean
open reports/allure-report/index.html
```
