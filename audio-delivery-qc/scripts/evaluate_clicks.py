"""Run the independent local click-confirmation experiment; never changes production defaults."""
import argparse
from pathlib import Path
import sys

from click_experiment.runner import run


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path, help='New directory, separate from audio sources')
    parser.add_argument('--essentia', action='store_true', help='Opt-in independent-detector benchmark (isolated Essentia runtime, schema 2)')
    args = parser.parse_args(argv)
    try:
        if args.essentia:
            from click_experiment.benchmark import run as independent_run
            result = independent_run(args.manifest, args.output)
        else:
            result = run(args.manifest, args.output)
    except KeyboardInterrupt:
        print('Experiment cancelled; no completed evaluation.', file=sys.stderr)
        return 130
    except Exception as exc:
        print(f'Experiment could not complete: {exc}', file=sys.stderr)
        return 2
    print(result['decision']['decision'])
    print(args.output.resolve() / 'report.html')
    return 0 if result['decision']['decision'] == 'VIABLE' else 1 if result['decision']['decision'] == 'NOT_VIABLE' else 3


if __name__ == '__main__':
    raise SystemExit(main())
