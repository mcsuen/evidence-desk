from __future__ import annotations

from typing import Any, Literal, Protocol, TYPE_CHECKING
from pydantic import BaseModel, ConfigDict, Field, model_validator
import base64

if TYPE_CHECKING:
    from .runtime import WorkflowContext


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid')


class ReplyTarget(Contract):
    team_id: str
    user_id: str
    channel_id: str
    thread_ts: str | None = None
    # Slash commands have no message timestamp. Subsequent deliveries wait for
    # this durable receipt's Slack timestamp instead of posting at channel root.
    root_delivery_id: str | None = None


class AttachmentRef(Contract):
    id: str = Field(pattern=r'^attachment_[A-Za-z0-9_-]{1,80}$')
    file_id: str
    name: str = ''
    media_type: str = ''
    size: int = 0
    sha256: str = ''
    status: Literal['pending', 'ready', 'failed'] = 'pending'
    error: str | None = None


class InboundEvent(Contract):
    id: str
    kind: Literal['message', 'mention', 'command', 'action', 'submission', 'changed', 'deleted']
    target: ReplyTarget
    text: str = ''
    attachments: list[AttachmentRef] = Field(default_factory=list)
    action_id: str = ''
    metadata: dict[str, Any] = Field(default_factory=dict)
    values: dict[str, Any] = Field(default_factory=dict)


class OutputFile(Contract):
    filename: str = 'report.txt'
    title: str = '结果文件'
    content: str | None = None
    data_base64: str | None = None

    @classmethod
    def from_bytes(cls, data: bytes, *, filename: str, title='结果文件'):
        return cls(filename=filename, title=title, data_base64=base64.b64encode(data).decode('ascii'))

    @model_validator(mode='after')
    def valid_content(self):
        if (self.content is None) == (self.data_base64 is None):
            raise ValueError('结果文件须提供文本或二进制内容之一')
        raw = self.content.encode() if self.content is not None else base64.b64decode(self.data_base64, validate=True)
        if len(raw) > 40_000_000:
            raise ValueError('结果文件超过 40 MB 上限')
        self.filename = self.filename.replace('\\', '/').split('/')[-1][:200] or 'report.bin'
        return self


class WorkflowUpdate(Contract):
    text: str
    status: Literal['message', 'queued', 'running', 'waiting_action', 'completed', 'failed', 'cancelled'] = 'message'
    blocks: list[dict[str, Any]] | None = None
    files: list[OutputFile] = Field(default_factory=list)


class WorkflowModal(Contract):
    title: str
    action_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    blocks: list[dict[str, Any]]
    submit: str = '提交'


class WorkflowAdapter(Protocol):
    """Handlers must use event.id for idempotent business mutations.

    No SDK client, token, response URL or arbitrary filesystem path is exposed.
    handle() runs in the durable worker. open_modal() is a fast, read-only
    operation; it must not start a workflow or mutate business state.
    """
    name: str
    commands: tuple[str, ...]

    def handle(self, event: InboundEvent, context: WorkflowContext) -> None: ...
    def open_modal(self, event: InboundEvent, context: WorkflowContext) -> WorkflowModal: ...
    def validate_submission(self, event: InboundEvent) -> dict[str, str]: ...
    def poll(self, context: WorkflowContext) -> None: ...


class WorkflowRejected(ValueError):
    """A deliberately user-facing rejection from a business adapter."""
