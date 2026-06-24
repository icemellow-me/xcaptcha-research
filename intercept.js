/**
 * Example: Intercept and log all fetch/XHR requests from the proxied page.
 * 
 * Drop this file and run:
 *   python3 proxy.py --inject intercept.js
 * 
 * All fetch() and XMLHttpRequest calls will be logged to console
 * AND stored in window.__interceptedRequests for later inspection.
 */

(function() {
    'use strict';
    
    window.__interceptedRequests = [];
    
    // ─── Intercept fetch() ─────────────────────────────────────
    const origFetch = window.fetch;
    window.fetch = async function(...args) {
        const url = typeof args[0] === 'string' ? args[0] : args[0]?.url;
        const opts = args[1] || {};
        const method = opts.method || 'GET';
        const headers = {};
        
        if (opts.headers) {
            if (opts.headers instanceof Headers) {
                opts.headers.forEach((v, k) => headers[k] = v);
            } else if (typeof opts.headers === 'object') {
                Object.assign(headers, opts.headers);
            }
        }
        
        const entry = {
            time: Date.now(),
            method: method,
            url: url,
            headers: headers,
            body: opts.body ? opts.body.toString().substring(0, 1000) : null,
            type: 'fetch'
        };
        
        window.__interceptedRequests.push(entry);
        console.log('[INTERCEPTOR] fetch:', method, url);
        
        const response = await origFetch.apply(this, args);
        
        try {
            const clone = response.clone();
            const text = await clone.text();
            window.__interceptedRequests.push({
                time: Date.now(),
                url: url,
                status: response.status,
                responseText: text.substring(0, 2000),
                type: 'response'
            });
            console.log('[INTERCEPTOR] response:', response.status, url);
        } catch(e) {}
        
        return response;
    };
    
    // ─── Intercept XMLHttpRequest ───────────────────────────────
    const origXHROpen = XMLHttpRequest.prototype.open;
    const origXHRSend = XMLHttpRequest.prototype.send;
    
    XMLHttpRequest.prototype.open = function(method, url, ...rest) {
        this.__url = url;
        this.__method = method;
        this.__headers = {};
        return origXHROpen.call(this, method, url, ...rest);
    };
    
    XMLHttpRequest.prototype.setRequestHeader = function(name, value) {
        this.__headers[name] = value;
        return XMLHttpRequest.prototype.setRequestHeader.call(this, name, value);
    };
    
    XMLHttpRequest.prototype.send = function(body) {
        window.__interceptedRequests.push({
            time: Date.now(),
            method: this.__method,
            url: this.__url?.substring(0, 500),
            headers: this.__headers,
            body: body ? body.toString().substring(0, 1000) : null,
            type: 'xhr'
        });
        console.log('[INTERCEPTOR] XHR:', this.__method, this.__url);
        return origXHRSend.call(this, body);
    };
    
    // ─── Intercept WebSocket ────────────────────────────────────
    const origWS = window.WebSocket;
    window.WebSocket = function(url, protocols) {
        console.log('[INTERCEPTOR] WebSocket:', url);
        const ws = protocols ? new origWS(url, protocols) : new origWS(url);
        
        const origSend = ws.send.bind(ws);
        ws.send = function(data) {
            window.__interceptedRequests.push({
                time: Date.now(),
                url: url,
                data: typeof data === 'string' ? data.substring(0, 1000) : '[binary]',
                type: 'ws_send'
            });
            console.log('[INTERCEPTOR] WS send:', typeof data === 'string' ? data.substring(0, 200) : '[binary]');
            return origSend(data);
        };
        
        ws.addEventListener('message', (event) => {
            window.__interceptedRequests.push({
                time: Date.now(),
                url: url,
                data: typeof event.data === 'string' ? event.data.substring(0, 1000) : '[binary]',
                type: 'ws_recv'
            });
            console.log('[INTERCEPTOR] WS recv:', typeof event.data === 'string' ? event.data.substring(0, 200) : '[binary]');
        });
        
        return ws;
    };
    window.WebSocket.prototype = origWS.prototype;
    window.WebSocket.CONNECTING = origWS.CONNECTING;
    window.WebSocket.OPEN = origWS.OPEN;
    window.WebSocket.CLOSING = origWS.CLOSING;
    window.WebSocket.CLOSED = origWS.CLOSED;
    
    console.log('[INTERCEPTOR] ✅ Request interceptor installed');
})();
