#!/bin/zsh

cd "$(dirname "$0")" || exit 1

if [[ ! -x .venv/bin/python ]]; then
  echo "Не найдено окружение .venv — создаю..."
  python3 -m venv .venv || exit 1
  .venv/bin/pip install --quiet -r requirements.txt || exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "Не найден ffmpeg. Установите его: brew install ffmpeg"
  echo "Нажмите Enter, чтобы закрыть."
  read -r
  exit 1
fi

exec .venv/bin/python app.py
