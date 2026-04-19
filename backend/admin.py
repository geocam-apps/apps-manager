from sqladmin import ModelView
from .models import User, App, AppShare, JobLog


class UserAdmin(ModelView, model=User):
    column_list = [User.id, User.username, User.email, User.is_admin, User.is_active, User.created_at]
    column_searchable_list = [User.username, User.email]
    column_sortable_list = [User.id, User.created_at]
    form_excluded_columns = [User.hashed_password, User.apps, User.received_shares]
    name = "User"
    name_plural = "Users"
    icon = "fa-solid fa-users"


class AppAdmin(ModelView, model=App):
    column_list = [App.id, App.name, App.owner_id, App.status, App.container_ip, App.created_at]
    column_searchable_list = [App.name]
    column_sortable_list = [App.id, App.created_at]
    form_excluded_columns = [App.shares, App.logs, App.owner]
    name = "App"
    name_plural = "Apps"
    icon = "fa-solid fa-cube"


class AppShareAdmin(ModelView, model=AppShare):
    column_list = [AppShare.id, AppShare.app_id, AppShare.user_id, AppShare.created_at]
    name = "App Share"
    name_plural = "App Shares"
    icon = "fa-solid fa-share-nodes"


class JobLogAdmin(ModelView, model=JobLog):
    column_list = [JobLog.id, JobLog.app_id, JobLog.step, JobLog.status, JobLog.message, JobLog.created_at]
    column_sortable_list = [JobLog.id, JobLog.created_at]
    name = "Job Log"
    name_plural = "Job Logs"
    icon = "fa-solid fa-list"
