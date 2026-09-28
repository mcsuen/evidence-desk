"""Shared pytest configuration. Tests use private temporary control stores."""
import os
# Detect callers that mutate cached immutable objects in place (see Workspace.check_cache).
os.environ.setdefault('PITR_CACHE_GUARD', '1')
