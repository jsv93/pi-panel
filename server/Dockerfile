FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
VOLUME ["/data"]
EXPOSE 8099
ENV PANEL_DB=/data/panels.db PANEL_UI_DIR=/data/ui
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8099"]
