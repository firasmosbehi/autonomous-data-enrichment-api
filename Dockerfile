FROM python:3.12-slim

WORKDIR /app

# Install Poetry
RUN pip install poetry

# Copy dependency files
COPY pyproject.toml poetry.lock ./

# Configure Poetry to not create a virtual environment
RUN poetry config virtualenvs.create false

# Install dependencies only (not the project itself)
RUN poetry install --only main --no-root --no-interaction --no-ansi

# Copy application code
COPY enrichment_api ./enrichment_api

# Expose port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "enrichment_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
