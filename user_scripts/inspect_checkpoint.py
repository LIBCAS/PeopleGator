"""Read-only JSON inspection of protected, locally generated checkpoints."""

import argparse
import json
from pathlib import Path
import sys


def main():
    """Inspect a trusted checkpoint without initializing engines or app clients."""
    from people_gator.core.checkpoints import CheckpointError, atomic_json, read_metadata, read_ledger
    from people_gator.core.checkpoint_inspection import inspect_checkpoint
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('checkpoint', help='Trusted local stage directory or checkpoint.json; Pickle can execute code.')
    parser.add_argument('--details', nargs='+', choices=('ocr', 'regions', 'entities'), default=['ocr', 'regions', 'entities'])
    parser.add_argument('--output-path', help='Optional private diagnostic JSON file; otherwise writes stdout.')
    args = parser.parse_args()
    try:
        result = inspect_checkpoint(args.checkpoint, args.details)
        if args.output_path:
            output = Path(args.output_path).resolve()
            data, marker = read_metadata(args.checkpoint)
            history = Path(data['run_directory']).resolve()
            ledger = read_ledger(history, data['run_id'], data['document_id'])
            protected = [history] + [Path(path).parent.resolve() for path in ledger['checkpoints']]
            if any(output.is_relative_to(directory) for directory in protected):
                raise CheckpointError('Diagnostic export cannot overwrite checkpoint history files')
            output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            atomic_json(output, result)
        else:
            print(json.dumps(result, ensure_ascii=True, allow_nan=False, indent=2))
        return 0
    except CheckpointError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (OSError, TypeError, ValueError):
        print('Checkpoint diagnostic output could not be written as JSON', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
