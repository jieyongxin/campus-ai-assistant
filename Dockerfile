FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Shanghai

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN python scripts/build_index.py

EXPOSE 8000
# 单 worker：会话上下文、限流计数和索引都在进程内存里，多 worker 会让
# 多轮对话随机丢上下文（同一会话的两次请求可能落到不同进程）。要横向扩展
# 请先把 sessions/ratelimit 换成 Redis，再通过 --workers 或编排层扩副本。
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
