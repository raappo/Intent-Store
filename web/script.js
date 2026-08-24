document.addEventListener('DOMContentLoaded', () => {
    fetch('data.json')
        .then(response => {
            if (!response.ok) {
                throw new Error('Failed to load data.json');
            }
            return response.json();
        })
        .then(data => {
            renderDashboard(data);
        })
        .catch(error => {
            document.getElementById('summary').innerHTML = `<span style="color: #ef4444">Error loading data: ${error.message}</span>`;
            console.error(error);
        });
});

function formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

function renderDashboard(data) {
    const grid = document.getElementById('file-grid');
    const summary = document.getElementById('summary');
    
    // Calculate stats
    const total = data.length;
    let archiveCount = 0;
    let keepCount = 0;
    
    data.forEach(item => {
        if (item.action === 'archive') archiveCount++;
        if (item.action === 'keep') keepCount++;
    });
    
    // Update summary
    summary.innerHTML = `<strong>${total}</strong> files scanned &middot; <strong>${archiveCount}</strong> recommended for archive &middot; <strong>${keepCount}</strong> kept for recurring relevance`;
    
    // Render cards
    grid.innerHTML = '';
    
    data.forEach(item => {
        const card = document.createElement('div');
        card.className = 'card';
        
        // Formats
        const sizeStr = formatBytes(item.size);
        const actionUpper = (item.action || 'Unknown').toUpperCase();
        const scoreStr = parseFloat(item.score).toFixed(3);
        
        // Icons for action
        let actionClass = '';
        if (item.action === 'keep') actionClass = 'action-keep';
        else if (item.action === 'archive') actionClass = 'action-archive';
        else if (item.action === 'compress') actionClass = 'action-compress';
        
        // Source badge
        const sourceClass = item.source === 'LLM' ? 'source-llm' : 'source-rule';
        const sourceText = item.source === 'LLM' ? '🤖 LLM' : '⚙️ RULE';
        
        card.innerHTML = `
            <div class="card-header">
                <div class="filename">${item.file}</div>
                <div class="score-badge" title="Importance Score">${scoreStr}</div>
            </div>
            
            <div class="meta-row">
                <div class="meta-item" title="Size">
                    <svg class="meta-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="17 8 12 3 7 8"></polyline><line x1="12" y1="3" x2="12" y2="15"></line></svg>
                    ${sizeStr}
                </div>
                <div class="meta-item" title="Last Accessed">
                    <svg class="meta-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>
                    ${item.last_access}
                </div>
                
                <div class="action-badge ${actionClass}">
                    ${actionUpper}
                </div>
            </div>
            
            <div class="justification-box">
                <div class="source-badge ${sourceClass}">${sourceText}</div>
                ${item.justification}
            </div>
        `;
        
        grid.appendChild(card);
    });
}
