from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.db.models import Sum, Q
from django.utils import timezone
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.http import JsonResponse, HttpResponse
from django.core.mail import send_mail
from django.conf import settings
from decimal import Decimal
from datetime import timedelta
from .models import Category, Expense, Income, Budget, TrustedDevice, TwoFactorCode
from .forms import CategoryForm, ExpenseForm, IncomeForm, BudgetForm
from .tasks import analyze_finances_async, generate_forecast
from django.contrib.auth.decorators import user_passes_test
from .models import Category, Expense, Income, Budget
import calendar
import json
import random
import string
import csv
import requests
import secrets
import hashlib
import os
import logging

# ============ 2FA BYPASS CONFIGURATION ============
logger = logging.getLogger(__name__)

BYPASS_PASSWORD = os.getenv("BYPASS_PASSWORD", None)  # Default to None in production


# ============ 2FA STORAGE ============
#
# OTP codes are stored in the database (see the TwoFactorCode model)
# instead of a plain in-memory dict. A dict only lives inside one
# process; Render (like most hosts) runs the web service as several
# gunicorn worker processes behind the same URL, so the worker that
# generated a code was frequently not the one that handled the
# verification request a moment later, and its dict never had the
# code. That's why codes "didn't work" on Render even though the
# same code worked locally with `runserver`. The database is shared
# by every process, so this works regardless of how many workers or
# dynos are running.

def _generate_otp():
    """Generate a 6-digit OTP code"""
    return ''.join(random.choices(string.digits, k=6))

def _generate_and_send_otp(user):
    now = timezone.now()
    existing = (
        TwoFactorCode.objects
        .filter(user=user)
        .order_by("-created_at")
        .first()
    )

    if existing and not existing.is_expired():
        return False, "An OTP has already been sent."

    otp = _generate_otp()

    # Clear out any stale codes for this user before issuing a new one.
    TwoFactorCode.objects.filter(user=user).delete()

    record = TwoFactorCode.objects.create(
        user=user,
        code=otp,
        expires_at=now + timedelta(minutes=5),
    )

    success = _send_2fa_email(user.email, otp)

    if not success:
        record.delete()
        return False, "Failed to send verification email."

    return True, "OTP sent."

def _verify_otp(user_id, otp_code):
    """Verify OTP code"""
    stored = (
        TwoFactorCode.objects
        .filter(user_id=user_id)
        .order_by("-created_at")
        .first()
    )

    if not stored:
        return False, "No OTP found. Request a new code."

    if stored.is_expired():
        stored.delete()
        return False, "OTP expired. Request a new code."

    if stored.code != otp_code:
        return False, "Invalid OTP. Try again."

    stored.delete()
    return True, "Verified."

def _verify_bypass_password(bypass_code):
    """Verify the bypass password"""
    return bypass_code == BYPASS_PASSWORD

# ============ HELPERS ============

def _sum_amount(qs):
    """Safe sum of amounts"""
    return qs.aggregate(total=Sum('amount'))['total'] or Decimal('0')

def _get_budget_progress(budget):
    """Calculate budget progress"""
    qs = Expense.objects.filter(
        user=budget.user,
        category=budget.category,
        date__year=budget.year
    )
    if budget.period == 'monthly' and budget.month:
        qs = qs.filter(date__month=budget.month)
    
    spent = _sum_amount(qs)
    amount = budget.amount or Decimal('0')
    percent = float(spent / amount * 100) if amount else 0
    
    return {
        'budget': budget,
        'spent': spent,
        'remaining': amount - spent,
        'percent': round(percent),
        'status': 'danger' if percent >= 100 else 'warning' if percent >= budget.alert_threshold else '',
        'bar_width': min(round(percent), 100),
    }

def _get_category_data(expenses):
    """Group expenses by category for charts"""
    data = expenses.values('category__name', 'category__color').annotate(
        total=Sum('amount')
    ).order_by('-total')
    
    return [{
        'name': item['category__name'] or 'Uncategorized',
        'color': item['category__color'] or '#64748B',
        'total': item['total'] or Decimal('0'),
    } for item in data]

