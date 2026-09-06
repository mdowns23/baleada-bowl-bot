FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Database and logs live in a mounted volume at /app/data
ENV DB_PATH=/app/data/fantasy_bot.db
ENV LOG_PATH=/app/data/bot.log

CMD ["python", "bot.py"]
