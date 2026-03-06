FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install CPU-only PyTorch first (~200MB vs ~2GB with CUDA)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Then install everything else (sentence-transformers will use the CPU torch)
RUN pip install --no-cache-dir -r requirements.txt

# Install headless Chromium for HTML previewing loops
RUN playwright install --with-deps chromium

# Download spaCy language model
RUN python -m spacy download en_core_web_sm

COPY . .

COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
