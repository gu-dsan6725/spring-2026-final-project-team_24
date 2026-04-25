# Adapted from: vendor/yubo/app/services/providers/__init__.py
"""Pluggable AI provider dispatch.

- Embeddings: ``embed_texts`` (currently OpenAI).
- Chat / JSON completion: ``chat_json_completion`` dispatches to OpenAI, Anthropic,
  or Groq based on ``LLM_PROVIDER`` setting.
- Tool-calling completion: ``chat_tool_completion`` dispatches to OpenAI, Anthropic,
  or Groq for multi-turn tool-calling conversations (used by item generation pipeline).
"""

from __future__ import annotations

from app.config import settings


def embeddings_available() -> bool:
    return bool(settings.OPENAI_API_KEY)


def chat_available(provider: str | None = None) -> bool:
    name = (provider or "openai").lower().strip()
    if name == "openai":
        return bool(settings.OPENAI_API_KEY)
    if name == "anthropic":
        return bool(settings.ANTHROPIC_API_KEY)
    if name == "groq":
        return bool(settings.GROQ_API_KEY)
    return False


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed via the configured provider (currently only OpenAI)."""
    from app.ai.providers.openai_embeddings import embed_texts as _embed

    return await _embed(texts)


async def chat_json_completion(
    *,
    system: str,
    user: str | list,
    provider: str | None = None,
) -> str:
    """Return assistant text expected to be a single JSON object.

    ``user`` may be a plain string OR an OpenAI-style multipart list
    (``[{"type": "text", …}, {"type": "image_url", …}]``) for
    multimodal prompts. OpenAI handles the list natively; Anthropic
    translates via ``_convert_user_content_to_anthropic``. Groq does
    not support multimodal JSON mode — images are stripped with a
    warning and only the text parts are sent.

    ``provider`` overrides the default; accepted values:
    ``"openai"``, ``"anthropic"``, ``"groq"``.
    """
    name = (provider or "openai").lower().strip()

    if name == "openai":
        from app.ai.providers.openai_chat import complete_json_openai

        return await complete_json_openai(system=system, user=user)
    if name == "anthropic":
        from app.ai.providers.anthropic_chat import complete_json_anthropic

        return await complete_json_anthropic(system=system, user=user)
    if name == "groq":
        from app.ai.providers.local_llm import get_groq_client

        # Groq's chat completions endpoint (and its JSON mode) does not
        # accept image parts. If the caller passed multipart content,
        # flatten to the concatenated text so we still get a grading
        # response — an empty result would be worse.
        if isinstance(user, list):
            import logging as _logging

            text_parts = [p.get("text", "") for p in user if isinstance(p, dict) and p.get("type") == "text"]
            image_count = sum(1 for p in user if isinstance(p, dict) and p.get("type") == "image_url")
            if image_count:
                _logging.getLogger(__name__).warning(
                    "chat_json_completion: groq does not support multimodal input; "
                    "dropping %d image part(s).",
                    image_count,
                )
            user_text: str | list = "\n\n".join(t for t in text_parts if t)
        else:
            user_text = user

        client = get_groq_client()
        resp = await client.chat.completions.create(
            model=settings.GROQ_MODEL,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_text},
            ],
            temperature=0.2,
        )
        return resp.choices[0].message.content or "{}"

    raise ValueError(
        f"Unknown provider={name!r}. Supported: openai, anthropic, groq.",
    )


async def chat_tool_completion(
    *,
    messages: list[dict],
    tools: list[dict],
    provider: str | None = None,
    temperature: float = 0.4,
) -> dict:
    """Call an LLM with tool-calling support and return the first tool call.

    Returns ``{"name": "<tool>", "arguments": {…}}`` from the assistant's
    first ``tool_calls`` entry.  Falls back to JSON extraction from plain
    text if the model doesn't produce a tool call.

    Supported providers: ``"anthropic"``, ``"openai"``, ``"groq"``.
    """
    import json as _json

    from app.ai.jsonutil import load_llm_json

    name = (provider or settings.ITEM_GENERATION_PROVIDER).lower().strip()

    if name == "anthropic":
        return await _anthropic_tool_completion(messages, tools, temperature)

    if name == "openai":
        from app.ai.providers.openai_chat import _client

        client = _client()
        model = "gpt-4o-mini"
    elif name == "groq":
        from app.ai.providers.local_llm import get_groq_client

        client = get_groq_client()
        model = settings.GROQ_MODEL
    else:
        raise ValueError(
            f"Tool-calling not supported for provider={name!r}. "
            "Supported: anthropic, openai, groq.",
        )

    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            temperature=temperature,
        )
    except Exception as exc:
        parsed = _parse_failed_generation(exc, load_llm_json)
        if parsed is not None:
            return parsed
        raise

    choice = resp.choices[0]
    msg = choice.message

    if msg.tool_calls:
        tc = msg.tool_calls[0]
        try:
            args = _json.loads(tc.function.arguments)
        except _json.JSONDecodeError:
            args = load_llm_json(tc.function.arguments) or {}
        return {"name": tc.function.name, "arguments": args}

    content = msg.content or ""
    parsed = load_llm_json(content)
    if parsed:
        return {"name": "generate_item", "arguments": parsed}

    raise RuntimeError(
        f"LLM did not produce a tool call or parseable JSON. "
        f"Raw content: {content[:500]}"
    )


# ---------------------------------------------------------------------------
# Anthropic tool-calling — native API (not OpenAI-compatible)
# ---------------------------------------------------------------------------

def _openai_tools_to_anthropic(tools: list[dict]) -> list[dict]:
    """Convert OpenAI tool schemas to Anthropic format."""
    result = []
    for tool in tools:
        fn = tool.get("function", {})
        result.append({
            "name": fn.get("name", ""),
            "description": fn.get("description", ""),
            "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
        })
    return result


def _openai_messages_to_anthropic(
    messages: list[dict],
) -> tuple[str, list[dict]]:
    """Convert OpenAI-format messages (with synthetic tool calls) to Anthropic.

    Returns ``(system_prompt, anthropic_messages)``.

    Anthropic rules:
    - ``system`` is a top-level parameter, not a message
    - Messages must alternate user / assistant
    - Tool use: assistant message has ``tool_use`` content blocks
    - Tool results: user message has ``tool_result`` content blocks
    """
    import json as _json

    system = ""
    anthropic_msgs: list[dict] = []

    for msg in messages:
        role = msg.get("role", "")

        if role == "system":
            system = msg.get("content", "")
            continue

        if role == "assistant":
            tool_calls = msg.get("tool_calls", [])
            if tool_calls:
                content_blocks = []
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    try:
                        inp = _json.loads(fn.get("arguments", "{}"))
                    except _json.JSONDecodeError:
                        inp = {}
                    content_blocks.append({
                        "type": "tool_use",
                        "id": tc.get("id", ""),
                        "name": fn.get("name", ""),
                        "input": inp,
                    })
                anthropic_msgs.append({"role": "assistant", "content": content_blocks})
            else:
                text = msg.get("content") or ""
                if text:
                    anthropic_msgs.append({"role": "assistant", "content": text})
            continue

        if role == "tool":
            tool_result = {
                "type": "tool_result",
                "tool_use_id": msg.get("tool_call_id", ""),
                "content": msg.get("content", ""),
            }
            if anthropic_msgs and anthropic_msgs[-1]["role"] == "user":
                prev = anthropic_msgs[-1]["content"]
                if isinstance(prev, list):
                    prev.append(tool_result)
                else:
                    anthropic_msgs[-1]["content"] = [
                        {"type": "text", "text": prev},
                        tool_result,
                    ]
            else:
                anthropic_msgs.append({"role": "user", "content": [tool_result]})
            continue

        if role == "user":
            raw_content = msg.get("content", "")
            new_blocks = _convert_user_content_to_anthropic(raw_content)

            if anthropic_msgs and anthropic_msgs[-1]["role"] == "user":
                prev = anthropic_msgs[-1]["content"]
                if isinstance(prev, list):
                    prev.extend(new_blocks)
                else:
                    anthropic_msgs[-1]["content"] = [
                        {"type": "text", "text": prev},
                        *new_blocks,
                    ]
            else:
                if len(new_blocks) == 1 and new_blocks[0]["type"] == "text":
                    anthropic_msgs.append({"role": "user", "content": new_blocks[0]["text"]})
                else:
                    anthropic_msgs.append({"role": "user", "content": new_blocks})
            continue

    return system, anthropic_msgs


def _convert_user_content_to_anthropic(content: str | list) -> list[dict]:
    """Turn OpenAI user content (string or multipart array) into Anthropic blocks.

    Handles ``image_url`` parts with ``data:`` URIs by converting them to
    Anthropic ``image`` blocks with ``base64`` source.
    """
    import re as _re

    if isinstance(content, str):
        return [{"type": "text", "text": content}]

    blocks: list[dict] = []
    for part in content:
        ptype = part.get("type", "")
        if ptype == "text":
            blocks.append({"type": "text", "text": part.get("text", "")})
        elif ptype == "image_url":
            url = (part.get("image_url") or {}).get("url", "")
            m = _re.match(r"data:(image/[^;]+);base64,(.+)", url, _re.DOTALL)
            if m:
                blocks.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": m.group(1),
                        "data": m.group(2),
                    },
                })
            else:
                blocks.append({
                    "type": "image",
                    "source": {"type": "url", "url": url},
                })
        else:
            blocks.append({"type": "text", "text": str(part)})
    return blocks


async def _anthropic_tool_completion(
    messages: list[dict],
    tools: list[dict],
    temperature: float,
) -> dict:
    """Call Anthropic Claude with native tool use."""
    import anthropic

    if not settings.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not configured")

    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    anthropic_tools = _openai_tools_to_anthropic(tools)
    system_prompt, anthropic_msgs = _openai_messages_to_anthropic(messages)

    resp = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=4096,
        temperature=temperature,
        system=system_prompt,
        messages=anthropic_msgs,
        tools=anthropic_tools,
    )

    for block in resp.content:
        if block.type == "tool_use":
            return {"name": block.name, "arguments": block.input}

    # Fallback: parse text content
    from app.ai.jsonutil import load_llm_json

    for block in resp.content:
        if block.type == "text" and block.text:
            parsed = load_llm_json(block.text)
            if parsed:
                return {"name": "generate_item", "arguments": parsed}

    text_content = " ".join(b.text for b in resp.content if b.type == "text")
    raise RuntimeError(
        f"Anthropic did not produce a tool call or parseable JSON. "
        f"Raw: {text_content[:500]}"
    )


# ---------------------------------------------------------------------------
# Groq failed_generation fallback
# ---------------------------------------------------------------------------

def _parse_failed_generation(exc: Exception, load_llm_json) -> dict | None:  # type: ignore[type-arg]
    """Extract a valid tool call from Groq's ``failed_generation`` error body."""
    import re

    body = getattr(exc, "body", None) or {}
    if not isinstance(body, dict):
        return None
    failed = body.get("error", {}).get("failed_generation", "") if isinstance(body.get("error"), dict) else ""
    if not failed:
        return None

    m = re.search(r"<function=(\w+)>(.*?)</function>", failed, re.DOTALL)
    if m:
        fn_name = m.group(1)
        parsed = load_llm_json(m.group(2))
        if parsed:
            return {"name": fn_name, "arguments": parsed}

    parsed = load_llm_json(failed)
    if parsed:
        return {"name": "generate_item", "arguments": parsed}

    return None
