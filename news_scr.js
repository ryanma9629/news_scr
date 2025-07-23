// JavaScript for News Search Application (news_scr.js)
// Handles web search functionality, result display, and user interactions

// Global session management
let currentSessionId = null;

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
        showAlert('Please enter company name', 'danger');
        return;
    }
    
    // Hide previous results
    hideSearchResults();
    
    // Disable form during search
    $('#frm_web_search input, #frm_web_search select').prop('disabled', true);
    $('#frm_web_search input[type="submit"]').val('Searching...');
    
    // Make API request
    $.ajax({
        url: 'http://127.0.0.1:8280/api/search',
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify(formData),
        timeout: 30000,
        beforeSend: function() {
            showAlert(`
                <div class="d-flex align-items-center">
                    <div class="spinner-border spinner-border-sm me-2" role="status">
                        <span class="visually-hidden">Loading...</span>
                    </div>
                    Searching for "${formData.company_name}" related news using ${formData.search_engine}, please wait...
                </div>
            `, 'info', false);
        }
    }).done(function(response) {
        hideAlert();
        handleSearchSuccess(response);
    }).fail(function(xhr, status, error) {
        hideAlert();
        handleSearchError(xhr, status, error);
    }).always(function() {
        // Re-enable form
        $('#frm_web_search input, #frm_web_search select').prop('disabled', false);
        $('#frm_web_search input[type="submit"]').val('Click to search');
    });
}

function handleSearchSuccess(response) {
    if (response.success && response.results.length > 0) {
        // Save session ID for subsequent API calls
        if (response.session_id) {
            currentSessionId = response.session_id;
            console.log('Session ID saved:', currentSessionId);
        }
        
        // Display search results
        displaySearchResults(response.results);
        showAlert(response.message, 'success', false);
        
        // Show operation buttons but only enable Get Content
        $('#div_operation').show();
        $('#btn_crawler').removeClass('disabled');
        // Keep other buttons disabled until content is retrieved
        $('#btn_tagging, #btn_summary, #btn_qa').addClass('disabled');
        
    } else {
        showAlert(response.message || 'No related news found', 'warning');
        hideSearchResults();
    }
}