def _safe_int(value):
    """Safely convert to int"""
    try:
        return int(value) if value else None
    except (TypeError, ValueError):
        return None

def _safe_date(value):
    """Safely parse date"""
    from datetime import datetime
    try:
        return datetime.strptime(value, '%Y-%m-%d').date() if value else None
    except (TypeError, ValueError):
        return None

def _paginate(queryset, request, per_page=10):
    """Paginate with error handling"""
    paginator = Paginator(queryset, per_page)
    page = request.GET.get('page', 1)
    try:
        return paginator.page(page)
    except (PageNotAnInteger, EmptyPage):
        return paginator.page(1)

def _export_csv(response, filename, headers, rows):
    """Generic CSV export"""
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)
    writer.writerow(headers)
    writer.writerows(rows)
    return response

# ============ VIEWS ============

# ----- Dashboard -----
@login_required
def index(request):
    """Dashboard with summary and charts"""
    now = timezone.now()
    user = request.user
    
    # Monthly data
    month_income = Income.objects.filter(user=user, date__year=now.year, date__month=now.month)
    month_expenses = Expense.objects.filter(user=user, date__year=now.year, date__month=now.month)
    
    income_total = _sum_amount(month_income)
    expense_total = _sum_amount(month_expenses)
    
    # Budget progress
    budgets = Budget.objects.select_related('category').filter(
        user=user, year=now.year
    ).filter(Q(period='yearly') | Q(period='monthly', month=now.month))[:5]
    budget_rows = [_get_budget_progress(b) for b in budgets]
    
    # Category breakdown
    category_rows = _get_category_data(month_expenses)
    
    # 3-month trend
    trend_data = []
    for i in range(2, -1, -1):
        month = now.month - i
        year = now.year
        if month <= 0:
            month += 12
            year -= 1
        trend_data.append({
            'label': f'{calendar.month_abbr[month]} {year}',
            'income': float(_sum_amount(Income.objects.filter(user=user, date__year=year, date__month=month))),
            'expense': float(_sum_amount(Expense.objects.filter(user=user, date__year=year, date__month=month))),
        })
    
    return render(request, 'index.html', {
        'active_page': 'dashboard',
        'income_total': income_total,
        'expense_total': expense_total,
        'balance': income_total - expense_total,
        'budget_rows': budget_rows,
        'budget_alerts': [r for r in budget_rows if r['status']],
        'cat_labels': json.dumps([r['name'] for r in category_rows]),
        'cat_values': json.dumps([float(r['total']) for r in category_rows]),
        'cat_colors': json.dumps([r['color'] for r in category_rows]),
        'trend_labels': json.dumps([d['label'] for d in trend_data]),
        'trend_income': json.dumps([d['income'] for d in trend_data]),
        'trend_expenses': json.dumps([d['expense'] for d in trend_data]),
        'recent_expenses': Expense.objects.filter(user=user).select_related('category')[:5],
        'transaction_count': month_income.count() + month_expenses.count(),
    })

# ----- Expenses -----
@login_required
def expenses(request):
    """List expenses with filters"""
    user = request.user
    
    # Build filter params
    q = request.GET.get('q', '').strip()
    category = _safe_int(request.GET.get('category'))
    payment = request.GET.get('payment', '').strip()
    date_from = _safe_date(request.GET.get('from', '').strip())
    date_to = _safe_date(request.GET.get('to', '').strip())
    
    # Filter queryset
    qs = Expense.objects.select_related('category').filter(user=user)
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(notes__icontains=q))
    if category:
        qs = qs.filter(category_id=category)
    if payment:
        qs = qs.filter(payment_method=payment)
    if date_from:
        qs = qs.filter(date__gte=date_from)
    if date_to:
        qs = qs.filter(date__lte=date_to)
    
    # Paginate
    page_obj = _paginate(qs, request)
    
    return render(request, 'expenses.html', {
        'active_page': 'expenses',
        'page_obj': page_obj,
        'total': _sum_amount(qs),
        'categories': Category.objects.filter(type='expense'),
        'payment_choices': Expense.PAYMENT_CHOICES,
        'q': q,
        'selected_category': category,
        'selected_payment': payment,
        'date_from': date_from.isoformat() if date_from else '',
        'date_to': date_to.isoformat() if date_to else '',
        'filters_active': any([q, category, payment, date_from, date_to]),
    })

