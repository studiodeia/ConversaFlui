# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set environment variables
# Prevents Python from writing pyc files to disc (equivalent to python -B)
ENV PYTHONDONTWRITEBYTECODE 1
# Prevents Python from buffering stdout and stderr (ensures logs appear immediately)
ENV PYTHONUNBUFFERED 1

# Set the working directory in the container
WORKDIR /app

# Install system dependencies required for FFmpeg and potentially other libraries
# Using --no-install-recommends reduces image size
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    # Clean up apt cache to reduce image size
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the container at /app
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
# Using --no-cache-dir reduces image size
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container at /app
COPY main.py .

# Expose the port the app runs on.
# Railway will automatically detect and use the PORT environment variable,
# but exposing it here is good practice. The actual port number will be
# set by Railway via the $PORT env var.
# EXPOSE 8000 # We don't know the exact port Railway will assign, so commenting this out or setting to $PORT isn't standard. Railway handles port mapping.

# Define the command to run the application.
# Use the PORT environment variable provided by Railway.
# Listen on 0.0.0.0 to accept connections from outside the container.
CMD uvicorn main:app --host 0.0.0.0 --port $PORT