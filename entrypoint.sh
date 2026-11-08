#!/bin/sh
# MODE=app     -> web app (Flask + HTML/CSS/JS) on port 8000 via gunicorn   [default]
# MODE=classic -> backup Streamlit app on port 8000
# MODE=job     -> run the Grants.gov refresh once and exit (daily Container Apps Job)
set -e
case "$MODE" in
  job)     exec python -m data_retrieval.refresh ;;
  classic) exec streamlit run app.py --server.port "${PORT:-8000}" --server.address 0.0.0.0 ;;
  *)       exec gunicorn -c web/gunicorn.conf.py web.server:app ;;
esac