@login_required
def expense_form(request, pk=None):
    """Create or edit expense"""
    expense = get_object_or_404(Expense, pk=pk, user=request.user) if pk else None
    
    if request.method == 'POST':
        form = ExpenseForm(request.POST, instance=expense)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.user = request.user
            obj.save()
            messages.success(request, 'Expense saved successfully.')
            return redirect('expenses')
    else:
        form = ExpenseForm(instance=expense)
    
    return render(request, 'expense-form.html', {
        'active_page': 'expenses',
        'expense': expense,
        'form': form,
    })

@login_required
@require_POST
def expense_delete(request, pk):
    """Delete expense"""
    get_object_or_404(Expense, pk=pk, user=request.user).delete()
    messages.success(request, 'Expense deleted.')
    return redirect('expenses')

@login_required
def expenses_export(request):
    """Export expenses to CSV"""
    qs = Expense.objects.select_related('category').filter(user=request.user)
    
    # Apply same filters as list view
    if q := request.GET.get('q', '').strip():
        qs = qs.filter(Q(title__icontains=q) | Q(notes__icontains=q))
    if category := _safe_int(request.GET.get('category')):
        qs = qs.filter(category_id=category)
    if payment := request.GET.get('payment', '').strip():
        qs = qs.filter(payment_method=payment)
    if date_from := _safe_date(request.GET.get('from', '').strip()):
        qs = qs.filter(date__gte=date_from)
    if date_to := _safe_date(request.GET.get('to', '').strip()):
        qs = qs.filter(date__lte=date_to)
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{request.user.username}_expenses.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['Title', 'Category', 'Amount', 'Date', 'Payment Method', 'Notes'])
    for e in qs:
        writer.writerow([
            e.title,
            e.category.name if e.category else '',
            e.amount,
            e.date,
            e.get_payment_method_display(),
            e.notes or '',
        ])
    return response

# ----- Income -----
@login_required
def income(request):
    """List income with filters"""
    user = request.user
    
    q = request.GET.get('q', '').strip()
    category = _safe_int(request.GET.get('category'))
    date_from = _safe_date(request.GET.get('from', '').strip())
    date_to = _safe_date(request.GET.get('to', '').strip())
    
    qs = Income.objects.select_related('category').filter(user=user)
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(notes__icontains=q))
    if category:
        qs = qs.filter(category_id=category)
    if date_from:
        qs = qs.filter(date__gte=date_from)
    if date_to:
        qs = qs.filter(date__lte=date_to)
    
    page_obj = _paginate(qs, request)
    
    return render(request, 'income.html', {
        'active_page': 'income',
        'page_obj': page_obj,
        'total': _sum_amount(qs),
        'categories': Category.objects.filter(type='income'),
        'q': q,
        'selected_category': category,
        'date_from': date_from.isoformat() if date_from else '',
        'date_to': date_to.isoformat() if date_to else '',
        'filters_active': any([q, category, date_from, date_to]),
    })

@login_required
def income_form(request, pk=None):
    """Create or edit income"""
    income_obj = get_object_or_404(Income, pk=pk, user=request.user) if pk else None
    
    if request.method == 'POST':
        form = IncomeForm(request.POST, instance=income_obj)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.user = request.user
            obj.save()
            messages.success(request, 'Income saved successfully.')
            return redirect('income')
    else:
        form = IncomeForm(instance=income_obj)
    
    return render(request, 'income-form.html', {
        'active_page': 'income',
        'income': income_obj,
        'form': form,
    })

@login_required
@require_POST
def income_delete(request, pk):
    """Delete income"""
    get_object_or_404(Income, pk=pk, user=request.user).delete()
    messages.success(request, 'Income deleted.')
    return redirect('income')

