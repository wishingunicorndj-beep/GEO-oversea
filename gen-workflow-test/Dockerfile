# 定制生文工作流生成服务
#
# 基础镜像固定 3.11：这是已验证过的运行时环境。
# 代码已不依赖 cgi（自实现 multipart 解析），但没必要为此换版本 —— 换环境需要全流程重测。
FROM python:3.11-slim

# Chromium 用于把看板 HTML 转成 PDF。--no-install-recommends 控制镜像体积。
# 字体必须装中文字体，否则 PDF 里中文会显示成方框。
RUN apt-get update && apt-get install -y --no-install-recommends \
        chromium \
        fonts-wqy-zenhei \
        fonts-wqy-microhei \
        fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先装依赖，利用层缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 生成物目录，容器内可写
RUN mkdir -p clients output

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    GEO_CHROME=/usr/bin/chromium

EXPOSE 8901

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8901/api/status',timeout=4).status==200 else 1)"

CMD ["python3", "server.py", "--port", "8901", "--host", "0.0.0.0"]
