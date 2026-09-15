"""Loopback-only OTLP receiver. Raw telemetry preserved; parser gated by CLI probe."""
import gzip, json
from datetime import datetime, timezone
from pathlib import Path
from ...storage import digest

PROFILE=Path(__file__).with_name('telemetry-profile.json')

def supported(cli_version):
    try:return json.loads(PROFILE.read_text()).get('cli_version')==cli_version
    except (OSError,ValueError):return False

def value(raw):
    for k in ('stringValue','boolValue','intValue','doubleValue'):
        if k in raw:return raw[k]
    if 'arrayValue' in raw:return [value(v) for v in raw['arrayValue'].get('values',[])]
    return raw

def timestamp(ns):
    try:return datetime.fromtimestamp(int(ns)/1e9,tz=timezone.utc).isoformat()
    except (ValueError,TypeError,OverflowError):return None

def receive(trace,attempt,body,content_type,path,encoding=''):
    if encoding=='gzip':body=gzip.decompress(body)
    if len(body)>8_000_000:raise ValueError('遥测请求过大')
    if 'json' in content_type:payload=json.loads(body)
    else:
        from google.protobuf.json_format import MessageToDict
        if path.endswith('/logs'):
            from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import ExportLogsServiceRequest
            message=ExportLogsServiceRequest()
        else:
            from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
            message=ExportTraceServiceRequest()
        message.ParseFromString(body);payload=MessageToDict(message)
    for resource in payload.get('resourceLogs',[]):
        for scope in resource.get('scopeLogs',[]):
            for record in scope.get('logRecords',[]):
                attrs={a['key']:value(a.get('value',{})) for a in record.get('attributes',[])}
                name=attrs.get('event.name') or attrs.get('event_name') or record.get('eventName') or value(record.get('body',{}))
                name=str(name);eid='otel:log:'+digest(record)
                trace.emit('otel.log',event_id=eid,source='otel',span_id=f'attempt:{attempt}',occurred_at=timestamp(record.get('timeUnixNano')),content=record,data={'event_name':name,'attempt':attempt})
                # Never add token values to CLI turn totals: the same usage can appear in both channels.
                if name not in ('codex.conversation_starts','codex.api_request','codex.sse_event','codex.websocket_request','codex.websocket_event','codex.tool_decision','codex.tool_result','codex.user_prompt','codex.startup_phase','codex.turn_ttft','codex.websocket_connect'):
                    trace.gap('otel-name:'+name[:120],'有未识别的遥测事件，原始事件已保留')
    for resource in payload.get('resourceSpans',[]):
        for scope in resource.get('scopeSpans',[]):
            for record in scope.get('spans',[]):
                trace.emit('otel.span',event_id='otel:span:'+digest(record),source='otel',span_id=f'attempt:{attempt}',occurred_at=timestamp(record.get('startTimeUnixNano')),content=record,data={'attempt':attempt})
    return {}
