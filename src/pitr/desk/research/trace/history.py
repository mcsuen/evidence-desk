"""Read the current request trace without reconstructing a different execution format."""
from .store import Trace

def ensure_history(desk,request):
    trace=Trace(desk,request['task_id'])
    trace.observe_task(request['task'])
    if (desk.root/'trace-capture-failures'/request['task_id']).exists():
        trace.gap('capture-failure','部分采集失败；请检查本机诊断包')
    return trace
