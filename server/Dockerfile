FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY run.sh /run.sh
RUN chmod +x /run.sh
VOLUME ["/data"]
EXPOSE 8099
ENV PANEL_DB=/data/panels.db PANEL_UI_DIR=/data/ui \
    PANEL_BUNDLE_DIR=/data/bundle PANEL_SSH_DIR=/data/ssh
# One image for both deployments. run.sh reads /data/options.json when Home
# Assistant's Supervisor has written one and otherwise does nothing, so the
# standalone path is unaffected -- and there is no second image to drift.
CMD ["/run.sh"]
