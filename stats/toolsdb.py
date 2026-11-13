import configparser
import os
from datetime import datetime
from decimal import Decimal

import pymysql

from stats import settings


def replica_login():
    cp = configparser.ConfigParser()
    cp.read(os.path.expanduser("~/replica.my.cnf"))
    return cp["client"]["user"].strip("'\""), cp["client"]["password"].strip("'\"")


def db_full_name():
    user, _ = replica_login()
    return f"{user}__{settings.db_name}_p"


def connect(dict_rows=True, create=False, cursor=None):
    user, password = replica_login()
    opts = dict(host=settings.db_host, user=user, password=password, charset="utf8mb4", autocommit=True)
    name = f"{user}__{settings.db_name}_p"
    if create:
        c = pymysql.connect(**opts)
        with c.cursor() as cur:
            cur.execute(f"CREATE DATABASE IF NOT EXISTS `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        c.close()
    if cursor is None:
        cursor = pymysql.cursors.DictCursor if dict_rows else pymysql.cursors.Cursor
    return pymysql.connect(database=name, cursorclass=cursor, **opts)


def clean(v):
    # turn db values into things jsonify can handle
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    if isinstance(v, (bytes, bytearray)):
        return v.decode("utf-8", "replace")
    return v
