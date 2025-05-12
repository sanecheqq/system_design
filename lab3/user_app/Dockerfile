FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY user_app.py .

CMD ["uvicorn", "user_app:app", "--host", "0.0.0.0", "--port", "8000"]