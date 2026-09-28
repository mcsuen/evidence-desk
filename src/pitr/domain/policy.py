"""The same source qualification is used by tools, search, views and reports."""
from .common import Forbidden, instant
from .contracts import Scope, SourceVersion


def source_allowed(source: SourceVersion, scope: Scope):
    if scope.subjects and source.subjects and not set(scope.subjects).intersection(source.subjects):
        raise Forbidden('原件主体不在研究范围内')
    if scope.mode == 'historical':
        if instant(source.available_at) > instant(scope.as_of):
            raise Forbidden('原件版本晚于研究截止时间')
        proven = source.availability_basis in ('authoritative', 'archive')
        acquired_before = instant(source.observed_at) <= instant(scope.as_of)
        declared = scope.proof_level == 'declared' and source.availability_basis == 'declared'
        if not proven and not acquired_before and not declared:
            raise Forbidden('历史可得时间缺少足够依据')
    return True
