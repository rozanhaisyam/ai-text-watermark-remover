FROM python:3.11-slim

# PDF export uses a TrueType font with Unicode coverage.
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 appuser
COPY app.py main.py script.js styles.css ./
COPY static ./static
COPY templates ./templates
USER appuser

# Default only: PORT can be supplied by the hosting platform at runtime.
EXPOSE 8000
CMD ["python", "main.py"]
