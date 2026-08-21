from django import forms
from .models import Category, Client, Expense

class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ['name', 'type', 'color', 'icon']
        widgets = {
            'color': forms.TextInput(attrs={'type': 'color'}),
        }

class ClientForm(forms.ModelForm):

    class Meta:
        model = Client
        fields = [
            'name',
            'contact_person',
            'email',
            'phone',
            'address',
            'notes',
            'is_active',
        ]
        widgets = {
            'address': forms.Textarea(attrs={'rows': 3}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }
class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = ['title', 'amount', 'date', 'payment_method', 'notes', 'category', 'client']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'amount': forms.NumberInput(attrs={'step': '0.01'}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }
