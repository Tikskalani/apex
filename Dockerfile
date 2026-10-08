# APEX hosted demo. Pure-stdlib Python: nothing to pip install.
# Build:  docker build -t apex .
# Local:  docker run --rm -p 8080:8080 -e OPENAI_API_KEY=... -e APEX_ACCESS_CODE=... \
#           -e APEX_SESSION_SECRET=... -v apex_data:/data apex
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APEX_BIND=0.0.0.0 \
    APEX_PORT=8080 \
    APEX_DB=/data/apex.db \
    APEX_TRUST_PROXY=1

RUN useradd --create-home --uid 10001 apex && mkdir -p /data

WORKDIR /app
# Code is root-owned and read-only to the app user. .dockerignore admits only
# these four files, so config.json and apex.db can never end up in the image.
COPY agent_server.py apex_store.py apex_engine.py index.html ./

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=4).status == 200 else 1)"

# Hosting volumes mount as root: hand /data to the app user, then drop root.
CMD ["sh", "-c", "chown -R apex:apex /data && exec setpriv --reuid=10001 --regid=10001 --init-groups python agent_server.py"]
