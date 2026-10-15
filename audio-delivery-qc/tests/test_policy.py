from copy import deepcopy
from dataclasses import asdict

import pytest

from audio_qc.measurement import MeasurementContext, ZeroRun
from audio_qc.models import AudioFile, Defect, Status
from audio_qc.rules import assess_file, evaluate_file_policy, evaluate_level_policy, apply_rules


@pytest.fixture
def facts():
    return AudioFile('/not/accessed.wav', 'not/accessed.wav', sample_rate=48000, bit_depth=24,
                     channels=6, channel_layout='5.1', codec='pcm_s24le',
                     bwf={'present': True},
                     measurements={'integrated_lufs': -23.0, 'true_peak_dbtp': -1.5,
                                   'decoded_sample_frames': 48000, 'overload_samples': 0,
                                   'longest_rail_run_per_channel': [0]*6,
                                   'rail_samples_per_channel': [0]*6,
                                   'nonfinite_samples': 0, 'digital_silence': False})


def check(facts, policy, code, context=None):
    return next(c for c in evaluate_file_policy(facts, policy, context) if c.code == code)


def test_same_measurement_object_two_policies(facts, config):
    before = deepcopy(asdict(facts))
    ebu = deepcopy(config)
    ebu['loudness'].update(target_lufs=-23, tolerance=.5)
    ebu['true_peak']['maximum'] = -1
    other = deepcopy(ebu)
    other['loudness'].update(target_lufs=-14, tolerance=1)
    other['true_peak']['maximum'] = -6
    assert check(facts, ebu, 'integrated_loudness').status == Status.PASS
    assert check(facts, ebu, 'true_peak').status == Status.PASS
    assert check(facts, other, 'integrated_loudness').status == Status.FAIL
    assert check(facts, other, 'true_peak').status == Status.FAIL
    assert asdict(facts) == before


@pytest.mark.parametrize('rate,required,status', [(48000,48000,'PASS'), (44100,48000,'FAIL'), (44100,None,'PASS')])
def test_sample_rate(facts, config, rate, required, status):
    facts.sample_rate = rate
    config['sample_rate']['required'] = required
    assert check(facts, config, 'sample_rate').status == status


@pytest.mark.parametrize('field,measured,status', [('required',16,'FAIL'), ('preferred',16,'WARNING'),
                                                 ('required',24,'PASS'), ('preferred',24,'PASS'),
                                                 ('required',None,'INFO'), ('preferred',None,'INFO')])
def test_bit_depth(facts, config, field, measured, status):
    facts.bit_depth = measured
    config['bit_depth'][field] = 24
    assert check(facts, config, 'bit_depth_'+field).status == status


@pytest.mark.parametrize('value,status', [(-23,'PASS'),(-23.5,'PASS'),(-22.5,'PASS'),
                                        (-23.5000000005,'PASS'),(-22.4999999995,'PASS'),
                                        (-23.50001,'FAIL'),(-22.49999,'FAIL'),(None,'WARNING')])
def test_integrated_loudness_inclusive_tolerance(facts, config, value, status):
    facts.measurements['integrated_lufs'] = value
    config['loudness'].update(target_lufs=-23,tolerance=.5)
    assert check(facts, config, 'integrated_loudness').status == status


def test_loudness_without_target_and_unavailable_reason(facts, config):
    assert check(facts, config, 'integrated_loudness').status == Status.INFO
    facts.measurements['integrated_lufs'] = None
    facts.measurements['loudness_unavailable'] = 'No supported explicit channel layout'
    result = check(facts, config, 'integrated_loudness')
    assert result.status == Status.WARNING and result.message == facts.measurements['loudness_unavailable']
    config['loudness']['enabled'] = False
    assert check(facts, config, 'integrated_loudness').status == Status.INFO


@pytest.mark.parametrize('value,status', [(-8,'PASS'),(-6,'PASS'),(-5,'FAIL'),
                                        (-5.9999999995,'PASS'),(None,'WARNING')])
