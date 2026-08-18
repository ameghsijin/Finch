import json
import re
from celery import shared_task
from django_ai_lens import run_ai_query
from django.contrib.auth.models import User
from .models import Expense, Income, Budget
from datetime import datetime

@shared_task
def analyze_finances_async(question, user_id):
    """Run AI query on user's financial data with better error handling"""
    try:
        user = User.objects.get(id=user_id)
        
        # Get some user data to provide context
        recent_expenses = Expense.objects.filter(user=user)[:10]
        recent_incomes = Income.objects.filter(user=user)[:5]
        
        # Build a simple summary of their data
        expense_summary = "\n".join([
            f"- {e.date}: ${float(e.amount):.2f} - {e.title}" 
            for e in recent_expenses
        ])
        income_summary = "\n".join([
            f"- {i.date}: ${float(i.amount):.2f} - {i.title}" 
            for i in recent_incomes
        ])
        
        # Try to use the existing django-ai-lens first
        try:
            result = run_ai_query(
                question=question,
                app_labels=["app"],
                human_friendly_result=True,
            )
            return {
                'user_id': user_id,
                'question': question,
                'answer': result.get('human_friendly_result', 'No answer generated'),
                'data': result.get('data', []),
                'timestamp': datetime.now().isoformat()
            }
        except Exception as e:
            # If django-ai-lens fails, fall back to direct API with better prompt
            print(f"django-ai-lens failed: {e}, falling back to direct API")
            
            # Use direct Gemini API with a cleaner prompt
            import google.generativeai as genai
            from django.conf import settings
            
            genai.configure(api_key=settings.GEMINI_API_KEY)
            model = genai.GenerativeModel(settings.GEMINI_MODEL)
            
            prompt = f"""
            Based on the user's recent financial data, answer this question: "{question}"
            
            RECENT EXPENSES:
            {expense_summary if expense_summary else "No expense data available"}
            
            RECENT INCOMES:
            {income_summary if income_summary else "No income data available"}
            
            Please provide a helpful, concise answer. Format your response as plain text.
            Include specific numbers when available. Be friendly and helpful.
            """
            
            response = model.generate_content(prompt)
            
            # Clean the response text
            answer_text = response.text.strip()
            # Remove any markdown or special characters that might cause issues
            answer_text = re.sub(r'[^\w\s$.,0-9\-]', '', answer_text)
            
            return {
                'user_id': user_id,
                'question': question,
                'answer': answer_text if answer_text else "I couldn't find enough financial data to answer that question. Try adding some expenses or incomes first.",
                'data': [],
                'timestamp': datetime.now().isoformat()
            }
            
    except Exception as e:
        return {
            'error': str(e),
            'question': question,
            'user_id': user_id,
            'timestamp': datetime.now().isoformat()
        }


@shared_task
def generate_forecast(user_id, months=6):
    """Generate spending forecast for next X months"""
    try:
        user = User.objects.get(id=user_id)
        
        # Get historical data
        expenses = Expense.objects.filter(user=user).order_by('date')
        incomes = Income.objects.filter(user=user).order_by('date')
        
        # Prepare data summary
        expense_text = "\n".join([
            f"{e.date}: ${float(e.amount):.2f} - {e.title}" 
            for e in expenses[:30]
        ])
        income_text = "\n".join([
            f"{i.date}: ${float(i.amount):.2f} - {i.title}" 
            for i in incomes[:20]
        ])
        
        # Use Gemini to analyze trends
        import google.generativeai as genai
        from django.conf import settings
        
        genai.configure(api_key=settings.GEMINI_API_KEY)
        model = genai.GenerativeModel(settings.GEMINI_MODEL)
        
        prompt = f"""
        Given this expense data (last 30 entries):
        {expense_text if expense_text else "No expense data"}
        
        And this income data (last 20 entries):
        {income_text if income_text else "No income data"}
        
        Predict the next {months} months of expenses and income.
        Provide a simple summary with:
        1. Predicted monthly expense totals
        2. Predicted monthly income totals
        3. Monthly net totals (income - expenses)
        4. Key insights about spending patterns
        """
        
        response = model.generate_content(prompt)
        
        return {
            'user_id': user_id,
            'months': months,
            'forecast': response.text.strip(),
            'generated_at': datetime.now().isoformat()
        }
    except Exception as e:
        return {'error': str(e)}