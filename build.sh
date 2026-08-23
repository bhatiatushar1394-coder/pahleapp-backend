#!/usr/bin/env bash
set -o errexit
pip install -r requirements.txt
python manage.py collectstatic --noinput
python manage.py migrate --noinput
if [ "${SEED_ON_DEPLOY}" = "true" ]; then
  python manage.py seed
fi
