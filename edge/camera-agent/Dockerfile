# Runs as an Azure IoT Edge module on a store gateway, or as a plain container.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /srv

# OpenCV needs these even in headless use.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY agent.py ./

# Overridden per store by the deployment manifest.
ENV SHOPPERMIND_API_URL=http://localhost:8000
ENTRYPOINT ["python", "agent.py"]
CMD ["--simulate", "--cameras", "CAM-1:entrance"]
