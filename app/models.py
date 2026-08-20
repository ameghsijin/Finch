from django.conf import settings
from django.db import models
from django.utils import timezone


class Category(models.Model):
    TYPE_CHOICES = [
        ('expense', 'Expense'),
        ('income', 'Income'),
    ]
    ICON_CHOICES = [
        ('Tag', 'Tag'),
        ('Food', 'Food'),
        ('Transport', 'Transport'),
        ('Home', 'Home'),
        ('Shopping', 'Shopping'),
        ('Salary', 'Salary'),
    ]

    name = models.CharField(max_length=100)
    type = models.CharField(max_length=7, choices=TYPE_CHOICES, default='expense')
    color = models.CharField(max_length=7, default='#0F766E')
    icon = models.CharField(max_length=30, choices=ICON_CHOICES, default='Tag')

    def __str__(self):
        return f'{self.name} ({self.get_type_display()})'


class Expense(models.Model):
    PAYMENT_CHOICES = [
        ('UPI', 'UPI'),
        ('Cash', 'Cash'),
        ('Card', 'Card'),
        ('Bank Transfer', 'Bank Transfer'),
        ('Other', 'Other'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='expenses',
    )
    title = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    date = models.DateField(default=timezone.now)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_CHOICES, default='UPI')
    notes = models.TextField(blank=True)
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={'type': 'expense'},
    )

    class Meta:
        ordering = ['-date', '-pk']

    def __str__(self):
        return self.title


class Income(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='incomes',
    )
    title = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    date = models.DateField(default=timezone.now)
    notes = models.TextField(blank=True)
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={'type': 'income'},
    )

    class Meta:
        ordering = ['-date', '-pk']

    def __str__(self):
        return self.title


class Budget(models.Model):
    PERIOD_CHOICES = [
        ('monthly', 'Monthly'),
        ('yearly', 'Yearly'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='budgets',
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    period = models.CharField(max_length=7, choices=PERIOD_CHOICES, default='monthly')
    month = models.PositiveSmallIntegerField(blank=True, null=True)
    year = models.PositiveSmallIntegerField()
    alert_threshold = models.PositiveSmallIntegerField(default=80)
    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        limit_choices_to={'type': 'expense'},
    )

    class Meta:
        ordering = ['-year', '-month']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'category', 'period', 'month', 'year'],
                name='unique_budget_period',
            ),
        ]

    def __str__(self):
        return f'{self.category} · {self.period} {self.year}'

class TrustedDevice(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="trusted_devices",
    )
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    def __str__(self):
        return f"{self.user.username} trusted device"


