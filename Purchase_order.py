import os
import requests

# ============================
#  从环境变量读配置（给 GitHub Actions 用）
# ============================
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_DATABASE_ID = os.environ["NOTION_DATABASE_ID"]
SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_USER_ID = os.environ["SLACK_USER_ID"]

# Notion 字段名（按你自己的表来，有差异可以用 env 覆盖）
NOTION_TITLE_PROPERTY = os.getenv("NOTION_TITLE_PROPERTY", "Product Name")   # 商品名
NOTION_DESCRIPTION_PROPERTY = os.getenv("NOTION_DESCRIPTION_PROPERTY", "Notes")  # 备注
NOTION_NOTIFIED_PROPERTY = os.getenv("NOTION_NOTIFIED_PROPERTY", "Notified")    # Checkbox
NOTION_STATUS_PROPERTY = os.getenv("NOTION_STATUS_PROPERTY", "Status")          # 状态列
NOTION_STATUS_TARGET = os.getenv("NOTION_STATUS_TARGET", "Requesting")          # 目标状态

NOTION_QUANTITY_PROPERTY = os.getenv("NOTION_QUANTITY_PROPERTY", "Quantity")
NOTION_APPLICANT_PROPERTY = os.getenv("NOTION_APPLICANT_PROPERTY", "Applicant")
NOTION_EXPECTED_PRICE_PROPERTY = os.getenv("NOTION_EXPECTED_PRICE_PROPERTY", "Expected Price")

# ============================
#  Notion API（旧版 2022-06-28）
# ============================
NOTION_QUERY_URL = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
NOTION_PAGE_URL = "https://api.notion.com/v1/pages"
NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",   # ✅ 固定旧版本
    "Content-Type": "application/json",
}

# Slack API
SLACK_API_URL = "https://slack.com/api/chat.postMessage"
SLACK_HEADERS = {
    "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
    "Content-Type": "application/json; charset=utf-8",
}


# ============================
#          Notion 部分
# ============================

def fetch_all_pages():
    """
    使用旧版数据库查询接口：
      POST /v1/databases/{database_id}/query

    不带 filter，按 last_edited_time 排序取回所有页面。
    之后在 Python 里按 Status / Notified 过滤，避免各种类型不匹配。
    """
    payload = {
        "sorts": [
            {
                "timestamp": "last_edited_time",
                "direction": "ascending"
            }
        ],
        "page_size": 100
    }

    results = []
    has_more = True
    next_cursor = None

    while has_more:
        if next_cursor:
            payload["start_cursor"] = next_cursor

        resp = requests.post(NOTION_QUERY_URL, headers=NOTION_HEADERS, json=payload)

        if not resp.ok:
            print("Error:  Notion API returned:", resp.status_code, resp.text)
            resp.raise_for_status()

        data = resp.json()
        results.extend(data.get("results", []))
        has_more = data.get("has_more", False)
        next_cursor = data.get("next_cursor")

    return results


def get_status_name(page: dict):
    """从 Status 属性里取当前状态名"""
    props = page.get("properties", {})
    s_prop = props.get(NOTION_STATUS_PROPERTY)
    if not s_prop:
        return None
    status = s_prop.get("status")
    if not status:
        return None
    return status.get("name")


def get_notified_flag(page: dict) -> bool:
    """从 Notified 属性里取 checkbox 布尔值"""
    props = page.get("properties", {})
    n_prop = props.get(NOTION_NOTIFIED_PROPERTY)
    if not n_prop:
        return False
    # checkbox 类型字段格式：{"checkbox": true/false}
    return bool(n_prop.get("checkbox", False))


def extract_title(page: dict) -> str:
    """从标题列里取出商品名 / 项目名"""
    try:
        title_items = page["properties"][NOTION_TITLE_PROPERTY]["title"]
        if not title_items:
            return "(无标题)"
        return "".join(t.get("plain_text", "") for t in title_items) or "(无标题)"
    except Exception:
        return "(无标题)"


def extract_description(page: dict) -> str:
    """从 Notes（或你指定的描述列）里取文字，可为空"""
    if not NOTION_DESCRIPTION_PROPERTY:
        return ""

    props = page.get("properties", {})
    desc_prop = props.get(NOTION_DESCRIPTION_PROPERTY)
    if not desc_prop:
        return ""

    if "rich_text" in desc_prop:
        texts = desc_prop.get("rich_text", [])
        return "".join(t.get("plain_text", "") for t in texts)

    return ""


