#!/usr/bin/env bash
# Запускать из корня репозитория на VPS (после git clone).
# Использование: bash deploy/bootstrap-vps.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -f pyproject.toml ]]; then
  echo "Запусти скрипт из клона репозитория (рядом с pyproject.toml)." >&2
  exit 1
fi

PY="${PY:-python3}"
if ! command -v "$PY" &>/dev/null; then
  echo "Нет $PY в PATH. Установи Python 3.11+ или задай PY=/usr/bin/python3.12" >&2
  exit 1
fi

"$PY" -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install -U pip
pip install -e .

echo ""
echo "Готово. Дальше:"
echo "  1) cp .env.example .env && chmod 600 .env && nano .env"
echo "     Задай DATABASE_PATH абсолютным, например: $ROOT/data/bot.sqlite3"
echo "  2) Подставь User/WorkingDirectory/ExecStart в deploy/tg-digest-bot.service.example"
echo "  3) sudo cp deploy/tg-digest-bot.service.example /etc/systemd/system/tg-digest-bot.service"
echo "  4) sudo systemctl daemon-reload && sudo systemctl enable --now tg-digest-bot"
echo "  5) Логи: journalctl -u tg-digest-bot -f"
