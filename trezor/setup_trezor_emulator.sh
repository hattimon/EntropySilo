#!/bin/bash
set -Eeuo pipefail

cat >&2 <<'EOF'
ODMOWA: emulator Trezora jest celowo wyłączony w produkcyjnym EntropySilo.
To środowisko nie zapewnia zabezpieczeń sprzętowego portfela.
Przeczytaj README_TREZOR.txt i użyj osobnej karty laboratoryjnej bez realnych kluczy.
EOF
exit 1
