import importlib.util
from pathlib import Path
import pytest


def runner():
    spec=importlib.util.spec_from_file_location('verify_m6',Path(__file__).parents[1]/'scripts/verify_m6.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_acceptance_output_is_new(tmp_path):
    with pytest.raises(FileExistsError): runner().verify(tmp_path)


@pytest.mark.integration
def test_acceptance_scenarios_and_integrity(tmp_path):
    result=runner().verify(tmp_path/'acceptance')
    assert result['source_integrity']
    assert set(result['scenarios'])=={'A','B','C','D','E','F'}
    assert result['scenarios']['A']['audio_compliance']=='PASS'
    assert result['scenarios']['B']['audio_compliance']=='FAIL'
    assert result['scenarios']['C']['audio_compliance']=='INCOMPLETE'
    assert result['scenarios']['D']['execution_status']=='PARTIAL'
    assert result['scenarios']['E']['programme_state']=='SUCCESS'
    assert result['scenarios']['E']['integrated_lufs'] is None
    assert not result['scenarios']['F']['complete_marker']
    assert len(result['equivalence'])==2