function handleSearchError(xhr, status, error) {
    let errorMessage = 'Search failed, please try again later';
    
    if (xhr.responseJSON && xhr.responseJSON.detail) {
        errorMessage = xhr.responseJSON.detail;
    } else if (status === 'timeout') {
        errorMessage = 'Search timeout, please check network connection or try again later';
    } else if (xhr.status === 0) {
        errorMessage = 'Unable to connect to server, please check network settings or confirm server is running';
    } else if (xhr.status === 500) {
        errorMessage = 'Server internal error, possibly API configuration issue';
    } else if (xhr.status === 404) {
        errorMessage = 'API endpoint does not exist, please check server configuration';
    } else if (xhr.status === 422) {
        errorMessage = 'Request parameters error, please check input content';
    }
    
    showAlert(`
        <div class="d-flex align-items-center">
            <i class="bi bi-exclamation-triangle-fill me-2"></i>
            <div>
                <strong>Search Failed</strong><br>
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
            <h5 class="mb-0">Search Results</h5>
        </div>
        <div class="table-responsive">
            <table class="table table-striped table-hover" id="news-results-table">
                <thead class="table-dark">
                    <tr>
                        <th scope="col" style="width: 5%">No.</th>
                        <th scope="col" style="width: 40%">News Title</th>
                        <th scope="col" style="width: 20%">Source</th>
                        <th scope="col" style="width: 10%">Content Status</th>
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
            <small>Found ${results.length} news articles</small>
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
        return 'Unknown Source';
    }
}

// Export functions for external use
window.performSearch = performSearch;
window.showAlert = showAlert;
window.getNewsContent = getNewsContent;

function getNewsContent() {
    const newsRows = $('#news-results-table tbody tr');
    if (newsRows.length === 0) {
        showAlert('No news results found', 'warning');
        return;
    }

    // Set all status to loading
    $('.content-status').each(function() {
        $(this).html('<i class="bi bi-hourglass-split text-warning" title="Loading"></i>');
    });
    
    // Get all news URLs and create mapping
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

    // Check if session_id exists
    if (!currentSessionId) {
        showAlert('Session ID not found, please search again', 'danger');
        return;
    }

    // Call API to get content
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
            contents_load_days: parseInt($('#contents_load_days').val()),
            session_id: currentSessionId
        }),
        timeout: 120000,
        beforeSend: function() {
            console.log('Get content AJAX beforeSend triggered');
            // Disable get content button to prevent duplicate submission
            $('#btn_crawler_submit').prop('disabled', true);
            showAlert(`
                <div class="d-flex align-items-center">
                    <div class="spinner-border spinner-border-sm me-2" role="status">
                        <span class="visually-hidden">Loading...</span>
                    </div>
                    Getting news full content, please wait...
                </div>
            `, 'info', false);
        }
    }).done(function(response) {
        console.log('Get content AJAX done triggered');
        hideAlert();
        handleGetContentSuccess(response, urlToIndex);
    }).fail(function(xhr, status, error) {
        console.log('Get content AJAX fail triggered');
        hideAlert();
        handleGetContentError(xhr, status, error);
    }).always(function() {
        console.log('Get content AJAX always triggered');
        // Re-enable get content button
        $('#btn_crawler_submit').prop('disabled', false);
    });
}

function handleGetContentSuccess(response, urlToIndex) {
    if (response.success && response.results) {
        let successCount = 0;
        let failCount = 0;
        
        // Update status for each result
        response.results.forEach(function(result, resultIndex) {
            const index = urlToIndex[result.url];
            
            // Use index to locate status cell
            const statusCell = $(`.content-status[data-index="${index}"]`);
            
            if (statusCell.length > 0) {
                if (result.success && result.content) {
                    const successHtml = '<i class="bi bi-check-circle-fill text-success" title="Success"></i>';
                    statusCell.html(successHtml);
                    successCount++;
                } else {
                    const errorMsg = result.error || 'Failed';
                    const failHtml = `<i class="bi bi-x-circle-fill text-danger" title="${errorMsg}"></i>`;
                    statusCell.html(failHtml);
                    failCount++;
                }
            } else {
                console.error(`Status cell with index ${index} not found`);
                failCount++;
            }
        });
        
        // Display result statistics
        showAlert(`Content retrieval completed: ${successCount} successful, ${failCount} failed`, 'success', false);
        
        // Only enable other function buttons when at least one URL's content is retrieved
        if (successCount > 0) {
            $('#btn_tagging, #btn_summary, #btn_qa').removeClass('disabled');
        } else {
            $('#btn_tagging, #btn_summary, #btn_qa').addClass('disabled');
        }
    } else {
        showAlert(response.message || 'Content retrieval failed', 'danger');
        // Set all status to failed
        $('.content-status').html('<i class="bi bi-x-circle-fill text-danger" title="Failed"></i>');
        // Ensure other buttons remain disabled
        $('#btn_tagging, #btn_summary, #btn_qa').addClass('disabled');
    }
}

function handleGetContentError(xhr, status, error) {
    let errorMessage = 'Content retrieval failed, please try again later';
    
    if (xhr.responseJSON && xhr.responseJSON.detail) {
        errorMessage = xhr.responseJSON.detail;
    } else if (status === 'timeout') {
        errorMessage = 'Content retrieval timeout, please check network connection or try again later';
    } else if (xhr.status === 0) {
        errorMessage = 'Unable to connect to server, please check network settings or confirm server is running';
    } else if (xhr.status === 500) {
        errorMessage = 'Server internal error, possibly crawler configuration issue';
    } else if (xhr.status === 404) {
        errorMessage = 'API endpoint does not exist, please check server configuration';
    }
    
    showAlert(`
        <div class="d-flex align-items-center">
            <i class="bi bi-exclamation-triangle-fill me-2"></i>
            <div>
                <strong>Content Retrieval Failed</strong><br>
                <small>${errorMessage}</small>
            </div>
        </div>
    `, 'danger');
    
    // Set all status to failed
    $('.content-status').html('<i class="bi bi-x-circle-fill text-danger" title="Failed"></i>');
    // Ensure other buttons remain disabled
    $('#btn_tagging, #btn_summary, #btn_qa').addClass('disabled');
    console.error('Get content error:', { xhr, status, error });
}

function performTagging() {
    const newsRows = $('#news-results-table tbody tr');
    if (newsRows.length === 0) {
        showAlert('No news results found', 'warning');
        return;
    }

    // Check if session_id exists
    if (!currentSessionId) {
        showAlert('Session ID not found, please search again', 'danger');
        return;
    }

    // Get all news URLs and create mapping
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

    // Call API for tagging processing
    const requestData = {
        urls: urls,
        company_name: $('#company_name').val().trim(),
        lang: $('#lang').val(),
        tagging_method: $('#tagging_method').val(),
        tags_save: $('#tags_save').prop('checked'),
        tags_load: $('#tags_load').prop('checked'),
        tags_save_days: parseInt($('#tags_save_days').val()),
        tags_load_days: parseInt($('#tags_load_days').val()),
        session_id: currentSessionId
    };
    
    $.ajax({
        url: 'http://127.0.0.1:8280/api/tagging',
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify(requestData),
        timeout: 180000,
        beforeSend: function() {
            console.log('Tagging AJAX beforeSend triggered');
            // Disable tagging button to prevent duplicate submission
            $('#btn_tagging_submit').prop('disabled', true);
            showAlert(`
                <div class="d-flex align-items-center">
                    <div class="spinner-border spinner-border-sm me-2" role="status">
                        <span class="visually-hidden">Loading...</span>
                    </div>
                    Processing FC tagging, please wait...
                </div>
            `, 'info', false);
        }
    }).done(function(response) {
        console.log('Tagging AJAX done triggered');
        hideAlert();
        handleTaggingSuccess(response, urlToIndex);
    }).fail(function(xhr, status, error) {
        console.log('Tagging AJAX fail triggered');
        hideAlert();
        handleTaggingError(xhr, status, error);
    }).always(function() {
        console.log('Tagging AJAX always triggered');
        // Re-enable tagging button
        $('#btn_tagging_submit').prop('disabled', false);
    });
}

function handleTaggingSuccess(response, urlToIndex) {
    if (response.success && response.results) {
        let successCount = 0;
        let failCount = 0;
        
        // Check if table already has Crime Type and Probability columns
        if (!$('#news-results-table thead tr th:contains("Crime Type")').length) {
            // Add new columns to table header
            $('#news-results-table thead tr').append('<th scope="col" style="width: 30%">Crime Type</th>');
            $('#news-results-table thead tr').append('<th scope="col" style="width: 10%">Probability</th>');
        }
        
        // Update tagging information for each result
        response.results.forEach(function(result, resultIndex) {
            const index = urlToIndex[result.url];
            
            // Use index to locate row
            const row = $(`#news-results-table tbody tr[data-index="${index}"]`);
            
            if (row.length > 0) {
                // Check if row already has Crime Type and Probability columns
                if (row.find('td').length < 6) {
                    // Add new columns to row
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
                console.error(`Row with index ${index} not found`);
                failCount++;
            }
        });
        
        // Display result statistics
        showAlert(`FC tagging completed: ${successCount} successful, ${failCount} failed`, 'success', false);
        
    } else {
        showAlert(response.message || 'FC tagging failed', 'danger');
    }
}

