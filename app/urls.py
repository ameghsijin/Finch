from django.urls import path

from .views import health_check
from . import views

urlpatterns = [

    path("", views.index, name="index"),

    # Expenses
    path("expenses/", views.expenses, name="expenses"),
    path("expenses/export/", views.expenses_export, name="expenses_export"),
    path("expense-form/", views.expense_form, name="expense_form"),
    path("expense-form/<int:pk>/", views.expense_form, name="expense_edit"),
    path("expense-delete/<int:pk>/", views.expense_delete, name="expense_delete"),

    # Income
    path("income/", views.income, name="income"),
    path("income/export/", views.income_export, name="income_export"),
    path("income-form/", views.income_form, name="income_form"),
    path("income-form/<int:pk>/", views.income_form, name="income_edit"),
    path("income-delete/<int:pk>/", views.income_delete, name="income_delete"),

    # Budgets
    path("budget/", views.budgets, name="budgets"),
    path("budget/export/", views.budgets_export, name="budgets_export"),
    path("budget-form/", views.budget_form, name="budget_form"),
    path("budget-form/<int:pk>/", views.budget_form, name="budget_edit"),
    path("budget-delete/<int:pk>/", views.budget_delete, name="budget_delete"),

    # Categories
    path("categories/", views.categories, name="categories"),
    path("category-form/", views.category_form, name="category_form"),
    path("category-form/<int:pk>/", views.category_form, name="category_edit"),
    path("category-delete/<int:pk>/", views.category_delete, name="category_delete"),

    # Clients
    path("clients/", views.clients, name="clients"),
    path("client-form/", views.client_form, name="client_form"),
    path("client-form/<int:pk>/", views.client_form, name="client_edit"),
    path("client/<int:pk>/", views.client_detail, name="client_detail"),

    # Reports
    path("reports/", views.reports, name="reports"),

    # Authentication
    path("login/", views.login_view, name="login"),
    path("signup/", views.signup_view, name="signup"),
    path("logout/", views.logout_view, name="logout"),
    path("mfa/setup/", views.mfa_setup, name="mfa_setup"),
    path("mfa/login/", views.mfa_login, name="mfa_login"),

    # AI
    path("ai-assistant/", views.ai_assistant, name="ai_assistant"),
    path("ai-query/", views.ai_query, name="ai_query"),
    path("ai-forecast/", views.ai_forecast, name="ai_forecast"),
    path("forecast/", views.forecast, name="forecast"),
    path("forecast/<int:months>/", views.forecast, name="forecast_months"),

    # Profile
    path("profile/", views.profile, name="profile"),

    #Uptime
    path("health/", health_check),
]