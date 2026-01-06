"""飞书 webhook 通知"""

import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)


class FeishuNotifier:
    """发送飞书 webhook 通知"""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send_notification(
        self,
        repo_name: str,
        commit_count: int,
        summary: str,
        markpost_url: Optional[str] = None
    ):
        """发送飞书通知

        Args:
            repo_name: 仓库名称
            commit_count: 提交数量
            summary: 变更摘要
            markpost_url: Markpost 报告链接（可选）
        """
        # 构造飞书卡片消息
        card = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": f"📊 {repo_name} 代码变更通知"
                    },
                    "template": "blue"
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": f"**变更摘要**\n{summary}"
                        }
                    },
                    {
                        "tag": "hr"
                    },
                    {
                        "tag": "div",
                        "fields": [
                            {
                                "is_short": True,
                                "text": {
                                    "tag": "lark_md",
                                    "content": f"**提交数量**\n{commit_count}"
                                }
                            },
                            {
                                "is_short": True,
                                "text": {
                                    "tag": "lark_md",
                                    "content": f"**仓库**\n{repo_name}"
                                }
                            }
                        ]
                    }
                ]
            }
        }

        # 如果有 markpost 链接，添加按钮
        if markpost_url:
            card["card"]["elements"].append({
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {
                            "tag": "plain_text",
                            "content": "查看详细报告"
                        },
                        "type": "default",
                        "url": markpost_url
                    }
                ]
            })

        # 发送请求
        try:
            logger.info(f"发送飞书通知: {repo_name}")
            response = requests.post(
                self.webhook_url,
                json=card,
                timeout=10
            )
            response.raise_for_status()
            logger.info(f"飞书通知发送成功: {repo_name}")
        except requests.RequestException as e:
            logger.error(f"发送飞书通知失败: {e}")
            raise RuntimeError(f"发送飞书通知失败: {e}") from e
