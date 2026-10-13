FROM python:3.11-slim

WORKDIR /app

# Install system build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy platform source tree
COPY . .

# Set Python path to include backend root
ENV PYTHONPATH=/app/backend

# Create uploads directory
RUN mkdir -p /app/backend/uploads/firmware

EXPOSE 8000

# Run FastAPI backend with uvicorn
CMD ["uvicorn", "src.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000"]
