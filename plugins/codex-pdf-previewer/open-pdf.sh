#!/bin/sh
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd) || exit 1
if [ "$#" -eq 0 ]; then
  printf 'Usage: %s "/path/to/document.pdf"\n' "$0"
  exit 2
fi
exec python3 "$script_dir/scripts/preview.py" open "$@"
