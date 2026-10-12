try:
    import pymysql

    pymysql.install_as_MySQLdb()
except ModuleNotFoundError:
    # pymysql is only required for MySQL deployments (see requirements.txt).
    # Allow local SQLite runs without it installed.
    pass