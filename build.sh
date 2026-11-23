#!/usr/bin/env bash
set -euo pipefail
python -m pip install -r requirements.txt
npm ci --prefix frontend --include=dev
npm run build --prefix frontend
python manage.py collectstatic --noinput
