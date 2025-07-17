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
    
    // Bind company name and language change events to update QA query
    $('#company_name, #lang').on('change input', function() {
        // Update QA query if modal is visible
        if ($('#qa_modal').hasClass('show')) {
            setDefaultQAQuery();
        }
    });
    
    // Bind other button events
    $('#btn_crawler').on('click', function() {
        // Get Content button just opens the modal, no immediate action
        // The actual content fetching will be triggered by the Submit button in the modal
    });
    
    $('#btn_qa').on('click', function() {
        // Set default query when QA modal opens
        setDefaultQAQuery();
    });
    
    $('#btn_crawler_submit').on('click', function() {
        // This is the Submit button in the crawler modal
        getNewsContent();
    });
    
    $('#btn_tagging_submit').on('click', function() {
        performTagging();
    });
    
    $('#btn_summary_submit').on('click', function() {
        performSummary();
    });
    
    $('#btn_qa_submit').on('click', function() {
        performQA();
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
                        <th scope="col" style="width: 5%">序号</th>
                        <th scope="col" style="width: 40%">新闻标题</th>
                        <th scope="col" style="width: 20%">来源</th>
                        <th scope="col" style="width: 10%">全文状态</th>
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

function showAlert(message, type, autoHide = true) {
    const alertHtml = `
        <div class="alert alert-${type} alert-dismissible fade show" role="alert">
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
    `;
    
    $('#div_ajax_info').html(alertHtml).show();
    
    // Auto-hide success and info messages after 5 seconds, unless autoHide is false
    if (autoHide && (type === 'success' || type === 'info')) {
        setTimeout(function() {
            $('#div_ajax_info').fadeOut();
        }, 5000);
    }
}

function hideAlert() {
    console.log('hideAlert called');
    $('#div_ajax_info').hide();
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

    // 显示带有spinner的获取内容提示，不自动隐藏
    showAlert(`
        <div class="d-flex align-items-center">
            <div class="spinner-border spinner-border-sm me-2" role="status">
                <span class="visually-hidden">Loading...</span>
            </div>
            正在获取新闻全文内容，请稍候...
        </div>
    `, 'info', false);

    // 设置所有状态为获取中
    $('.content-status').each(function() {
        $(this).html('<i class="bi bi-hourglass-split text-warning" title="获取中"></i>');
    });
    
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
            crawler_type: 'apify',
            company_name: $('#company_name').val().trim(),
            lang: $('#lang').val(),
            contents_save: $('#contents_save').prop('checked'),
            contents_load: $('#contents_load').prop('checked'),
            contents_save_days: parseInt($('#contents_save_days').val()),
            contents_load_days: parseInt($('#contents_load_days').val())
        }),
        timeout: 120000, // 2分钟超时
        success: function(response) {
            console.log('AJAX success callback triggered');
            handleGetContentSuccess(response, urlToIndex);
        },
        error: function(xhr, status, error) {
            console.log('AJAX error callback triggered');
            handleGetContentError(xhr, status, error);
        }
    });
}

