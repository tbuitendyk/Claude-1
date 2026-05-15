FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY bible_data.py download_kjv.py download_vp.py server.py ./

# KJV data is downloaded at container startup via server.py if absent.
# To bake it into the image instead (faster cold starts), uncomment:
# RUN python download_kjv.py

EXPOSE 8000

ENV TRANSPORT=http
ENV HOST=0.0.0.0
ENV PORT=8000

CMD ["python", "server.py"]