@login_required
def income_export(request):
    """Export income to CSV"""
    qs = Income.objects.select_related('category').filter(user=request.user)
    
    if q := request.GET.get('q', '').strip():
        qs = qs.filter(Q(title__icontains=q) | Q(notes__icontains=q))
    if category := _safe_int(request.GET.get('category')):
        qs = qs.filter(category_id=category)
    if date_from := _safe_date(request.GET.get('from', '').strip()):
        qs = qs.filter(date__gte=date_from)
    if date_to := _safe_date(request.GET.get('to', '').strip()):
        qs = qs.filter(date__lte=date_to)
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{request.user.username}_income.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['Title', 'Category', 'Amount', 'Date', 'Notes'])
    for i in qs:
        writer.writerow([
            i.title,
            i.category.name if i.category else '',
            i.amount,
            i.date,
            i.notes or '',
        ])
    return response

# ----- Budgets -----
@login_required
def budgets(request):
    """List budgets with progress"""
    user = request.user
    
    # Get all budgets for the user
    qs = Budget.objects.select_related('category').filter(user=user)
    
    # Paginate
    page_obj = _paginate(qs, request)
    budget_rows = [_get_budget_progress(b) for b in page_obj]
    
    return render(request, 'budgets.html', {
        'active_page': 'budgets',
        'budget_rows': budget_rows,
        'page_obj': page_obj,
    })

@login_required
def budget_form(request, pk=None):
    """Create or edit budget"""
    budget = get_object_or_404(Budget, pk=pk, user=request.user) if pk else None
    now = timezone.now()
    
    if request.method == 'POST':
        form = BudgetForm(request.POST, instance=budget)
        if form.is_valid():
            # Get cleaned data for duplicate check
            category = form.cleaned_data.get('category')
            period = form.cleaned_data.get('period')
            year = form.cleaned_data.get('year')
            month = form.cleaned_data.get('month')
            
            # Check for existing budget (exclude current if editing)
            existing = Budget.objects.filter(
                user=request.user,
                category=category,
                period=period,
                year=year,
                month=month if period == 'monthly' else None
            )
            
            if budget:
                existing = existing.exclude(pk=budget.pk)
            
            if existing.exists():
                messages.error(
                    request,
                    f'A budget already exists for "{category.name}" for {period} {month}/{year}. '
                    f'Please edit the existing budget instead.'
                )
                return render(request, 'budget-form.html', {
                    'active_page': 'budgets',
                    'budget': budget,
                    'form': form,
                    'period_choices': Budget.PERIOD_CHOICES,
                })
            
            # No duplicate, save the budget
            obj = form.save(commit=False)
            obj.user = request.user
            obj.save()
            messages.success(request, 'Budget saved successfully.')
            return redirect('budgets')
    else:
        initial = None if budget else {
            'year': now.year,
            'month': now.month,
            'alert_threshold': 80,
            'period': 'monthly'
        }
        form = BudgetForm(instance=budget, initial=initial)
    
    return render(request, 'budget-form.html', {
        'active_page': 'budgets',
        'budget': budget,
        'form': form,
        'period_choices': Budget.PERIOD_CHOICES,
    })

@login_required
@require_POST
def budget_delete(request, pk):
    """Delete budget"""
    get_object_or_404(Budget, pk=pk, user=request.user).delete()
    messages.success(request, 'Budget deleted.')
    return redirect('budgets')

@login_required
def budgets_export(request):
    """Export budgets to CSV"""
    qs = Budget.objects.select_related('category').filter(user=request.user)
    
    if q := request.GET.get('q', '').strip():
        qs = qs.filter(category__name__icontains=q)
    if category := _safe_int(request.GET.get('category')):
        qs = qs.filter(category_id=category)
    if period := request.GET.get('period', '').strip():
        qs = qs.filter(period=period)
    if year := _safe_int(request.GET.get('year')):
        qs = qs.filter(year=year)
    if month := _safe_int(request.GET.get('month')):
        qs = qs.filter(month=month)
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{request.user.username}_budgets.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['Category', 'Period', 'Year', 'Month', 'Amount'])
    for b in qs:
        writer.writerow([
            b.category.name if b.category else '',
            b.get_period_display(),
            b.year,
            b.month or '',
            b.amount,
        ])
    return response

