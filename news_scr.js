// JavaScript for News Search Application (news_scr.js)
// Optimized version with improved efficiency and maintainability

// Configuration constants
const SUPPORTED_LLM_MODELS = ['gpt-4.1', 'gpt-4o', 'gpt-4o-mini', 'deepseek-chat', 'qwen-max', 'qwen-plus', 'qwen-turbo'];

// Global state management
const AppState = {
    sessionId: null,
    newsResults: [],

    setSessionId(id) {
        this.sessionId = id;
    },

    setNewsResults(results) {
        this.newsResults = results;
    },

    getUrls() {
        return this.newsResults.map(result => result.url);
    },

    hasSession() {
        return !!this.sessionId;
    },

    hasResults() {
        return this.newsResults.length > 0;
    }
};

// UI state management
const UIState = {
    enableButtons(selector) {
        $(selector).removeClass('disabled');
    },

    disableButtons(selector) {
        $(selector).addClass('disabled');
    },

    toggleFormInputs(disabled) {
        $('#frm_web_search input, #frm_web_search select').prop('disabled', disabled);
        const submitBtn = $('#frm_web_search input[type="submit"]');
        submitBtn.val(disabled ? 'Searching...' : 'Click to search');
    },

    toggleSubmitButton(selector, disabled, loadingText, normalText) {
        $(selector).prop('disabled', disabled);
        if (loadingText && normalText) {
            $(selector).text(disabled ? loadingText : normalText);
        }
    }
};

// Generic AJAX utility
const AjaxHelper = {
    makeRequest(options) {
        const defaultOptions = {
            method: 'POST',
            contentType: 'application/json',
            xhrFields: { withCredentials: true },
            timeout: 30000
        };

        return $.ajax({
            ...defaultOptions,
            ...options,
            data: typeof options.data === 'object' ? JSON.stringify(options.data) : options.data
        });
    },

    handleError(xhr, status, context = '') {
        let message = `${context} failed, please try again later`;

        if (xhr.responseJSON?.detail || xhr.responseJSON?.message) {
            message = xhr.responseJSON.detail || xhr.responseJSON.message;
        } else if (xhr.responseText) {
            message = `Server response: ${xhr.responseText}`;
        } else {
            const errorMap = {
                'timeout': `${context} timeout, please check network connection`,
                0: 'Unable to connect to server, please check network settings',
                404: 'API endpoint does not exist, please check server configuration',
                422: 'Request parameters error, please check input content',
                500: 'Server internal error, possibly configuration issue'
            };
            message = errorMap[status] || errorMap[xhr.status] || message;
        }

        return message;
    },

    createFailHandler(context, customHandler = null) {
        return (xhr, status, error) => {
            AlertManager.hide();
            const message = this.handleError(xhr, status, context);
            AlertManager.showError(`${context} Failed`, message);
            if (customHandler) customHandler();
        };
    }
};

// Alert management
const AlertManager = {
    show(message, type, autoHide = true) {
        const alertHtml = `
            <div class="alert alert-${type} alert-dismissible fade show" role="alert">
                ${message}
                <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
            </div>
        `;

        $('#div_ajax_info').html(alertHtml).show();

        if (autoHide && (type === 'success' || type === 'info')) {
            setTimeout(() => $('#div_ajax_info').fadeOut(), 5000);
        }
    },

    hide() {
        $('#div_ajax_info').hide();
    },

    showLoading(message) {
        this.show(`
            <div class="d-flex align-items-center">
                <div class="spinner-border spinner-border-sm me-2" role="status">
                    <span class="visually-hidden">Loading...</span>
                </div>
                ${message}
            </div>
        `, 'info', false);
    },

    showError(title, message) {
        this.show(`
            <div class="d-flex align-items-center">
                <i class="bi bi-exclamation-triangle-fill me-2"></i>
                <div>
                    <strong>${title}</strong><br>
                    <small>${message}</small>
                </div>
            </div>
        `, 'danger');
    }
};

