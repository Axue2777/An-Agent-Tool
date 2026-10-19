import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

# 数据库固定放在后端目录，不受终端工作路径影响。
DB_PATH = Path(__file__).resolve().parent / "agent.db"


# 每次操作使用独立连接，适配目前线程执行的聊天任务。
@contextmanager
def connect_db():
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        # 正常退出提交事务，异常退出回滚事务。
        with connection:
            yield connection
    finally:
        connection.close()


# 数据库存 UTC，保留时区信息，方便以后统一转成用户所在时区。
def now():
    return datetime.now(timezone.utc).isoformat()


# 初始化只创建缺少的表，不清空已有记录。
def init_db():
    with connect_db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                tool_steps_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id)
            );
            CREATE INDEX IF NOT EXISTS idx_messages_conversation
            ON messages(conversation_id, id);
        """)


# 收到问题就保存：创建或更新会话，并追加最新用户消息。
def save_user_message(conversation_id, content):
    chat_id = str(conversation_id)
    timestamp = now()
    # 用首次提问的前 30 个字符命名，将换行和连续空白合并为一个空格。
    title = " ".join(content.split())[:30] or "新建聊天"
    with connect_db() as db:
        db.execute("""
            INSERT INTO conversations(id, title, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title = CASE
                    WHEN conversations.title = '新建聊天'
                    AND NOT EXISTS (
                        SELECT 1 FROM messages
                        WHERE conversation_id = excluded.id AND role = 'user'
                    )
                    THEN excluded.title
                    ELSE conversations.title
                END,
                updated_at = excluded.updated_at
        """, (chat_id, title, timestamp, timestamp))
        # 在同一事务中完成命名和消息保存；后续消息不再触发自动命名。
        db.execute("""
            INSERT INTO messages(conversation_id, role, content, created_at)
            VALUES (?, 'user', ?, ?)
        """, (chat_id, content, timestamp))


# 一轮成功后保存完整回答及工具结果，不逐片段反复写库。
def save_assistant_message(conversation_id, content, tool_steps):
    chat_id = str(conversation_id)
    timestamp = now()
    with connect_db() as db:
        db.execute("""
            INSERT INTO messages(
                conversation_id, role, content, tool_steps_json, created_at
            ) VALUES (?, 'assistant', ?, ?, ?)
        """, (chat_id, content, json.dumps(tool_steps, ensure_ascii=False), timestamp))
        db.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (timestamp, chat_id),
        )


# 返回会话列表；更新较近的会话排在前面。
def list_conversations():
    with connect_db() as db:
        rows = db.execute("""
            SELECT id, title, created_at, updated_at
            FROM conversations ORDER BY updated_at DESC, id
        """).fetchall()
    return [dict(row) for row in rows]


# 根据编号读取完整会话，将工具步骤还原成列表。
def get_conversation(conversation_id):
    with connect_db() as db:
        chat = db.execute(
            "SELECT * FROM conversations WHERE id = ?", (str(conversation_id),)
        ).fetchone()
        if chat is None:
            return None
        rows = db.execute("""
            SELECT id, role, content, tool_steps_json, created_at
            FROM messages WHERE conversation_id = ? ORDER BY id
        """, (str(conversation_id),)).fetchall()
    result = dict(chat)
    result["messages"] = []
    for row in rows:
        message = dict(row)
        message["tool_steps"] = json.loads(message.pop("tool_steps_json"))
        result["messages"].append(message)
    return result

# 关键知识点：

# - PRIMARY KEY 唯一标识会话或消息。
# - FOREIGN KEY 将消息关联到会话。
# - SQL 参数使用 ? 占位，用户文本不拼接到 SQL 中。
# - ON CONFLICT 仅在首次提问时替换默认标题，保留手动设置的非默认名称。
# - 每条用户消息与对应会话创建在一个事务中保存。
# - 不在等待模型时保持数据库事务，避免长时间占锁。
# - 工具步骤使用 JSON 保留原始结构，恢复后仍能用于执行记录和下载链接。

# 创建空会话，让“新建聊天”无需等到发送消息才保存。
def create_conversation(conversation_id):
    timestamp = now()
    with connect_db() as db:
        db.execute("""
            INSERT INTO conversations(id, title, created_at, updated_at)
            VALUES (?, ?, ?, ?)
        """, (str(conversation_id), "新建聊天", timestamp, timestamp))
    return get_conversation(conversation_id)


# 修改标题，返回是否找到并更新了对应会话。
def rename_conversation(conversation_id, title):
    with connect_db() as db:
        cursor = db.execute("""
            UPDATE conversations SET title = ?, updated_at = ?
            WHERE id = ?
        """, (title, now(), str(conversation_id)))
        return cursor.rowcount > 0


# 在同一事务中先删除消息，再删除会话，满足外键约束。
def delete_conversation(conversation_id):
    with connect_db() as db:
        db.execute(
            "DELETE FROM messages WHERE conversation_id = ?",
            (str(conversation_id),),
        )
        cursor = db.execute(
            "DELETE FROM conversations WHERE id = ?",
            (str(conversation_id),),
        )
        return cursor.rowcount > 0

# 只读取最近 21 条消息，不删除数据库中的完整历史。
def get_recent_messages(conversation_id):
    with connect_db() as db:
        rows = db.execute("""
            SELECT role, content
            FROM messages
            WHERE conversation_id = ?
            ORDER BY id DESC
            LIMIT 21
        """, (str(conversation_id),)).fetchall()

    # 查询时最新在前，交给模型前恢复为正常聊天顺序。
    history = [dict(row) for row in reversed(rows)]

    # 截取后如果从助手回答开始，移除这条缺少问题的回答。
    while history and history[0]["role"] == "assistant":
        history.pop(0)

    return history