function handleTaggingError(xhr, status, error) {
    let errorMessage = 'FC tagging failed, please try again later';
    
    if (xhr.responseJSON && xhr.responseJSON.detail) {
        errorMessage = xhr.responseJSON.detail;
    } else if (xhr.responseText) {
        errorMessage = `Server response: ${xhr.responseText}`;
    } else if (status === 'timeout') {
        errorMessage = 'FC tagging timeout, please check network connection or try again later';
    } else if (xhr.status === 0) {
        errorMessage = 'Unable to connect to server, please check network settings or confirm server is running';
    } else if (xhr.status === 500) {
        errorMessage = 'Server internal error, possibly tagging configuration issue';
    } else if (xhr.status === 404) {
        errorMessage = 'API endpoint does not exist, please check server configuration';
    } else if (xhr.status === 422) {
        errorMessage = 'Request parameters error, please check input parameters';
    }
    
    showAlert(`
        <div class="d-flex align-items-center">
            <i class="bi bi-exclamation-triangle-fill me-2"></i>
            <div>
                <strong>FC Tagging Failed</strong><br>
                <small>${errorMessage}</small>
            </div>
        </div>
    `, 'danger');
    
    console.error('Tagging error:', { xhr, status, error });
}

function performSummary() {
    const newsRows = $('#news-results-table tbody tr');
    if (newsRows.length === 0) {
        showAlert('No news results found', 'warning');
        return;
    }

    // Check if session_id exists
    if (!currentSessionId) {
        showAlert('Session ID not found, please search again', 'danger');
        return;
    }

    // Clear summary result area first
    $('#div_summary_res').empty().hide();

    // Get all news URLs
    const urls = [];
    newsRows.each(function() {
        const url = $(this).data('url');
        if (url) {
            urls.push(url);
        }
    });

    // Collect form parameters
    const requestData = {
        urls: urls,
        company_name: $('#company_name').val().trim(),
        lang: $('#lang').val(),
        summary_method: $('#summary_method').val(),
        max_words: parseInt($('#summary_max_words').val()),
        cluster_docs: $('#summary_clus_docs').prop('checked'),
        num_clusters: parseInt($('#summary_num_clus').val()),
        session_id: currentSessionId
    };
    
    // Call API for summary processing
    $.ajax({
        url: 'http://127.0.0.1:8280/api/summary',
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify(requestData),
        timeout: 300000,
        beforeSend: function() {
            console.log('Summary AJAX beforeSend triggered');
            // Disable summary button to prevent duplicate submission
            $('#btn_summary_submit').prop('disabled', true);
            showAlert(`
                <div class="d-flex align-items-center">
                    <div class="spinner-border spinner-border-sm me-2" role="status">
                        <span class="visually-hidden">Loading...</span>
                    </div>
                    Generating summary, please wait...
                </div>
            `, 'info', false);
        }
    }).done(function(response) {
        console.log('Summary AJAX done triggered');
        hideAlert();
        handleSummarySuccess(response);
    }).fail(function(xhr, status, error) {
        console.log('Summary AJAX fail triggered');
        hideAlert();
        handleSummaryError(xhr, status, error);
    }).always(function() {
        console.log('Summary AJAX always triggered');
        // Re-enable summary button
        $('#btn_summary_submit').prop('disabled', false);
    });
}

