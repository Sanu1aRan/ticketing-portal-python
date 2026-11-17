# Django expects the "MySQLdb" driver. PyMySQL is a pure-Python driver that
# installs on Windows without a compiler, so we tell Django to use it instead.
import pymysql

pymysql.install_as_MySQLdb()
