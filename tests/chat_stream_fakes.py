"""Fake streamed chat completions for client tests.

The client streams every completion and reassembles it with the SDK's own accumulator, so
a fake `create` hands back what a provider would: an iterable of real
`ChatCompletionChunk`s — content deltas first, then a trailing choice-less chunk carrying
`usage`, the shape OpenRouter sends under `stream_options={"include_usage": True}`. Real
SDK types rather than stand-ins, so a test exercises the same reassembly the live path
does, `cost` included (OpenRouter puts it on `usage`; the SDK keeps unknown fields).
"""

from __future__ import annotations

from openai.types.chat import ChatCompletionChunk
from openai.types.chat.chat_completion_chunk import (
    Choice,
    ChoiceDelta,
    ChoiceDeltaToolCall,
    ChoiceDeltaToolCallFunction,
)
from openai.types.completion_usage import CompletionUsage

MODEL = "x/y"


def _chunk(*, delta: ChoiceDelta, finish_reason: str | None = None) -> ChatCompletionChunk:
    return ChatCompletionChunk(
        id="chatcmpl-fake",
        object="chat.completion.chunk",
        created=0,
        model=MODEL,
        choices=[Choice(index=0, delta=delta, finish_reason=finish_reason)],
    )


def usage_chunk(
    *, prompt_tokens: int = 10, completion_tokens: int = 5, cost: float = 0.001
) -> ChatCompletionChunk:
    """The final chunk: no choices, usage only — with OpenRouter's `cost` extra."""
    return ChatCompletionChunk(
        id="chatcmpl-fake",
        object="chat.completion.chunk",
        created=0,
        model=MODEL,
        choices=[],
        usage=CompletionUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            cost=cost,
        ),
    )


def content_chunks(text: str, *, pieces: int = 2) -> list[ChatCompletionChunk]:
    """`text` split over `pieces` deltas, so reassembly (not pass-through) is exercised."""
    step = max(1, -(-len(text) // pieces))
    parts = [text[i : i + step] for i in range(0, len(text), step)] or [""]
    chunks = [_chunk(delta=ChoiceDelta(role="assistant", content=parts[0]))]
    chunks += [_chunk(delta=ChoiceDelta(content=p)) for p in parts[1:]]
    return chunks


def tool_call_chunks(
    name: str, arguments: str, *, call_id: str = "call_1"
) -> list[ChatCompletionChunk]:
    """One function tool call whose arguments arrive over two deltas, as providers send
    them; the second delta carries neither id nor name, only the index."""
    half = len(arguments) // 2
    first = ChoiceDelta(
        role="assistant",
        tool_calls=[
            ChoiceDeltaToolCall(
                index=0,
                id=call_id,
                type="function",
                function=ChoiceDeltaToolCallFunction(name=name, arguments=arguments[:half]),
            )
        ],
    )
    second = ChoiceDelta(
        tool_calls=[
            ChoiceDeltaToolCall(
                index=0, function=ChoiceDeltaToolCallFunction(arguments=arguments[half:])
            )
        ]
    )
    return [_chunk(delta=first), _chunk(delta=second)]


def fake_stream(
    text: str = "",
    *,
    finish_reason: str = "stop",
    tool_call: tuple[str, str] | None = None,
    cost: float = 0.001,
) -> list[ChatCompletionChunk]:
    """A whole streamed answer: content and/or one tool call, a finish chunk, then usage."""
    chunks: list[ChatCompletionChunk] = []
    if text:
        chunks += content_chunks(text)
    if tool_call is not None:
        chunks += tool_call_chunks(*tool_call)
        finish_reason = "tool_calls"
    chunks.append(_chunk(delta=ChoiceDelta(), finish_reason=finish_reason))
    chunks.append(usage_chunk(cost=cost))
    return chunks
