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
# 下面这些是“默认值”，你可以在 workflow 里通过 env 改掉
NOTION_TITLE_PROPERTY = os.getenv("NOTION_TITLE_PROPERTY", "Product Name")   # 商品名
NOTION_DESCRIPTION_PROPERTY = os.getenv("NOTION_DESCRIPTION_PROPERTY", "Notes")  # 备注
NOTION_NOTIFIED_PROPERTY = os.getenv("NOTION_NOTIFIED_PROPERTY", "Notified")    # Checkbox
NOTION_STATUS_PROPERTY = os.getenv("NOTION_STATUS_PROPERTY", "Status")          # 状态列
NOTION_STATUS_TARGET = os.getenv("NOTION_STATUS_TARGET", "Requesting")          # 目标状态

# 新增：数量 / 申请人 / 预期价格
NOTION_QUANTITY_PROPERTY = os.getenv("NOTION_QUANTITY_PROPERTY", "Quantity")
NOTION_APPLICANT_PROPERTY = os.getenv("NOTION_APPLICANT_PROPERTY", "Applicant")
NOTION_EXPECTED_PRICE_PROPERTY = os.getenv("NOTION_EXPECTED_PRICE_PROPERTY", "Expected Price")

# Notion API
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

def fetch_requesting_unnotified_pages():
    """
    从 Notion 数据库中查找：
      - Status == NOTION_STATUS_TARGET
      - Notified == False
    的所有记录。
    用户只要把 Status 改成 Requesting，就会在下次遍历时被捞出来。
    """
    payload = {
        "filter": {
            "and": [
                {
                    "property": NOTION_STATUS_PROPERTY,
                    "status": {
                        "equals": NOTION_STATUS_TARGET
                    }
                },
                {
                    "property": NOTION_NOTIFIED_PROPERTY,
                    "checkbox": {
                        "equals": False
                    }
                }
            ]
        },
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
        resp.raise_for_status()
        data = resp.json()

        results.extend(data.get("results", []))
        has_more = data.get("has_more", False)
        next_cursor = data.get("next_cursor")

    return results


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
    # 数值类型：Notion API 里一般是 {"number": 3}
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
    # 这里简单转成字符串，如果你想加货币符号，可以在这里改
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

    # 多人时用逗号拼
    names = []
    for p in people:
        name = p.get("name")
        if name:
            names.append(name)
        else:
            # 兜底用邮箱
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
    print(f"[INFO] 查询 Status == '{NOTION_STATUS_TARGET}' 且 Notified == false 的记录...")
    pages = fetch_requesting_unnotified_pages()
    print(f"[INFO] 找到 {len(pages)} 条需要通知的项目。")

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

        # 拼装 Slack 消息：Product → Quantity → Applicant → Expected Price → Notes
        if description:
            message = (
                f"📦 New Order Request（Status: {NOTION_STATUS_TARGET}）：\n"
                f"- Product: {title}\n"
                f"- Quantity: {quantity}\n"
                f"- Applicant: {applicant}\n"
                f"- Expected Price: {expected_price}\n"
                f"- Notes: {description}\n"
            )
        else:
            message = (
                f"📦 New Order Request（Status: {NOTION_STATUS_TARGET}）：\n"
                f"- Product: {title}\n"
                f"- Quantity: {quantity}\n"
                f"- Applicant: {applicant}\n"
                f"- Expected Price: {expected_price}\n"
            )

        print(f"[INFO] 发送 Slack 消息：{title}")
        send_slack_message(message)

        print(f"[INFO] 标记 Notified=True：{page_id}")
        mark_as_notified(page_id)

    print("[INFO] 所有需要通知的项目已处理完毕。")


if __name__ == "__main__":
    main()