function handleSummarySuccess(response) {
    if (response.success && response.summary) {
        // Display summary result
        displaySummaryResult(response.summary);
        showAlert(response.message || 'Summary generated successfully', 'success', false);
    } else {
        showAlert(response.message || 'Summary generation failed', 'danger');
    }
}

function handleSummaryError(xhr, status, error) {
    let errorMessage = 'Summary generation failed, please try again later';
    
    if (xhr.responseJSON && xhr.responseJSON.message) {
        errorMessage = xhr.responseJSON.message;
    } else if (xhr.responseText) {
        errorMessage = `Server response: ${xhr.responseText}`;
    } else if (status === 'timeout') {
        errorMessage = 'Summary generation timeout, please check network connection or try again later';
    } else if (xhr.status === 0) {
        errorMessage = 'Unable to connect to server, please check network settings or confirm server is running';
    } else if (xhr.status === 500) {
        errorMessage = 'Server internal error, possibly summary processing configuration issue';
    } else if (xhr.status === 404) {
        errorMessage = 'API endpoint does not exist, please check server configuration';
    } else if (xhr.status === 422) {
        errorMessage = 'Request parameters error, please check input parameters';
    }
    
    showAlert(`
        <div class="d-flex align-items-center">
            <i class="bi bi-exclamation-triangle-fill me-2"></i>
            <div>
                <strong>Summary Generation Failed</strong><br>
                <small>${errorMessage}</small>
            </div>
        </div>
    `, 'danger');
    
    console.error('Summary error:', { xhr, status, error });
}

