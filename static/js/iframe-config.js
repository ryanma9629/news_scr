// IFRAME-specific configuration and utilities for cross-origin embedding
window.IFrameUtils = {
    // Check if running inside an IFRAME
    isInIFrame: function() {
        try {
            return window.self !== window.top;
        } catch (e) {
            return true;
        }
    },

    // Post message to parent window
    postToParent: function(data) {
        if (this.isInIFrame()) {
            window.parent.postMessage(data, '*');
        }
    },

    // Handle IFRAME-specific styling
    applyIFrameStyles: function() {
        if (this.isInIFrame()) {
            document.body.style.margin = '0';
            document.body.style.padding = '10px';
            document.body.style.overflow = 'auto';
            
            // Adjust container styling for IFRAME
            const container = document.querySelector('.container');
            if (container) {
                container.style.maxWidth = '100%';
                container.style.padding = '10px';
            }
            
            // Add IFRAME-specific CSS class
            document.body.classList.add('iframe-mode');
        }
    },

    // Communicate height changes to parent
    updateHeight: function() {
        if (this.isInIFrame()) {
            const height = Math.max(
                document.body.scrollHeight,
                document.body.offsetHeight,
                document.documentElement.clientHeight,
                document.documentElement.scrollHeight,
                document.documentElement.offsetHeight
            );
            this.postToParent({
                type: 'iframe-height-update',
                height: height
            });
        }
    },

    // Handle cookie consent for IFRAME embedding
    handleCookieConsent: function() {
        if (this.isInIFrame()) {
            // For IFRAME embedding with SameSite=None, we need Secure cookies
            // This is automatically handled by the server configuration
            console.log('IFRAME detected: Cookie policies applied for cross-origin embedding');
        }
    },

    // Test if cookies are working in IFRAME context
    testCookieSupport: function() {
        if (this.isInIFrame()) {
            // Test if we can set/read cookies
            const testCookieName = 'iframe_cookie_test';
            const testCookieValue = 'test_' + Date.now();
            
            // Try to set a test cookie
            document.cookie = `${testCookieName}=${testCookieValue}; SameSite=None; Secure=${location.protocol === 'https:'}; path=/`;
            
            // Check if we can read it back
            const cookieSupported = document.cookie.includes(`${testCookieName}=${testCookieValue}`);
            
            if (!cookieSupported) {
                this.postToParent({
                    type: 'cookie-warning',
                    message: 'Cookies may not work properly in this IFRAME. Some features may be limited.'
                });
                
                // Show a warning to the user
                console.warn('Cookie support limited in IFRAME context');
            }
            
            // Clean up test cookie
            document.cookie = `${testCookieName}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; SameSite=None; Secure=${location.protocol === 'https:'}; path=/`;
            
            return cookieSupported;
        }
        return true;
    },

    // Initialize IFRAME utilities
    init: function() {
        if (this.isInIFrame()) {
            console.log('IFRAME mode detected, applying configurations...');
            
            this.applyIFrameStyles();
            this.handleCookieConsent();
            this.testCookieSupport();
            
            // Update height on content changes
            const observer = new MutationObserver(() => {
                this.updateHeight();
            });
            
            observer.observe(document.body, {
                childList: true,
                subtree: true,
                attributes: true
            });

            // Update height on window resize
            window.addEventListener('resize', () => {
                this.updateHeight();
            });

            // Initial height update (delayed to ensure DOM is ready)
            setTimeout(() => this.updateHeight(), 100);
            setTimeout(() => this.updateHeight(), 500);
            setTimeout(() => this.updateHeight(), 1000);
        }
    }
};

// Auto-initialize when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    window.IFrameUtils.init();
});

// Also initialize immediately if DOM is already loaded
if (document.readyState === 'loading') {
    // Still loading, wait for DOMContentLoaded
} else {
    // DOM is already loaded
    window.IFrameUtils.init();
}