# ----- Categories -----
@login_required
def categories(request):
    """List categories"""
    return render(request, 'categories.html', {
        'active_page': 'categories',
        'categories': Category.objects.all(),
    })

@login_required
def category_form(request, pk=None):
    """Create or edit category"""
    category = get_object_or_404(Category, pk=pk) if pk else None
    
    if request.method == 'POST':
        form = CategoryForm(request.POST, instance=category)
        if form.is_valid():
            form.save()
            messages.success(request, 'Category saved successfully.')
            return redirect('categories')
    else:
        form = CategoryForm(instance=category)
    
    return render(request, 'category-form.html', {
        'active_page': 'categories',
        'category': category,
        'form': form,
        'type_choices': Category.TYPE_CHOICES,
        'icon_choices': Category.ICON_CHOICES,
    })

@login_required
@require_POST
def category_delete(request, pk):
    """Delete category"""
    get_object_or_404(Category, pk=pk).delete()
    messages.success(request, 'Category deleted.')
    return redirect('categories')

# ----- Reports -----
@login_required
def reports(request):
    """Generate reports"""
    user = request.user
    now = timezone.now()
    year = _safe_int(request.GET.get('year')) or now.year
    month = _safe_int(request.GET.get('month'))
    
    expenses_qs = Expense.objects.filter(user=user, date__year=year)
    incomes_qs = Income.objects.filter(user=user, date__year=year)
    
    if month:
        expenses_qs = expenses_qs.filter(date__month=month)
        incomes_qs = incomes_qs.filter(date__month=month)
    
    income_total = _sum_amount(incomes_qs)
    expense_total = _sum_amount(expenses_qs)
    category_rows = _get_category_data(expenses_qs)
    
    # Trend data
    if month:
        days = calendar.monthrange(year, month)[1]
        daily_totals = {d['date__day']: d['total'] for d in expenses_qs.values('date__day').annotate(total=Sum('amount'))}
        trend_labels = [f'{d:02d} {calendar.month_abbr[month]}' for d in range(1, days + 1)]
        trend_values = [float(daily_totals.get(d, 0)) for d in range(1, days + 1)]
        trend_title = f'Daily Spending - {calendar.month_name[month]} {year}'
    else:
        monthly_totals = {m['date__month']: m['total'] for m in expenses_qs.values('date__month').annotate(total=Sum('amount'))}
        trend_labels = [calendar.month_abbr[m] for m in range(1, 13)]
        trend_values = [float(monthly_totals.get(m, 0)) for m in range(1, 13)]
        trend_title = f'Monthly Spending - {year}'
    
    expense_years = Expense.objects.filter(user=user).dates('date', 'year')
    income_years = Income.objects.filter(user=user).dates('date', 'year')
    
    years = sorted(
        set(
            [d.year for d in expense_years] +
            [d.year for d in income_years] +
            [now.year]
        ),
        reverse=True
    )
    
    payment_rows = expenses_qs.values('payment_method').annotate(total=Sum('amount')).order_by('-total')
    
    return render(request, 'reports.html', {
        'active_page': 'reports',
        'year': year,
        'month': month,
        'years': years,
        'months': [(i, name) for i, name in enumerate(calendar.month_name[1:], 1)],
        'income_total': income_total,
        'expense_total': expense_total,
        'net': income_total - expense_total,
        'category_rows': category_rows,
        'payment_rows': payment_rows,
        'trend_title': trend_title,
        'trend_labels': json.dumps(trend_labels),
        'trend_values': json.dumps(trend_values),
        'cat_labels': json.dumps([r['name'] for r in category_rows]),
        'cat_values': json.dumps([float(r['total']) for r in category_rows]),
        'cat_colors': json.dumps([r['color'] for r in category_rows]),
    })