// Utility functions
const Utils = {
    escapeHtml(text) {
        const map = {
            '&': '&amp;', '<': '&lt;', '>': '&gt;',
            '"': '&quot;', "'": '&#039;'
        };
        return text.replace(/[&<>"']/g, m => map[m]);
    },

    getDomainFromUrl(url) {
        try {
            const domain = new URL(url).hostname;
            return domain.length > 30 ? domain.substring(0, 30) + '...' : domain;
        } catch {
            return 'Unknown Source';
        }
    },

    getFormData() {
        const formData = {
            company_name: $('#company_name').val().trim(),
            lang: $('#lang').val(),
            search_suffix: $('#search_suffix').val(),
            search_engine: $('#search_engine').val(),
            num_results: parseInt($('#num_results').val()),
            llm_model: $('#llm_model').val()
        };

        // Validate LLM model
        if (!SUPPORTED_LLM_MODELS.includes(formData.llm_model)) {
            throw new Error(`LLM model "${formData.llm_model}" is currently unsupported. Please select one of: ${SUPPORTED_LLM_MODELS.join(', ')}`);
        }

        return formData;
    },

    validateSession() {
        if (!AppState.hasSession()) {
            AlertManager.show('Session ID not found, please search again', 'danger');
            return false;
        }
        return true;
    },

    validateResults() {
        if (!AppState.hasResults()) {
            AlertManager.show('No news results found', 'warning');
            return false;
        }
        return true;
    },

    createUrlToIndexMapping() {
        const urlToIndex = {};
        AppState.newsResults.forEach((result, index) => {
            urlToIndex[result.url] = index;
        });
        return urlToIndex;
        return true;
    }
};

$(document).ready(() => initializeApp());

function initializeApp() {
    // Handle VI_DEPLOY configuration
    if (window.VI_DEPLOY) {
        // Hide company name input section
        $('#company_name_section').hide();
        
        // Set company name from URL parameter if provided
        if (window.URL_COMPANY_NAME) {
            $('#company_name').val(window.URL_COMPANY_NAME);
            
            // Add a notification showing the company name being analyzed
            const notification = `
                <div class="alert alert-info alert-dismissible fade show" role="alert">
                    <i class="bi bi-info-circle me-2"></i>
                    <strong>VI Deploy Mode:</strong> Analyzing news for <strong>${window.URL_COMPANY_NAME}</strong>
                    <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
                </div>
            `;
            $('#div_ajax_info').html(notification).show();
        } else {
            // If no company name in URL, show error
            console.warn('VI_DEPLOY mode enabled but no company_name provided in URL');
            const errorNotification = `
                <div class="alert alert-warning alert-dismissible fade show" role="alert">
                    <i class="bi bi-exclamation-triangle me-2"></i>
                    <strong>Warning:</strong> No company name provided in URL. Please add ?company_name=YourCompany to the URL.
                    <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
                </div>
            `;
            $('#div_ajax_info').html(errorNotification).show();
        }
        
        // Remove the required attribute since the field is hidden
        $('#company_name').removeAttr('required');
    }
    
    // Event bindings
    const eventBindings = [
        ['#frm_web_search', 'submit', (e) => { e.preventDefault(); performSearch(); }],
        ['#company_name, #lang', 'change input', () => {
            if ($('#qa_modal').hasClass('show')) setDefaultQAQuery();
        }],
        ['#btn_crawler_submit', 'click', getNewsContent],
        ['#btn_tagging_submit', 'click', performTagging],
        ['#btn_summary_submit', 'click', performSummary],
        ['#btn_qa_submit', 'click', performQA],
        ['#btn_qa', 'click', setDefaultQAQuery],
        ['#llm_model', 'change', handleLLMModelChange]
    ];

    eventBindings.forEach(([selector, event, handler]) => {
        $(selector).on(event, handler);
    });
}

// Handle LLM model selection
function handleLLMModelChange() {
    const selectedModel = $('#llm_model').val();

    if (!SUPPORTED_LLM_MODELS.includes(selectedModel)) {
        AlertManager.show(
            `LLM model "${selectedModel}" is currently not supported. Please select one of: ${SUPPORTED_LLM_MODELS.join(', ')}`,
            'warning'
        );
        // Reset to default supported model
        $('#llm_model').val('gpt-4o');
    }
}

// Search functionality
function performSearch() {
    try {
        const formData = Utils.getFormData();

        if (!formData.company_name) {
            AlertManager.show('Please enter company name', 'danger');
            return;
        }

        hideSearchResults();
        clearPreviousResults();
        UIState.toggleFormInputs(true);

        AjaxHelper.makeRequest({
            url: '/api/search',
            data: formData,
            beforeSend: () => AlertManager.showLoading(
                `Searching for "${formData.company_name}" related news using ${formData.search_engine}, please wait...`
            )
        })
            .done(handleSearchSuccess)
            .fail(AjaxHelper.createFailHandler('Search', () => hideSearchResults()))
            .always(() => {
                UIState.toggleFormInputs(false);
            });
    } catch (error) {
        AlertManager.show(error.message, 'danger');
        UIState.toggleFormInputs(false);
    }
}

function handleSearchSuccess(response) {
    AlertManager.hide();

    if (response.success && response.results?.length > 0) {
        AppState.setSessionId(response.session_id);
        AppState.setNewsResults(response.results);

        displaySearchResults(response.results);
        AlertManager.show(response.message, 'success', false);

        // Show operations and enable Get Content only
        $('#div_operation').show();
        UIState.enableButtons('#btn_crawler');
        UIState.disableButtons('#btn_tagging, #btn_summary, #btn_qa');
    } else {
        AlertManager.show(response.message || 'No related news found', 'warning');
        hideSearchResults();
    }
}

function displaySearchResults(results) {
    const tableHtml = `
        <div class="d-flex justify-content-between align-items-center mb-3">
            <h5 class="mb-0">Search Results</h5>
        </div>
        <div class="table-responsive">
            <table class="table table-striped table-hover" id="news-results-table">
                <thead class="table-dark-blue">
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
                                   title="${Utils.escapeHtml(result.title)}">
                                    ${Utils.escapeHtml(result.title)}
                                </a>
                            </td>
                            <td>
                                <small class="text-muted" title="${result.url}">
                                    ${Utils.getDomainFromUrl(result.url)}
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
    UIState.disableButtons('#btn_crawler, #btn_tagging, #btn_summary, #btn_qa');
}

function clearPreviousResults() {
    // Clear summary results
    $('#div_summary_res').empty().hide();

    // Clear Q&A results  
    $('#div_qa_res').empty().hide();
}

// Content crawling functionality
function getNewsContent() {
    if (!Utils.validateResults() || !Utils.validateSession()) return;

    // Set loading status for all content cells
    $('.content-status').html('<i class="bi bi-hourglass-split text-warning" title="Loading"></i>');

    const requestData = {
        urls: AppState.getUrls(),
        crawler_type: $('#crawler_type').val() || 'playwright:adaptive',
        company_name: $('#company_name').val().trim(),
        lang: $('#lang').val(),
        contents_save: $('#contents_save').prop('checked'),
        contents_load: $('#contents_load').prop('checked'),
        contents_save_days: parseInt($('#contents_save_days').val()),
        contents_load_days: parseInt($('#contents_load_days').val()),
        session_id: AppState.sessionId
    };

    AjaxHelper.makeRequest({
        url: '/api/crawler',
        data: requestData,
        timeout: 120000,
        beforeSend: () => {
            UIState.toggleSubmitButton('#btn_crawler_submit', true);
            AlertManager.showLoading('Getting news full content, please wait...');
        }
    })
        .done((response) => {
            AlertManager.hide();
            handleContentSuccess(response);
        })
        .fail(AjaxHelper.createFailHandler('Content retrieval', () => {
            $('.content-status').html('<i class="bi bi-x-circle-fill text-danger" title="Failed"></i>');
            UIState.disableButtons('#btn_tagging, #btn_summary, #btn_qa');
        }))
        .always(() => {
            UIState.toggleSubmitButton('#btn_crawler_submit', false);
        });
}

function handleContentSuccess(response) {
    if (response.success && response.results) {
        let successCount = 0;
        let failCount = 0;

        // Create URL to index mapping for efficiency
        const urlToIndex = Utils.createUrlToIndexMapping();

        response.results.forEach(result => {
            const index = urlToIndex[result.url];
            const statusCell = $(`.content-status[data-index="${index}"]`);

            if (statusCell.length > 0) {
                if (result.success && result.content) {
                    statusCell.html('<i class="bi bi-check-circle-fill text-success" title="Success"></i>');
                    successCount++;
                } else {
                    const errorMsg = result.error || 'Failed';
                    statusCell.html(`<i class="bi bi-x-circle-fill text-danger" title="${errorMsg}"></i>`);
                    failCount++;
                }
            } else {
                failCount++;
            }
        });

        AlertManager.show(`Content retrieval completed: ${successCount} successful, ${failCount} failed`, 'success', false);

        // Enable other operations only if content was retrieved successfully
        if (successCount > 0) {
            UIState.enableButtons('#btn_tagging, #btn_summary, #btn_qa');
        } else {
            UIState.disableButtons('#btn_tagging, #btn_summary, #btn_qa');
        }
    } else {
        AlertManager.show(response.message || 'Content retrieval failed', 'danger');
        $('.content-status').html('<i class="bi bi-x-circle-fill text-danger" title="Failed"></i>');
        UIState.disableButtons('#btn_tagging, #btn_summary, #btn_qa');
    }
}

// Tagging functionality
function performTagging() {
    if (!Utils.validateResults() || !Utils.validateSession()) return;

    // Remove existing tagging columns first
    removeTaggingColumns();

    const requestData = {
        urls: AppState.getUrls(),
        company_name: $('#company_name').val().trim(),
        lang: $('#lang').val(),
        tagging_method: $('#tagging_method').val(),
        llm_model: $('#llm_model').val(),
        tags_save: $('#tags_save').prop('checked'),
        tags_load: $('#tags_load').prop('checked'),
        tags_save_days: parseInt($('#tags_save_days').val()),
        tags_load_days: parseInt($('#tags_load_days').val()),
        session_id: AppState.sessionId
    };

    AjaxHelper.makeRequest({
        url: '/api/tagging',
        data: requestData,
        timeout: 180000,
        beforeSend: () => {
            UIState.toggleSubmitButton('#btn_tagging_submit', true);
            AlertManager.showLoading('Processing FC tagging, please wait...');
        }
    })
        .done(handleTaggingSuccess)
        .fail((xhr, status, error) => {
            AlertManager.hide();
            const message = AjaxHelper.handleError(xhr, status, 'FC tagging');
            AlertManager.showError('FC Tagging Failed', message);
        })
        .always(() => {
            UIState.toggleSubmitButton('#btn_tagging_submit', false);
        });
}

function removeTaggingColumns() {
    const tableHeader = $('#news-results-table thead tr');
    
    // Remove Crime Type column header if exists
    tableHeader.find('th:contains("Crime Type")').remove();
    
    // Remove Probability column header if exists
    tableHeader.find('th:contains("Probability")').remove();
    
    // Remove corresponding data cells from all rows
    $('#news-results-table tbody tr').each(function() {
        const $row = $(this);
        const cellCount = $row.find('td').length;
        
        // Remove last two cells if they are tagging-related (assuming they are crime-type and probability)
        if (cellCount > 4) { // Original 4 columns: No., Title, Source, Content Status
            $row.find('td.crime-type, td.probability').remove();
            
            // If no specific classes, remove the last two cells
            if ($row.find('td').length > 4) {
                $row.find('td:last').remove();
                $row.find('td:last').remove();
            }
        }
    });
}

function handleTaggingSuccess(response) {
    AlertManager.hide();

    if (response.success && response.results) {
        let successCount = 0;
        let failCount = 0;

        // Add table columns if they don't exist
        const tableHeader = $('#news-results-table thead tr');
        if (!tableHeader.find('th:contains("Crime Type")').length) {
            tableHeader.append('<th scope="col" style="width: 30%">Crime Type</th>');
            tableHeader.append('<th scope="col" style="width: 10%">Probability</th>');
        }

        // Create URL to index mapping for efficiency
        const urlToIndex = Utils.createUrlToIndexMapping();

        response.results.forEach(result => {
            const index = urlToIndex[result.url];
            const row = $(`#news-results-table tbody tr[data-index="${index}"]`);

            if (row.length > 0) {
                // Add new columns to row if they don't exist
                if (row.find('td').length < 6) {
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
                failCount++;
            }
        });

        AlertManager.show(`FC tagging completed: ${successCount} successful, ${failCount} failed`, 'success', false);
    } else {
        AlertManager.show(response.message || 'FC tagging failed', 'danger');
    }
}

