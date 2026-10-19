from copy import deepcopy
import csv
import hashlib
import json
import subprocess

import numpy as np
import pytest

from audio_qc.defects import detect_window
from audio_qc.issues import consolidate_issues
from audio_qc.models import AudioFile, Defect
from audio_qc.reports import build_report, write_reports
from audio_qc.scanner import inspect_file
from audio_qc.snippets import export_snippets
from audio_qc.synthetic import sine, write_wav


def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest(),path.stat().st_size,path.stat().st_mtime_ns


def decode(path, channels):
    pcm = subprocess.run(['ffmpeg','-v','error','-i',str(path),'-f','f64le','-c:a','pcm_f64le','-'],
                         capture_output=True,check=True).stdout
    return np.frombuffer(pcm,dtype='<f8').reshape(-1,channels)


@pytest.mark.integration
@pytest.mark.parametrize('context',[0,.125])
def test_one_51_snippet_preserves_all_original_channels_order_gain_and_full_issue_extent(tmp_path,config,context):
    config['defects'].update(enabled=True,max_candidates=1,
                             snippet_before_seconds=context,snippet_after_seconds=context)
    # Each original channel has a different tone; unaffected channels must also
    # survive export. A downmix, reorder, gain change, or missing context fails.
    samples = np.column_stack([sine(3,amplitude=.015+.002*c,frequency=150+30*c)[:,0] for c in range(6)])
    samples[47996:47999,0] += .7
    samples[48000:48008,0] += .8
    samples[47999:48005,1] += .7
    samples[48002:48007,4] += .7
    assert len(detect_window(samples,48000,config['defects'])) == 4
    source = write_wav(tmp_path/'5.1 source.wav',samples,mask=0x3f,bext=True,time_reference=172800000)
    before = fingerprint(source)
    audio = inspect_file(source,config,with_hash=True)
    issue, = audio.defects
    assert issue.channels == [1,2,5]
    assert len(issue.channel_events) == 3 and issue.merged_candidate_count == 4
    assert not any(c.code == 'defects_capped' for c in audio.checks)
    output = tmp_path/'reports'
    output.mkdir()
    export_snippets(audio,output,config,1)
    snippet, = (output/'defect_snippets').glob('*.wav')
    assert snippet == output/issue.snippet
    info = json.loads(subprocess.run(['ffprobe','-v','error','-show_streams','-of','json',str(snippet)],
                                    capture_output=True,text=True,check=True).stdout)['streams'][0]
    assert (info['channels'],info['channel_layout'],info['sample_rate'],info['codec_name']) == (6,'5.1','48000','pcm_f32le')
    first = issue.cluster_first_sample-round(context*48000)
    end = issue.cluster_last_sample+1+round(context*48000)
    np.testing.assert_array_equal(decode(snippet,6),decode(source,6)[first:end])
    assert (first,end) == (47996-round(context*48000),48008+round(context*48000))
    write_reports(build_report(source,[audio],[],config,{},0),output)
    report = json.loads((output/'QC_REPORT.json').read_text())
    assert report['schema_version'] == 5 and report['summary']['defect_issues'] == 1
    saved, = report['files'][0]['defects']
    assert saved['channels'] == [1,2,5]
    assert saved['cluster_first_sample'] == 47996 and saved['cluster_last_sample'] == 48007
    for measured,event in zip(issue.channel_events,saved['channel_events']):
        assert event['sample_index'] == measured.sample_index
        assert event['timestamp_seconds'].hex() == measured.timestamp_seconds.hex()
        assert event['file_start_timecode'] == '01:00:00:00'
        assert event['timecode'] and event['timecode_basis'] == 'BWF_TIMEREFERENCE'
        assert event['snippet'] is None
    with (output/'QC_DEFECTS.csv').open(encoding='utf-8-sig',newline='') as handle:
        row, = csv.DictReader(handle)
    assert row['Channels'] == '1, 2, 5' and row['Merged Candidate Count'] == '4'
    assert json.loads(row['Channel Events']) == saved['channel_events']
    html = (output/'QC_REPORT.html').read_text()
    assert '<td>1, 2, 5</td>' in html and html.count('>Evidence WAV</a>') == 1
    assert fingerprint(source) == before


@pytest.mark.parametrize('frame_rate',['23.976','24','25','29.97 NDF','29.97 DF','30'])
def test_nested_timecode_is_report_only_and_preserves_forensic_precision(config,frame_rate):
    detections = [Defect(n/48000,n,ch,'POSSIBLE CLICK / TICK',3/48000,None,
                         {'duration_samples':3},'original') for n,ch in ((2529767,1),(2529770,2))]
    audio = AudioFile('/delivery/source.wav','source.wav',sample_rate=48000,
                      bwf={'present':True,'time_reference':172800000},
                      defects=consolidate_issues(detections,48000,2))
    before = deepcopy(audio)
    config['timecode']['frame_rate'] = frame_rate
    report = build_report('/delivery',[audio],[],config,{},0)
    issue, = report['files'][0]['defects']
    assert issue['sample_index'] == 2529767
    assert issue['timestamp_seconds'].hex() == detections[0].timestamp_seconds.hex()
    assert issue['offset'] == '00:00:52.703'
    if frame_rate == '25':
        assert issue['timecode'] == '01:00:52:17'
    for event, original in zip(issue['channel_events'],detections):
        assert event['timecode_frame_rate'] == frame_rate
        assert event['sample_index'] == original.sample_index
        assert event['timestamp_seconds'].hex() == original.timestamp_seconds.hex()
        assert event['measurements'] == original.measurements
    assert audio == before
