"""Desktop API preferences. Secrets are stored in Windows Credential Manager."""
import hashlib
import json
import os
import re
from threading import RLock
from urllib.parse import urlsplit
from uuid import uuid4
from ipaddress import ip_address

import httpx
from fastapi import APIRouter, HTTPException, Request
from openai import APIConnectionError, APITimeoutError, OpenAI
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError
from typing import Literal

from runtime_paths import DATA_ROOT


BASE_URLS = {
    "deepseek": "https://api.deepseek.com",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4/",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "openai": "https://api.openai.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
}
PROVIDERS = ("deepseek", "qwen", "zhipu", "openai", "gemini", "custom")
MODEL_FIELDS = tuple(f"{provider}_model" for provider in PROVIDERS)
KEY_FIELDS = tuple(f"{provider}_key" for provider in PROVIDERS) + ("search_key",)
PROVIDER_LABELS = {
    "deepseek": "DeepSeek", "qwen": "千问", "zhipu": "智谱",
    "openai": "OpenAI", "gemini": "Gemini", "custom": "自定义服务",
}
LOCK = RLock()
router = APIRouter(prefix="/chat/settings", tags=["API settings"])


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    revision: str = "initial"
    provider: Literal["deepseek", "qwen", "zhipu", "openai", "gemini", "custom"] = "deepseek"
    deepseek_model: str = Field(default="deepseek-flash", min_length=1, max_length=80)
    zhipu_model: str = Field(default="glm-4.7-flash", min_length=1, max_length=80)
    qwen_model: str = Field(default="qwen-plus", min_length=1, max_length=80)
    openai_model: str = Field(default="gpt-5-mini", min_length=1, max_length=80)
    gemini_model: str = Field(default="gemini-3.8-flash", min_length=1, max_length=80)
    custom_model: str = Field(default="custom-model", min_length=1, max_length=80)
    qwen_base_url: str = Field(default=BASE_URLS["qwen"], max_length=512)
    custom_base_url: str = Field(default="", max_length=512)
    search_enabled: bool = False
    share_chat_key: bool = False
    deepseek_key: SecretStr = SecretStr("")
    zhipu_key: SecretStr = SecretStr("")
    qwen_key: SecretStr = SecretStr("")
    openai_key: SecretStr = SecretStr("")
    gemini_key: SecretStr = SecretStr("")
    custom_key: SecretStr = SecretStr("")
    search_key: SecretStr = SecretStr("")