// Summary functionality
function performSummary() {
    if (!Utils.validateResults() || !Utils.validateSession()) return;

    // Clear previous summary results
    $('#div_summary_res').empty().hide();

    const requestData = {
        urls: AppState.getUrls(),
        company_name: $('#company_name').val().trim(),
        lang: $('#lang').val(),
        summary_method: $('#summary_method').val(),
        llm_model: $('#llm_model').val(),
        summary_level: $('#summary_level').val(),
        cluster_docs: $('#summary_clus_docs').prop('checked'),
        num_clusters: parseInt($('#summary_num_clus').val()),
        session_id: AppState.sessionId
    };

    AjaxHelper.makeRequest({
        url: '/api/summary',
        data: requestData,
        timeout: 300000,
        beforeSend: () => {
            UIState.toggleSubmitButton('#btn_summary_submit', true);
            AlertManager.showLoading('Generating summary, please wait...');
        }
    })
        .done(handleSummarySuccess)
        .fail((xhr, status, error) => {
            AlertManager.hide();
            const message = AjaxHelper.handleError(xhr, status, 'Summary generation');
            AlertManager.showError('Summary Generation Failed', message);
        })
        .always(() => {
            UIState.toggleSubmitButton('#btn_summary_submit', false);
        });
}

function handleSummarySuccess(response) {
    AlertManager.hide();

    if (response.success && response.summary) {
        displaySummaryResult(response.summary);
        AlertManager.show(response.message || 'Summary generated successfully', 'success', false);
    } else {
        AlertManager.show(response.message || 'Summary generation failed', 'danger');
    }
}

