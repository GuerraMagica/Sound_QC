import csv
import hashlib
from html.parser import HTMLParser
import json
from urllib.parse import quote

import pytest

from audio_qc.defects import detect_window
from audio_qc.models import AudioFile, Defect, Status
from audio_qc.reports import build_report, write_reports
from audio_qc.scanner import inspect_file
from audio_qc.snippets import export_snippets
from audio_qc.synthetic import sine, write_wav


class Anchors(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.links.append(dict(attrs))


@pytest.mark.integration
def test_consolidated_reports_and_one_snippet_per_multichannel_issue(tmp_path, config):
    config["defects"]["enabled"] = True
    samples = sine(3, channels=2, amplitude=.03, frequency=220)
    samples[47996:47999] += .7
    samples[48000:48008] += .8
    assert len(detect_window(samples, 48000, config["defects"])) == 4
    source = write_wav(tmp_path/"click pair.wav", samples, bext=True, time_reference=172800000)
    before = (hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_size, source.stat().st_mtime_ns)
    audio = inspect_file(source, config, with_hash=True)
    assert len(audio.defects) == 1
    assert audio.defects[0].channels == [1, 2]
    assert audio.defects[0].merged_candidate_count == 4
    assert [e.merged_candidate_count for e in audio.defects[0].channel_events] == [2, 2]
    output = tmp_path/"reports"
    output.mkdir()
    export_snippets(audio, output, config, 1)
    assert len(list((output/"defect_snippets").glob("*.wav"))) == 1
    assert all((output/e.snippet).is_file() for e in audio.defects)
    report = build_report(source, [audio], [], config, {}, 0)
    write_reports(report, output)
    saved = json.loads((output/"QC_REPORT.json").read_text())
    assert saved["summary"]["defect_candidates"] == saved["summary"]["defect_issues"] == 1
    events = saved["files"][0]["defects"]
    assert len(events) == 1
    assert events[0]["channel_events"][0]["timecode"] == events[0]["channel_events"][1]["timecode"]
    for original, event in zip(audio.defects, events):
        assert event["sample_index"] == original.sample_index
        assert event["timestamp_seconds"].hex() == original.timestamp_seconds.hex()
        assert event["cluster_first_sample"] == 47996
        assert event["cluster_last_sample"] == 48007
    with (output/"QC_DEFECTS.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["Channels"] == "1, 2"
    assert json.loads(rows[0]["Channel Events"]) == events[0]["channel_events"]
    with (output/"QC_REPORT.csv").open(encoding="utf-8-sig", newline="") as handle:
        assert next(csv.DictReader(handle))["Defect Candidates"] == "1"
    html = (output/"QC_REPORT.html").read_text()
    assert '<strong>1</strong><span>defect issues</span>' in html
    assert '<th>Channels</th>' in html
    table = html.split('<h3>Defect issues</h3>')[1].split('</table>')[0]
    assert '<td>1, 2</td>' in table
    assert html.count('>Evidence WAV</a>') == 1
    assert 'sample_index' in table and 'merged_candidate_count' in table
    anchors = Anchors()
    anchors.feed(html)
    links = [a for a in anchors.links if a['href'].startswith('defect_snippets/')]
    assert len(links) == 1
    assert all(a['target'] == '_blank' and a['rel'] == 'noopener' for a in links)
    assert before == (hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_size, source.stat().st_mtime_ns)


def test_evidence_link_keeps_relative_path_escaped_and_csp(tmp_path, config):
    audio = AudioFile('/delivery/test.wav', 'test.wav', sample_rate=48000)
    path = 'defect_snippets/a & "日本語" #1.wav'
    audio.defects = [Defect(1.0, 48000, 1, 'POSSIBLE CLICK / TICK', 3/48000,
                            Status.WARNING, {'duration_samples': 3}, 'test', snippet=path)]
    write_reports(build_report('/delivery', [audio], [], config, {}, 0), tmp_path)
    html = (tmp_path/'QC_REPORT.html').read_text()
    anchors = Anchors()
    anchors.feed(html)
    anchor, = [a for a in anchors.links if a['href'].startswith('defect_snippets/')]
    assert anchor == {'href': quote(path, safe='/'), 'target': '_blank', 'rel': 'noopener'}
    assert "default-src 'none'; style-src 'unsafe-inline'; media-src 'self' file:; base-uri 'none'; form-action 'none'" in html
    assert '<script' not in html
