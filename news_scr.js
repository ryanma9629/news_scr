// JavaScript for News Search Application (news_scr.js)
// Handles web search functionality, result display, and user interactions

$(document).ready(function() {
    // Initialize the application
    initializeApp();
});

function initializeApp() {
    // Bind form submission event
    $('#frm_web_search').on('submit', function(e) {
        e.preventDefault();
        performSearch();
    });
    
    // Bind other button events
    $('#btn_crawler').on('click', function() {
        // Use the getNewsContent function for Get Content functionality
        getNewsContent();
    });
    
    $('#btn_tagging_submit').on('click', function() {
        alert('标签功能尚未实现');
    });
    
    $('#btn_summary_submit').on('click', function() {
        alert('摘要功能尚未实现');
    });
    
    $('#btn_qa_submit').on('click', function() {
        alert('问答功能尚未实现');
    });
}

function performSearch() {
    // Get form data
    const formData = {
        company_name: $('#company_name').val().trim(),
        lang: $('#lang').val(),
        search_suffix: $('#search_suffix').val(),
        search_engine: $('#search_engine').val(),
        num_results: parseInt($('#num_results').val()),
        llm_model: $('#llm_model').val()
    };
    
    // Validate form data
    if (!formData.company_name) {
        showAlert('请输入公司名称', 'danger');
        return;
    }
    
    // Show loading message with spinner
    showAlert(`
        <div class="d-flex align-items-center">
            <div class="spinner-border spinner-border-sm me-2" role="status">
                <span class="visually-hidden">Loading...</span>
            </div>
            正在使用 ${formData.search_engine} 搜索"${formData.company_name}"相关新闻，请稍候...
        </div>
    `, 'info');
    
    // Hide previous results
    hideSearchResults();
    
    // Disable form during search
    $('#frm_web_search input, #frm_web_search select').prop('disabled', true);
    $('#frm_web_search input[type="submit"]').val('搜索中...');
    
    // Make API request
    $.ajax({
        url: 'http://127.0.0.1:8280/api/search',  // 指定完整的API服务器地址
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify(formData),
        timeout: 30000, // 30 second timeout
        success: function(response) {
            handleSearchSuccess(response);
        },
        error: function(xhr, status, error) {
            handleSearchError(xhr, status, error);
        },
        complete: function() {
            // Re-enable form
            $('#frm_web_search input, #frm_web_search select').prop('disabled', false);
            $('#frm_web_search input[type="submit"]').val('Click to search');
        }
    });
}

function handleSearchSuccess(response) {
    if (response.success && response.results.length > 0) {
        // Display search results
        displaySearchResults(response.results);
        showAlert(response.message, 'success');
        
        // Show operation buttons but only enable Get Content
        $('#div_operation').show();
        $('#btn_crawler').removeClass('disabled');
        // Keep other buttons disabled until content is retrieved
        $('#btn_tagging, #btn_summary, #btn_qa').addClass('disabled');
        
    } else {
        showAlert(response.message || '没有找到相关新闻', 'warning');
        hideSearchResults();
    }
}

function handleSearchError(xhr, status, error) {
    let errorMessage = '搜索失败，请稍后重试';
    
    if (xhr.responseJSON && xhr.responseJSON.detail) {
        errorMessage = xhr.responseJSON.detail;
    } else if (status === 'timeout') {
        errorMessage = '搜索超时，请检查网络连接或稍后重试';
    } else if (xhr.status === 0) {
        errorMessage = '无法连接到服务器，请检查网络设置或确认服务器正在运行';
    } else if (xhr.status === 500) {
        errorMessage = '服务器内部错误，可能是API配置问题';
    } else if (xhr.status === 404) {
        errorMessage = 'API端点不存在，请检查服务器配置';
    } else if (xhr.status === 422) {
        errorMessage = '请求参数有误，请检查输入内容';
    }
    
    showAlert(`
        <div class="d-flex align-items-center">
            <i class="bi bi-exclamation-triangle-fill me-2"></i>
            <div>
                <strong>搜索失败</strong><br>
                <small>${errorMessage}</small>
            </div>
        </div>
    `, 'danger');
    
    hideSearchResults();
    console.error('Search error:', { xhr, status, error });
}