function displaySummaryResult(summary) {
    const summaryHtml = `
        <div class="p-3">
            <h5 class="mb-3">
                <i class="bi bi-file-text me-2"></i>
                Summary Results
            </h5>
            <div class="border rounded p-3 bg-white">
                <div class="summary-content" style="white-space: pre-wrap; line-height: 1.6;">
                    ${Utils.escapeHtml(summary)}
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

// QA functionality
function performQA() {
    if (!Utils.validateResults() || !Utils.validateSession()) return;

    const question = $('#ta_qa_query').val().trim();
    if (!question) {
        AlertManager.show('Please enter a question', 'warning');
        return;
    }

    const requestData = {
        question: question,
        company_name: $('#company_name').val().trim(),
        lang: $('#lang').val(),
        urls: AppState.getUrls(),
        llm_model: $('#llm_model').val(),
        session_id: AppState.sessionId
    };

    AjaxHelper.makeRequest({
        url: '/api/qa',
        data: requestData,
        timeout: 300000,
        beforeSend: () => {
            UIState.toggleSubmitButton('#btn_qa_submit', true);
            AlertManager.showLoading('Processing Q&A request, please wait...');
        }
    })
        .done(handleQASuccess)
        .fail((xhr, status, error) => {
            AlertManager.hide();
            const message = AjaxHelper.handleError(xhr, status, 'Q&A processing');
            AlertManager.showError('Q&A Processing Failed', message);
        })
        .always(() => {
            UIState.toggleSubmitButton('#btn_qa_submit', false);
        });
}

function handleQASuccess(response) {
    AlertManager.hide();

    if (response.success && response.answer) {
        displayQAResult(response.question, response.answer, response.urls || []);
        AlertManager.show(response.message || 'Q&A processing successful', 'success', false);
    } else {
        AlertManager.show(response.message || 'Q&A processing failed - no answer received', 'danger');
    }
}

function displayQAResult(question, answer, urls = []) {
    // Create sources HTML if URLs are provided
    let sourcesHtml = '';
    if (urls && urls.length > 0) {
        const sourceLinks = urls.map((url, index) => {
            const domain = Utils.getDomainFromUrl(url);
            return `<a href="${url}" target="_blank" rel="noopener noreferrer" class="text-decoration-none">
                        <span class="badge bg-secondary me-1">${index + 1}</span>
                        ${domain}
                    </a>`;
        }).join(' ');
        
        sourcesHtml = `
            <div class="sources mt-2 pt-2 border-top">
                <small class="text-muted">
                    <i class="bi bi-link-45deg me-1"></i>
                    <strong>Sources:</strong>
                </small>
                <div class="mt-1">
                    ${sourceLinks}
                </div>
            </div>
        `;
    }

    const qaHtml = `
        <div class="qa-item mb-3 p-3 border rounded">
            <div class="question mb-2">
                <strong class="text-primary">Q: </strong>
                <span>${Utils.escapeHtml(question)}</span>
            </div>
            <div class="answer">
                <strong class="text-success">A: </strong>
                <span style="white-space: pre-wrap; line-height: 1.6;">${Utils.escapeHtml(answer)}</span>
            </div>
            ${sourcesHtml}
            <div class="mt-2">
                <small class="text-muted">
                    <i class="bi bi-clock me-1"></i>
                    ${new Date().toLocaleString()}
                </small>
            </div>
        </div>
    `;

    const qaDiv = $('#div_qa_res');
    
    if (qaDiv.is(':hidden')) {
        qaDiv.show().html(`
            <div class="p-3">
                <h5 class="mb-3">
                    <i class="bi bi-question-circle me-2"></i>
                    Q&A Results
                </h5>
                <div class="qa-content">${qaHtml}</div>
            </div>
        `);
    } else {
        qaDiv.find('.qa-content').append(qaHtml);
    }

    // Scroll to newly added content
    qaDiv.find('.qa-item').last()[0].scrollIntoView({
        behavior: 'smooth',
        block: 'nearest'
    });
}

function setDefaultQAQuery() {
    const companyName = $('#company_name').val().trim();
    const lang = $('#lang').val();

    if (!companyName) {
        $('#ta_qa_query').val('');
        return;
    }

    const queryTemplates = {
        'zh-CN': `${companyName}的负面新闻有哪些？依次列出。`,
        'zh-HK': `${companyName}的負面新聞有哪些？依次列出。`,
        'zh-TW': `${companyName}的負面新聞有哪些？依次列出。`,
        'en-US': `What are the negative news about ${companyName}? Please list them in order.`,
        'ja-JP': `${companyName}のネガティブなニュースは何ですか？順番に列挙してください。`
    };

    const defaultQuery = queryTemplates[lang] || queryTemplates['en-US'];
    $('#ta_qa_query').val(defaultQuery);
}

// Export functions for global access (maintaining backward compatibility)
Object.assign(window, {
    performSearch,
    getNewsContent,
    performTagging,
    performSummary,
    performQA,
    setDefaultQAQuery,
    // Legacy support
    showAlert: AlertManager.show,
    hideAlert: AlertManager.hide
});