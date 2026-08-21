from django.contrib import admin
from .models import Category, Expense

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "type", "color", "icon")
    search_fields = ("name",)
    list_filter = ("type",)


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "title", "amount", "category", "date", "payment_method")
    search_fields = ("title", "notes", "user__username")
    list_filter = ("category", "payment_method", "date")
    date_hierarchy = "date"