function displaySummaryResult(summary) {
    // Display summary results in div_summary_res
    const summaryHtml = `
        <div class="p-3">
            <h5 class="mb-3">
                <i class="bi bi-file-text me-2"></i>
                Summary Results
            </h5>
            <div class="border rounded p-3 bg-white">
                <div class="summary-content" style="white-space: pre-wrap; line-height: 1.6;">
                    ${escapeHtml(summary)}
                </div>
            </div>
            <div class="mt-2">
                <small class="text-muted">
                    <i class="bi bi-info-circle me-1"></i>
                    Summary generated at: ${new Date().toLocaleString()}
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
        showAlert('No news results found', 'warning');
        return;
    }
    
    // Check if session_id exists
    if (!currentSessionId) {
        showAlert('Session ID not found, please search again', 'danger');
        return;
    }
    
    const question = $('#ta_qa_query').val().trim();
    if (!question) {
        showAlert('Please enter a question', 'warning');
        return;
    }
    
    // Get all news URLs
    const urls = [];
    newsRows.each(function() {
        const url = $(this).data('url');
        if (url) {
            urls.push(url);
        }
    });
    
    // Collect request parameters
    const requestData = {
        question: question,
        company_name: $('#company_name').val().trim(),
        lang: $('#lang').val(),
        urls: urls,
        session_id: currentSessionId
    };
    
    // Call API for Q&A processing
    $.ajax({
        url: 'http://127.0.0.1:8280/api/qa',
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify(requestData),
        timeout: 300000,
        beforeSend: function() {
            console.log('QA AJAX beforeSend triggered');
            // Disable QA button to prevent duplicate submission
            $('#btn_qa_submit').prop('disabled', true);
            showAlert(`
                <div class="d-flex align-items-center">
                    <div class="spinner-border spinner-border-sm me-2" role="status">
                        <span class="visually-hidden">Loading...</span>
                    </div>
                    Processing Q&A request, please wait...
                </div>
            `, 'info', false);
        }
    }).done(function(response) {
        console.log('QA AJAX done triggered');
        hideAlert();
        handleQASuccess(response);
    }).fail(function(xhr, status, error) {
        console.log('QA AJAX fail triggered');
        hideAlert();
        handleQAError(xhr, status, error);
    }).always(function() {
        console.log('QA AJAX always triggered');
        // Re-enable Q&A button
        $('#btn_qa_submit').prop('disabled', false);
    });
}

function handleQASuccess(response) {
    if (response.success && response.answer) {
        // Display Q&A result
        displayQAResult(response.question, response.answer);
        showAlert(response.message || 'Q&A processing successful', 'success', false);
    } else {
        showAlert(response.message || 'Q&A processing failed', 'danger');
    }
}

function handleQAError(xhr, status, error) {
    let errorMessage = 'Q&A processing failed, please try again later';
    
    if (xhr.responseJSON && xhr.responseJSON.message) {
        errorMessage = xhr.responseJSON.message;
    } else if (xhr.responseText) {
        errorMessage = `Server response: ${xhr.responseText}`;
    } else if (status === 'timeout') {
        errorMessage = 'Q&A processing timeout, please check network connection or try again later';
    } else if (xhr.status === 0) {
        errorMessage = 'Unable to connect to server, please check network settings or confirm server is running';
    } else if (xhr.status === 500) {
        errorMessage = 'Server internal error, possibly Q&A processing configuration issue';
    } else if (xhr.status === 404) {
        errorMessage = 'API endpoint does not exist, please check server configuration';
    }
    
    showAlert(`
        <div class="alert-content">
            <div class="fw-bold">Q&A Processing Failed</div>
            <div class="mt-2">
                <small>${errorMessage}</small>
            </div>
        </div>
    `, 'danger');
    
    console.error('QA error:', { xhr, status, error });
}

function displayQAResult(question, answer) {
    // Append and display Q&A results in div_qa_res
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
    
    // Display area and append content
    const qaDiv = $('#div_qa_res');
    if (qaDiv.is(':hidden')) {
        qaDiv.show();
        qaDiv.html(`
            <div class="p-3">
                <h5 class="mb-3">                <i class="bi bi-question-circle me-2"></i>
                Q&A Results
            </h5>
            <div class="qa-content">
                ${qaHtml}
            </div>
            </div>
        `);
    } else {
        // Append to existing content
        qaDiv.find('.qa-content').append(qaHtml);
    }
    
    // Scroll to newly added content
    qaDiv.find('.qa-item').last()[0].scrollIntoView({ 
        behavior: 'smooth', 
        block: 'nearest' 
    });
}