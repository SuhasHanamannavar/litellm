from collections.abc import Awaitable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal, Protocol, TypedDict, cast

from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter
from typing_extensions import ReadOnly

from litellm.rust_bridge.loader import get_native_bridge


class DecodedEvent(TypedDict):
    name: ReadOnly[str]
    attributes: ReadOnly[dict[str, str]]


class DecodedSpan(TypedDict):
    trace_id: ReadOnly[str]
    span_id: ReadOnly[str]
    parent_span_id: ReadOnly[str]
    trace_state: ReadOnly[str]
    name: ReadOnly[str]
    kind: ReadOnly[str]
    resource_attributes: ReadOnly[dict[str, str]]
    scope_name: ReadOnly[str]
    scope_version: ReadOnly[str]
    attributes: ReadOnly[dict[str, str]]
    start_ns: ReadOnly[int]
    end_ns: ReadOnly[int]
    status_code: ReadOnly[str]
    status_message: ReadOnly[str]
    events: ReadOnly[list[DecodedEvent]]


ReadQueryName = Literal["list_traces", "trace_spans", "span_detail", "span_error", "spend_by_response_ids"]


class NativeStore(Protocol):
    def __init__(self, config: "NativeConfig") -> None: ...

    def ensure_schema(self) -> Awaitable[None]: ...

    def insert_rows(self, table: str, rows: Sequence[Mapping[str, object]]) -> Awaitable[None]: ...

    def lens_query(self, name: str, parameters: Mapping[str, str | int | Sequence[str]]) -> Awaitable[str]: ...

    def query(self, name: ReadQueryName, parameters: Mapping[str, str | int | Sequence[str]]) -> Awaitable[str]: ...


class NativeTraces(Protocol):
    NativeTraceConfig: type["NativeConfig"]
    NativeTraceStorage: type[NativeStore]

    def trace_decode_otlp(
        self,
        body: bytes,
        content_type: str | None,
    ) -> list[DecodedSpan]: ...

    def trace_encode_error(self, message: str) -> bytes: ...


class QueryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    data: list[dict[str, JsonValue]]


QUERY_PARAMETERS: Final = TypeAdapter(dict[str, str | int | list[str]])


class NativeConfig(Protocol):
    def __init__(self, database: str, url: str, retention_days: int) -> None: ...


@dataclass(frozen=True, slots=True, repr=False)
class TraceStorageConfig:
    url: str
    database: str = "litellm"
    retention_days: int = 14


def _native() -> NativeTraces:
    native: Final = get_native_bridge()
    if native is None:
        raise RuntimeError("Agent tracing requires the Rust extension")
    return cast(NativeTraces, native)  # cast-ok: the native extension is validated against this protocol at call sites


def decode_otlp(body: bytes, content_type: str | None) -> list[DecodedSpan]:
    return _native().trace_decode_otlp(body, content_type)


def encode_error(message: str) -> bytes:
    if get_native_bridge() is None:
        return b""
    return _native().trace_encode_error(message)


class ClickHouseStorage:
    def __init__(self, config: TraceStorageConfig) -> None:
        native: Final = _native()
        validated: Final = native.NativeTraceConfig(
            config.database,
            config.url,
            config.retention_days,
        )
        self._native: Final = native.NativeTraceStorage(validated)

    async def ensure_schema(self) -> None:
        await self._native.ensure_schema()

    async def insert_rows(self, table: str, rows: Sequence[Mapping[str, object]]) -> None:
        await self._native.insert_rows(table, rows)

    async def query(
        self, name: ReadQueryName, parameters: Mapping[str, object] | None = None
    ) -> list[dict[str, JsonValue]]:
        result: Final = await self._native.query(
            name, QUERY_PARAMETERS.validate_python(parameters or MappingProxyType({}))
        )
        return QueryResponse.model_validate_json(result).data

    async def _lens_query(self, name: str, parameters: Mapping[str, object]) -> list[dict[str, JsonValue]]:
        result: Final = await self._native.lens_query(name, QUERY_PARAMETERS.validate_python(parameters))
        return QueryResponse.model_validate_json(result).data

    async def lens_sample(self, parameters: Mapping[str, object]) -> list[dict[str, JsonValue]]:
        return await self._lens_query("sample", parameters)

    async def lens_content(self, parameters: Mapping[str, object]) -> list[dict[str, JsonValue]]:
        return await self._lens_query("content", parameters)

    async def lens_evidence(self, parameters: Mapping[str, object]) -> list[dict[str, JsonValue]]:
        return await self._lens_query("evidence", parameters)
