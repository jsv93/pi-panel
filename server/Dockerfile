# Build context is the repository root, not server/, so the panel files can be
# baked in. They were populated by hand before, which produced a stale agent, a
# stale panel.html, and finally an empty directory on a fresh install — three
# failures with one cause. Shipping them means the bundle always matches the
# server that serves it.
FROM python:3.12-slim
WORKDIR /srv

COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server/app ./app
COPY server/run.sh /run.sh
RUN chmod +x /run.sh

# Fallback bundle. /data/bundle still wins if an operator puts files there, so
# a panel can be pinned to a hand-edited build without rebuilding the image.
COPY panel-ui/panel.html      /srv/bundle/panel.html
COPY agent/panel-agent.py     /srv/bundle/panel-agent.py
COPY panel-ui/backlight.py    /srv/bundle/backlight.py

VOLUME ["/data"]
EXPOSE 8099
ENV PANEL_DB=/data/panels.db PANEL_UI_DIR=/data/ui \
    PANEL_BUNDLE_DIR=/data/bundle PANEL_SSH_DIR=/data/ssh \
    PANEL_BUILTIN_BUNDLE=/srv/bundle
# One image for both deployments. run.sh reads /data/options.json when Home
# Assistant's Supervisor has written one and otherwise does nothing, so the
# standalone path is unaffected -- and there is no second image to drift.
CMD ["/run.sh"]
