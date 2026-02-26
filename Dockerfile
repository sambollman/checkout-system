FROM python:3.11-slim

# Create non-root user for security
RUN useradd -m -u 1000 appuser

# Set working directory
WORKDIR /app

# Copy requirements file
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy all application files
COPY . .

# Switch to non-root user
USER appuser

# Expose port 5000
EXPOSE 5000

# Run the Flask app
CMD ["python", "app.py"]
