# python:3.14 (локальная dev-машина) сознательно не используется как база —
# слишком свежий для гарантированных wheel'ов asyncpg/aiogram на Linux; 3.12
# полностью поддерживается всеми зависимостями из requirements.txt.
FROM python:3.12-slim

# Без этого stdout/stderr Python буферизуется блоками, когда он не в TTY
# (обычная ситуация в контейнере) — `docker compose logs` показывал бы вывод
# с задержкой/пачками вместо построчного стрима в реальном времени.
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chmod +x docker-entrypoint.sh

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["python", "main.py"]
