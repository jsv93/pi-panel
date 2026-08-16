# Same base as the standalone image on purpose: one runtime to reason about,
# and the dependencies (paramiko, cryptography) already have wheels for it.
FROM python:3.12-slim

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY run.sh /run.sh
RUN chmod +x /run.sh

# Written by the Supervisor; /data is the add-on's persistent volume, which is
# where the standalone deployment already keeps its database and bundle.
ENV PANEL_DB=/data/panels.db PANEL_UI_DIR=/data/ui \
    PANEL_BUNDLE_DIR=/data/bundle PANEL_SSH_DIR=/data/ssh

EXPOSE 8099
CMD ["/run.sh"]