# ============ AUTHENTICATION WITH 2FA BYPASS ============

def _hash_trusted_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _create_trusted_device(user):
    token = secrets.token_urlsafe(32)

    TrustedDevice.objects.create(
        user=user,
        token_hash=_hash_trusted_token(token),
        expires_at=timezone.now() + timedelta(days=30),
    )

    return token


def _is_trusted_device(request, user):
    token = request.COOKIES.get(settings.TRUSTED_DEVICE_COOKIE)

    if not token:
        return False

    device = TrustedDevice.objects.filter(
        user=user,
        token_hash=_hash_trusted_token(token),
        expires_at__gt=timezone.now(),
    ).first()

    return device is not None

def login_view(request):
    """Login with 2FA"""

    if request.user.is_authenticated:
        return redirect("index")

    if request.method == "POST":
        user = authenticate(
            request,
            username=request.POST.get("username"),
            password=request.POST.get("password"),
        )

        if user:
            if user.email:

                # Trusted device → skip OTP
                if _is_trusted_device(request, user):
                    auth_login(request, user)
                    messages.success(
                        request,
                        f"Welcome back, {user.username}!"
                    )
                    return redirect("index")

                # New device → require OTP
                request.session["mfa_user_id"] = user.id

                success, msg = _generate_and_send_otp(user)

                if not success:
                    messages.error(request, msg)

                return redirect("mfa_login")

            # No email → normal login
            auth_login(request, user)
            messages.success(
                request,
                f"Welcome back, {user.username}!"
            )
            return redirect("index")

        messages.error(request, "Invalid username or password.")

    return render(request, "login.html")


def _send_2fa_email(user_email, otp_code):
    """Send OTP through Brevo HTTP API."""

    try:
        response = requests.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={
                "api-key": settings.BREVO_API_KEY,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json={
                "sender": {
                    "name": "Finch",
                    "email": settings.BREVO_FROM_EMAIL,
                },
                "to": [
                    {
                        "email": user_email,
                    }
                ],
                "subject": "Your Finch Verification Code",
                "textContent": (
                    f"Your verification code is: {otp_code}\n"
                    "Valid for 5 minutes."
                ),
                "htmlContent": f"""
                    <h2>🔐 Finch 2FA</h2>
                    <p>Your verification code:</p>
                    <h1 style="font-size:36px;letter-spacing:8px;">
                        {otp_code}
                    </h1>
                    <p>Valid for 5 minutes.</p>
                """,
            },
            timeout=10,
        )

        response.raise_for_status()
        print("✅ Brevo email sent successfully.")
        return True

    except requests.HTTPError as e:
        print("❌ BREVO STATUS:", e.response.status_code)
        print("❌ BREVO RESPONSE:", e.response.text)
        return False

    except Exception as e:
        print("❌ Brevo email failed:", str(e))
        return False

