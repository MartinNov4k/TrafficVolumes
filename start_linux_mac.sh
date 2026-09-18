#!/usr/bin/env bash
# TrafficVolumes - spuštění zadávání intenzit.
# Použití: ./start_linux_mac.sh [projekt.tvol]
set -euo pipefail
cd "$(dirname "$0")"

projekt="${1:-}"
if [ -z "$projekt" ]; then
  projekt="$(ls -1 ./*.tvol 2>/dev/null | head -1 || true)"
fi
if [ -z "$projekt" ]; then
  echo "V této složce není žádný soubor *.tvol." >&2
  echo "Spusťte skript s cestou k projektu: ./start_linux_mac.sh projekt.tvol" >&2
  exit 1
fi

python3 -m trafficvolumes serve "$projekt" --open
