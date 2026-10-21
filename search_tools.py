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
        # JSON 解析成功不代表结构正确，先检查对象类型再读取字段。
        if not isinstance(payload, dict):
            return {"error": "智谱没有返回预期的搜索结果对象"}
        results = payload.get("search_result")
        if not isinstance(results, list):
            return {"error": "智谱没有返回预期的搜索结果列表"}

        sources = []
        for item in results[:5]:
            # 跳过异常条目，避免一条坏数据中断本次全部搜索结果。
            if not isinstance(item, dict):
                continue
            url = item.get("link") or ""
            if not isinstance(url, str):
                continue
            try:
                parsed = urlparse(url)
            except ValueError:
                continue
            if (parsed.scheme not in {"http", "https"} or not parsed.netloc
                    or parsed.username or parsed.password):
                continue
            # 文本字段可能缺失或类型异常，使用安全默认值而不强行切片。
            title = item.get("title")
            snippet = item.get("content")
            published_date = item.get("publish_date")
            sources.append({
                "title": title[:200] if isinstance(title, str) and title else "未命名网页",
                "url": url,
                "snippet": snippet[:2000] if isinstance(snippet, str) else "",
                "published_date": published_date if isinstance(published_date, str) else None,
            })
        return {"provider": "zhipu", "query": query.strip(), "sources": sources}
    except httpx.HTTPStatusError as error:
        # 只返回状态码，不将认证信息或完整异常响应写入聊天。
        return {"error": f"智谱搜索返回 HTTP {error.response.status_code}，请检查控制台"}
    except httpx.RequestError:
        return {"error": "智谱搜索连接失败或超时"}
    except ValueError:
        return {"error": "智谱搜索响应无法解析"}

# 功能解释：

# - SEARCH_TOOL 定义模型能看到的名称和参数。
# - search_web 真正访问搜索接口，密钥从后端环境读取。
# - search_engine 选择智谱搜索服务的引擎，本示例为 search_pro。
# - count=5 控制返回条数；content_size 控制摘要长度。
# - noLimit 表示不强制只查最近一周等时间段，不代表结果全部是最新。
# - 统一转换为 sources 后，上层模型不需要理解不同供应商的原始字段。
# - 没有结果时 sources 可以为空；模型应如实说明，不能编造。
# - 网络或服务错误以 error 返回，沿用现有工具错误展示。
