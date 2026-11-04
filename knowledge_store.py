"""每个聊天独立的资料库；复制到项目根目录后使用。"""
import csv
import io
from uuid import uuid4

from database import connect_db, now


def _chunks(text, size=1200):
    # 文档分段，避免一次把全文送给模型。
    for start in range(0, len(text), size):
        yield text[start:start + size]


def add_document(conversation_id, filename, text):
    if not text.strip():
        raise ValueError("资料中没有可用文字")
    if len(text) > 200_000:
        raise ValueError("单份资料解析后最多 20 万字")
    file_id = str(uuid4())
    with connect_db() as db:
        db.execute(
            "INSERT INTO knowledge_files(id, conversation_id, filename, kind, created_at) "
            "VALUES (?, ?, ?, 'document', ?)",
            (file_id, str(conversation_id), filename, now()),
        )
        db.executemany(
            "INSERT INTO knowledge_chunks(file_id, chunk_index, content) VALUES (?, ?, ?)",
            ((file_id, index, part) for index, part in enumerate(_chunks(text))),
        )
    return {"id": file_id, "filename": filename, "kind": "document"}


def add_inventory_csv(conversation_id, filename, content):
    try:
        reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig"), newline=""))
        if reader.fieldnames != ["product_name", "stock"]:
            raise ValueError("库存 CSV 表头必须是 product_name,stock")
        items = []
        seen = set()
        for row in reader:
            if len(items) >= 1000:
                raise ValueError("库存 CSV 最多 1000 行")
            name = (row.get("product_name") or "").strip()
            raw_stock = (row.get("stock") or "").strip()
            if not name or len(name) > 100 or name in seen:
                raise ValueError("商品名为空、过长或重复")
            if not raw_stock.isascii() or not raw_stock.isdecimal():
                raise ValueError(f"{name} 的库存必须是非负整数")
            stock = int(raw_stock)
            if stock > 1_000_000_000:
                raise ValueError("库存数值过大")
            items.append((name, stock))
            seen.add(name)
        if not items:
            raise ValueError("库存 CSV 不能为空")
    except UnicodeError as error:
        raise ValueError("库存 CSV 必须使用 UTF-8 编码") from error
    except csv.Error as error:
        raise ValueError("库存 CSV 格式错误") from error

    file_id = str(uuid4())
    # 同一事务完成元数据与商品导入；后上传文件覆盖同名商品。
    with connect_db() as db:
        db.execute(
            "INSERT INTO knowledge_files(id, conversation_id, filename, kind, created_at) "
            "VALUES (?, ?, ?, 'inventory', ?)",
            (file_id, str(conversation_id), filename, now()),
        )
        db.executemany("""
            INSERT INTO inventory_items(conversation_id, product_name, stock, file_id)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(conversation_id, product_name)
            DO UPDATE SET stock = excluded.stock, file_id = excluded.file_id
        """, ((str(conversation_id), name, stock, file_id) for name, stock in items))
    return {"id": file_id, "filename": filename, "kind": "inventory", "count": len(items)}


def list_files(conversation_id):
    with connect_db() as db:
        rows = db.execute("""
            SELECT id, filename, kind, created_at FROM knowledge_files
            WHERE conversation_id = ? ORDER BY created_at DESC, id
        """, (str(conversation_id),)).fetchall()
    return [dict(row) for row in rows]


def delete_file(conversation_id, file_id):
    with connect_db() as db:
        # 外键级联同时删除片段和该文件导入的库存行。
        result = db.execute(
            "DELETE FROM knowledge_files WHERE id = ? AND conversation_id = ?",
            (str(file_id), str(conversation_id)),
        )
        return result.rowcount > 0


def lookup_inventory(conversation_id, product_name):
    name = product_name.strip()
    if not name or len(name) > 100:
        raise ValueError("商品名不能为空或超过 100 字")
    with connect_db() as db:
        exact = db.execute("""
            SELECT product_name, stock FROM inventory_items
            WHERE conversation_id = ? AND product_name = ?
        """, (str(conversation_id), name)).fetchone()
        if exact:
            return {"found": True, "product_name": exact["product_name"], "stock": exact["stock"]}
        candidates = db.execute("""
            SELECT product_name FROM inventory_items
            WHERE conversation_id = ? AND instr(product_name, ?) > 0
            ORDER BY product_name LIMIT 10
        """, (str(conversation_id), name)).fetchall()
    return {"found": False, "query": name,
            "candidates": [row["product_name"] for row in candidates]}


def search_chunks(conversation_id, query):
    term = query.strip()[:100]
    if not term:
        raise ValueError("搜索词不能为空")
    with connect_db() as db:
        rows = db.execute("""
            SELECT f.filename, c.chunk_index, c.content
            FROM knowledge_chunks AS c
            JOIN knowledge_files AS f ON f.id = c.file_id
            WHERE f.conversation_id = ? AND instr(c.content, ?) > 0
            ORDER BY f.created_at DESC, c.chunk_index LIMIT 5
        """, (str(conversation_id), term)).fetchall()
    return {"query": term, "matches": [dict(row) for row in rows]}
