import hashlib
import subprocess
import numpy as np
import pytest


@pytest.mark.integration
@pytest.mark.parametrize('layout,channels', [('stereo', 2), ('5.1', 6)])
def test_reference_roles_and_pcm(tmp_path, layout, channels):
    from m6_fixtures import make_programme_fixture
    fixture = make_programme_fixture(tmp_path, layout=layout)
    before = {p: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_size, p.stat().st_mtime_ns)
              for p in [fixture['reference'], *fixture['members'].values()]}
    raw = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(fixture['reference']),
                                   '-f', 'f64le', '-c:a', 'pcm_f64le', '-'])
    values = np.frombuffer(raw, '<f8').reshape(-1, channels)
    assert len(values) == 576000
    for index, role in enumerate(fixture['members']):
        np.testing.assert_array_equal(values[:, index], fixture['pcm_by_role'][role])
    assert before == {p: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_size, p.stat().st_mtime_ns)
                      for p in before}