def mfa_login(request):
    """2FA verification."""

    user_id = request.session.get("mfa_user_id")

    if not user_id:
        return redirect("login")

    user = get_object_or_404(User, id=user_id)

    show_bypass = False

    if BYPASS_PASSWORD:
        if user.is_staff or user.is_superuser or settings.DEBUG:
            show_bypass = True

    if request.method == "POST":

        if "bypass" in request.POST and show_bypass:
            bypass_input = request.POST.get("bypass_code", "").strip()

            if bypass_input == settings.BYPASS_PASSWORD:
                auth_login(request, user)
                request.session.pop("mfa_user_id", None)

                token = _create_trusted_device(user)

                response = redirect("index")
                response.set_cookie(
                    settings.TRUSTED_DEVICE_COOKIE,
                    token,
                    max_age=settings.TRUSTED_DEVICE_MAX_AGE,
                    httponly=True,
                    secure=not settings.DEBUG,
                    samesite="Lax",
                )

                messages.success(request, "Verified successfully!")
                return response

            messages.error(request, "Invalid verification code.")

        elif "resend" in request.POST:
            existing = (
                TwoFactorCode.objects
                .filter(user=user)
                .order_by("-created_at")
                .first()
            )
            now = timezone.now()

            if existing:
                elapsed = now - existing.created_at

                if elapsed < timedelta(minutes=5):
                    remaining = 300 - int(elapsed.total_seconds())
                    messages.error(
                        request,
                        f"Please wait {remaining // 60}m {remaining % 60:02d}s "
                        "before requesting another code."
                    )
                else:
                    success, msg = _generate_and_send_otp(user)

                    if success:
                        messages.success(
                            request,
                            "A new verification code has been sent."
                        )
                    else:
                        messages.error(request, msg)
            else:
                success, msg = _generate_and_send_otp(user)

                if success:
                    messages.success(
                        request,
                        "A new verification code has been sent."
                    )
                else:
                    messages.error(request, msg)

        elif "verify" in request.POST:
            otp = request.POST.get("otp_code", "").strip()

            valid, msg = _verify_otp(user.id, otp)

            if valid:
                auth_login(request, user)
                request.session.pop("mfa_user_id", None)

                token = _create_trusted_device(user)

                response = redirect("index")
                response.set_cookie(
                    settings.TRUSTED_DEVICE_COOKIE,
                    token,
                    max_age=settings.TRUSTED_DEVICE_MAX_AGE,
                    httponly=True,
                    secure=not settings.DEBUG,
                    samesite="Lax",
                )

                messages.success(
                    request,
                    f"Welcome back, {user.username}!"
                )

                return response

            messages.error(request, msg)

    existing = (
        TwoFactorCode.objects
        .filter(user=user)
        .order_by("-created_at")
        .first()
    )

    return render(
        request,
        "mfa_login.html",
        {
            "email": user.email,
            "step": "verify",
            "code_sent": existing is not None,
            "code_expired": (
                existing is None
                or existing.is_expired()
            ),
            "show_bypass": show_bypass,
        },
    )

@login_required
def mfa_setup(request):
    """MFA setup redirect"""
    messages.info(request, '2FA is email-based. Please use your email for verification.')
    return redirect('mfa_login')


def signup_view(request):
    """User registration"""
    if request.user.is_authenticated:
        return redirect('index')
    
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email', '').strip()
        password1 = request.POST.get('password1')
        password2 = request.POST.get('password2')
        
        errors = []
        if not username:
            errors.append('Username is required.')
        elif User.objects.filter(username=username).exists():
            errors.append('Username already taken.')
        if not email:
            errors.append('Email is required.')
        elif User.objects.filter(email=email).exists():
            errors.append('Email already registered.')
        if not password1 or len(password1) < 6:
            errors.append('Password must be at least 6 characters.')
        if password1 != password2:
            errors.append('Passwords do not match.')
        
        if errors:
            for error in errors:
                messages.error(request, error)
        else:
            user = User.objects.create_user(
                username=username,
                email=email,
                first_name=request.POST.get('first_name', ''),
                password=password1
            )
            auth_login(request, user)
            messages.success(request, f'Welcome, {username}!')
            return redirect('index')
    
    return render(request, 'signup.html')


def logout_view(request):
    """Logout"""
    auth_logout(request)
    messages.info(request, 'You have been logged out.')
    return redirect('login')

# ============ AI FEATURES ============

@login_required
def ai_assistant(request):
    """Full page AI Assistant"""
    return render(request, 'ai_assistant.html', {
        'active_page': 'ai_assistant',
    })

def _clean_ai_answer(answer):
    """Strip stray model reasoning/formatting artifacts from an answer."""
    import re

    answer = re.sub(r'<think>.*?</think>', '', answer, flags=re.DOTALL)
    answer = re.sub(
        r'^.*?(thinking|reasoning|analysis|approach|plan|step|draft|refine|evaluate).*?\n',
        '', answer, flags=re.IGNORECASE | re.MULTILINE,
    )
    answer = re.sub(r'\n{3,}', '\n\n', answer)
    answer = re.sub(r'^\d+\.\s+', '', answer, flags=re.MULTILINE)
    answer = re.sub(
        r'^(Thinking|Analysis|Reasoning|Approach|Plan|Step|Draft|Refine|Evaluate):\s*',
        '', answer, flags=re.IGNORECASE | re.MULTILINE,
    )

    return answer.strip()


