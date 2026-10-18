import os
from urllib.parse import urlparse
import httpx


# 工具说明只暴露搜索词，认证信息由后端读取。
SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "search_web",
        "description": "使用智谱联网搜索公开资料，返回网页标题、链接和摘要。",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}


# 请求独立搜索接口，再把供应商字段转换成 Agent 使用的统一结果。
def search_web(query):
    if not isinstance(query, str) or not query.strip() or len(query) > 500:
        raise ValueError("搜索词必须是 1 至 500 字符的非空字符串")
    key = os.environ.get("ZHIPU_API_KEY")
    if not key:
        return {"error": "后端未配置 ZHIPU_API_KEY，无法联网搜索"}

    try:
        # 延续项目的直连设置，保留 HTTPS 证书验证并设置超时。
        with httpx.Client(timeout=20.0, trust_env=False) as client:
            response = client.post(
                "https://open.bigmodel.cn/api/paas/v4/web_search",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "search_engine": "search_pro",
                    "search_query": query.strip(),
                    "count": 5,
                    "search_recency_filter": "noLimit",
                    "content_size": "medium",
                },
            )
            response.raise_for_status()
            payload = response.json()

        # 智谱原始结果名为 search_result，网页地址字段为 link。
        results = payload.get("search_result")
        if not isinstance(results, list):
            return {"error": "智谱没有返回预期的搜索结果列表"}

        sources = []
        for item in results[:5]:
            url = item.get("link") or ""
            if urlparse(url).scheme not in {"http", "https"}:
                continue
            sources.append({
                "title": (item.get("title") or "未命名网页")[:200],
                "url": url,
                "snippet": (item.get("content") or "")[:2000],
                "published_date": item.get("publish_date"),
            })
        return {"provider": "zhipu", "query": query.strip(), "sources": sources}
    except httpx.HTTPStatusError as error:
        # 只返回状态码，不将认证信息或完整异常响应写入聊天。
        return {"error": f"智谱搜索返回 HTTP {error.response.status_code}，请检查控制台"}
    except httpx.RequestError:
        return {"error": "智谱搜索连接失败或超时"}
    except ValueError:
        return {"error": "智谱搜索响应无法解析"}