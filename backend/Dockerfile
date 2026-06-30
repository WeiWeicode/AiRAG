FROM python:3.11-slim

# 安裝基本依賴（含 Oracle Instant Client 所需的 libaio 與 ODBC 驅動）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    unzip \
    libaio1t64 \
    unixodbc-dev \
    tdsodbc \
    freetds-bin \
    freetds-dev \
    && LIBAIO_PATH=$(find /usr/lib /lib -name "libaio.so.1t64" -print -quit) \
    && if [ -n "$LIBAIO_PATH" ]; then ln -s "$LIBAIO_PATH" "$(dirname "$LIBAIO_PATH")/libaio.so.1"; fi \
    && rm -rf /var/lib/apt/lists/*

# 安裝 Oracle Instant Client 19c（Thick Mode）
# 依照 Ubuntu 主機架構下載對應 zip 放至 backend/ 目錄（需接受 OTN 授權）：
# x86_64: https://www.oracle.com/database/technologies/instant-client/linux-x86-64-downloads.html
# ARM64:   https://www.oracle.com/database/technologies/instant-client/linux-arm-aarch64-downloads.html
ENV ORACLE_HOME=/opt/oracle
COPY instantclient-basic-linux.*.zip /tmp/instantclient.zip
RUN mkdir -p /opt/oracle \
    && unzip /tmp/instantclient.zip -d /opt/oracle \
    && mv /opt/oracle/instantclient_19_* /opt/oracle/lib \
    && echo "/opt/oracle/lib" > /etc/ld.so.conf.d/oracle-instantclient.conf \
    && ldconfig \
    && rm /tmp/instantclient.zip

# 設定 Oracle Thick Mode 所需環境變數
ENV LD_LIBRARY_PATH=/opt/oracle/lib
ENV PATH=/opt/oracle/lib:$PATH
ENV ORACLE_CLIENT_LIB_DIR=/opt/oracle/lib

WORKDIR /app

# 複製並安裝 Python 套件
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 複製程式碼
COPY . .

# 暴露 FastAPI 連接埠
EXPOSE 53020

# 啟動命令
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "53020"]