def extract_quantity(page: dict) -> str:
    """从 Quantity 列取数值，返回字符串"""
    props = page.get("properties", {})
    q_prop = props.get(NOTION_QUANTITY_PROPERTY)
    if not q_prop:
        return "-"
    value = q_prop.get("number")
    if value is None:
        return "-"
    return str(value)


def extract_expected_price(page: dict) -> str:
    """从 Expected Price 列取数值，返回字符串"""
    props = page.get("properties", {})
    p_prop = props.get(NOTION_EXPECTED_PRICE_PROPERTY)
    if not p_prop:
        return "-"
    value = p_prop.get("number")
    if value is None:
        return "-"
    return str(value)


def extract_applicant(page: dict) -> str:
    """从 Applicant 列取申请人姓名（people 属性）"""
    props = page.get("properties", {})
    a_prop = props.get(NOTION_APPLICANT_PROPERTY)
    if not a_prop:
        return "-"

    people = a_prop.get("people", [])
    if not people:
        return "-"

    names = []
    for p in people:
        name = p.get("name")
        if name:
            names.append(name)
        else:
            person = p.get("person") or {}
            email = person.get("email")
            if email:
                names.append(email)
    return ", ".join(names) if names else "-"


def build_page_url(page_id: str) -> str:
    """根据 page_id 生成网页可访问的 Notion 链接"""
    clean_id = page_id.replace("-", "")
    return f"https://www.notion.so/{clean_id}"


def mark_as_notified(page_id: str):
    """把当前记录的 Notified 复选框设为 True，表示已经通知过"""
    url = f"{NOTION_PAGE_URL}/{page_id}"
    payload = {
        "properties": {
            NOTION_NOTIFIED_PROPERTY: {
                "checkbox": True
            }
        }
    }
    resp = requests.patch(url, headers=NOTION_HEADERS, json=payload)
    resp.raise_for_status()


# ============================
#           Slack 部分
# ============================

def send_slack_message(text: str):
    payload = {
        "channel": SLACK_USER_ID,  # 可以是用户 ID 或频道 ID
        "text": text,
    }
    resp = requests.post(SLACK_API_URL, headers=SLACK_HEADERS, json=payload)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Slack API Error: {data}")


# ============================
#              主程序
# ============================

def main():
    print(f"[INFO] 拉取数据库全部页面，然后在本地过滤 Status == '{NOTION_STATUS_TARGET}' 且 Notified == false ...")
    all_pages = fetch_all_pages()
    print(f"[INFO] 数据库总记录数: {len(all_pages)}")

    # 本地过滤：Status == Requesting 且 Notified == False
    pages = []
    for page in all_pages:
        status_name = get_status_name(page)
        notified = get_notified_flag(page)
        if status_name == NOTION_STATUS_TARGET and not notified:
            pages.append(page)

    print(f"[INFO] 满足条件( Status='{NOTION_STATUS_TARGET}', Notified=false ) 的记录数: {len(pages)}")

    if not pages:
        print("[INFO] 没有需要通知的项目。")
        return

    for page in pages:
        page_id = page["id"]
        last_edited_time = page.get("last_edited_time")

        title = extract_title(page)
        quantity = extract_quantity(page)
        applicant = extract_applicant(page)
        expected_price = extract_expected_price(page)
        description = extract_description(page)
        url = build_page_url(page_id)

        if description:
            message = (
                f"📦 新的采购请求（Status: {NOTION_STATUS_TARGET}）：\n"
                f"- Product: {title}\n"
                f"- Quantity: {quantity}\n"
                f"- Applicant: {applicant}\n"
                f"- Expected Price: {expected_price}\n"
                f"- Notes: {description}\n"
                f"- Link: {url}\n"
                f"- Last Edited: {last_edited_time}"
            )
        else:
            message = (
                f"📦 新的采购请求（Status: {NOTION_STATUS_TARGET}）：\n"
                f"- Product: {title}\n"
                f"- Quantity: {quantity}\n"
                f"- Applicant: {applicant}\n"
                f"- Expected Price: {expected_price}\n"
                f"- Link: {url}\n"
                f"- Last Edited: {last_edited_time}"
            )

        print(f"[INFO] 发送 Slack 消息：{title}")
        send_slack_message(message)

        print(f"[INFO] 标记 Notified=True：{page_id}")
        mark_as_notified(page_id)

    print("[INFO] 所有需要通知的项目已处理完毕。")


if __name__ == "__main__":
    main()
