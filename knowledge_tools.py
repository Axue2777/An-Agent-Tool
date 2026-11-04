"""提供给模型的资料库工具定义；复制到项目根目录后使用。"""

LOOKUP_INVENTORY_TOOL = {
    "type": "function",
    "function": {
        "name": "lookup_inventory",
        "description": "查询当前聊天上传的库存 CSV。找不到商品时返回未知或候选名称。",
        "parameters": {
            "type": "object",
            "properties": {"product_name": {"type": "string"}},
            "required": ["product_name"],
            "additionalProperties": False,
        },
    },
}

SEARCH_KNOWLEDGE_TOOL = {
    "type": "function",
    "function": {
        "name": "search_knowledge",
        "description": "按关键词检索当前聊天资料库中的文档片段，返回文件名和片段序号。",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}