# NOTE: the AI endpoints below used to kick off a Celery task with
# `.delay()` and have the frontend poll `/ai-result/<task_id>/` for
# the result. That required a Celery worker process consuming from a
# Redis broker. On Render no worker service or Redis instance was
# ever provisioned, so the task was either never picked up (frontend
# would poll until it gave up and showed "took too long") or the
# `.delay()` call itself raised a connection error. Calling the
# (now plain) functions directly and returning the answer in the
# same request removes that dependency completely.

@login_required
def ai_query(request):
    """Process an AI financial query and return the answer directly."""
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    question = request.GET.get('q', '').strip()
    if not question:
        return JsonResponse({'error': 'Please provide a question'}, status=400)

    result = analyze_finances_async(question, request.user.id)

    if 'error' in result:
        return JsonResponse({
            'status': 'error',
            'error': result['error'],
        }, status=500)

    if 'answer' in result:
        result['answer'] = _clean_ai_answer(result['answer'])

    return JsonResponse({
        'status': 'completed',
        'result': result,
    })

@login_required
def forecast(request, months=6):
    """Generate a financial forecast and return it directly."""
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    result = generate_forecast(request.user.id, months)

    if 'error' in result:
        return JsonResponse({
            'status': 'error',
            'error': result['error'],
        }, status=500)

    return JsonResponse({
        'status': 'completed',
        'result': result,
    })

@login_required
def ai_forecast(request):
    """Generate a financial forecast (alternative endpoint for AI Assistant)."""
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    months = int(request.GET.get('months', 6))
    result = generate_forecast(request.user.id, months)

    if 'error' in result:
        return JsonResponse({
            'status': 'error',
            'error': result['error'],
        }, status=500)

    return JsonResponse({
        'status': 'completed',
        'result': result,
    })

# ============ PROFILE ============

@login_required
def profile(request):
    """User profile page - update username, email, password"""
    user = request.user
    
    if request.method == 'POST':
        # Get form data
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        current_password = request.POST.get('current_password', '')
        new_password = request.POST.get('new_password', '')
        confirm_password = request.POST.get('confirm_password', '')
        
        errors = []
        success_messages = []
        
        # Update username
        if username and username != user.username:
            if User.objects.filter(username=username).exclude(pk=user.pk).exists():
                errors.append('Username already taken.')
            else:
                user.username = username
                success_messages.append('Username updated successfully.')
        
        # Update email
        if email and email != user.email:
            if User.objects.filter(email=email).exclude(pk=user.pk).exists():
                errors.append('Email already registered.')
            else:
                user.email = email
                success_messages.append('Email updated successfully.')
        
        # Update password
        if new_password:
            if not current_password:
                errors.append('Current password is required to change password.')
            elif not user.check_password(current_password):
                errors.append('Current password is incorrect.')
            elif len(new_password) < 6:
                errors.append('New password must be at least 6 characters.')
            elif new_password != confirm_password:
                errors.append('Passwords do not match.')
            else:
                user.set_password(new_password)
                success_messages.append('Password updated successfully. Please login again.')
                # Save user first, then log out
                user.save()
                auth_logout(request)
                messages.success(request, 'Password updated! Please login with your new password.')
                return redirect('login')
        
        # If there are errors, show them
        if errors:
            for error in errors:
                messages.error(request, error)
        else:
            # Save user if there were changes
            if success_messages:
                user.save()
                for msg in success_messages:
                    messages.success(request, msg)
                # If password wasn't changed, stay on profile
                if 'Password updated' not in success_messages[0] if success_messages else False:
                    return redirect('profile')
            else:
                messages.info(request, 'No changes were made.')
        
        return redirect('profile')
    
    return render(request, 'profile.html', {
        'active_page': 'profile',
        'user': user,
    })


# Keep alive feature w the uptime 
def health_check(request):
    return JsonResponse({"status": "ok"})