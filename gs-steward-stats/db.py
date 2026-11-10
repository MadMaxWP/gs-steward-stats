"""database on ToolsDB.

credentials come from ~/replica.my.cnf.
"""

import configparser
import os
from datetime import datetime
from decimal import Decimal
import pymysql
from .settings import settings


def credentials():
    """Read the user and password from ~/replica.my.cnf."""
    cp = configparser.ConfigParser()
    cp.read(os.path.expanduser("~/replica.my.cnf"))
    return cp["client"]["user"].strip("'\""), cp["client"]["password"].strip("'\"")


def connect():
    """Open a new connection to the tool database (rows come back as dicts)."""
    user, password = credentials()
    return pymysql.connect(
        host=settings["db_host"],
        user=user,
        password=password,
        database=f"{user}__{settings['db_name']}_p",
        charset="utf8mb4",
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
    )


def clean_value(value):
    """turn database values into JSON-friendly ones."""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", "replace")
    return value


def query_all(sql, args=None):
    """Run a query and return every row as a cleaned dict."""
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, args)
            return [{k: clean_value(v) for k, v in row.items()} for row in cur.fetchall()]
    finally:
        conn.close()
