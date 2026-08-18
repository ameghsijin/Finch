from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.db.models import Sum, Q
from django.utils import timezone
from django.core.paginator import Paginator
from decimal import Decimal
import calendar
import json
import random
import string
from datetime import datetime, timedelta
from .models import Category, Expense, Income, Budget
from .forms import CategoryForm, ExpenseForm, IncomeForm, BudgetForm
# from .exports import export_expenses, export_income, export_budgets
from django.http import JsonResponse, HttpResponse
import csv
import io
from celery.result import AsyncResult
from .tasks import analyze_finances_async, generate_forecast

# ============ 2FA STORAGE ============
_2fa_codes = {}  


def _generate_otp():
    """Generate a 6-digit OTP code"""
    return ''.join(random.choices(string.digits, k=6))


def _send_2fa_email(user_email, otp_code):
    """
    Send OTP code via Zoho Mail
    """
    from django.core.mail import send_mail
    from django.conf import settings
    
    subject = 'Your 2FA Verification Code - SpendWise'
    
    html_message = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background: #4F46E5; color: white; padding: 20px; text-align: center; border-radius: 8px 8px 0 0; }}
            .code {{ font-size: 36px; font-weight: bold; color: #4F46E5; padding: 30px; text-align: center; letter-spacing: 8px; background: #f8f9fa; border-radius: 8px; margin: 20px 0; }}
            .footer {{ margin-top: 30px; padding-top: 20px; border-top: 1px solid #eee; font-size: 12px; color: #666; text-align: center; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2>🔐 SpendWise 2FA Verification</h2>
            </div>
            
            <p>Hello,</p>
            <p>You requested a verification code to log in to your SpendWise account.</p>
            
            <div class="code">{otp_code}</div>
            
            <p><strong>⚠️ This code will expire in 5 minutes.</strong></p>
            <p>If you didn't request this code, please ignore this email.</p>
            
            <div class="footer">
                <p>Best regards,<br><strong>SpendWise Team</strong></p>
                <p><small>This is an automated message, please do not reply.</small></p>
            </div>
        </div>
    </body>
    </html>
    """
    
    plain_message = f"""
SpendWise 2FA Verification

Your verification code is: {otp_code}

This code will expire in 5 minutes.

If you didn't request this, please ignore this email.

Best regards,
SpendWise Team
"""
    
    try:
        send_mail(
            subject,
            plain_message,
            settings.DEFAULT_FROM_EMAIL,
            [user_email],
            fail_silently=False,
            html_message=html_message,
        )
        print(f"✅ 2FA email sent successfully to {user_email}")
        return True
    except Exception as e:
        print(f"❌ Failed to send email to {user_email}: {e}")
        # Fallback: print code to console
        print(f"\n{'='*50}")
        print(f"2FA CODE for {user_email}: {otp_code}")
        print(f"{'='*50}\n")
        return False

# Add to views.py temporarily
def test_email_template(request):
    from django.template.loader import render_to_string
    
    try:
        html = render_to_string('email/2fa_code.html', {'otp_code': '123456'})
        return HttpResponse(html)
    except Exception as e:
        return HttpResponse(f"Error: {e}")


def export_expenses(qs, username):
    """Export expenses queryset to CSV response"""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{username}_expenses.csv"'

    writer = csv.writer(response)
    writer.writerow(['ID', 'User', 'Title', 'Amount', 'Category', 'Date', 'Payment Method', 'Notes'])
    for e in qs:
        writer.writerow([
            e.pk,
            getattr(e.user, 'username', ''),
            e.title,
            f"{e.amount}",
            e.category.name if e.category else '',
            e.date.isoformat() if getattr(e, 'date', None) else '',
            e.payment_method,
            e.notes,
        ])
    return response


def export_income(qs, username):
    """Export incomes queryset to CSV response"""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{username}_income.csv"'

    writer = csv.writer(response)
    writer.writerow(['ID', 'User', 'Title', 'Amount', 'Category', 'Date', 'Notes'])
    for i in qs:
        writer.writerow([
            i.pk,
            getattr(i.user, 'username', ''),
            i.title,
            f"{i.amount}",
            i.category.name if i.category else '',
            i.date.isoformat() if getattr(i, 'date', None) else '',
            i.notes,
        ])
    return response


def export_budgets(budget_rows, username):
    """Export budgets (either queryset or prepared rows) to CSV"""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{username}_budgets.csv"'

    writer = csv.writer(response)
    writer.writerow(['Category', 'Period', 'Year', 'Month', 'Amount', 'Spent', 'Remaining', 'Percent', 'Status'])

    # budget_rows may be a queryset of Budget or a list of dicts from _budget_progress
    if hasattr(budget_rows, 'select_related') or hasattr(budget_rows, 'filter'):
        for b in budget_rows:
            writer.writerow([
                getattr(b.category, 'name', ''),
                b.period,
                b.year,
                b.month or '',
                f"{b.amount}",
                '',
                '',
                '',
                '',
            ])
    else:
        for row in budget_rows:
            b = row.get('budget') if isinstance(row, dict) else None
            writer.writerow([
                row.get('budget').category.name if b else row.get('category', ''),
                row.get('budget').period if b else row.get('period', ''),
                row.get('budget').year if b else row.get('year', ''),
                row.get('budget').month if b else row.get('month', ''),
                f"{row.get('budget').amount if b else row.get('amount', '')}",
                f"{row.get('spent', '')}",
                f"{row.get('remaining', '')}",
                f"{row.get('percent', '')}",
                row.get('status', ''),
            ])

    return response


def _generate_and_send_otp(user):
    """Generate OTP and send to user's email"""
    otp_code = _generate_otp()
    expiry = datetime.now() + timedelta(minutes=5)
    
    _2fa_codes[user.id] = {
        'code': otp_code,
        'expires': expiry,
        'email': user.email
    }
    
    # Send email
    success = _send_2fa_email(user.email, otp_code)
    
    # For development, if email fails, we still return the code for testing
    return otp_code


def _verify_otp(user_id, otp_code):
    """Verify OTP code for user"""
    if user_id not in _2fa_codes:
        return False, "No OTP code found. Please request a new code."
    
    stored = _2fa_codes[user_id]
    
    if datetime.now() > stored['expires']:
        del _2fa_codes[user_id]
        return False, "OTP code has expired. Please request a new code."
    
    if stored['code'] != otp_code:
        return False, "Invalid OTP code. Please try again."
    
    # Clean up after successful verification
    del _2fa_codes[user_id]
    return True, "OTP verified successfully."


# ============ HELPER FUNCTIONS (Reusable) ============

def _sum(qs):
    """Sum amounts from queryset"""
    return qs.aggregate(total=Sum('amount'))['total'] or Decimal('0')


def _budget_progress(budget):
    """Calculate budget spending progress with status"""
    qs = Expense.objects.filter(
        user=budget.user, 
        category=budget.category, 
        date__year=budget.year
    )
    if budget.period == 'monthly' and budget.month:
        qs = qs.filter(date__month=budget.month)
    
    spent = _sum(qs)
    amount = budget.amount or Decimal('0')
    percent = float(spent / amount * 100) if amount else 0
    
    # Status: danger if over, warning if near limit
    status = 'danger' if percent >= 100 else 'warning' if percent >= budget.alert_threshold else ''
    
    return {
        'budget': budget,
        'spent': spent,
        'remaining': amount - spent,
        'percent': round(percent),
        'bar_width': min(round(percent), 100),
        'status': status,
    }


def _category_rows(expenses):
    """Group expenses by category for charts"""
    rows = expenses.values('category__name', 'category__color').annotate(
        total=Sum('amount')
    ).order_by('-total')
    
    return [{
        'name': row['category__name'] or 'Uncategorized',
        'color': row['category__color'] or '#64748B',
        'total': row['total'] or Decimal('0'),
    } for row in rows]


def _save_form(request, form, message, redirect_name, set_user=False):
    """Handle form save with optional user assignment"""
    if request.method == 'POST' and form.is_valid():
        obj = form.save(commit=False)
        if set_user:
            obj.user = request.user
        obj.save()
        messages.success(request, message)
        return redirect(redirect_name)
    return None


def _get_int(value):
    """Safely convert to int"""
    try:
        return int(value) if value else None
    except (TypeError, ValueError):
        return None


def _get_date(value):
    """Safely parse date string"""
    from datetime import datetime
    try:
        return datetime.strptime(value, '%Y-%m-%d').date() if value else None
    except (TypeError, ValueError):
        return None


def _filters_active(*values):
    """Check if any filter is active"""
    return any(bool(v) for v in values)


def _paginate(queryset, request, per_page=10):
    """Paginate queryset with error handling"""
    paginator = Paginator(queryset, per_page)
    page = request.GET.get('page')
    try:
        return paginator.page(page)
    except:
        return paginator.page(1)


# ============ FILTER QUERYSETS ============

def _expense_queryset(user, params):
    """Build filtered expense queryset"""
    qs = Expense.objects.select_related('category').filter(user=user)
    
    if params.get('q'):
        qs = qs.filter(Q(title__icontains=params['q']) | Q(notes__icontains=params['q']))
    if params.get('category'):
        qs = qs.filter(category_id=params['category'])
    if params.get('payment'):
        qs = qs.filter(payment_method=params['payment'])
    if params.get('from'):
        qs = qs.filter(date__gte=params['from'])
    if params.get('to'):
        qs = qs.filter(date__lte=params['to'])
    return qs


def _income_queryset(user, params):
    """Build filtered income queryset"""
    qs = Income.objects.select_related('category').filter(user=user)
    
    if params.get('q'):
        qs = qs.filter(Q(title__icontains=params['q']) | Q(notes__icontains=params['q']))
    if params.get('category'):
        qs = qs.filter(category_id=params['category'])
    if params.get('from'):
        qs = qs.filter(date__gte=params['from'])
    if params.get('to'):
        qs = qs.filter(date__lte=params['to'])
    return qs


def _budget_queryset(user, params):
    """Build filtered budget queryset"""
    qs = Budget.objects.select_related('category').filter(user=user)
    
    if params.get('q'):
        qs = qs.filter(category__name__icontains=params['q'])
    if params.get('category'):
        qs = qs.filter(category_id=params['category'])
    if params.get('period'):
        qs = qs.filter(period=params['period'])
    if params.get('year'):
        qs = qs.filter(year=params['year'])
    if params.get('month'):
        qs = qs.filter(month=params['month'])
    return qs


# ============ VIEWS ============

# ----- Dashboard (Home) -----
@login_required
def index(request):
    """Dashboard - shows summary, charts, and recent data"""
    now = timezone.now()
    
    # Get current month's income/expenses
    month_income = Income.objects.filter(user=request.user, date__year=now.year, date__month=now.month)
    month_expenses = Expense.objects.filter(user=request.user, date__year=now.year, date__month=now.month)
    income_total = _sum(month_income)
    expense_total = _sum(month_expenses)
    
    # Budget progress (top 5)
    budgets = Budget.objects.select_related('category').filter(
        user=request.user, 
        year=now.year
    ).filter(Q(period='yearly') | Q(period='monthly', month=now.month))[:5]
    budget_rows = [_budget_progress(b) for b in budgets]
    
    # Category breakdown for pie chart
    category_rows = _category_rows(month_expenses)
    
    # 3-month trend for line chart
    trend_labels, trend_income, trend_expenses = [], [], []
    for offset in range(2, -1, -1):
        month = now.month - offset
        year = now.year
        if month <= 0:
            month += 12
            year -= 1
        trend_labels.append(f'{calendar.month_abbr[month]} {year}')
        trend_income.append(float(_sum(Income.objects.filter(user=request.user, date__year=year, date__month=month))))
        trend_expenses.append(float(_sum(Expense.objects.filter(user=request.user, date__year=year, date__month=month))))
    
    return render(request, 'index.html', {
        'active_page': 'dashboard',
        'income_total': income_total,
        'expense_total': expense_total,
        'balance': income_total - expense_total,
        'budget_rows': budget_rows,
        'budget_alerts': [row for row in budget_rows if row['status']],
        # Chart data (JSON serialized)
        'cat_labels': json.dumps([r['name'] for r in category_rows]),
        'cat_values': json.dumps([float(r['total']) for r in category_rows]),
        'cat_colors': json.dumps([r['color'] for r in category_rows]),
        'trend_labels': json.dumps(trend_labels),
        'trend_income': json.dumps(trend_income),
        'trend_expenses': json.dumps(trend_expenses),
    })


# ----- Expenses CRUD -----
@login_required
def expenses(request):
    """List expenses with filters and pagination"""
    params = {
        'q': request.GET.get('q', '').strip(),
        'category': _get_int(request.GET.get('category')),
        'payment': request.GET.get('payment', '').strip(),
        'from': _get_date(request.GET.get('from', '').strip()),
        'to': _get_date(request.GET.get('to', '').strip()),
    }
    
    expense_list = _expense_queryset(request.user, params)
    
    # ✅ CHANGE THIS: Use Paginator directly instead of _paginate
    paginator = Paginator(expense_list, 10)  # 10 per page
    page = request.GET.get('page')
    try:
        expenses_page = paginator.page(page)
    except:
        expenses_page = paginator.page(1)
    
    return render(request, 'expenses.html', {
        'active_page': 'expenses',
        'expenses': expenses_page,        # ← Paginated objects
        'paginator': paginator,           # ← ADD THIS (for template)
        'total': _sum(expense_list),
        'categories': Category.objects.filter(type='expense'),
        'payment_choices': Expense.PAYMENT_CHOICES,
        'q': params['q'],
        'selected_category': params['category'],
        'selected_payment': params['payment'],
        'date_from': params['from'].isoformat() if params['from'] else '',
        'date_to': params['to'].isoformat() if params['to'] else '',
        'filters_active': _filters_active(*params.values()),
    })


@login_required
def expense_form(request, pk=None):
    """Create or edit expense"""
    expense = get_object_or_404(Expense, pk=pk, user=request.user) if pk else None
    form = ExpenseForm(request.POST or None, instance=expense)
    return _save_form(request, form, 'Expense saved.', 'expenses', set_user=True) or render(request, 'expense-form.html', {
        'active_page': 'expenses',
        'expense': expense,
        'categories': form.fields['category'].queryset,
        'payment_choices': Expense.PAYMENT_CHOICES,
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
    """Export filtered expenses to CSV"""
    params = {
        'q': request.GET.get('q', '').strip(),
        'category': _get_int(request.GET.get('category')),
        'payment': request.GET.get('payment', '').strip(),
        'from': _get_date(request.GET.get('from', '').strip()),
        'to': _get_date(request.GET.get('to', '').strip()),
    }
    return export_expenses(_expense_queryset(request.user, params), request.user.username)


# ----- Income CRUD -----
@login_required
def income(request):
    """List income with filters and pagination"""
    params = {
        'q': request.GET.get('q', '').strip(),
        'category': _get_int(request.GET.get('category')),
        'from': _get_date(request.GET.get('from', '').strip()),
        'to': _get_date(request.GET.get('to', '').strip()),
    }
    
    income_list = _income_queryset(request.user, params)
    
    # ✅ Add paginator
    paginator = Paginator(income_list, 10)
    page = request.GET.get('page')
    try:
        incomes_page = paginator.page(page)
    except:
        incomes_page = paginator.page(1)
    
    return render(request, 'income.html', {
        'active_page': 'income',
        'incomes': incomes_page,          # ← Paginated objects
        'paginator': paginator,           # ← ADD THIS
        'total': _sum(income_list),
        'categories': Category.objects.filter(type='income'),
        'q': params['q'],
        'selected_category': params['category'],
        'date_from': params['from'].isoformat() if params['from'] else '',
        'date_to': params['to'].isoformat() if params['to'] else '',
        'filters_active': _filters_active(*params.values()),
    })


@login_required
def income_form(request, pk=None):
    """Create or edit income"""
    income = get_object_or_404(Income, pk=pk, user=request.user) if pk else None
    form = IncomeForm(request.POST or None, instance=income)
    return _save_form(request, form, 'Income saved.', 'income', set_user=True) or render(request, 'income-form.html', {
        'active_page': 'income',
        'income': income,
        'categories': form.fields['category'].queryset,
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
    """Export filtered income to CSV"""
    params = {
        'q': request.GET.get('q', '').strip(),
        'category': _get_int(request.GET.get('category')),
        'from': _get_date(request.GET.get('from', '').strip()),
        'to': _get_date(request.GET.get('to', '').strip()),
    }
    return export_income(_income_queryset(request.user, params), request.user.username)


# ----- Budgets CRUD -----
@login_required
def budgets(request):
    """List budgets with progress and pagination"""
    params = {
        'q': request.GET.get('q', '').strip(),
        'category': _get_int(request.GET.get('category')),
        'period': request.GET.get('period', '').strip(),
        'year': _get_int(request.GET.get('year')),
        'month': _get_int(request.GET.get('month')),
    }
    
    budget_qs = _budget_queryset(request.user, params)
    budgets_page = _paginate(budget_qs, request)
    budget_rows = [_budget_progress(b) for b in budgets_page]
    
    # Get available years for filter dropdown
    now = timezone.now()
    years = sorted(
        set(Budget.objects.filter(user=request.user).values_list('year', flat=True)) | {now.year},
        reverse=True,
    )
    
    return render(request, 'budgets.html', {
        'active_page': 'budgets',
        'budget_rows': budget_rows,
        'categories': Category.objects.filter(type='expense'),
        'period_choices': Budget.PERIOD_CHOICES,
        'years': years,
        'months': list(enumerate(calendar.month_name[1:], start=1)),
        'q': params['q'],
        'selected_category': params['category'],
        'selected_period': params['period'],
        'selected_year': params['year'],
        'selected_month': params['month'],
        'filters_active': _filters_active(*params.values()),
    })


@login_required
def budget_form(request, pk=None):
    """Create or edit budget"""
    budget = get_object_or_404(Budget, pk=pk, user=request.user) if pk else None
    now = timezone.now()
    
    form = BudgetForm(
        request.POST or None,
        instance=budget,
        initial=None if budget else {
            'year': now.year,
            'month': now.month,
            'alert_threshold': 80,
            'period': 'monthly',
        },
    )
    
    return _save_form(request, form, 'Budget saved.', 'budgets', set_user=True) or render(request, 'budget-form.html', {
        'active_page': 'budgets',
        'budget': budget,
        'form': form,
        'categories': form.fields['category'].queryset,
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
    """Export budgets with progress to CSV"""
    params = {
        'q': request.GET.get('q', '').strip(),
        'category': _get_int(request.GET.get('category')),
        'period': request.GET.get('period', '').strip(),
        'year': _get_int(request.GET.get('year')),
        'month': _get_int(request.GET.get('month')),
    }
    budget_rows = [_budget_progress(b) for b in _budget_queryset(request.user, params)]
    return export_budgets(budget_rows, request.user.username)


# ----- Categories -----
@login_required
def categories(request):
    """List all categories"""
    return render(request, 'categories.html', {
        'active_page': 'categories',
        'categories': Category.objects.all(),
    })


@login_required
def category_form(request, pk=None):
    """Create or edit category"""
    category = get_object_or_404(Category, pk=pk) if pk else None
    form = CategoryForm(request.POST or None, instance=category)
    return _save_form(request, form, 'Category saved.', 'categories') or render(request, 'category-form.html', {
        'active_page': 'categories',
        'category': category,
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
    """Generate reports with year/month filters"""
    now = timezone.now()
    year = _get_int(request.GET.get('year')) or now.year
    month = _get_int(request.GET.get('month'))  # None means "all months"
    
    # Build querysets
    expenses_qs = Expense.objects.filter(user=request.user, date__year=year)
    incomes_qs = Income.objects.filter(user=request.user, date__year=year)
    if month:
        expenses_qs = expenses_qs.filter(date__month=month)
        incomes_qs = incomes_qs.filter(date__month=month)
    
    income_total = _sum(incomes_qs)
    expense_total = _sum(expenses_qs)
    category_rows = _category_rows(expenses_qs)
    
    # Trend data (daily or monthly)
    if month:
        days = calendar.monthrange(year, month)[1]
        day_totals = {r['date__day']: r['total'] for r in expenses_qs.values('date__day').annotate(total=Sum('amount'))}
        trend_labels = [f'{d:02d} {calendar.month_abbr[month]}' for d in range(1, days + 1)]
        trend_values = [float(day_totals.get(d, 0)) for d in range(1, days + 1)]
        trend_title = 'Daily spend'
    else:
        month_totals = {r['date__month']: r['total'] for r in expenses_qs.values('date__month').annotate(total=Sum('amount'))}
        trend_labels = [calendar.month_abbr[m] for m in range(1, 13)]
        trend_values = [float(month_totals.get(m, 0)) for m in range(1, 13)]
        trend_title = 'Monthly spend'
    
    # Available years for filter dropdown
    years = sorted(
        {d.year for d in Expense.objects.filter(user=request.user).dates('date', 'year')} |
        {d.year for d in Income.objects.filter(user=request.user).dates('date', 'year')} |
        {now.year},
        reverse=True,
    )
    
    return render(request, 'reports.html', {
        'active_page': 'reports',
        'year': year,
        'month': month,
        'years': years,
        'months': list(enumerate(calendar.month_name[1:], start=1)),
        'income_total': income_total,
        'expense_total': expense_total,
        'net': income_total - expense_total,
        'category_rows': category_rows,
        'payment_rows': expenses_qs.values('payment_method').annotate(total=Sum('amount')).order_by('-total'),
        'trend_title': trend_title,
        'trend_labels': json.dumps(trend_labels),
        'trend_values': json.dumps(trend_values),
        'cat_labels': json.dumps([r['name'] for r in category_rows]),
        'cat_values': json.dumps([float(r['total']) for r in category_rows]),
        'cat_colors': json.dumps([r['color'] for r in category_rows]),
    })


# ============ 2FA VIEWS ============

def mfa_login(request):
    """
    Email-based 2FA verification step after password login.
    Users receive a 6-digit OTP via email.
    """
    user_id = request.session.get('mfa_user_id')
    if not user_id:
        return redirect('login')
    
    user = get_object_or_404(User, id=user_id)
    
    # Check if user has an email address
    if not user.email:
        messages.error(request, 'No email address associated with your account. Please contact support.')
        return redirect('login')
    
    if request.method == 'POST':
        if 'send_code' in request.POST:
            # Generate and send new OTP
            otp_code = _generate_and_send_otp(user)
            messages.info(request, f'Verification code sent to {user.email}. For development, check terminal for the code.')
            
            return render(request, 'mfa_login.html', {
                'email': user.email,
                'step': 'verify',
                'code_sent': True,
                'user_id': user.id,
            })
        
        elif 'verify' in request.POST:
            otp_code = request.POST.get('otp_code', '').strip()
            
            if not otp_code or len(otp_code) != 6:
                messages.error(request, 'Please enter a valid 6-digit code.')
                return render(request, 'mfa_login.html', {
                    'email': user.email,
                    'step': 'verify',
                    'code_sent': True,
                })
            
            is_valid, message = _verify_otp(user.id, otp_code)
            
            if is_valid:
                # Login successful
                auth_login(request, user)
                request.session.pop('mfa_user_id', None)
                messages.success(request, f'Welcome back, {user.username}!')
                return redirect('index')
            else:
                messages.error(request, message)
                
                # Check if code still exists (not expired)
                if user.id not in _2fa_codes:
                    # Code was consumed or expired, allow resend
                    return render(request, 'mfa_login.html', {
                        'email': user.email,
                        'step': 'verify',
                        'code_sent': False,
                        'code_expired': True,
                    })
                
                return render(request, 'mfa_login.html', {
                    'email': user.email,
                    'step': 'verify',
                    'code_sent': True,
                })
    
    # GET request - initial load
    # Auto-send code on page load
    otp_code = _generate_and_send_otp(user)
    messages.info(request, f'Verification code sent to {user.email}. For development, check terminal for the code.')
    
    return render(request, 'mfa_login.html', {
        'email': user.email,
        'step': 'verify',
        'code_sent': True,
    })


# ----- Authentication -----
def login_view(request):
    """Login with email-based 2FA support"""
    if request.user.is_authenticated:
        return redirect('index')
    
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        # Check if user has 2FA enabled (by checking if email exists)
        user = authenticate(request, username=username, password=password)
        
        if user:
            # If user has email, use 2FA
            if user.email:
                request.session['mfa_user_id'] = user.id
                return redirect('mfa_login')
            else:
                # No email set - direct login
                auth_login(request, user)
                messages.success(request, f'Welcome back, {user.username}!')
                return redirect('index')
        else:
            messages.error(request, 'Invalid username or password.')
    
    return render(request, 'login.html')


def signup_view(request):
    """User registration with email requirement for 2FA"""
    if request.user.is_authenticated:
        return redirect('index')
    
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email', '').strip()
        password1 = request.POST.get('password1')
        password2 = request.POST.get('password2')
        
        # Validation
        if not username:
            messages.error(request, 'Username is required.')
        elif User.objects.filter(username=username).exists():
            messages.error(request, 'Username already taken.')
        elif not email:
            messages.error(request, 'Email is required for 2FA verification.')
        elif User.objects.filter(email=email).exists():
            messages.error(request, 'Email already registered.')
        elif password1 != password2:
            messages.error(request, 'Passwords do not match.')
        elif len(password1 or '') < 6:
            messages.error(request, 'Password must be at least 6 characters.')
        else:
            # Create user
            user = User.objects.create_user(
                username=username,
                email=email,
                first_name=request.POST.get('first_name', ''),
                password=password1,
            )
            
            # Log in directly (will trigger 2FA if email is set)
            auth_login(request, user)
            messages.success(request, f'Account created successfully! Welcome, {username}!')
            
            # Since user has email, they'll be prompted for 2FA on next login
            return redirect('index')
    
    return render(request, 'signup.html')


def logout_view(request):
    """Logout user"""
    auth_logout(request)
    messages.info(request, 'You have been logged out.')
    return redirect('login')

    # Add this to your views.py (near the other views)
def mfa_setup(request):
    """Redirect to mfa_login since we're using email-based 2FA"""
    messages.info(request, '2FA is now email-based. Please use your email for verification.')
    return redirect('mfa_login')

@login_required
def ai_query(request):
    """Handle natural language queries about finances"""
    if request.method == 'GET':
        question = request.GET.get('q', '').strip()
        if not question:
            return JsonResponse({'error': 'Please provide a question'}, status=400)
        
        # Start background task
        task = analyze_finances_async.delay(question, request.user.id)
        
        return JsonResponse({
            'task_id': task.id,
            'status': 'processing',
            'message': 'Analyzing your financial data...'
        })
    
    return JsonResponse({'error': 'Method not allowed'}, status=405)

@login_required
def get_ai_result(request, task_id):
    """Check the status of an AI query"""
    task = AsyncResult(task_id)
    
    if task.ready():
        result = task.result
        if 'error' in result:
            return JsonResponse({'status': 'error', 'error': result['error']}, status=500)
        return JsonResponse({
            'status': 'completed',
            'result': result
        })
    else:
        return JsonResponse({
            'status': 'processing',
            'message': 'Still working on your query...'
        })

@login_required
def forecast(request, months=6):
    """Generate financial forecast"""
    if request.method == 'GET':
        # Start background task
        task = generate_forecast.delay(request.user.id, months)
        
        return JsonResponse({
            'task_id': task.id,
            'status': 'processing',
            'message': f'Generating {months}-month forecast...'
        })
    
    return JsonResponse({'error': 'Method not allowed'}, status=405)