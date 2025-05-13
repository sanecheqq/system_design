FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY order_app.py .

CMD ["uvicorn", "order_app:app", "--host", "0.0.0.0", "--port", "8002"]