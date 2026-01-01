FROM python:3.12-slim

# Install FFmpeg
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Ensure cookies.txt has correct permissions
RUN chmod 644 cookies.txt || true

# Expose port
EXPOSE 5000

# Start command with increased timeout for large downloads (10 minutes)
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:5000", "--timeout", "600", "--workers", "2"]
