"""Peewee 数据模型定义"""

from datetime import datetime
from peewee import (
    DatabaseProxy, Model, CharField, DateTimeField, BooleanField,
    IntegerField, TextField, ForeignKeyField
)

# 使用 DatabaseProxy 延迟绑定数据库
database_proxy = DatabaseProxy()


class BaseModel(Model):
    """基础模型类"""

    class Meta:
        database = database_proxy


class Repository(BaseModel):
    """仓库模型"""
    name = CharField()
    url = CharField(unique=True)  # owner/repo 格式
    branch = CharField()
    last_commit_hash = CharField(null=True)
    last_check_time = DateTimeField(null=True)
    enabled = BooleanField(default=True)
    created_at = DateTimeField(default=datetime.now)
    updated_at = DateTimeField(default=datetime.now)

    class Meta:
        table_name = 'repositories'


class Report(BaseModel):
    """报告模型"""
    repo = ForeignKeyField(Repository, backref='reports')
    commit_hash = CharField()
    previous_commit_hash = CharField(null=True)
    commit_count = IntegerField(default=1)
    markpost_id = CharField(null=True)
    markpost_url = CharField(null=True)
    report_content = TextField(null=True)
    created_at = DateTimeField(default=datetime.now)

    class Meta:
        table_name = 'reports'
