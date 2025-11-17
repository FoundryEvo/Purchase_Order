import os
import requests

# ============================
#  从环境变量读配置
# ============================
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_DATABASE_ID = os.environ["NOTION_DATABASE_ID"]
SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_USER_ID = os.environ["SLACK_USER_ID"]

NOTION_TITLE_PROPERTY = os.getenv("NOTION_TITLE_PROPERTY", "Product Name")
NOTION_DESCRIPTION_PROPERTY = os.getenv("NOTION_DESCRIPTION_PROPERTY", "Notes")
NOTION_NOTIFIED_PROPERTY = os.getenv("NOTION_NOTIFIED_PROPERTY", "Notified")  # ✅ checkbox
NOTION_STATUS_PROPERTY = os.getenv("NOTION_STATUS_PROPERTY", "Status")        # ✅ status
NOTION_STATUS_TARGET = os.getenv("NOTION_STATUS_TARGET", "Requesting")

NOTION_QUANTITY_PROPERTY = os.getenv("NOTION_QUANTITY_PROPERTY", "Quantity")
NOTION_APPLICANT_PROPERTY = os.getenv("NOTION_APPLICANT_PROPERTY", "Applicant")
NOTION_EXPECTED_PRICE_PROPERTY = os.getenv("NOTION_EXPECTED_PRICE_PROPERTY", "Expected Price")

# ============================
#  Notion API
# ============================
NOTION_QUERY_URL = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
NOTION_PAGE_URL = "https://api.notion.com/v1/pages"
NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
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
    payload = {
        "sorts": [{
            "timestamp": "last_edited_time",
            "direction": "ascending"
        }],
        "page_size": 100
    }

    results = []
    has_more = True
    next_cursor = None

    while has_more:
        if next_cursor:
            payload["start_cursor"] = next_cursor

        resp = requests.post(NOTION_QUERY_URL, headers=NOTION_HEADERS, json=payload)
        resp.raise_for_status()

        data = resp.json()
        results.extend(data.get("results", []))
        has_more = data.get("has_more", False)
        next_cursor = data.get("next_cursor")

    return results


def get_status_name(page: dict):
    prop = page["properties"].get(NOTION_STATUS_PROPERTY)
    if not prop:
        return None
    status = prop.get("status")
    if not status:
        return None
    return status.get("name")


def get_notified_flag(page: dict) -> bool:
    """Notified 为 checkbox：True 表示已通知"""
    prop = page["properties"].get(NOTION_NOTIFIED_PROPERTY)
    if not prop:
        return False
    # ✅ checkbox 字段结构：{"checkbox": true/false}
    return bool(prop.get("checkbox", False))


def extract_title(page: dict) -> str:
    try:
        title_items = page["properties"][NOTION_TITLE_PROPERTY]["title"]
        if not title_items:
            return "(无标题)"
        return "".join(t.get("plain_text", "") for t in title_items)
    except Exception:
        return "(无标题)"


def extract_description(page: dict) -> str:
    prop = page["properties"].get(NOTION_DESCRIPTION_PROPERTY)
    if not prop:
        return ""
    texts = prop.get("rich_text", [])
    return "".join(t.get("plain_text", "") for t in texts)


def extract_quantity(page: dict) -> str:
    p = page["properties"].get(NOTION_QUANTITY_PROPERTY)
    if not p or p.get("number") is None:
        return "-"
    return str(p["number"])


def extract_expected_price(page: dict) -> str:
    p = page["properties"].get(NOTION_EXPECTED_PRICE_PROPERTY)
    if not p or p.get("number") is None:
        return "-"
    return str(p["number"])


def extract_applicant(page: dict) -> str:
    p = page["properties"].get(NOTION_APPLICANT_PROPERTY)
    if not p:
        return "-"
    people = p.get("people", [])
    names = [person.get("name") or person.get("person", {}).get("email", "") for person in people]
    return ", ".join(filter(None, names)) or "-"


def build_page_url(page_id: str) -> str:
    clean_id = page_id.replace("-", "")
    return f"https://www.notion.so/{clean_id}"


def mark_as_notified(page_id: str):
    """把 Notified (checkbox) 勾上 True"""
    url = f"{NOTION_PAGE_URL}"
    payload = {
        "properties": {
            NOTION_NOTIFIED_PROPERTY: {
                "checkbox": True      # ✅ 现在用 checkbox
            }
        }
    }
    resp = requests.patch(url, headers=NOTION_HEADERS, json=payload)
    resp.raise_for_status()


# ============================
#          Slack 部分
# ============================
def send_slack_message(text: str, url: str):
    """发送带一个按钮的消息，按钮打开当前记录"""
    payload = {
        "channel": SLACK_USER_ID,
        "text": text,
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": text}
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "在 Notion 中查看"},
                        "url": url
                    }
                ]
            }
        ]
    }
    resp = requests.post(SLACK_API_URL, headers=SLACK_HEADERS, json=payload)
    resp.raise_for_status()


# ============================
#             主程序
# ============================
def main():
    print(f"[INFO] 拉取数据库全部页面...")
    all_pages = fetch_all_pages()
    print(f"[INFO] 总记录数: {len(all_pages)}")

    pages = []
    for page in all_pages:
        if get_status_name(page) == NOTION_STATUS_TARGET and not get_notified_flag(page):
            pages.append(page)

    print(f"[INFO] 符合条件( Status='{NOTION_STATUS_TARGET}', Notified=false ) 的记录数: {len(pages)}")
    if not pages:
        print("[INFO] 没有需要通知的项目。")
        return

    for page in pages:
        page_id = page["id"]

        title = extract_title(page)
        quantity = extract_quantity(page)
        applicant = extract_applicant(page)
        expected_price = extract_expected_price(page)
        description = extract_description(page)
        url = build_page_url(page_id)

        message = (
        f"👋Dear Prof. Matsuzaka,\n"
        f"📦You received an order request from {applicant}.\n\n"
        f"- Product: {title}\n"
        f"- Quantity: {quantity}\n"
        f"- Expected Price: {expected_price}\n"
        )
        if description:
            message += f"- Notes: {description}\n"

        print(f"[INFO] 发送 Slack 消息: {title}")
        send_slack_message(message, url)

        print(f"[INFO] 标记 Notified=True: {page_id}")
        mark_as_notified(page_id)

    print("[INFO] 所有需要通知的项目已处理完毕。")


if __name__ == "__main__":
    main()
