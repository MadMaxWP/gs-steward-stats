import configparser
import os
from datetime import datetime
from decimal import Decimal

import pymysql

from stats import settings


def replica_login():
    # toolforge gives every job and webservice these envvars. replica.my.cnf
    # is only there when the home folder is mounted (old setups, local runs)
    user, password = os.environ.get("TOOL_TOOLSDB_USER"), os.environ.get("TOOL_TOOLSDB_PASSWORD")
    if user and password:
        return user, password
    cp = configparser.ConfigParser()
    cp.read(os.path.expanduser("~/replica.my.cnf"))
    return cp["client"]["user"].strip("'\""), cp["client"]["password"].strip("'\"")


def db_full_name():
    user, _ = replica_login()
    return f"{user}__{settings.db_name}_p"


def connect(dict_rows=False, create=False, cursor=None, host=None):
    # plain tuple rows unless asked, db.py asks for dict rows itself
    user, password = replica_login()
    opts = dict(
        host=host or settings.db_host, user=user, password=password, charset="utf8mb4", autocommit=True,
        connect_timeout=10, read_timeout=600, write_timeout=120,
    )
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