def test_true_peak_is_upper_limit(facts, config, value, status):
    config['true_peak']['maximum'] = -6
    facts.measurements['true_peak_dbtp'] = value
    assert check(facts, config, 'true_peak').status == status


def test_true_peak_without_maximum_and_disabled_levels(facts, config):
    assert check(facts, config, 'true_peak').status == Status.INFO
    config['loudness']['enabled'] = False
    assert not any(c.code == 'true_peak' for c in evaluate_file_policy(facts, config))


@pytest.mark.parametrize('present,required,warn,status', [(True,True,True,'PASS'), (False,True,False,'FAIL'),
                                                        (False,False,True,'WARNING'), (False,False,False,'INFO'),
                                                        (None,True,False,'WARNING'), (None,False,True,'INFO')])
def test_bwf_policy(facts, config, present, required, warn, status):
    facts.bwf['present'] = present
    config['bwf'].update(required=required, warn_if_missing=warn)
    assert check(facts, config, 'bwf').status == status


@pytest.mark.parametrize('fail,run,rails,status', [(True,3,3,'FAIL'),(False,3,3,'WARNING'),
                                               (True,2,2,'WARNING'),(True,0,0,'PASS')])
def test_clipping_policy(facts, config, fail, run, rails, status):
    config['clipping']['fail'] = fail
    facts.measurements['longest_rail_run_per_channel'][0] = run
    facts.measurements['rail_samples_per_channel'][0] = rails
    assert check(facts, config, 'clipping').status == status


def test_overload_nonfinite_silence_remain_explicit(facts, config):
    facts.measurements.update(overload_samples=1, nonfinite_samples=2, digital_silence=True)
    assert check(facts, config, 'clipping').status == Status.FAIL
    assert check(facts, config, 'nonfinite_samples').status == Status.FAIL
    assert check(facts, config, 'silence').status == Status.INFO


@pytest.mark.parametrize('allowed,status', [([6],'PASS'),([1,2],'WARNING')])
def test_channel_policy(facts, config, allowed, status):
    config['channels']['allowed'] = allowed
    assert check(facts, config, 'channel_count').status == status


def test_candidates_are_classified_only_on_report_copy(facts, config):
    config['defects']['enabled'] = True
    assert check(facts, config, 'defect_candidates').status == Status.INFO
    facts.defects = [Defect(1,48000,1,'POSSIBLE CLICK / TICK',3/48000,None,{'duration_samples':3},'test')]
    before = deepcopy(asdict(facts))
    assert check(facts, config, 'defect_candidates').status == Status.WARNING
    report_audio = assess_file(facts, config)
    assert report_audio.defects[0].severity == Status.WARNING
    assert asdict(facts) == before
    report_audio.defects[0].measurements['duration_samples'] = 999
    assert facts.defects[0].measurements['duration_samples'] == 3


def test_explicit_zero_run_uses_context_without_mutation(facts, config):
    config['defects']['enabled'] = True
    config['defects']['dropouts']['fail_zero_run_ms'] = 800
    context = MeasurementContext(zero_runs=(ZeroRun(48000,12000),))
    before = deepcopy((asdict(facts),asdict(context),config))
    assert check(facts, config, 'explicit_zero_run_rule', context).status == Status.FAIL
    assessed = assess_file(facts, config, context)
    assert assessed.defects[0].severity == Status.FAIL
    assert assessed.defects[0].sample_index == 12000
    assert assessed.defects[0].measurements['zero_samples'] == 48000
    assert (asdict(facts),asdict(context),config) == before


def test_level_rules_are_reusable_without_a_file(facts, config):
    levels = evaluate_level_policy(facts.measurements, config)
    assert levels == [c for c in evaluate_file_policy(facts, config) if c.code in {'integrated_loudness','lra','true_peak'}]


def test_legacy_adapter_retains_check_contract(facts, config):
    expected = assess_file(facts, config)
    apply_rules(facts, config)
    assert asdict(facts) == asdict(expected)
