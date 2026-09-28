# Linux image with WeasyPrint's native libs, so CV PDFs render. Desktop toasts are no-ops here.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
      libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libffi8 fonts-dejavu \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md ./
COPY jobhunter ./jobhunter
RUN pip install --no-cache-dir ".[pdf]"
ENV DESKTOP_NOTIFICATIONS=false
EXPOSE 8000
CMD ["uvicorn", "jobhunter.interfaces.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
