FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    unzip \
    libaio1t64 \
    unixodbc-dev \
    tdsodbc \
    freetds-bin \
    freetds-dev \
    && ln -s /usr/lib/x86_64-linux-gnu/libaio.so.1t64 /usr/lib/x86_64-linux-gnu/libaio.so.1 \
    && rm -rf /var/lib/apt/lists/*

# Set up Oracle Instant Client 19c
ENV ORACLE_HOME=/opt/oracle/instantclient
RUN mkdir -p /opt/oracle \
    && curl -fL https://download.oracle.com/otn_software/linux/instantclient/1922000/instantclient-basic-linux.x64-19.22.0.0.0dbru.zip -o /tmp/instantclient.zip \
    && unzip /tmp/instantclient.zip -d /opt/oracle \
    && mv /opt/oracle/instantclient_19_22 $ORACLE_HOME \
    && rm /tmp/instantclient.zip \
    && echo "$ORACLE_HOME" > /etc/ld.so.conf.d/oracle-instantclient.conf \
    && ldconfig

# Set environment variables for Oracle thick client mode
ENV LD_LIBRARY_PATH=$ORACLE_HOME
ENV PATH=$ORACLE_HOME:$PATH

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
