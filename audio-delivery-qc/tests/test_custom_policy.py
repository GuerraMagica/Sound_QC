from copy import deepcopy

import pytest

from audio_qc.config import resolve_config
from audio_qc.models import AudioFile
from audio_qc.rules import assess_file, evaluate_file_policy, measurement_requirements


def custom():
    return resolve_config({'preset':'CUSTOM','loudness':{'target_lufs':-14,'tolerance':1},
                           'true_peak':{'maximum':-6}})


@pytest.mark.parametrize('lufs,expected',[(-15,'PASS'),(-13,'PASS'),(-15.0000000005,'PASS'),
                                         (-12.9999999995,'PASS'),(-15.001,'FAIL'),(-12.999,'FAIL'),(None,'WARNING')])
def test_custom_loudness_inclusive_boundaries_and_unavailable(lufs,expected):
    audio=AudioFile('/not/read','fixture',measurements={'integrated_lufs':lufs,'true_peak_dbtp':-8})
    check=next(c for c in evaluate_file_policy(audio,custom()) if c.code=='integrated_loudness')
    assert check.status==expected


@pytest.mark.parametrize('peak,expected',[(-8,'PASS'),(-6,'PASS'),(-5,'FAIL'),(None,'WARNING')])
def test_custom_peak_is_upper_limit(peak,expected):
    audio=AudioFile('/not/read','fixture',measurements={'integrated_lufs':-14,'true_peak_dbtp':peak})
    check=next(c for c in evaluate_file_policy(audio,custom()) if c.code=='true_peak')
    assert check.status==expected


def test_canonical_policies_reuse_same_facts_without_io_or_clustering(monkeypatch):
    audio=AudioFile('/not/read.wav','fixture',measurements={'integrated_lufs':-23,'true_peak_dbtp':-1.5})
    before=deepcopy(audio)
    policies=[resolve_config({'preset':'BROADCAST_EBU_R128'}),custom()]
    assert measurement_requirements(policies[0])==measurement_requirements(policies[1])
    def forbidden(*a,**k):
        pytest.fail('Policy performed I/O, measurement or grouping')
    for name in ('audio_qc.process.stream_process','audio_qc.issues.consolidate_issues',
                 'audio_qc.issues.IssueConsolidator.extend','audio_qc.scanner.measure_file',
                 'pathlib.Path.read_bytes','builtins.open'):
        monkeypatch.setattr(name,forbidden)
    for policy,expected in zip(policies,['PASS','FAIL']):
        result=assess_file(audio,policy)
        assert [c.status for c in result.checks if c.code in ('integrated_loudness','true_peak')]==[expected]*2
        assert result.measurements==audio.measurements
        assert audio==before
