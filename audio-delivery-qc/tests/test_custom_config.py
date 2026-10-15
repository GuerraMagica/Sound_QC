from copy import deepcopy
from pathlib import Path

import pytest

from audio_qc.config import ConfigError, load_config, resolve_config, save_config


def custom():
    return resolve_config({'preset':'CUSTOM', 'sample_rate':{'required':48000},
                           'bit_depth':{'required':24}, 'loudness':{'target_lufs':-14,'tolerance':1},
                           'true_peak':{'maximum':-6}, 'bwf':{'required':True},
                           'channels':{'allowed':[1,2,6]}, 'clipping':{'fail':False}})


def test_custom_canonical_defaults_and_no_input_mutation():
    supplied = custom()
    before = deepcopy(supplied)
    assert resolve_config(supplied) == supplied
    assert supplied == before
    defaults = load_config(preset='CUSTOM')
    assert defaults['sample_rate']['required'] is None
    assert defaults['bit_depth'] == {'required':None,'preferred':None}
    assert defaults['loudness'] == {'enabled':True,'target_lufs':None,'tolerance':None}
    assert defaults['true_peak']['maximum'] is None
    assert defaults['bwf'] == {'required':False,'warn_if_missing':False}


def test_explicit_null_removes_inherited_requirements():
    result = resolve_config({'preset':'BROADCAST_EBU_R128','sample_rate':{'required':None},
                             'bit_depth':{'preferred':None}, 'loudness':{'target_lufs':None},
                             'true_peak':{'maximum':None}})
    assert result['sample_rate']['required'] is None
    assert result['bit_depth']['preferred'] is None
    assert result['loudness'] == {'enabled':True,'target_lufs':None,'tolerance':None}
    assert result['true_peak']['maximum'] is None


@pytest.mark.parametrize('patch', [
    {'sample_rate':{'required':999}}, {'sample_rate':{'required':768001}},
    {'sample_rate':{'required':48000.0}}, {'sample_rate':{'required':True}},
    {'sample_rate':{'required':10**1000}}, {'sample_rate':{'required':'48000'}},
    {'bit_depth':{'required':7}}, {'bit_depth':{'preferred':48}},
    {'bit_depth':{'required':24,'preferred':16}},
    {'loudness':{'target_lufs':-14}}, {'loudness':{'tolerance':1}},
    {'loudness':{'target_lufs':None,'tolerance':1}},
    {'loudness':{'target_lufs':-14,'tolerance':-1}},
    {'loudness':{'enabled':False,'target_lufs':-14,'tolerance':1}},
    {'loudness':{'target_lufs':float('nan'),'tolerance':1}},
    {'loudness':{'target_lufs':-14,'tolerance':float('inf')}},
    {'true_peak':{'maximum':float('-inf')}}, {'true_peak':{'maximum':'-6'}},
    {'true_peak':{'maximum':True}}, {'channels':{'allowed':[]}},
    {'channels':{'allowed':[0]}}, {'channels':{'allowed':[257]}},
    {'channels':{'allowed':[1.5]}}, {'channels':{'allowed':[True]}},
    {'channels':{'allowed':'1,2'}}, {'clipping':{'ignored':True}},
    {'bwf':{'required':'yes'}}, {'unknown':1},
])
def test_strict_custom_validation(patch):
    with pytest.raises(ConfigError):
        resolve_config({'preset':'CUSTOM',**patch})


def test_yaml_roundtrip_preserves_all_options_and_nulls(tmp_path):
    value = custom()
    value['defects']['enabled'] = True
    value['defects']['clicks']['merge_gap_ms'] = .25
    value['defects']['issues']['cross_channel_merge_ms'] = 0
    value['timecode'] = {'frame_rate':'29.97 DF','source':'MANUAL','manual_start':'10:00:00;00'}
    value['process_timeout_seconds'] = 120
    value['expected_stems'] = ['DIA','FX']
    value['clipping']['consecutive_samples'] = 5
    path = tmp_path/'Especificación 日本語 con espacios.yaml'
    save_config(path,value)
    assert load_config(path) == value
    assert 'preset: CUSTOM' in path.read_text()
    assert 'preferred: null' in path.read_text()
    assert list(tmp_path.glob('.audio-qc-*')) == []


def test_atomic_save_failure_leaves_existing_file_and_presets_untouched(tmp_path,monkeypatch):
    path = tmp_path/'custom.yaml'
    path.write_text('original bytes')
    def fail(*args):
        raise PermissionError('denied')
    monkeypatch.setattr('audio_qc.config.os.replace',fail)
    with pytest.raises(ConfigError,match='denied'):
        save_config(path,custom())
    assert path.read_text() == 'original bytes'
    assert list(tmp_path.glob('.audio-qc-*')) == []


def test_save_rejects_builtin_audio_destination_and_missing_directory(tmp_path):
    bundled = Path(__file__).parents[1]/'config/default.yaml'
    before = bundled.read_bytes()
    with pytest.raises(ConfigError,match='presets'):
        save_config(bundled,custom())
    assert bundled.read_bytes() == before
    with pytest.raises(ConfigError,match='yaml'):
        save_config(tmp_path/'audio.wav',custom())
    with pytest.raises(ConfigError,match='guardar'):
        save_config(tmp_path/'missing'/'custom.yaml',custom())


def test_custom_resolution_does_not_modify_builtin_presets():
    before = {p:load_config(preset=p) for p in ('FILM_48K','BROADCAST_EBU_R128','CUSTOM')}
    result = custom()
    result['defects']['clicks']['sensitivity'] = 'low'
    assert {p:load_config(preset=p) for p in before} == before
