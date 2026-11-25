"""Read-only JSON inspection of trusted local checkpoints."""

import argparse
import json
from pathlib import Path

from people_gator.core.checkpoint_inspection import inspect_checkpoint


def main():
    """Inspect a trusted checkpoint without initializing engines or app clients."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('checkpoint', type=Path, help='Trusted local stage directory or checkpoint.json; Pickle can execute code.')
    parser.add_argument('--details', nargs='+', choices=('ocr', 'regions', 'entities'), default=['ocr', 'regions', 'entities'])
    parser.add_argument('--output-path', type=Path, help='Optional diagnostic JSON file; otherwise writes stdout.')
    args = parser.parse_args()
    result = inspect_checkpoint(args.checkpoint, args.details)
    payload = json.dumps(result, ensure_ascii=True, allow_nan=False, indent=2)
    if args.output_path:
        marker = args.checkpoint / 'checkpoint.json' if args.checkpoint.is_dir() else args.checkpoint
        if args.output_path.exists() and (args.output_path.samefile(marker)
                                         or args.output_path.samefile(marker.with_name('document.pkl'))):
            parser.error('Choose a diagnostic output file outside the input checkpoint pair.')
        args.output_path.parent.mkdir(parents=True, exist_ok=True)
        args.output_path.write_text(payload + '\n', encoding='utf-8')
    else:
        print(payload)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
