import os
import requests

# ============================
#  1. 从环境变量读配置
# ============================
# Notion 配置
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_DATABASE_ID = os.environ["NOTION_DATABASE_ID"]

# Slack 配置
SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_USER_ID = os.environ["SLACK_USER_ID"]

# Notion 属性名配置
NOTION_TITLE_PROPERTY = os.getenv("NOTION_TITLE_PROPERTY", "Product Name")
NOTION_DESCRIPTION_PROPERTY = os.getenv("NOTION_DESCRIPTION_PROPERTY", "Notes")
NOTION_NOTIFIED_PROPERTY = os.getenv("NOTION_NOTIFIED_PROPERTY", "Notified")  # Checkbox
NOTION_STATUS_PROPERTY = os.getenv("NOTION_STATUS_PROPERTY", "Status")        # Status
NOTION_STATUS_TARGET = os.getenv("NOTION_STATUS_TARGET", "Requesting")

NOTION_QUANTITY_PROPERTY = os.getenv("NOTION_QUANTITY_PROPERTY", "Quantity")
NOTION_APPLICANT_PROPERTY = os.getenv("NOTION_APPLICANT_PROPERTY", "Applicant")
NOTION_EXPECTED_PRICE_PROPERTY = os.getenv("NOTION_EXPECTED_PRICE_PROPERTY", "Expected Price")

# API URL
NOTION_QUERY_URL = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
NOTION_PAGE_URL = "https://api.notion.com/v1/pages"
NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

SLACK_API_URL = "https://slack.com/api/chat.postMessage"
SLACK_HEADERS = {
    "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
    "Content-Type": "application/json; charset=utf-8",
}

# ============================
#  2. Notion 逻辑部分
# ============================
def fetch_all_pages():
    payload = {
        "sorts": [{"timestamp": "last_edited_time", "direction": "ascending"}],
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
    return prop.get("status", {}).get("name") if prop else None

def get_notified_flag(page: dict) -> bool:
    prop = page["properties"].get(NOTION_NOTIFIED_PROPERTY)
    return bool(prop.get("checkbox", False)) if prop else False

def extract_title(page: dict) -> str:
    try:
        title_items = page["properties"][NOTION_TITLE_PROPERTY]["title"]
        return "".join(t.get("plain_text", "") for t in title_items) if title_items else "(无标题)"
    except Exception:
        return "(无标题)"

def extract_description(page: dict) -> str:
    prop = page["properties"].get(NOTION_DESCRIPTION_PROPERTY)
    texts = prop.get("rich_text", []) if prop else []
    return "".join(t.get("plain_text", "") for t in texts)

def extract_quantity(page: dict) -> str:
    p = page["properties"].get(NOTION_QUANTITY_PROPERTY)
    return str(p["number"]) if p and p.get("number") is not None else "-"

def extract_expected_price(page: dict) -> str:
    p = page["properties"].get(NOTION_EXPECTED_PRICE_PROPERTY)
    return str(p["number"]) if p and p.get("number") is not None else "-"

def extract_applicant(page: dict) -> str:
    p = page["properties"].get(NOTION_APPLICANT_PROPERTY)
    if not p: return "-"
    people = p.get("people", [])
    names = [person.get("name") or person.get("person", {}).get("email", "") for person in people]
    return ", ".join(filter(None, names)) or "-"

def build_database_url() -> str:
    return f"https://www.notion.so/213756632df1800b870def0eb8ed4318?v=213756632df180aa87b5000ca6013019"

def mark_as_notified(page_id: str):
    url = f"{NOTION_PAGE_URL}/{page_id}"
    payload = {"properties": {NOTION_NOTIFIED_PROPERTY: {"checkbox": True}}}
    resp = requests.patch(url, headers=NOTION_HEADERS, json=payload)
    resp.raise_for_status()

# ============================
#  3. 通知逻辑部分 (仅 Slack)
# ============================
def send_slack_message(text: str, url: str):
    payload = {
        "channel": SLACK_USER_ID,
        "text": text,
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": text}},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "See Details"},
                        "url": url
                    }
                ]
            }
        ]
    }
    resp = requests.post(SLACK_API_URL, headers=SLACK_HEADERS, json=payload)
    resp.raise_for_status()

# ============================
#  4. 主程序
# ============================
def main():
    print(f"[INFO] 正在拉取 Notion 数据库...")
    all_pages = fetch_all_pages()
    
    # 筛选待通知的项目
    pending_pages = [
        p for p in all_pages 
        if get_status_name(p) == NOTION_STATUS_TARGET and not get_notified_flag(p)
    ]

    if not pending_pages:
        print("[INFO] 没有需要通知的新项目。")
        return

    db_url = build_database_url()

    for page in pending_pages:
        page_id = page["id"]
        title = extract_title(page)
        quantity = extract_quantity(page)
        applicant = extract_applicant(page)
        expected_price = extract_expected_price(page)
        description = extract_description(page)

        # 构建 Slack 消息文本
        message_body = (
            f"👋 Dear Prof. Matsuzaka,\n"
            f"📦 You received a new order request from {applicant}.\n\n"
            f"- Product: {title}\n"
            f"- Quantity: {quantity}\n"
            f"- Expected Price: ￥{expected_price}\n"
        )
        if description:
            message_body += f"- Notes: {description}\n"
        
        # 发送 Slack 通知
        print(f"[INFO] 正在通知 Slack: {title}")
        send_slack_message(message_body, db_url)

        # 回写 Notion，标记为已通知
        print(f"[INFO] 正在标记 Notion 状态...")
        mark_as_notified(page_id)

    print("[INFO] 所有任务处理完毕。")

if __name__ == "__main__":
    main()
