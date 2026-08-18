# python:3.14 (локальная dev-машина) сознательно не используется как база —
# слишком свежий для гарантированных wheel'ов asyncpg/aiogram на Linux; 3.12
# полностью поддерживается всеми зависимостями из requirements.txt.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chmod +x docker-entrypoint.sh

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["python", "main.py"]
