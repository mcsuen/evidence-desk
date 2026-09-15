"""Schema export consistency and drift detection."""
import pytest


def test_schema_generation_detects_duplicates_and_drift(tmp_path):
    from pitr.schemas import export_schemas
    export_schemas(tmp_path)
    export_schemas(tmp_path, check=True)
    (tmp_path / 'research_request.v999.json').write_text('{}')
    with pytest.raises(ValueError, match='契约不一致'):
        export_schemas(tmp_path, check=True)
    export_schemas(tmp_path)
    assert not (tmp_path / 'research_request.v999.json').exists()