class Update(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str
    provider: Literal["deepseek", "qwen", "zhipu", "openai", "gemini", "custom"]
    deepseek_model: str = Field(min_length=1, max_length=80)
    zhipu_model: str = Field(min_length=1, max_length=80)
    qwen_model: str | None = Field(default=None, min_length=1, max_length=80)
    openai_model: str | None = Field(default=None, min_length=1, max_length=80)
    gemini_model: str | None = Field(default=None, min_length=1, max_length=80)
    custom_model: str | None = Field(default=None, min_length=1, max_length=80)
    qwen_base_url: str | None = Field(default=None, max_length=512)
    custom_base_url: str | None = Field(default=None, max_length=512)
    search_enabled: bool
    share_chat_key: bool
    # None keeps the old secret; an empty string explicitly deletes it.
    deepseek_key: SecretStr | None = None
    zhipu_key: SecretStr | None = None
    qwen_key: SecretStr | None = None
    openai_key: SecretStr | None = None
    gemini_key: SecretStr | None = None
    custom_key: SecretStr | None = None
    search_key: SecretStr | None = None


def _vault():
    # Pin the Windows backend: never fall back to plaintext files.
    from keyring.backends.Windows import WinVaultKeyring
    return WinVaultKeyring()


def _service():
    # Stable across installs and development directories, under the current Windows user.
    return "AgentWorkspace-api-v2"


def _legacy_service():
    # Read the previous location-derived entry once, then migrate to the stable service.
    identity = str(DATA_ROOT.resolve()).casefold().encode("utf-8")
    return "AgentWorkspace-" + hashlib.sha256(identity).hexdigest()[:16]


def _raw(config):
    data = config.model_dump(mode="json")
    for name in KEY_FIELDS:
        data[name] = getattr(config, name).get_secret_value()
    return data


def _persist(vault, config):
    # Keep each key in a separate credential: a single Windows credential has a size limit.
    metadata = json.dumps(config.model_dump(mode="json", exclude=set(KEY_FIELDS)),
                          ensure_ascii=True, separators=(",", ":"))
    if len(metadata.encode("utf-16-le")) > 2400:
        raise HTTPException(422, "设置内容过长，请缩短模型编号或接口地址。")
    for name in KEY_FIELDS:
        value = getattr(config, name).get_secret_value()
        existing = vault.get_password(_service(), name)
        if value:
            if existing != value:
                vault.set_password(_service(), name, value)
            if vault.get_password(_service(), name) != value:
                raise RuntimeError("credential verification failed")
        elif existing is not None:
            vault.delete_password(_service(), name)
            if vault.get_password(_service(), name) is not None:
                raise RuntimeError("credential deletion verification failed")
    vault.set_password(_service(), "settings", metadata)
    if vault.get_password(_service(), "settings") != metadata:
        raise RuntimeError("settings verification failed")


def load_settings():
    with LOCK:
        try:
            vault = _vault()
            stored = vault.get_password(_service(), "settings")
            if stored is not None:
                data = json.loads(stored)
                for name in KEY_FIELDS:
                    data[name] = vault.get_password(_service(), name) or ""
                return Settings.model_validate(data)
            legacy = vault.get_password(_legacy_service(), "api-settings")
            if legacy is not None:
                config = Settings.model_validate_json(legacy)
                _persist(vault, config)
                return config
            # Legacy .env is only used before the first in-app save.
            ds = os.environ.get("DEEPSEEK_API_KEY", "").strip()
            zp = os.environ.get("ZHIPU_API_KEY", "").strip()
            return Settings(
                deepseek_key=ds, zhipu_key=zp, search_key=zp,
                qwen_key=os.environ.get("DASHSCOPE_API_KEY", "").strip(),
                openai_key=os.environ.get("OPENAI_API_KEY", "").strip(),
                gemini_key=os.environ.get("GEMINI_API_KEY", "").strip(),
                search_enabled=bool(zp),
            )
        except Exception:
            raise HTTPException(503, "无法读取 Windows 凭据，请检查当前用户环境。") from None


def chat_key(config):
    return getattr(config, f"{config.provider}_key").get_secret_value()


def model_name(config):
    return getattr(config, f"{config.provider}_model")


def chat_base_url(config):
    if config.provider == "custom":
        return config.custom_base_url
    if config.provider == "qwen":
        return config.qwen_base_url
    return BASE_URLS[config.provider]


def search_key(config):
    # 搜索只属于智谱模式，始终使用当前智谱聊天密钥。
    return config.zhipu_key.get_secret_value() if config.provider == "zhipu" else ""


def require_chat(config):
    if not chat_key(config):
        raise HTTPException(422, "请先在 API 设置中填写当前聊天服务的密钥。")


def public_settings(config):
    # The GET response must never include keys, even as masked placeholders.
    result = {
        "revision": config.revision,
        "provider": config.provider,
        **{name: getattr(config, name) for name in MODEL_FIELDS},
        "qwen_base_url": config.qwen_base_url,
        "custom_base_url": config.custom_base_url,
        "search_enabled": config.provider == "zhipu" and config.search_enabled,
        "share_chat_key": config.provider == "zhipu",
        "chat_configured": bool(chat_key(config)),
        "search_configured": bool(search_key(config)),
    }
    result.update({f"has_{name}": bool(getattr(config, name).get_secret_value())
                   for name in KEY_FIELDS})
    return result


def create_chat_client(config):
    require_chat(config)
    return OpenAI(
        api_key=chat_key(config), base_url=chat_base_url(config),
        # Streaming can spend longer than a short connection test before its first token.
        http_client=httpx.Client(
            trust_env=False,
            timeout=httpx.Timeout(connect=10.0, read=90.0, write=30.0, pool=10.0),
        ),
        max_retries=0,
    )


def describe_chat_error(error, config):
    """Turn known provider failures into safe, actionable messages without echoing response bodies."""
    if isinstance(error, APITimeoutError):
        return "模型响应超时，请稍后重试；持续超时可切换聊天服务商。"
    if isinstance(error, APIConnectionError):
        return "无法连接聊天服务，请检查网络后重试。"

    status = getattr(error, "status_code", None)
    if status == 429:
        body = getattr(error, "body", None)
        issue = body.get("error", body) if isinstance(body, dict) else {}
        code = issue.get("code") if isinstance(issue, dict) else None
        safe_code = str(code) if str(code).isdigit() and len(str(code)) <= 5 else "未知"
        if config.provider == "zhipu" and safe_code == "1305":
            return "智谱模型当前繁忙（1305），请稍后重试，或切换到 DeepSeek 聊天。"
        provider = PROVIDER_LABELS[config.provider]
        return f"{provider}返回 429（错误码 {safe_code}），请检查额度、调用频率或服务状态。"
    if status in (401, 403):
        return "聊天服务鉴权失败，请检查 API 密钥与模型权限。"
    if status == 400:
        return "聊天服务拒绝了请求（HTTP 400），请检查模型编号和工具调用支持情况。"
    if isinstance(status, int) and 500 <= status <= 599:
        return f"聊天服务暂不可用（HTTP {status}），请稍后重试。"
    return None


def _valid_api_url(value, *, qwen=False):
    if not value or len(value) > 2048 or any(char.isspace() for char in value):
        return False
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        if (parsed.scheme != "https" or not host or parsed.username or parsed.password
                or parsed.query or parsed.fragment):
            return False
        if qwen:
            return host in {
                "dashscope.aliyuncs.com", "dashscope-intl.aliyuncs.com",
                "dashscope-us.aliyuncs.com",
            } or host.endswith((".dashscope.aliyuncs.com", ".maas.aliyuncs.com"))
        if host == "localhost" or host.endswith(".localhost"):
            return False
        try:
            return ip_address(host).is_global
        except ValueError:
            return True
    except ValueError:
        return False


def save_settings(update):
    with LOCK:
        current = load_settings()
        if update.revision != current.revision:
            raise HTTPException(409, "设置已被其他窗口修改，请关闭后重新打开设置。")
        data = _raw(current)
        data.update(update.model_dump(exclude=set(KEY_FIELDS), exclude_none=True))
        for name in KEY_FIELDS:
            new_key = getattr(update, name)
            if new_key is not None:
                value = new_key.get_secret_value().strip()
                if len(value) > 256 or any(ord(c) < 33 or ord(c) > 126 for c in value):
                    raise HTTPException(422, "密钥格式不正确，请检查是否包含空格或换行。")
                data[name] = value
        for name in MODEL_FIELDS:
            if not re.fullmatch(r"[A-Za-z0-9_.:-]+", data[name]):
                raise HTTPException(422, "模型编号只能包含字母、数字、点、横线、冒号和下划线。")
        if not _valid_api_url(data["qwen_base_url"], qwen=True):
            raise HTTPException(422, "千问接口地址必须使用官方 HTTPS 域名。")
        if data["provider"] == "custom" and not _valid_api_url(data["custom_base_url"]):
            raise HTTPException(422, "自定义接口需要可公开访问的 HTTPS Base URL。")
        if data["custom_base_url"] and not _valid_api_url(data["custom_base_url"]):
            raise HTTPException(422, "自定义接口地址格式不正确。")
        if data["provider"] != "zhipu" and data["search_enabled"]:
            raise HTTPException(422, "当前联网搜索仅支持智谱，请切换到智谱或关闭搜索。")
        # 兼容旧设置：独立搜索密钥留存，但不再参与请求。
        data["share_chat_key"] = data["provider"] == "zhipu"
        data["revision"] = uuid4().hex
        config = Settings.model_validate(data)
        try:
            _persist(_vault(), config)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(503, "保存 Windows 凭据失败；设置没有确认保存。") from None
        return public_settings(config)


def _check_origin(request):
    # Only the backend's own origin or the exact frontend started by dev.py may edit settings.
    # Vite forwards /chat requests without changing the browser's Origin header.
    host = request.headers.get("host", "")
    if not re.fullmatch(r"(?:127\.0\.0\.1|localhost)(?::\d+)?", host):
        raise HTTPException(403, "设置接口仅允许本机访问。")
    origin = request.headers.get("origin")
    if origin:
        try:
            parsed = urlsplit(origin)
            allowed_frontend = os.environ.get("AGENT_SETTINGS_ORIGIN", "")
            valid = (parsed.scheme == "http" and not parsed.path
                     and not parsed.query and not parsed.fragment
                     and not parsed.username and not parsed.password
                     and (parsed.netloc == host or origin == allowed_frontend))
        except ValueError:
            valid = False
        if not valid:
            raise HTTPException(403, "拒绝跨来源设置请求。")


async def _read_json(request):
    _check_origin(request)
    if request.headers.get("content-type", "").split(";")[0] != "application/json":
        raise HTTPException(415, "请使用 JSON 请求。")
    content = bytearray()
    async for part in request.stream():
        content.extend(part)
        if len(content) > 8192:
            raise HTTPException(413, "配置请求过大。")
    try:
        return json.loads(content)
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(422, "配置请求不是有效 JSON。") from None


@router.get("")
def read_settings(request: Request):
    _check_origin(request)
    return public_settings(load_settings())


@router.post("")
async def write_settings(request: Request):
    body = await _read_json(request)
    try:
        update = Update.model_validate(body)
    except ValidationError:
        # Do not echo Pydantic's raw input: it may contain a secret.
        raise HTTPException(422, "设置字段不正确，请重新打开设置后填写。") from None
    from starlette.concurrency import run_in_threadpool
    return await run_in_threadpool(save_settings, update)


@router.post("/test")
async def test_settings(request: Request):
    body = await _read_json(request)
    if not isinstance(body, dict) or set(body) != {"kind"} or body["kind"] not in ("chat", "search"):
        raise HTTPException(422, "测试类型必须为 chat 或 search。")
    from starlette.concurrency import run_in_threadpool
    return await run_in_threadpool(_test_connection, body["kind"])


def _test_connection(kind):
    config = load_settings()
    try:
        if kind == "chat":
            with create_chat_client(config) as client:
                options = {"max_completion_tokens": 64} if config.provider == "openai" else {"max_tokens": 16}
                if config.provider == "deepseek":
                    options["extra_body"] = {"thinking": {"type": "disabled"}}
                result = client.chat.completions.create(
                    model=model_name(config),
                    messages=[{"role": "user", "content": "Reply OK."}],
                    **options,
                )
                if not result.choices:
                    raise HTTPException(502, "模型接口没有返回预期结果。")
        else:
            if config.provider != "zhipu" or not config.search_enabled or not search_key(config):
                raise HTTPException(422, "请切换到智谱，开启搜索并配置智谱密钥。")
            from search_tools import search_web
            result = search_web("Vue 官方文档", api_key=search_key(config))
            if result.get("error"):
                raise HTTPException(502, result["error"])
        return {"ok": True, "message": "接口调用成功；不代表工具调用、余额或所有模型均可用。"}
    except HTTPException:
        raise
    except Exception as error:
        status = getattr(error, "status_code", None)
        body = getattr(error, "body", None)
        issue = body.get("error", body) if isinstance(body, dict) else {}
        code = issue.get("code") if isinstance(issue, dict) else None

        # 只显示数字错误码，不把响应正文或密钥显示到界面。
        safe_code = str(code) if str(code).isdigit() and len(str(code)) <= 5 else "未知"
        if status == 429:
            if config.provider == "zhipu" and safe_code == "1305":
                raise HTTPException(
                    429, "智谱模型当前繁忙（1305），请稍后重试，或切换到 DeepSeek 聊天。"
                ) from None
            provider = PROVIDER_LABELS[config.provider]
            raise HTTPException(
                429, f"{provider}返回 429；业务错误码：{safe_code}。请检查余额、限额或服务状态。"
            ) from None

        detail = (
            f"服务返回 HTTP {status}，请检查密钥、权限和模型编号。"
            if isinstance(status, int)
            else "接口连接失败，请检查网络和服务配置。"
        )
        raise HTTPException(502, detail) from None