function displaySearchResults(results) {
    const tableHtml = `
        <div class="d-flex justify-content-between align-items-center mb-3">
            <h5 class="mb-0">搜索结果</h5>
        </div>
        <div class="table-responsive">
            <table class="table table-striped table-hover" id="news-results-table">
                <thead class="table-dark">
                    <tr>
                        <th scope="col" style="width: 8%">序号</th>
                        <th scope="col" style="width: 60%">新闻标题</th>
                        <th scope="col" style="width: 20%">来源</th>
                        <th scope="col" style="width: 12%">全文状态</th>
                    </tr>
                </thead>
                <tbody>
                    ${results.map((result, index) => `
                        <tr data-url="${result.url}" data-index="${index}">
                            <td class="text-center">${index + 1}</td>
                            <td>
                                <a href="${result.url}" target="_blank" class="text-decoration-none" 
                                   title="${escapeHtml(result.title)}">
                                    ${escapeHtml(result.title)}
                                </a>
                            </td>
                            <td>
                                <small class="text-muted" title="${result.url}">
                                    ${getDomainFromUrl(result.url)}
                                </small>
                            </td>
                            <td class="text-center content-status" data-index="${index}" data-url="${result.url}">
                                <span class="text-muted">-</span>
                            </td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>
        <div class="mt-3 text-muted">
            <small>共找到 ${results.length} 条新闻</small>
        </div>
    `;
    
    $('#div_search_res').html(tableHtml).show();
}

function hideSearchResults() {
    $('#div_search_res').hide();
    $('#div_operation').hide();
    // Disable all operation buttons when hiding results
    $('#btn_crawler, #btn_tagging, #btn_summary, #btn_qa').addClass('disabled');
}

function showAlert(message, type) {
    const alertHtml = `
        <div class="alert alert-${type} alert-dismissible fade show" role="alert">
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
    `;
    
    $('#div_ajax_info').html(alertHtml).show();
    
    // Auto-hide success and info messages after 5 seconds
    if (type === 'success' || type === 'info') {
        setTimeout(function() {
            $('#div_ajax_info').fadeOut();
        }, 5000);
    }
}

function escapeHtml(text) {
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return text.replace(/[&<>"']/g, function(m) { return map[m]; });
}

function getDomainFromUrl(url) {
    try {
        const domain = new URL(url).hostname;
        return domain.length > 30 ? domain.substring(0, 30) + '...' : domain;
    } catch (e) {
        return '未知来源';
    }
}

// Export functions for external use
window.performSearch = performSearch;
window.showAlert = showAlert;
window.getNewsContent = getNewsContent;

function getNewsContent() {
    const newsRows = $('#news-results-table tbody tr');
    if (newsRows.length === 0) {
        showAlert('没有找到新闻结果', 'warning');
        return;
    }

    // 显示开始获取内容的提示
    showAlert('开始获取新闻全文内容，请稍候...', 'info');

    // 设置所有状态为获取中
    $('.content-status').each(function() {
        $(this).html('<i class="bi bi-hourglass-split text-warning" title="获取中"></i>');    });
    
    // 获取所有新闻URL并创建映射
    const urls = [];
    const urlToIndex = {};
    newsRows.each(function() {
        const url = $(this).data('url');
        const index = $(this).data('index');
        if (url) {
            urls.push(url);
            urlToIndex[url] = index;
        }
    });

    // 调用API获取内容
    $.ajax({
        url: 'http://127.0.0.1:8280/api/crawler',
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({
            urls: urls,
            crawler_type: 'apify'
        }),
        timeout: 120000, // 2分钟超时
        success: function(response) {
            handleGetContentSuccess(response, urlToIndex);
        },
        error: function(xhr, status, error) {
            handleGetContentError(xhr, status, error);
        }
    });
}

function handleGetContentSuccess(response, urlToIndex) {
    if (response.success && response.results) {
        let successCount = 0;
        let failCount = 0;
        
        // 为每个结果更新状态
        response.results.forEach(function(result, resultIndex) {
            const index = urlToIndex[result.url];
            
            // 使用索引来定位状态单元格
            const statusCell = $(`.content-status[data-index="${index}"]`);
            
            if (statusCell.length > 0) {
                if (result.success && result.content) {
                    const successHtml = '<i class="bi bi-check-circle-fill text-success" title="获取成功"></i>';
                    statusCell.html(successHtml);
                    successCount++;
                } else {
                    const errorMsg = result.error || '获取失败';
                    const failHtml = `<i class="bi bi-x-circle-fill text-danger" title="${errorMsg}"></i>`;
                    statusCell.html(failHtml);
                    failCount++;
                }
            } else {
                console.error(`未找到索引为 ${index} 的状态单元格`);
                failCount++;
            }
        });
        
        // 显示结果统计
        showAlert(`内容获取完成：成功 ${successCount} 条，失败 ${failCount} 条`, 'success');
        
        // 只有当至少获取了一个URL的全文后，才启用其他功能按钮
        if (successCount > 0) {
            $('#btn_tagging, #btn_summary, #btn_qa').removeClass('disabled');
        } else {
            $('#btn_tagging, #btn_summary, #btn_qa').addClass('disabled');
        }
    } else {
        showAlert(response.message || '获取内容失败', 'danger');
        // 所有状态设为失败
        $('.content-status').html('<i class="bi bi-x-circle-fill text-danger" title="获取失败"></i>');
        // 确保其他按钮保持禁用状态
        $('#btn_tagging, #btn_summary, #btn_qa').addClass('disabled');
    }
}

function handleGetContentError(xhr, status, error) {
    let errorMessage = '获取内容失败，请稍后重试';
    
    if (xhr.responseJSON && xhr.responseJSON.detail) {
        errorMessage = xhr.responseJSON.detail;
    } else if (status === 'timeout') {
        errorMessage = '获取内容超时，请检查网络连接或稍后重试';
    } else if (xhr.status === 0) {
        errorMessage = '无法连接到服务器，请检查网络设置或确认服务器正在运行';
    } else if (xhr.status === 500) {
        errorMessage = '服务器内部错误，可能是爬虫配置问题';
    } else if (xhr.status === 404) {
        errorMessage = 'API端点不存在，请检查服务器配置';
    }
    
    showAlert(`
        <div class="d-flex align-items-center">
            <i class="bi bi-exclamation-triangle-fill me-2"></i>
            <div>
                <strong>获取内容失败</strong><br>
                <small>${errorMessage}</small>
            </div>
        </div>
    `, 'danger');
    
    // 所有状态设为失败
    $('.content-status').html('<i class="bi bi-x-circle-fill text-danger" title="获取失败"></i>');
    // 确保其他按钮保持禁用状态
    $('#btn_tagging, #btn_summary, #btn_qa').addClass('disabled');
    console.error('Get content error:', { xhr, status, error });
}

// Export functions for external use
window.performSearch = performSearch;
window.showAlert = showAlert;
window.getNewsContent = getNewsContent;