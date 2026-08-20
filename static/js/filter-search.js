// Filter search functionality for expenses/income
(function() {
    'use strict';

    // Debounce search to avoid excessive filtering
    function debounce(func, wait) {
        let timeout;
        return function(...args) {
            clearTimeout(timeout);
            timeout = setTimeout(() => func.apply(this, args), wait);
        };
    }

    // Initialize when DOM is ready
    document.addEventListener('DOMContentLoaded', function() {
        const searchInput = document.querySelector('.js-debounce-search');
        const table = document.querySelector('.fin-table');
        
        if (!searchInput || !table) return;
        
        const rows = table.querySelectorAll('tbody tr');
        
        function filterTable() {
            const query = searchInput.value.toLowerCase().trim();
            
            rows.forEach(row => {
                // Skip empty rows or rows with colspan (like "No expenses" message)
                if (row.querySelector('td[colspan]')) return;
                
                const text = row.textContent.toLowerCase();
                row.style.display = text.includes(query) ? '' : 'none';
            });
        }
        
        // Use debounced search
        searchInput.addEventListener('input', debounce(filterTable, 300));
        
        // Also handle filter form submission via AJAX? No, we'll keep it simple
        // Just client-side filtering for the current page
        console.log('✅ filter-search.js loaded');
    });

})();