function handleGetContentSuccess(response, urlToIndex) {
    console.log('handleGetContentSuccess called');
    // 先隐藏加载消息
    hideAlert();
    console.log('Loading alert hidden');
    
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
    console.log('handleGetContentError called');
    // 先隐藏加载消息
    hideAlert();
    console.log('Loading alert hidden');
    
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

function performTagging() {
    const newsRows = $('#news-results-table tbody tr');
    if (newsRows.length === 0) {
        showAlert('没有找到新闻结果', 'warning');
        return;
    }

    // 显示带有spinner的标签处理提示，不自动隐藏
    showAlert(`
        <div class="d-flex align-items-center">
            <div class="spinner-border spinner-border-sm me-2" role="status">
                <span class="visually-hidden">Loading...</span>
            </div>
            正在进行FC标签处理，请稍候...
        </div>
    `, 'info', false);

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

    // 调用API进行标签处理
    const requestData = {
        urls: urls,
        company_name: $('#company_name').val().trim(),
        lang: $('#lang').val(),
        tagging_method: $('#tagging_method').val(),
        tags_save: $('#tags_save').prop('checked'),
        tags_load: $('#tags_load').prop('checked'),
        tags_save_days: parseInt($('#tags_save_days').val()),
        tags_load_days: parseInt($('#tags_load_days').val())
    };
    
    console.log('Tagging request data:', requestData);
    
    $.ajax({
        url: 'http://127.0.0.1:8280/api/tagging',
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify(requestData),
        timeout: 180000, // 3分钟超时
        success: function(response) {
            console.log('Tagging AJAX success callback triggered');
            handleTaggingSuccess(response, urlToIndex);
        },
        error: function(xhr, status, error) {
            console.log('Tagging AJAX error callback triggered');
            handleTaggingError(xhr, status, error);
        }
    });
}

function handleTaggingSuccess(response, urlToIndex) {
    console.log('handleTaggingSuccess called');
    // 先隐藏加载消息
    hideAlert();
    console.log('Loading alert hidden');
    
    if (response.success && response.results) {
        let successCount = 0;
        let failCount = 0;
        
        // 检查表格是否已经有Crime Type和Probability列
        if (!$('#news-results-table thead tr th:contains("Crime Type")').length) {
            // 添加新的列到表头
            $('#news-results-table thead tr').append('<th scope="col" style="width: 30%">Crime Type</th>');
            $('#news-results-table thead tr').append('<th scope="col" style="width: 10%">Probability</th>');
        }
        
        // 为每个结果更新标签信息
        response.results.forEach(function(result, resultIndex) {
            const index = urlToIndex[result.url];
            
            // 使用索引来定位行
            const row = $(`#news-results-table tbody tr[data-index="${index}"]`);
            
            if (row.length > 0) {
                // 检查行是否已经有Crime Type和Probability列
                if (row.find('td').length < 6) {
                    // 添加新的列到行
                    row.append('<td class="crime-type"></td>');
                    row.append('<td class="probability"></td>');
                }
                
                if (result.success && result.crime_type && result.probability) {
                    row.find('.crime-type').text(result.crime_type);
                    row.find('.probability').text(result.probability);
                    successCount++;
                } else {
                    row.find('.crime-type').text('-');
                    row.find('.probability').text('-');
                    failCount++;
                }
            } else {
                console.error(`未找到索引为 ${index} 的行`);
                failCount++;
            }
        });
        
        // 显示结果统计
        showAlert(`FC标签处理完成：成功 ${successCount} 条，失败 ${failCount} 条`, 'success');
        
    } else {
        showAlert(response.message || 'FC标签处理失败', 'danger');
    }
}

function handleTaggingError(xhr, status, error) {
    console.log('handleTaggingError called');
    console.log('xhr:', xhr);
    console.log('status:', status);
    console.log('error:', error);
    
    // 先隐藏加载消息
    hideAlert();
    console.log('Loading alert hidden');
    
    let errorMessage = 'FC标签处理失败，请稍后重试';
    
    if (xhr.responseJSON && xhr.responseJSON.detail) {
        errorMessage = xhr.responseJSON.detail;
        console.log('Server error detail:', xhr.responseJSON.detail);
    } else if (xhr.responseText) {
        console.log('Server response text:', xhr.responseText);
        errorMessage = `服务器响应: ${xhr.responseText}`;
    } else if (status === 'timeout') {
        errorMessage = 'FC标签处理超时，请检查网络连接或稍后重试';
    } else if (xhr.status === 0) {
        errorMessage = '无法连接到服务器，请检查网络设置或确认服务器正在运行';
    } else if (xhr.status === 500) {
        errorMessage = '服务器内部错误，可能是标签处理配置问题';
    } else if (xhr.status === 404) {
        errorMessage = 'API端点不存在，请检查服务器配置';
    } else if (xhr.status === 422) {
        errorMessage = '请求参数错误，请检查输入参数';
    }
    
    showAlert(`
        <div class="d-flex align-items-center">
            <i class="bi bi-exclamation-triangle-fill me-2"></i>
            <div>
                <strong>FC标签处理失败</strong><br>
                <small>${errorMessage}</small>
            </div>
        </div>
    `, 'danger');
    
    console.error('Tagging error:', { xhr, status, error });
}

function performSummary() {
    const newsRows = $('#news-results-table tbody tr');
    if (newsRows.length === 0) {
        showAlert('没有找到新闻结果', 'warning');
        return;
    }

    // 先清空摘要结果区域
    $('#div_summary_res').empty().hide();

    // 显示带有spinner的摘要处理提示，不自动隐藏
    showAlert(`
        <div class="d-flex align-items-center">
            <div class="spinner-border spinner-border-sm me-2" role="status">
                <span class="visually-hidden">Loading...</span>
            </div>
            正在生成摘要，请稍候...
        </div>
    `, 'info', false);

    // 获取所有新闻URL
    const urls = [];
    newsRows.each(function() {
        const url = $(this).data('url');
        if (url) {
            urls.push(url);
        }
    });

    // 收集表单参数
    const requestData = {
        urls: urls,
        company_name: $('#company_name').val().trim(),
        lang: $('#lang').val(),
        summary_method: $('#summary_method').val(),
        max_words: parseInt($('#summary_max_words').val()),
        cluster_docs: $('#summary_clus_docs').prop('checked'),
        num_clusters: parseInt($('#summary_num_clus').val())
    };
    
    console.log('Summary request data:', requestData);
    
    // 调用API进行摘要处理
    $.ajax({
        url: 'http://127.0.0.1:8280/api/summary',
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify(requestData),
        timeout: 300000, // 5分钟超时
        success: function(response) {
            console.log('Summary AJAX success callback triggered');
            handleSummarySuccess(response);
        },
        error: function(xhr, status, error) {
            console.log('Summary AJAX error callback triggered');
            handleSummaryError(xhr, status, error);
        }
    });
}

function handleSummarySuccess(response) {
    console.log('handleSummarySuccess called');
    // 先隐藏加载消息
    hideAlert();
    console.log('Loading alert hidden');
    
    if (response.success && response.summary) {
        // 显示摘要结果
        displaySummaryResult(response.summary);
        showAlert(response.message, 'success');
    } else {
        showAlert(response.message || '摘要生成失败', 'danger');
    }
}

function handleSummaryError(xhr, status, error) {
    console.log('handleSummaryError called');
    console.log('xhr:', xhr);
    console.log('status:', status);
    console.log('error:', error);
    
    // 先隐藏加载消息
    hideAlert();
    console.log('Loading alert hidden');
    
    let errorMessage = '摘要生成失败，请稍后重试';
    
    if (xhr.responseJSON && xhr.responseJSON.message) {
        errorMessage = xhr.responseJSON.message;
        console.log('Server error message:', xhr.responseJSON.message);
    } else if (xhr.responseText) {
        console.log('Server response text:', xhr.responseText);
        errorMessage = `服务器响应: ${xhr.responseText}`;
    } else if (status === 'timeout') {
        errorMessage = '摘要生成超时，请检查网络连接或稍后重试';
    } else if (xhr.status === 0) {
        errorMessage = '无法连接到服务器，请检查网络设置或确认服务器正在运行';
    } else if (xhr.status === 500) {
        errorMessage = '服务器内部错误，可能是摘要处理配置问题';
    } else if (xhr.status === 404) {
        errorMessage = 'API端点不存在，请检查服务器配置';
    } else if (xhr.status === 422) {
        errorMessage = '请求参数错误，请检查输入参数';
    }
    
    showAlert(`
        <div class="d-flex align-items-center">
            <i class="bi bi-exclamation-triangle-fill me-2"></i>
            <div>
                <strong>摘要生成失败</strong><br>
                <small>${errorMessage}</small>
            </div>
        </div>
    `, 'danger');
    
    console.error('Summary error:', { xhr, status, error });
}

function displaySummaryResult(summary) {
    // 在div_summary_res中显示摘要结果
    const summaryHtml = `
        <div class="p-3">
            <h5 class="mb-3">
                <i class="bi bi-file-text me-2"></i>
                摘要结果
            </h5>
            <div class="border rounded p-3 bg-white">
                <div class="summary-content" style="white-space: pre-wrap; line-height: 1.6;">
                    ${escapeHtml(summary)}
                </div>
            </div>
            <div class="mt-2">
                <small class="text-muted">
                    <i class="bi bi-info-circle me-1"></i>
                    摘要生成时间: ${new Date().toLocaleString()}
                </small>
            </div>
        </div>
    `;
    
    $('#div_summary_res').html(summaryHtml).show();
}

function setDefaultQAQuery() {
    const companyName = $('#company_name').val().trim();
    const lang = $('#lang').val();
    
    if (!companyName) {
        // If no company name, clear the query
        $('#ta_qa_query').val('');
        return;
    }
    
    // Default query templates for different languages
    const queryTemplates = {
        'zh-CN': `${companyName}的负面新闻有哪些？依次列出。`,
        'zh-HK': `${companyName}的負面新聞有哪些？依次列出。`,
        'zh-TW': `${companyName}的負面新聞有哪些？依次列出。`,
        'en-US': `What are the negative news about ${companyName}? Please list them in order.`,
        'ja-JP': `${companyName}のネガティブなニュースは何ですか？順番に列挙してください。`
    };
    
    // Get the query template for the selected language
    const defaultQuery = queryTemplates[lang] || queryTemplates['en-US'];
    
    // Set the default query in the textarea
    $('#ta_qa_query').val(defaultQuery);
}

// Export functions for external use
window.performSearch = performSearch;
window.showAlert = showAlert;
window.getNewsContent = getNewsContent;
window.performTagging = performTagging;
window.performSummary = performSummary;
window.performQA = performQA;
window.setDefaultQAQuery = setDefaultQAQuery;
window.performQA = performQA;

function performQA() {
    const newsRows = $('#news-results-table tbody tr');
    if (newsRows.length === 0) {
        showAlert('没有找到新闻结果', 'warning');
        return;
    }
    
    const question = $('#ta_qa_query').val().trim();
    if (!question) {
        showAlert('请输入问题', 'warning');
        return;
    }
    
    // 显示带有spinner的问答处理提示
    showAlert(`
        <div class="d-flex align-items-center">
            <div class="spinner-border spinner-border-sm me-2" role="status">
                <span class="visually-hidden">Loading...</span>
            </div>
            正在处理问答请求，请稍候...
        </div>
    `, 'info', false);
    
    // 获取所有新闻URL
    const urls = [];
    newsRows.each(function() {
        const url = $(this).data('url');
        if (url) {
            urls.push(url);
        }
    });
    
    // 收集请求参数
    const requestData = {
        question: question,
        company_name: $('#company_name').val().trim(),
        lang: $('#lang').val(),
        urls: urls
    };
    
    console.log('QA request data:', requestData);
    
    // 调用API进行问答处理
    $.ajax({
        url: 'http://127.0.0.1:8280/api/qa',
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify(requestData),
        timeout: 300000, // 5分钟超时
        success: function(response) {
            console.log('QA AJAX success callback triggered');
            handleQASuccess(response);
        },
        error: function(xhr, status, error) {
            console.log('QA AJAX error callback triggered');
            handleQAError(xhr, status, error);
        }
    });
}

function handleQASuccess(response) {
    console.log('handleQASuccess called');
    // 先隐藏加载消息
    hideAlert();
    console.log('Loading alert hidden');
    
    if (response.success && response.answer) {
        // 显示问答结果
        displayQAResult(response.question, response.answer);
        showAlert(response.message || '问答处理成功', 'success');
    } else {
        showAlert(response.message || '问答处理失败', 'danger');
    }
}

function handleQAError(xhr, status, error) {
    console.log('handleQAError called');
    console.log('xhr:', xhr);
    console.log('status:', status);
    console.log('error:', error);
    
    // 先隐藏加载消息
    hideAlert();
    console.log('Loading alert hidden');
    
    let errorMessage = '问答处理失败，请稍后重试';
    
    if (xhr.responseJSON && xhr.responseJSON.message) {
        errorMessage = xhr.responseJSON.message;
        console.log('Server error message:', xhr.responseJSON.message);
    } else if (xhr.responseText) {
        console.log('Server response text:', xhr.responseText);
        errorMessage = `服务器响应: ${xhr.responseText}`;
    } else if (status === 'timeout') {
        errorMessage = '问答处理超时，请检查网络连接或稍后重试';
    } else if (xhr.status === 0) {
        errorMessage = '无法连接到服务器，请检查网络设置或确认服务器正在运行';
    } else if (xhr.status === 500) {
        errorMessage = '服务器内部错误，可能是问答处理配置问题';
    } else if (xhr.status === 404) {
        errorMessage = 'API端点不存在，请检查服务器配置';
    }
    
    showAlert(`
        <div class="alert-content">
            <div class="fw-bold">问答处理失败</div>
            <div class="mt-2">
                <small>${errorMessage}</small>
            </div>
        </div>
    `, 'danger');
    
    console.error('QA error:', { xhr, status, error });
}

function displayQAResult(question, answer) {
    // 在div_qa_res中追加显示问答结果
    const qaHtml = `
        <div class="qa-item mb-3 p-3 border rounded">
            <div class="question mb-2">
                <strong class="text-primary">Q: </strong>
                <span>${escapeHtml(question)}</span>
            </div>
            <div class="answer">
                <strong class="text-success">A: </strong>
                <span style="white-space: pre-wrap; line-height: 1.6;">${escapeHtml(answer)}</span>
            </div>
            <div class="mt-2">
                <small class="text-muted">
                    <i class="bi bi-clock me-1"></i>
                    ${new Date().toLocaleString()}
                </small>
            </div>
        </div>
    `;
    
    // 显示区域并追加内容
    const qaDiv = $('#div_qa_res');
    if (qaDiv.is(':hidden')) {
        qaDiv.show();
        qaDiv.html(`
            <div class="p-3">
                <h5 class="mb-3">
                    <i class="bi bi-question-circle me-2"></i>
                    问答结果
                </h5>
                <div class="qa-content">
                    ${qaHtml}
                </div>
            </div>
        `);
    } else {
        // 追加到现有内容
        qaDiv.find('.qa-content').append(qaHtml);
    }
    
    // 滚动到新添加的内容
    qaDiv.find('.qa-item').last()[0].scrollIntoView({ 
        behavior: 'smooth', 
        block: 'nearest' 
    });
}