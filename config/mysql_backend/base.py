"""
Django's normal MySQL backend, with one addition: it also works on the
MariaDB 10.4 that ships inside XAMPP.

Django 5.2 officially needs MariaDB 10.5+ (or MySQL 8.0.11+). The only thing
this project would use from 10.5 is "INSERT ... RETURNING", so on an older
MariaDB we switch that off and Django falls back to the classic
"INSERT, then ask for the new id" way. On MySQL 8 or a newer MariaDB this
file changes nothing.
"""

from django.db.backends.mysql import base, features
from django.utils.functional import cached_property


class DatabaseFeatures(features.DatabaseFeatures):
    @cached_property
    def _old_mariadb(self):
        conn = self.connection
        return conn.mysql_is_mariadb and conn.mysql_version < (10, 5)

    @cached_property
    def minimum_database_version(self):
        if self.connection.mysql_is_mariadb:
            return (10, 4)
        return super().minimum_database_version

    @cached_property
    def can_return_columns_from_insert(self):
        if self._old_mariadb:
            return False
        return super().can_return_columns_from_insert

    @cached_property
    def can_return_rows_from_bulk_insert(self):
        return self.can_return_columns_from_insert


class DatabaseWrapper(base.DatabaseWrapper):
    features_class = DatabaseFeatures
