import logging
import pyodbc
import asyncio
from config import settings
from contextlib import contextmanager

logger = logging.getLogger("airag.sqlserver")

import re

@contextmanager
def get_sqlserver_conn():
    conn_str = settings.SQLSERVER_CONNECTION_STRING
    if not conn_str:
        logger.warning("SQLSERVER_CONNECTION_STRING is not configured.")
        raise ValueError("SQL Server connection string is empty.")
    
    # 動態匹配系統中可用的驅動程式
    try:
        installed_drivers = pyodbc.drivers()
        logger.info(f"Available ODBC drivers in system: {installed_drivers}")
        
        # 優先級匹配
        selected_driver = None
        for d in installed_drivers:
            if "ODBC Driver 17" in d:
                selected_driver = d
                break
        if not selected_driver:
            for d in installed_drivers:
                if "ODBC Driver 18" in d:
                    selected_driver = d
                    break
        if not selected_driver:
            for d in installed_drivers:
                if "FreeTDS" in d:
                    selected_driver = d
                    break
        if not selected_driver:
            for d in installed_drivers:
                if "sql" in d.lower() or "tds" in d.lower():
                    selected_driver = d
                    break
                    
        if selected_driver:
            # 取代 DRIVER={...} 部分
            if "DRIVER=" in conn_str:
                conn_str = re.sub(r"DRIVER=\{[^}]+\}", f"DRIVER={{{selected_driver}}}", conn_str)
                conn_str = re.sub(r"DRIVER=[^;]+", f"DRIVER={{{selected_driver}}}", conn_str)
            
            # 如果使用的是 FreeTDS 驅動程式，確保連線參數齊全 (加上 PORT 與 TDS_Version)
            if "FreeTDS" in selected_driver:
                if "PORT=" not in conn_str and "port=" not in conn_str:
                    conn_str += ";PORT=1433"
                if "TDS_Version" not in conn_str and "tds_version" not in conn_str:
                    conn_str += ";TDS_Version=7.4"
            logger.info(f"Using dynamically selected ODBC driver: {selected_driver}")
    except Exception as de:
        logger.warning(f"Failed to dynamically query/substitute ODBC drivers: {de}")

    conn = None
    try:
        conn = pyodbc.connect(conn_str)
        yield conn
    except Exception as e:
        logger.error(f"SQL Server connection failed: {e}")
        raise e
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

async def execute_query_async(query: str, params: tuple = ()):
    """
    在獨立執行緒中執行 SQL Server 唯讀查詢，防止阻塞 FastAPI 的事件循環。
    """
    def _run():
        with get_sqlserver_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, params)
                if cursor.description:
                    columns = [col[0] for col in cursor.description]
                    return [dict(zip(columns, row)) for row in cursor.fetchall()]
                return []
    
    return await asyncio.to_thread(_run)
