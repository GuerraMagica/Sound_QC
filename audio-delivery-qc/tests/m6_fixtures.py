"""Independent role-ordered PCM reference; never import the virtual input builder."""
import numpy as np
import yaml
from audio_qc.synthetic import write_wav


def make_programme_fixture(root, *, layout, seconds=12, case='asymmetric', time_reference=172800000):
    roles = ('L', 'R') if layout == 'stereo' else ('L', 'R', 'C', 'LFE', 'Ls', 'Rs')
    t = np.arange(round(seconds * 48000)) / 48000
    pcm = {}
    members = {}
    for i, role in enumerate(roles):
        envelope = np.where((t.astype(int) // 3) % 2, 0.7, 0.2)
        signal = envelope * (0.04 + i * 0.012) * np.sin(2*np.pi*(83+i*137)*t)
        if case == 'silence' or case == 'lfe' and role != 'LFE':
            signal[:] = 0
        if case == 'below_gate':
            signal *= 1e-5
        if role == 'LFE' and case in ('lfe', 'lfe_peak'):
            signal = .95 * np.sin(2*np.pi*60*t)
        signal = np.rint(signal * 2**23) / 2**23
        pcm[role] = signal
        members[role] = write_wav(root / 'sources' / f'Programa 日本語.{role}.wav', signal,
                                  bext=time_reference is not None, time_reference=time_reference or 0)
    reference = write_wav(root / 'reference.wav', np.column_stack(list(pcm.values())),
                          mask=3 if layout == 'stereo' else 0x60f, bext=True, time_reference=time_reference or 0)
    manifest = root / 'groups.yaml'
    manifest.write_text(yaml.safe_dump({'schema_version': 1, 'programme_groups': [
        {'id': 'test', 'name': 'Programa 日本語', 'layout': layout,
         'alignment': {'mode': 'bwf_time_reference' if time_reference is not None else 'common_file_start'},
         'members': [{'channel': r, 'file': str(p.relative_to(root))} for r, p in members.items()]}]},
         allow_unicode=True), encoding='utf-8')
    return dict(members=members, reference=reference, manifest=manifest, sample_rate=48000,
                sample_count=len(t), pcm_by_role=pcm)
