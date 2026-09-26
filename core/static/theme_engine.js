/**
 * OPB Super-App Dynamic Multi-Theme & Ultra-Rich Aesthetic Engine (v4.0)
 * Provides institutional fintech design tokens, dynamic theme switching,
 * WCAG-compliant contrast ratios, modern typography (Inter / Plus Jakarta Sans / JetBrains Mono),
 * responsive micro-animations, and full semantic component abstractions.
 */
(function() {
    'use strict';

    const THEMES = {
        'dark-cyber': {
            name: '🌌 Dark Cyber (Dark)',
            type: 'dark',
            vars: {
                '--bg-primary': '#080c14',
                '--bg-secondary': '#0f172a',
                '--bg-card': '#131e33',
                '--bg-card-hover': '#182744',
                '--text-primary': '#f8fafc',
                '--text-secondary': '#cbd5e1',
                '--text-muted': '#94a3b8',
                '--border-color': '#1e293b',
                '--border-color-hover': '#38bdf8',
                '--accent-color': '#38bdf8',
                '--accent-gradient': 'linear-gradient(135deg, #0284c7 0%, #2563eb 50%, #7c3aed 100%)',
                '--btn-primary-text': '#080c14',
                '--nav-active-text': '#082f49',
                '--success-color': '#22c55e',
                '--warning-color': '#f59e0b',
                '--danger-color': '#f87171',
                '--card-shadow': '0 20px 40px -15px rgba(0, 0, 0, 0.7)',
                '--input-bg': '#0b1120',
                '--input-border': '#1e293b',
                '--header-glow': 'rgba(56, 189, 248, 0.15)',
                '--notification-success': '#10b981',
                '--notification-warning': '#f59e0b',
                '--notification-danger': '#ef4444',
                '--notification-info': '#38bdf8',
                '--notification-neutral': '#94a3b8',
                '--notification-signal': '#10b981',
                '--notification-border': '#1e293b',
                '--notification-surface': '#131e33',
                '--notification-muted-text': '#94a3b8'
            }
        },
        'dracula-purple': {
            name: '🟣 Dracula Purple (Light)',
            type: 'light',
            vars: {
                '--bg-primary': '#faf7fc',
                '--bg-secondary': '#f2ecf8',
                '--bg-card': '#ffffff',
                '--bg-card-hover': '#f8f1fb',
                '--text-primary': '#24172b',
                '--text-secondary': '#4c3a57',
                '--text-muted': '#6b5a75',
                '--border-color': '#d8cbe2',
                '--border-color-hover': '#7c3aed',
                '--accent-color': '#7c3aed',
                '--accent-gradient': 'linear-gradient(135deg, #7c3aed 0%, #db2777 100%)',
                '--btn-primary-text': '#ffffff',
                '--nav-active-text': '#ffffff',
                '--success-color': '#15803d',
                '--warning-color': '#92400e',
                '--danger-color': '#b91c1c',
                '--card-shadow': '0 4px 20px -4px rgba(76, 58, 87, 0.08), 0 0 0 1px #e3d9ea',
                '--input-bg': '#ffffff',
                '--input-border': '#a78bb8',
                '--header-glow': 'rgba(124, 58, 237, 0.10)',
                '--notification-success': '#15803d',
                '--notification-warning': '#b45309',
                '--notification-danger': '#b91c1c',
                '--notification-info': '#7c3aed',
                '--notification-neutral': '#6b5a75',
                '--notification-signal': '#15803d',
                '--notification-border': '#d8cbe2',
                '--notification-surface': '#ffffff',
                '--notification-muted-text': '#6b5a75'
            }
        },
        'ivory-gold': {
            name: '🏛️ Ivory Gold (Light)',
            type: 'light',
            vars: {
                '--bg-primary': '#f5f0e6',
                '--bg-secondary': '#ede4d4',
                '--bg-card': '#ffffff',
                '--bg-card-hover': '#faf6ee',
                '--text-primary': '#1c1917',
                '--text-secondary': '#292524',
                '--text-muted': '#57534e',
                '--border-color': '#d6cbba',
                '--border-color-hover': '#92400e',
                '--accent-color': '#92400e',
                '--accent-gradient': 'linear-gradient(135deg, #d97706 0%, #b45309 100%)',
                '--btn-primary-text': '#ffffff',
                '--nav-active-text': '#ffffff',
                '--success-color': '#15803d',
                '--warning-color': '#92400e',
                '--danger-color': '#b91c1c',
                '--card-shadow': '0 4px 20px -2px rgba(68, 64, 60, 0.08), 0 0 0 1px #d6cbba',
                '--input-bg': '#ffffff',
                '--input-border': '#a89f91',
                '--header-glow': 'rgba(217, 119, 6, 0.1)',
                '--notification-success': '#15803d',
                '--notification-warning': '#b45309',
                '--notification-danger': '#b91c1c',
                '--notification-info': '#92400e',
                '--notification-neutral': '#57534e',
                '--notification-signal': '#15803d',
                '--notification-border': '#d6cbba',
                '--notification-surface': '#ffffff',
                '--notification-muted-text': '#57534e'
            }
        },
        'midnight-slate': {
            name: '🌑 Midnight Slate (Light)',
            type: 'light',
            vars: {
                '--bg-primary': '#f6f8fb',
                '--bg-secondary': '#eaf0f6',
                '--bg-card': '#ffffff',
                '--bg-card-hover': '#f0f5fa',
                '--text-primary': '#0f172a',
                '--text-secondary': '#334155',
                '--text-muted': '#54667a',
                '--border-color': '#cbd5e1',
                '--border-color-hover': '#1d4ed8',
                '--accent-color': '#1d4ed8',
                '--accent-gradient': 'linear-gradient(135deg, #1d4ed8 0%, #0ea5e9 100%)',
                '--btn-primary-text': '#ffffff',
                '--nav-active-text': '#ffffff',
                '--success-color': '#15803d',
                '--warning-color': '#92400e',
                '--danger-color': '#b91c1c',
                '--card-shadow': '0 4px 18px -4px rgba(15, 23, 42, 0.08), 0 0 0 1px #dbe3ec',
                '--input-bg': '#ffffff',
                '--input-border': '#94a3b8',
                '--header-glow': 'rgba(29, 78, 216, 0.10)',
                '--notification-success': '#15803d',
                '--notification-warning': '#b45309',
                '--notification-danger': '#b91c1c',
                '--notification-info': '#1d4ed8',
                '--notification-neutral': '#54667a',
                '--notification-signal': '#15803d',
                '--notification-border': '#cbd5e1',
                '--notification-surface': '#ffffff',
                '--notification-muted-text': '#54667a'
            }
        },
        'emerald-matrix': {
            name: '❇️ Emerald Matrix (Dark)',
            type: 'dark',
            vars: {
                '--bg-primary': '#020d07',
                '--bg-secondary': '#061d13',
                '--bg-card': '#0a2c1d',
                '--bg-card-hover': '#103d29',
                '--text-primary': '#ecfdf5',
                '--text-secondary': '#a7f3d0',
                '--text-muted': '#6ee7b7',
                '--border-color': '#14533a',
                '--border-color-hover': '#10b981',
                '--accent-color': '#10b981',
                '--accent-gradient': 'linear-gradient(135deg, #34d399 0%, #059669 100%)',
                '--btn-primary-text': '#020d07',
                '--nav-active-text': '#020d07',
                '--success-color': '#34d399',
                '--warning-color': '#fbbf24',
                '--danger-color': '#f87171',
                '--card-shadow': '0 20px 40px -15px rgba(3, 18, 11, 0.7)',
                '--input-bg': '#051b11',
                '--input-border': '#14533a',
                '--header-glow': 'rgba(16, 185, 129, 0.15)',
                '--notification-success': '#34d399',
                '--notification-warning': '#fbbf24',
                '--notification-danger': '#f87171',
                '--notification-info': '#10b981',
                '--notification-neutral': '#6ee7b7',
                '--notification-signal': '#34d399',
                '--notification-border': '#14533a',
                '--notification-surface': '#0a2c1d',
                '--notification-muted-text': '#6ee7b7'
            }
        }
    };

    function injectRichStyles() {
        if (document.getElementById('opb-rich-styles')) {
            document.getElementById('opb-rich-styles').remove();
        }
        const style = document.createElement('style');
        style.id = 'opb-rich-styles';
        style.innerHTML = `
            body {
                font-family: 'Inter', 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif !important;
                font-feature-settings: 'cv02' 1, 'cv03' 1, 'cv04' 1, 'cv11' 1, 'tnum' 1, 'zero' 1 !important;
                background-color: var(--bg-primary, #080c14) !important;
                color: var(--text-primary, #f8fafc) !important;
                transition: background-color 0.25s ease, color 0.25s ease;
            }

            ::-webkit-scrollbar { width: 8px; height: 8px; }
            ::-webkit-scrollbar-track { background: var(--bg-primary, #080c14); }
            ::-webkit-scrollbar-thumb { background: var(--border-color, #1e293b); border-radius: 4px; }
            ::-webkit-scrollbar-thumb:hover { background: var(--accent-color, #38bdf8); }

            /* ── Core Container & Card Tokens ────────────────────────────── */
            .card, .login-card, div[class*="stat-card"], .stat-card {
                background-color: var(--bg-card, #131e33) !important;
                border: 1px solid var(--border-color, #1e293b) !important;
                color: var(--text-primary, #f8fafc) !important;
                box-shadow: var(--card-shadow) !important;
            }

            /* ── Form Inputs & Controls ─────────────────────────────────── */
            .input-control, .input-field, input[type="text"], input[type="password"], input[type="number"], select, textarea, .reason-input {
                background-color: var(--input-bg, #0b1120) !important;
                border: 1px solid var(--input-border, #1e293b) !important;
                color: var(--text-primary, #f8fafc) !important;
            }

            .input-control:focus, .input-field:focus, input:focus, select:focus, textarea:focus, .reason-input:focus {
                border-color: var(--accent-color, #38bdf8) !important;
            }

            /* ── Typography & Headings ──────────────────────────────────── */
            .login-title, h1, h2, h3, h4, h5, h6 {
                color: var(--text-primary, #f8fafc) !important;
            }

            .login-subtitle, .subtitle, .input-label, label, p, .text-muted {
                color: var(--text-muted, #94a3b8) !important;
            }

            .stat-value {
                color: var(--text-primary, #f8fafc) !important;
                font-family: 'JetBrains Mono', 'Inter', monospace !important;
                font-feature-settings: 'tnum' 1, 'zero' 1 !important;
            }

            .stat-label {
                color: var(--text-muted, #94a3b8) !important;
                font-weight: 700 !important;
                letter-spacing: 0.04em !important;
            }

            /* ── Universal Semantic Badges ──────────────────────────────── */
            .badge, .opb-badge {
                font-family: 'JetBrains Mono', monospace !important;
                font-weight: 700 !important;
            }

            .badge-ok, .badge-active, .badge-buy {
                background: rgba(34, 197, 94, 0.14) !important;
                color: var(--success-color, #22c55e) !important;
                border: 1px solid var(--success-color, #22c55e) !important;
            }

            .badge-critical, .badge-halt, .badge-sell {
                background: rgba(239, 68, 68, 0.14) !important;
                color: var(--danger-color, #ef4444) !important;
                border: 1px solid var(--danger-color, #ef4444) !important;
            }

            .badge-warning, .badge-hold {
                background: rgba(245, 158, 11, 0.14) !important;
                color: var(--warning-color, #f59e0b) !important;
                border: 1px solid var(--warning-color, #f59e0b) !important;
            }

            /* ── Navigation Components ───────────────────────────────────── */
            .opb-nav-top {
                background: var(--bg-card, #131e33) !important;
                border: 1px solid var(--border-color, #1e293b) !important;
                box-shadow: var(--card-shadow) !important;
            }

            .opb-nav-workspaces {
                background: var(--bg-secondary, #0f172a) !important;
                border: 1px solid var(--border-color, #1e293b) !important;
                box-shadow: var(--card-shadow) !important;
            }

            .opb-nav-links-bar {
                background: var(--bg-secondary, #0f172a) !important;
                border: 1px solid var(--border-color, #1e293b) !important;
                box-shadow: var(--card-shadow) !important;
            }

            .opb-user-badge {
                background: var(--bg-secondary, #0f172a) !important;
                border: 1px solid var(--border-color, #1e293b) !important;
                color: var(--text-primary, #f8fafc) !important;
            }

            .opb-ws-btn {
                color: var(--text-secondary, #94a3b8) !important;
            }

            .opb-ws-btn:hover {
                color: var(--accent-color, #38bdf8) !important;
                background: var(--bg-card-hover) !important;
            }

            .opb-ws-group.active .opb-ws-btn {
                color: var(--accent-color, #38bdf8) !important;
                background: var(--bg-card) !important;
                border-color: var(--accent-color, #38bdf8) !important;
            }

            .opb-ws-item {
                color: var(--text-primary, #f8fafc) !important;
            }

            .opb-ws-item:hover {
                background: var(--bg-card-hover, rgba(56, 189, 248, 0.12)) !important;
            }

            .opb-nav-links-bar a, .opb-nav-link {
                color: var(--text-secondary, #94a3b8) !important;
                transition: all 0.2s ease !important;
            }

            .opb-nav-links-bar a:hover, .opb-nav-link:hover {
                color: var(--accent-color, #38bdf8) !important;
            }

            .opb-nav-links-bar span {
                color: var(--text-muted, #64748b) !important;
            }

            /* ── PWA & Details Banners ───────────────────────────────────── */
            details, .pwa-install-banner {
                background: var(--bg-card, #131e33) !important;
                border: 1px solid var(--border-color, #1e293b) !important;
                color: var(--text-secondary, #cbd5e1) !important;
                box-shadow: var(--card-shadow) !important;
            }

            details summary, .pwa-install-banner summary {
                color: var(--accent-color, #38bdf8) !important;
                font-weight: 700 !important;
            }

            details p, details div, details ol, details li {
                color: var(--text-secondary, #cbd5e1) !important;
            }

            /* ── Tabs & Quick Navigation ─────────────────────────────────── */
            .tab-bar .tab, .tab {
                background: var(--bg-card, #131e33) !important;
                border: 1px solid var(--border-color, #1e293b) !important;
                color: var(--text-muted, #94a3b8) !important;
                font-weight: 600 !important;
            }

            .tab-bar .tab.active, .tab.active {
                background: var(--bg-card-hover, rgba(56, 189, 248, 0.15)) !important;
                border-color: var(--accent-color, #38bdf8) !important;
                color: var(--accent-color, #38bdf8) !important;
                font-weight: 700 !important;
            }

            .quick-link {
                background: var(--bg-card, #131e33) !important;
                border: 1px solid var(--border-color, #1e293b) !important;
                color: var(--text-secondary, #cbd5e1) !important;
                box-shadow: var(--card-shadow) !important;
            }

            .quick-link:hover {
                border-color: var(--accent-color, #38bdf8) !important;
                color: var(--accent-color, #38bdf8) !important;
                background: var(--bg-card-hover, #182744) !important;
                transform: translateY(-2px) !important;
            }

            /* ── Strategy Flyout & Badges ────────────────────────────────── */
            .opb-strategies-flyout {
                background: var(--bg-card, #131e33) !important;
                border: 1px solid var(--border-color, #1e293b) !important;
                color: var(--text-primary, #f8fafc) !important;
                box-shadow: var(--card-shadow, 0 20px 50px rgba(0,0,0,0.85)) !important;
            }

            .strat-item {
                background: var(--bg-secondary, #0f172a) !important;
                border: 1px solid var(--border-color, #1e293b) !important;
            }

            .strat-title {
                color: var(--text-primary, #f8fafc) !important;
            }

            .strat-desc {
                color: var(--text-secondary, #94a3b8) !important;
            }

            /* ── Tables & Data Grids ─────────────────────────────────────── */
            table, tr, td, th {
                border-color: var(--border-color, #1e293b) !important;
            }

            th {
                background: var(--bg-secondary, #0f172a) !important;
                color: var(--text-muted, #94a3b8) !important;
            }

            td {
                color: var(--text-secondary, #cbd5e1) !important;
            }

            tr:hover td {
                background: var(--bg-card-hover, rgba(56, 189, 248, 0.05)) !important;
            }

            /* ── Emergency Kill Switch Button ───────────────────────────── */
            .opb-emergency-kill-btn {
                display: inline-flex !important;
                align-items: center !important;
                gap: 0.4rem !important;
                background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%) !important;
                color: #ffffff !important;
                border: 1px solid #b91c1c !important;
                padding: 0.32rem 0.85rem !important;
                border-radius: 0.5rem !important;
                font-size: 0.75rem !important;
                font-weight: 800 !important;
                letter-spacing: 0.05em !important;
                text-transform: uppercase !important;
                cursor: pointer !important;
                transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1) !important;
                text-decoration: none !important;
                box-shadow: 0 2px 10px rgba(220, 38, 38, 0.45) !important;
                white-space: nowrap !important;
                line-height: 1.2 !important;
            }

            .opb-emergency-kill-btn:hover {
                background: linear-gradient(135deg, #f87171 0%, #b91c1c 100%) !important;
                color: #ffffff !important;
                box-shadow: 0 4px 16px rgba(220, 38, 38, 0.65), 0 0 12px rgba(239, 68, 68, 0.5) !important;
                transform: translateY(-1px) scale(1.02) !important;
                border-color: #ef4444 !important;
            }

            .opb-emergency-kill-btn:active {
                transform: translateY(0) scale(0.98) !important;
            }

            /* ── Theme Selectors & Status Dock ───────────────────────────── */
            .top-theme-dock {
                background: var(--bg-card, #131e33) !important;
                border: 1px solid var(--border-color, #1e293b) !important;
            }

            .system-status-dock {
                position: fixed !important;
                bottom: 1.5rem !important;
                left: 50% !important;
                transform: translateX(-50%) !important;
                display: flex !important;
                align-items: center !important;
                gap: 0.6rem !important;
                background: var(--bg-card, #131e33) !important;
                border: 1px solid var(--border-color, #1e293b) !important;
                padding: 0.45rem 1rem !important;
                border-radius: 9999px !important;
                font-size: 0.75rem !important;
                font-weight: 600 !important;
                color: var(--text-muted, #94a3b8) !important;
                box-shadow: var(--card-shadow, 0 10px 25px -5px rgba(0, 0, 0, 0.3)) !important;
                backdrop-filter: blur(12px) !important;
                -webkit-backdrop-filter: blur(12px) !important;
                z-index: 20 !important;
                pointer-events: none !important;
                white-space: nowrap !important;
                letter-spacing: 0.02em !important;
            }

            /* ── Universal Multi-Theme Toast & Popup System ──────────────────────── */
            #opb-toast-container {
                position: fixed;
                top: 1.5rem;
                right: 1.5rem;
                z-index: 999999;
                display: flex;
                flex-direction: column;
                gap: 0.75rem;
                max-width: 420px;
                width: calc(100vw - 3rem);
                pointer-events: none;
            }

            .opb-toast {
                pointer-events: auto;
                position: relative;
                background: var(--bg-card, #131e33);
                border: 1px solid var(--border-color, #1e293b);
                border-radius: 0.85rem;
                box-shadow: var(--card-shadow, 0 20px 40px -15px rgba(0, 0, 0, 0.7));
                backdrop-filter: blur(16px);
                -webkit-backdrop-filter: blur(16px);
                padding: 1rem 1.25rem;
                display: flex;
                gap: 0.85rem;
                align-items: flex-start;
                overflow: hidden;
                transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
                animation: opbToastSlideIn 0.35s cubic-bezier(0.16, 1, 0.3, 1);
            }

            .opb-toast.opb-toast-leaving {
                opacity: 0;
                transform: translateX(100%) scale(0.95);
            }

            .opb-toast-icon {
                font-size: 1.25rem;
                line-height: 1;
                margin-top: 0.1rem;
                flex-shrink: 0;
            }

            .opb-toast-content {
                flex: 1;
                min-width: 0;
            }

            .opb-toast-title {
                font-size: 0.9rem;
                font-weight: 700;
                color: var(--text-primary, #ffffff);
                margin-bottom: 0.25rem;
                letter-spacing: -0.01em;
            }

            .opb-toast-message {
                font-size: 0.825rem;
                color: var(--text-secondary, #cbd5e1);
                line-height: 1.45;
                word-break: break-word;
            }

            .opb-toast-close {
                background: transparent;
                border: none;
                color: var(--text-muted, #94a3b8);
                cursor: pointer;
                font-size: 0.85rem;
                padding: 0.25rem;
                margin: -0.25rem -0.25rem 0 0;
                line-height: 1;
                border-radius: 0.35rem;
                transition: color 0.2s, background-color 0.2s;
            }

            .opb-toast-close:hover {
                color: var(--text-primary, #ffffff);
                background: rgba(255, 255, 255, 0.08);
            }

            .opb-modal-close-btn, #opb-modal-close-btn {
                background: var(--bg-secondary, #1e293b) !important;
                border: 1px solid var(--border-color, #334155) !important;
                color: var(--text-primary, #f8fafc) !important;
                cursor: pointer !important;
                font-size: 1.25rem !important;
                font-weight: 700 !important;
                width: 44px !important;
                height: 44px !important;
                min-width: 44px !important;
                min-height: 44px !important;
                flex-shrink: 0 !important;
                box-sizing: border-box !important;
                display: inline-flex !important;
                align-items: center !important;
                justify-content: center !important;
                border-radius: 0.5rem !important;
                padding: 0 !important;
                margin: 0 !important;
                line-height: 1 !important;
                transition: color 0.15s ease, background-color 0.15s ease, border-color 0.15s ease !important;
            }

            .opb-modal-close-btn:hover, #opb-modal-close-btn:hover,
            .opb-modal-close-btn:focus-visible, #opb-modal-close-btn:focus-visible {
                color: #ffffff !important;
                background: var(--danger-color, #ef4444) !important;
                border-color: var(--danger-color, #ef4444) !important;
            }

            .opb-ws-group.menu-closed .opb-ws-dropdown {
                visibility: hidden !important;
                opacity: 0 !important;
                pointer-events: none !important;
            }

            .opb-toast-progress {
                position: absolute;
                bottom: 0;
                left: 0;
                height: 3px;
                background: currentColor;
                opacity: 0.5;
                width: 100%;
                transform-origin: left;
            }

            .opb-toast-error {
                border-color: var(--danger-color, #ef4444);
                color: var(--danger-color, #ef4444);
            }
            .opb-toast-error .opb-toast-icon { color: var(--danger-color, #ef4444); }

            .opb-toast-success {
                border-color: var(--success-color, #22c55e);
                color: var(--success-color, #22c55e);
            }
            .opb-toast-success .opb-toast-icon { color: var(--success-color, #22c55e); }

            .opb-toast-warning {
                border-color: var(--warning-color, #f59e0b);
                color: var(--warning-color, #f59e0b);
            }
            .opb-toast-warning .opb-toast-icon { color: var(--warning-color, #f59e0b); }

            .opb-toast-info {
                border-color: var(--accent-color, #38bdf8);
                color: var(--accent-color, #38bdf8);
            }
            .opb-toast-info .opb-toast-icon { color: var(--accent-color, #38bdf8); }

            @keyframes opbToastSlideIn {
                0% { opacity: 0; transform: translateX(100%) scale(0.9); }
                100% { opacity: 1; transform: translateX(0) scale(1); }
            }

            /* ── Universal Multi-Theme Modal System ──────────────────────────────── */
            .opb-modal-backdrop {
                position: fixed;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                background: rgba(0, 0, 0, 0.65);
                backdrop-filter: none;
                -webkit-backdrop-filter: none;
                z-index: 1000000;
                display: none;
                align-items: center;
                justify-content: center;
                padding: 1.5rem;
                opacity: 0;
                pointer-events: none;
                transition: opacity 0.25s ease;
            }

            .opb-modal-backdrop.opb-modal-active,
            .opb-modal-backdrop.active {
                display: flex !important;
                opacity: 1 !important;
                pointer-events: auto !important;
                backdrop-filter: blur(8px) !important;
                -webkit-backdrop-filter: blur(8px) !important;
            }

            .opb-modal {
                background: var(--bg-card, #131e33);
                border: 1px solid var(--border-color, #1e293b);
                border-radius: 1.25rem;
                box-shadow: var(--card-shadow, 0 25px 50px -12px rgba(0, 0, 0, 0.75));
                max-width: 520px;
                width: 100%;
                overflow: hidden;
                transform: scale(0.95) translateY(10px);
                transition: transform 0.25s cubic-bezier(0.16, 1, 0.3, 1);
            }

            .opb-modal-backdrop.opb-modal-active .opb-modal,
            .opb-modal.active,
            .opb-modal.opb-modal-active,
            .opb-modal.show {
                transform: scale(1) translateY(0);
            }

            .opb-modal[style*="position: fixed"],
            .opb-modal[style*="position:fixed"] {
                transform: none !important;
            }

            .opb-modal-header {
                padding: 1.5rem 1.75rem 1rem 1.75rem;
                display: flex;
                align-items: center;
                justify-content: space-between;
                border-bottom: 1px solid var(--border-color, #1e293b);
            }

            .opb-modal-title-group {
                display: flex;
                align-items: center;
                gap: 0.75rem;
            }

            .opb-modal-title {
                font-size: 1.2rem;
                font-weight: 800;
                color: var(--text-primary, #ffffff);
                letter-spacing: -0.02em;
            }

            .opb-modal-body {
                padding: 1.5rem 1.75rem;
                color: var(--text-secondary, #cbd5e1);
                font-size: 0.925rem;
                line-height: 1.6;
                max-height: 60vh;
                overflow-y: auto;
            }

            .opb-modal-footer {
                padding: 1rem 1.75rem 1.5rem 1.75rem;
                display: flex;
                align-items: center;
                justify-content: flex-end;
                gap: 0.75rem;
                border-top: 1px solid var(--border-color, #1e293b);
            }

            .opb-modal-btn {
                padding: 0.65rem 1.25rem;
                border-radius: 0.5rem;
                font-size: 0.875rem;
                font-weight: 700;
                cursor: pointer;
                border: none;
                transition: all 0.2s ease;
                display: inline-flex;
                align-items: center;
                gap: 0.4rem;
            }

            .opb-modal-btn-primary {
                background: var(--accent-gradient, linear-gradient(135deg, #0284c7 0%, #2563eb 100%));
                color: #ffffff;
            }
            .opb-modal-btn-primary:hover {
                filter: brightness(1.1);
                transform: translateY(-1px);
            }

            .opb-modal-btn-secondary {
                background: transparent;
                border: 1px solid var(--border-color, #1e293b);
                color: var(--text-secondary, #cbd5e1);
            }
            .opb-modal-btn-secondary:hover {
                background: rgba(255, 255, 255, 0.05);
                color: var(--text-primary, #ffffff);
            }

            .opb-modal-btn-danger {
                background: var(--danger-color, #ef4444);
                color: #ffffff;
            }
            .opb-modal-btn-danger:hover {
                filter: brightness(1.1);
                transform: translateY(-1px);
            }

            /* ── Universal Filter Bar & Signal Metric Strip (OPB-FILTER-2026) ── */
            .filter-bar, .opb-filter-bar {
                background: var(--bg-card, #111726) !important;
                border: 1px solid var(--border-color, #1e293b) !important;
                color: var(--text-primary, #f8fafc) !important;
                box-shadow: var(--card-shadow) !important;
            }
            .timeframe-btn, .opb-timeframe-btn {
                background: var(--bg-secondary, #0f172a) !important;
                color: var(--text-secondary, #94a3b8) !important;
                border: 1px solid var(--border-color, #1e293b) !important;
            }
            .timeframe-btn:hover, .opb-timeframe-btn:hover {
                background: var(--bg-card-hover, #182238) !important;
                color: var(--text-primary, #f8fafc) !important;
                border-color: var(--border-color-hover, #38bdf8) !important;
            }
            .timeframe-btn.active, .opb-timeframe-btn.active {
                background: var(--accent-color, #0284c7) !important;
                color: var(--btn-primary-text, #ffffff) !important;
                border-color: var(--accent-color, #0284c7) !important;
                font-weight: 700 !important;
            }
            .filter-select, .opb-filter-select, .column-filter, .opb-column-filter {
                background: var(--input-bg, #0d1322) !important;
                color: var(--text-primary, #f8fafc) !important;
                border: 1px solid var(--input-border, var(--border-color, #1e293b)) !important;
            }
            .opb-signal-metric-card {
                background: var(--bg-card, #111726) !important;
                border: 1px solid var(--border-color, #1e293b) !important;
                box-shadow: var(--card-shadow) !important;
            }
        `;
        document.head.appendChild(style);
    }

    /* ── Universal Toast & Modal Engine Implementation ──────────────────── */

    function ensureToastContainer() {
        let container = document.getElementById('opb-toast-container');
        if (!container) {
            container = document.createElement('div');
            container.id = 'opb-toast-container';
            container.setAttribute('aria-live', 'polite');
            document.body.appendChild(container);
        }
        return container;
    }

    const CANONICAL_SEVERITY_UI = {
        'INFO':            { type: 'info',    badge: 'INFO',            icon: 'fa-info-circle',          emoji: 'ℹ️', token: 'var(--notification-info)' },
        'SUCCESS':         { type: 'success', badge: 'SUCCESS',         icon: 'fa-check-circle',         emoji: '✅', token: 'var(--notification-success)' },
        'WARNING':         { type: 'warning', badge: 'WARNING',         icon: 'fa-exclamation-triangle', emoji: '⚠️', token: 'var(--notification-warning)' },
        'ERROR':           { type: 'error',   badge: 'ERROR',           icon: 'fa-exclamation-circle',   emoji: '🚨', token: 'var(--notification-danger)' },
        'CRITICAL':        { type: 'error',   badge: 'CRITICAL',        icon: 'fa-radiation',            emoji: '🛑', token: 'var(--notification-danger)' },
        'SIGNAL_MODERATE': { type: 'warning', badge: 'MODERATE SIGNAL', icon: 'fa-bolt',                 emoji: '🟡', token: 'var(--notification-warning)' },
        'SIGNAL_STRONG':   { type: 'success', badge: 'STRONG SIGNAL',   icon: 'fa-gem',                  emoji: '💎', token: 'var(--notification-signal)' },
        'SECURITY':        { type: 'warning', badge: 'SECURITY AUDIT',  icon: 'fa-shield-alt',           emoji: '🛡️', token: 'var(--notification-warning)' },
        'ACTION_REQUIRED': { type: 'warning', badge: 'ACTION REQUIRED', icon: 'fa-bolt',                 emoji: '⚡', token: 'var(--notification-warning)' }
    };

    function normalizeToastOptions(optionsOrMessage, typeArg, titleArg, durationArg) {
        if (typeof optionsOrMessage === 'string' || typeof optionsOrMessage === 'number') {
            const rawType = String(typeArg || 'info').toLowerCase();
            const sevMap = {
                'success': 'SUCCESS',
                'ok': 'SUCCESS',
                'error': 'ERROR',
                'danger': 'ERROR',
                'critical': 'CRITICAL',
                'warning': 'WARNING',
                'warn': 'WARNING',
                'security': 'SECURITY',
                'action_required': 'ACTION_REQUIRED',
                'signal_strong': 'SIGNAL_STRONG',
                'signal_moderate': 'SIGNAL_MODERATE',
                'info': 'INFO'
            };
            const sev = sevMap[rawType] || 'INFO';
            const ui = CANONICAL_SEVERITY_UI[sev] || CANONICAL_SEVERITY_UI['INFO'];
            return {
                type: ui.type,
                severity: sev,
                badge: ui.badge,
                emoji: ui.emoji,
                iconClass: ui.icon,
                token: ui.token,
                categoryLabel: 'OPB QUANTITATIVE ENGINE',
                title: titleArg || ui.badge,
                message: String(optionsOrMessage),
                keyValues: [],
                primaryAction: null,
                duration: durationArg !== undefined ? durationArg : 5000
            };
        }
        const opts = optionsOrMessage || {};
        const rawSev = String(opts.severity || opts.type || 'INFO').toUpperCase();
        const aliasMap = {
            'DANGER': 'ERROR',
            'WARN': 'WARNING',
            'OK': 'SUCCESS'
        };
        const sev = CANONICAL_SEVERITY_UI[rawSev] ? rawSev : (aliasMap[rawSev] || 'INFO');
        const ui = CANONICAL_SEVERITY_UI[sev] || CANONICAL_SEVERITY_UI['INFO'];
        return {
            type: ui.type,
            severity: sev,
            badge: opts.severity_badge || opts.badge || ui.badge,
            emoji: opts.primary_icon || ui.emoji,
            iconClass: ui.icon,
            token: opts.accent_token || ui.token,
            categoryLabel: opts.category_label || opts.categoryLabel || 'OPB QUANTITATIVE ENGINE',
            title: opts.title || ui.badge,
            message: opts.summary || opts.message || '',
            keyValues: opts.key_values || opts.keyValues || [],
            primaryAction: opts.primary_action || opts.primaryAction || null,
            notificationId: opts.notification_id || opts.id || '',
            timestampIst: opts.timestamp_ist || opts.timestamp_human || '',
            duration: opts.duration !== undefined ? opts.duration : 5000
        };
    }

    function renderCanonicalNotificationCard(payload) {
        const norm = normalizeToastOptions(payload);
        let kvHtml = '';
        if (Array.isArray(norm.keyValues) && norm.keyValues.length > 0) {
            const items = norm.keyValues.slice(0, 6).map(kv => {
                const lbl = escapeHtml(String(kv.label || kv.key || (Array.isArray(kv) ? kv[0] : '')));
                const val = escapeHtml(String(kv.value !== undefined ? kv.value : (Array.isArray(kv) ? kv[1] : '')));
                return `<div class="opb-notification-kv-item"><span class="opb-notification-kv-label">${lbl}</span><span class="opb-notification-kv-value">${val}</span></div>`;
            }).join('');
            kvHtml = `<div class="opb-notification-kv-grid">${items}</div>`;
        }
        let actionHtml = '';
        if (norm.primaryAction && norm.primaryAction.label && norm.primaryAction.url) {
            actionHtml = `<div style="margin-top:0.65rem;"><a href="${escapeHtml(norm.primaryAction.url)}" class="btn btn-primary" style="padding:0.35rem 0.75rem;font-size:0.75rem;">${escapeHtml(norm.primaryAction.label)} &rarr;</a></div>`;
        }
        return `
            <div class="opb-notification-card" data-severity="${escapeHtml(norm.severity)}" style="padding:1rem 1.15rem;">
                <div class="opb-notification-header">
                    <span>🎯 ${escapeHtml(norm.categoryLabel)}</span>
                    <span class="opb-notification-badge" style="border-color:${norm.token};color:${norm.token};">${escapeHtml(norm.emoji)} ${escapeHtml(norm.badge)}</span>
                </div>
                <div class="opb-toast-title" style="font-size:0.95rem;font-weight:800;margin-bottom:0.25rem;">${escapeHtml(norm.title)}</div>
                <div class="opb-toast-message" style="font-size:0.82rem;">${escapeHtml(norm.message)}</div>
                ${kvHtml}
                ${actionHtml}
            </div>
        `;
    }

    function showToast(optionsOrMessage, typeArg, titleArg, durationArg) {
        const norm = normalizeToastOptions(optionsOrMessage, typeArg, titleArg, durationArg);
        const container = ensureToastContainer();
        const toast = document.createElement('div');
        toast.className = `opb-toast opb-toast-${norm.type} opb-notification-card`;
        toast.setAttribute('data-severity', norm.severity);
        toast.setAttribute('role', norm.type === 'error' ? 'alert' : 'status');

        let kvHtml = '';
        if (Array.isArray(norm.keyValues) && norm.keyValues.length > 0) {
            const items = norm.keyValues.slice(0, 4).map(kv => {
                const lbl = escapeHtml(String(kv.label || kv.key || (Array.isArray(kv) ? kv[0] : '')));
                const val = escapeHtml(String(kv.value !== undefined ? kv.value : (Array.isArray(kv) ? kv[1] : '')));
                return `<div class="opb-notification-kv-item"><span class="opb-notification-kv-label">${lbl}</span><span class="opb-notification-kv-value">${val}</span></div>`;
            }).join('');
            kvHtml = `<div class="opb-notification-kv-grid">${items}</div>`;
        }

        toast.innerHTML = `
            <div class="opb-toast-icon" style="color:${norm.token};"><i class="fas ${norm.iconClass}"></i></div>
            <div class="opb-toast-content">
                <div class="opb-notification-header">
                    <span>🎯 ${escapeHtml(norm.categoryLabel)}</span>
                    <span class="opb-notification-badge" style="border-color:${norm.token};color:${norm.token};">${escapeHtml(norm.emoji)} ${escapeHtml(norm.badge)}</span>
                </div>
                <div class="opb-toast-title">${escapeHtml(norm.title)}</div>
                <div class="opb-toast-message">${escapeHtml(norm.message)}</div>
                ${kvHtml}
            </div>
            <button class="opb-toast-close" title="Dismiss" aria-label="Dismiss">
                <i class="fas fa-times"></i>
            </button>
            ${norm.duration > 0 ? `<div class="opb-toast-progress" style="transition: transform ${norm.duration}ms linear; transform: scaleX(1);"></div>` : ''}
        `;

        container.appendChild(toast);

        // Also mirror into legacy #toastContainer if present on page for backwards DOM compatibility
        const legacyContainer = document.getElementById('toastContainer');
        let legacyToast = null;
        if (legacyContainer) {
            legacyToast = document.createElement('div');
            legacyToast.className = `toast ${norm.type} visible opb-notification-card`;
            legacyToast.setAttribute('data-severity', norm.severity);
            legacyToast.style.display = 'none';
            legacyToast.textContent = norm.message || norm.title;
            legacyContainer.appendChild(legacyToast);
        }

        const closeBtn = toast.querySelector('.opb-toast-close');
        const removeToast = () => {
            if (toast.classList.contains('opb-toast-leaving')) return;
            toast.classList.add('opb-toast-leaving');
            setTimeout(() => {
                if (toast.parentNode) toast.parentNode.removeChild(toast);
                if (legacyToast && legacyToast.parentNode) legacyToast.parentNode.removeChild(legacyToast);
            }, 300);
        };

        if (closeBtn) closeBtn.onclick = removeToast;

        if (norm.duration > 0) {
            const progressBar = toast.querySelector('.opb-toast-progress');
            requestAnimationFrame(() => {
                if (progressBar) progressBar.style.transform = 'scaleX(0)';
            });
            setTimeout(removeToast, norm.duration);
        }

        return toast;
    }

    function showModal(options) {
        let backdrop = document.getElementById('opb-global-modal-backdrop');
        if (!backdrop) {
            backdrop = document.createElement('div');
            backdrop.id = 'opb-global-modal-backdrop';
            backdrop.className = 'opb-modal-backdrop';
            document.body.appendChild(backdrop);
        }

        const type = options.type || 'info';
        const title = options.title || 'Notification';
        const message = options.message || '';
        const details = options.details || '';
        const confirmText = options.confirmText || 'OK';
        const cancelText = options.cancelText || '';
        const onConfirm = typeof options.onConfirm === 'function' ? options.onConfirm : null;

        let iconColor = 'var(--accent-color)';
        let iconClass = 'fa-info-circle';
        if (type === 'error') { iconColor = 'var(--danger-color)'; iconClass = 'fa-exclamation-triangle'; }
        else if (type === 'success') { iconColor = 'var(--success-color)'; iconClass = 'fa-check-circle'; }
        else if (type === 'warning') { iconColor = 'var(--warning-color)'; iconClass = 'fa-exclamation-circle'; }

        backdrop.innerHTML = `
            <div class="opb-modal" role="dialog" aria-modal="true">
                <div class="opb-modal-header">
                    <div class="opb-modal-title-group">
                        <i class="fas ${iconClass}" style="color: ${iconColor}; font-size: 1.25rem;"></i>
                        <span class="opb-modal-title">${escapeHtml(title)}</span>
                    </div>
                    <button class="opb-modal-close-btn" id="opb-modal-close-btn" aria-label="Close">
                        <i class="fas fa-times"></i>
                    </button>
                </div>
                <div class="opb-modal-body">
                    <div style="margin-bottom: ${details ? '1rem' : '0'};">${escapeHtml(message)}</div>
                    ${details ? `<pre style="background: var(--input-bg); border: 1px solid var(--border-color); border-radius: 0.5rem; padding: 0.75rem; font-size: 0.8rem; overflow-x: auto; color: var(--text-secondary); max-height: 200px;"><code>${escapeHtml(typeof details === 'object' ? JSON.stringify(details, null, 2) : String(details))}</code></pre>` : ''}
                </div>
                <div class="opb-modal-footer">
                    ${cancelText ? `<button class="opb-modal-btn opb-modal-btn-secondary" id="opb-modal-cancel-btn">${escapeHtml(cancelText)}</button>` : ''}
                    <button class="opb-modal-btn ${type === 'error' ? 'opb-modal-btn-danger' : 'opb-modal-btn-primary'}" id="opb-modal-confirm-btn">
                        ${escapeHtml(confirmText)}
                    </button>
                </div>
            </div>
        `;

        const closeModal = () => {
            backdrop.classList.remove('opb-modal-active');
        };

        const closeBtn = backdrop.querySelector('#opb-modal-close-btn');
        if (closeBtn) closeBtn.onclick = closeModal;

        const cancelBtn = backdrop.querySelector('#opb-modal-cancel-btn');
        if (cancelBtn) cancelBtn.onclick = closeModal;

        const confirmBtn = backdrop.querySelector('#opb-modal-confirm-btn');
        if (confirmBtn) {
            confirmBtn.onclick = () => {
                closeModal();
                if (onConfirm) onConfirm();
            };
        }

        backdrop.onclick = (e) => {
            if (e.target === backdrop) closeModal();
        };

        requestAnimationFrame(() => {
            backdrop.classList.add('opb-modal-active');
        });
    }

    function escapeHtml(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    function applyTheme(themeKey) {
        if (!document.getElementById('opb-rich-styles')) {
            injectRichStyles();
        }
        const theme = THEMES[themeKey] || THEMES['dark-cyber'];
        const effectiveKey = THEMES[themeKey] ? themeKey : 'dark-cyber';
        const root = document.documentElement;
        const isDark = (theme.type === 'dark');
        
        // 1. Root class synchronization (eliminates light theme dark-mode override)
        if (isDark) {
            root.classList.add('dark');
            root.classList.remove('light');
        } else {
            root.classList.remove('dark');
            root.classList.add('light');
        }

        // 2. Data attributes on html (root)
        root.setAttribute('data-theme', effectiveKey);
        root.setAttribute('data-theme-type', theme.type || 'dark');

        // 3. CSS variables on root
        Object.entries(theme.vars).forEach(([key, val]) => {
            root.style.setProperty(key, val);
        });

        // 4. Synchronize body
        if (document.body) {
            if (isDark) {
                document.body.classList.add('dark');
                document.body.classList.remove('light');
            } else {
                document.body.classList.remove('dark');
                document.body.classList.add('light');
            }
            document.body.style.backgroundColor = theme.vars['--bg-primary'];
            document.body.style.color = theme.vars['--text-primary'];
            document.body.setAttribute('data-theme', effectiveKey);
            document.body.setAttribute('data-theme-type', theme.type || 'dark');
        }

        // 5. Persistence (guarded against sandboxed iframe / restricted storage SecurityError)
        try {
            localStorage.setItem('opb_app_theme', effectiveKey);
            localStorage.setItem('opb_theme', effectiveKey);
        } catch (_e) {}
        try {
            document.cookie = "opb_theme=" + effectiveKey + "; path=/; max-age=31536000";
        } catch (_e) {}

        // 6. Sync all dropdown selectors across desktop and mobile
        const THEME_SELECTORS = '.opb-theme-selector, #global-theme-select, #admin-theme-select, .opb-top-theme-select, #opb-theme-select-nav, #drawerThemeSelect, #desktopThemeSelect, select[data-theme-select], select[data-theme-selector]';
        const selectElements = document.querySelectorAll(THEME_SELECTORS);
        selectElements.forEach(selectEl => {
            if (selectEl && selectEl.value !== effectiveKey) {
                selectEl.value = effectiveKey;
            }
        });

        window.dispatchEvent(new CustomEvent('opbThemeChanged', { detail: { theme: effectiveKey, config: theme } }));
    }

    function setDensity(density) {
        const validDensities = ['compact', 'comfortable', 'spacious'];
        const selected = validDensities.includes(density) ? density : 'comfortable';
        document.documentElement.setAttribute('data-density', selected);
        try {
            localStorage.setItem('opb_app_density', selected);
        } catch (_e) {}
        
        const densitySelects = document.querySelectorAll('.opb-density-select');
        densitySelects.forEach(sel => {
            if (sel) sel.value = selected;
        });
    }

    function getSavedTheme() {
        try {
            const ls = localStorage.getItem('opb_app_theme') || localStorage.getItem('opb_theme');
            if (ls && THEMES[ls]) return ls;
        } catch (_e) {}
        try {
            const cookieMatch = document.cookie.match(/(?:^|;\s*)opb_theme=([^;]+)/);
            if (cookieMatch && THEMES[cookieMatch[1]]) return cookieMatch[1];
        } catch (_e) {}
        const attrTheme = document.documentElement && document.documentElement.getAttribute('data-theme');
        if (attrTheme && THEMES[attrTheme]) return attrTheme;
        return 'dark-cyber';
    }

    function getSavedDensity() {
        try {
            return localStorage.getItem('opb_app_density') || 'comfortable';
        } catch (_e) {
            return 'comfortable';
        }
    }

    function initThemeEngine() {
        injectRichStyles();
        const savedTheme = getSavedTheme();
        applyTheme(savedTheme);
        const savedDensity = getSavedDensity();
        setDensity(savedDensity);

        function setupListeners() {
            injectRichStyles();
            const currentTheme = getSavedTheme();
            applyTheme(currentTheme);
            setDensity(getSavedDensity());

            const THEME_SELECTORS = '.opb-theme-selector, #global-theme-select, #admin-theme-select, .opb-top-theme-select, #opb-theme-select-nav, #drawerThemeSelect, #desktopThemeSelect, select[data-theme-select], select[data-theme-selector]';
            const selectElements = document.querySelectorAll(THEME_SELECTORS);
            selectElements.forEach(selectEl => {
                if (selectEl) {
                    selectEl.value = currentTheme;
                }
            });

            // Global delegated event listener: catches ALL theme changes anywhere in DOM instantly
            document.addEventListener('change', function(e) {
                if (e.target && (e.target.matches(THEME_SELECTORS) || e.target.closest(THEME_SELECTORS))) {
                    applyTheme(e.target.value);
                }
            });

            const densitySelects = document.querySelectorAll('.opb-density-select');
            densitySelects.forEach(sel => {
                if (sel) {
                    sel.value = getSavedDensity();
                    sel.onchange = function(e) {
                        setDensity(this.value);
                    };
                }
            });
        }

        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', setupListeners);
        } else {
            setupListeners();
        }

        // Global Institutional Keyboard Shortcuts
        window.addEventListener('keydown', (e) => {
            const activeTag = document.activeElement ? document.activeElement.tagName.toLowerCase() : '';
            if (activeTag === 'input' || activeTag === 'textarea' || activeTag === 'select') return;

            if (e.key === 'F1') {
                e.preventDefault();
                window.location.href = '/';
            } else if (e.key === 'F2') {
                e.preventDefault();
                window.location.href = '/intelligence';
            } else if (e.key === 'F3') {
                e.preventDefault();
                window.location.href = '/governance';
            } else if (e.key === 'F4') {
                e.preventDefault();
                window.location.href = '/admin/config';
            } else if (e.shiftKey && e.key === 'Escape') {
                e.preventDefault();
                if (window.showModal) {
                    window.showModal({
                        type: 'error',
                        title: '🛑 EMERGENCY SQUARE-OFF & KILL SWITCH',
                        message: 'Trigger Emergency Kill Switch to immediately halt automated order placement?',
                        confirmText: 'KILL SWITCH IMMEDIATE HALT',
                        cancelText: 'Resume Session',
                        onConfirm: async () => {
                            try {
                                const m = document.cookie.match(/(?:^|;\s*)opb_csrf=([^;]+)/);
                                const csrf = m ? decodeURIComponent(m[1]) : '';
                                const headers = csrf ? { 'X-CSRF-Token': csrf } : {};
                                const res = await fetch('/api/system/kill', { method: 'POST', headers: headers, credentials: 'include' });
                                if (res.ok) {
                                    window.showSuccess('Kill Switch Active: Trading Halted', 'Halted');
                                } else {
                                    window.location.href = '/admin/kill-switch';
                                }
                            } catch(err) {
                                window.location.href = '/admin/kill-switch';
                            }
                        }
                    });
                }
            }
        });

        // Global Error handler: log unhandled promise rejections cleanly without intrusive UI toasts
        window.addEventListener('unhandledrejection', (event) => {
            const reason = event.reason;
            const message = (reason && (reason.message || reason.detail || String(reason))) || '';
            // Ignore normal browser navigation aborts and resize observer events
            if (!String(message).includes('ResizeObserver') && !String(message).includes('abort')) {
                console.warn('[OPB Notice]', reason);
            }
        });
    }


    // Expose Global API with full backwards compatibility and case-insensitivity
    window.applyTheme = applyTheme;
    window.setTheme = applyTheme;
    window.showModal = showModal;
    window.showToast = showToast;
    window.renderCanonicalNotificationCard = renderCanonicalNotificationCard;
    window.OPBNotify = {
        toast: showToast,
        modal: showModal,
        renderCard: renderCanonicalNotificationCard,
        severities: CANONICAL_SEVERITY_UI
    };
    window.OPBTheme = {
        applyTheme: applyTheme,
        setTheme: applyTheme,
        getTheme: getSavedTheme,
        getThemes: () => THEMES,
        setDensity: setDensity,
        showToast: showToast,
        showModal: showModal,
        renderCanonicalNotificationCard: renderCanonicalNotificationCard
    };

    // OPB UNIVERSAL INTERACTIVE ENGINE (Eye Toggles, Mobile Drawer, Themes)
    // ══════════════════════════════════════════════════════════════════════════
    
    // 1. Universal Password / Token Eye Icon Visibility Toggle
    function handleGlobalEyeToggle(e) {
        const eyeTarget = e.target.closest('[data-toggle="password"], [data-toggle-password], .password-toggle-btn, .eye-toggle-btn, #eyeIconLogin, #eyeIconPassword, #eyeIconConfirmPassword, #eyeIconCurrent, #eyeIconNew, #eyeIconConfirm, #eyeIconToken, #eyeIconCreate, #eyeIconReset, #eyeIconRecKey, #eyeIconNewEmg, #eyeIconConfEmg');
        if (!eyeTarget) {
            // Check if it's an eye icon inside a password input group
            const isEyeIcon = e.target.classList.contains('fa-eye') || e.target.classList.contains('fa-eye-slash');
            if (!isEyeIcon) return;
            const pwGroup = e.target.closest('.form-group, .input-group, .opb-input-group, .password-wrapper, div');
            if (!pwGroup || !pwGroup.querySelector('input[type="password"], input[data-password="true"]')) return;
        }

        // Find the icon element
        let icon = eyeTarget.tagName.toLowerCase() === 'i' ? eyeTarget : eyeTarget.querySelector('i.fa-eye, i.fa-eye-slash');
        if (!icon && eyeTarget.classList.contains('fa-eye')) icon = eyeTarget;
        if (!icon && eyeTarget.classList.contains('fa-eye-slash')) icon = eyeTarget;

        // Find the input element (look in parent container or by ID)
        let input = null;
        const container = eyeTarget.closest('.form-group, .input-group, .opb-input-group, div, fieldset') || eyeTarget.parentElement;
        if (container) {
            input = container.querySelector('input[type="password"], input[type="text"]');
        }
        if (!input && eyeTarget.getAttribute('data-target')) {
            input = document.getElementById(eyeTarget.getAttribute('data-target'));
        }

        if (input) {
            const isPassword = input.type === 'password';
            input.type = isPassword ? 'text' : 'password';
            if (icon) {
                if (isPassword) {
                    icon.classList.remove('fa-eye');
                    icon.classList.add('fa-eye-slash');
                } else {
                    icon.classList.remove('fa-eye-slash');
                    icon.classList.add('fa-eye');
                }
            }
        }
    }

    // 2. Universal Mobile Navigation Drawer State Toggle
    function toggleMobileDrawer(forceState) {
        const checkbox = document.getElementById('opbMobileDrawerCheckbox');
        const isCurrentlyOpen = document.body.classList.contains('drawer-open') || (checkbox && checkbox.checked);
        const shouldOpen = forceState !== undefined ? forceState : !isCurrentlyOpen;

        if (shouldOpen) {
            document.body.classList.add('drawer-open');
            document.documentElement.classList.add('drawer-open');
            if (checkbox) checkbox.checked = true;
        } else {
            document.body.classList.remove('drawer-open');
            document.documentElement.classList.remove('drawer-open');
            if (checkbox) checkbox.checked = false;
        }
    }
    window.toggleMobileDrawer = toggleMobileDrawer;

    function handleGlobalDrawerClick(e) {
        // Triggers to open/toggle drawer
        if (e.target.closest('.mobile-hamburger-btn, #mobileMenuBtn, .mobile-dock-tab[data-drawer="true"], [data-toggle-drawer="true"]')) {
            e.preventDefault();
            e.stopPropagation();
            toggleMobileDrawer();
            return;
        }

        // Triggers to close drawer
        if (e.target.closest('.opb-mobile-drawer-backdrop, #opbMobileDrawerBackdrop, .drawer-close-btn, .drawer-nav-item')) {
            // If navigating to a link, allow link default then close
            setTimeout(() => toggleMobileDrawer(false), 50);
            return;
        }
    }

    // 3. Universal Theme Switch Listener
    function handleGlobalThemeSelect(e) {
        const themeTarget = e.target.closest('.opb-theme-selector, #global-theme-select, #admin-theme-select, .opb-top-theme-select, #opb-theme-select-nav, #drawerThemeSelect, select[data-theme-select], select[data-theme-selector], [data-set-theme]');
        if (!themeTarget) return;

        let themeKey = '';
        if (themeTarget.tagName.toLowerCase() === 'select') {
            themeKey = themeTarget.value;
        } else if (themeTarget.getAttribute('data-set-theme')) {
            e.preventDefault();
            themeKey = themeTarget.getAttribute('data-set-theme');
        }

        if (themeKey) {
            applyTheme(themeKey);
        }
    }

    // Attach high-priority delegated listeners to document root
    function handleDesktopWorkspaceMenuClick(e) {
        const trigger = e.target.closest('.opb-ws-group > .opb-nav-item');
        if (!trigger || !window.matchMedia('(min-width: 1024px)').matches) return;

        const group = trigger.closest('.opb-ws-group');
        if (!group) return;

        const alreadyPinned = group.classList.contains('menu-pinned');
        document.querySelectorAll('.opb-ws-group').forEach(function(other) {
            if (other !== group) {
                other.classList.remove('menu-pinned', 'menu-closed');
            }
        });
        e.preventDefault();
        if (alreadyPinned) {
            group.classList.remove('menu-pinned');
            group.classList.add('menu-closed');
            if (document.activeElement && group.contains(document.activeElement)) {
                document.activeElement.blur();
            }
            group.blur?.();
            return;
        }
        group.classList.remove('menu-closed');
        group.classList.add('menu-pinned');
    }

    document.addEventListener('mouseover', function(e) {
        const group = e.target.closest && e.target.closest('.opb-ws-group');
        if (!group) {
            document.querySelectorAll('.opb-ws-group.menu-closed').forEach(function(g) {
                g.classList.remove('menu-closed');
            });
        }
    }, { capture: false, passive: true });

    document.addEventListener('click', function(e) {
        handleDesktopWorkspaceMenuClick(e);
        handleGlobalDrawerClick(e);
        handleGlobalThemeSelect(e);
    }, { capture: false, passive: false });

    document.addEventListener('click', function(e) {
        if (!e.target.closest('.opb-ws-group')) {
            document.querySelectorAll('.opb-ws-group').forEach(function(group) {
                group.classList.remove('menu-pinned', 'menu-closed');
                if (document.activeElement && group.contains(document.activeElement)) {
                    document.activeElement.blur();
                }
            });
        }
    }, { capture: false, passive: true });

    document.addEventListener('change', function(e) {
        handleGlobalThemeSelect(e);
    }, { capture: true, passive: false });

    // Expose Global API
    window.OPBThemeEngine = {
        THEMES: THEMES,
        applyTheme: applyTheme,
        setTheme: applyTheme,
        setDensity: setDensity,
        init: initThemeEngine
    };
    window.OpbThemeEngine = window.OPBThemeEngine;
    window.togglePasswordVisibility = function(inputId, iconId) {
        const input = document.getElementById(inputId);
        const icon = document.getElementById(iconId);
        if (input) {
            const isPassword = input.type === 'password';
            input.type = isPassword ? 'text' : 'password';
            if (icon) {
                if (isPassword) {
                    icon.classList.remove('fa-eye');
                    icon.classList.add('fa-eye-slash');
                } else {
                    icon.classList.remove('fa-eye-slash');
                    icon.classList.add('fa-eye');
                }
            }
        }
    };

    const _DUMMY = {
        THEMES: THEMES,
        applyTheme: applyTheme,
        setTheme: applyTheme,
        setDensity: setDensity,
        init: initThemeEngine
    };
    window.OpbThemeEngine = window.OPBThemeEngine;

    // Universal binder for all theme select elements
    function bindAllThemeSelectors() {
        const savedTheme = getSavedTheme();
        const selectors = document.querySelectorAll('select#opb-theme-select-nav, select#drawerThemeSelect, select.opb-theme-select, select[data-theme-select]');
        selectors.forEach(function(sel) {
            sel.value = savedTheme;
            sel.addEventListener('change', function(e) {
                applyTheme(this.value);
                // Synchronize all other theme selectors
                selectors.forEach(s => s.value = this.value);
            });
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bindAllThemeSelectors);
    } else {
        bindAllThemeSelectors();
    }


    window.showToast = showToast;
    window.showModal = showModal;
    window.showError = (msg, title, details) => showToast({ type: 'error', title: title || 'Error', message: msg, duration: 7000 });
    window.showSuccess = (msg, title) => showToast({ type: 'success', title: title || 'Success', message: msg, duration: 4000 });
    window.showWarning = (msg, title) => showToast({ type: 'warning', title: title || 'Warning', message: msg, duration: 5000 });
    window.showInfo = (msg, title) => showToast({ type: 'info', title: title || 'Info', message: msg, duration: 4000 });

    initThemeEngine();
})();


    // ── Universal Password & Secret Visibility Controller (OPB 2026 Invariant) ──
    const EYE_SVG_OPEN = `<svg viewBox="0 0 24 24" class="eye-svg-open"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>`;
    const EYE_SVG_CLOSED = `<svg viewBox="0 0 24 24" class="eye-svg-closed"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path><line x1="1" y1="1" x2="23" y2="23"></line></svg>`;

    function togglePasswordField(toggleBtn) {
        if (!toggleBtn) return;
        const wrapper = toggleBtn.closest('.opb-password-wrapper, .input-password-wrapper, .form-group, div');
        if (!wrapper) return;
        const input = wrapper.querySelector('input[type="password"], input[type="text"]');
        if (!input) return;

        const isCurrentlyPassword = input.type === 'password';
        input.type = isCurrentlyPassword ? 'text' : 'password';
        
        // Update SVG / FontAwesome Icon
        const svgContainer = toggleBtn.querySelector('svg');
        if (svgContainer) {
            toggleBtn.innerHTML = isCurrentlyPassword ? EYE_SVG_CLOSED : EYE_SVG_OPEN;
        } else {
            const faIcon = toggleBtn.querySelector('.fa-eye, .fa-eye-slash');
            if (faIcon) {
                faIcon.classList.toggle('fa-eye', !isCurrentlyPassword);
                faIcon.classList.toggle('fa-eye-slash', isCurrentlyPassword);
            } else {
                toggleBtn.innerHTML = isCurrentlyPassword ? EYE_SVG_CLOSED : EYE_SVG_OPEN;
            }
        }
        toggleBtn.setAttribute('aria-label', isCurrentlyPassword ? 'Hide password' : 'Show password');
        toggleBtn.setAttribute('title', isCurrentlyPassword ? 'Hide password' : 'Show password');
        toggleBtn.setAttribute('aria-pressed', isCurrentlyPassword ? 'true' : 'false');
    }
    window.togglePasswordField = togglePasswordField;

    function initUniversalPasswordToggles() {
        document.querySelectorAll('input[type="password"]').forEach(input => {
            const wrapper = input.parentElement;
            if (!wrapper) return;
            wrapper.classList.add('opb-password-wrapper');
            let toggleBtn = wrapper.querySelector('.opb-password-toggle, .password-toggle-btn, [data-toggle="password"]');
            if (!toggleBtn) {
                toggleBtn = document.createElement('button');
                toggleBtn.type = 'button';
                toggleBtn.className = 'opb-password-toggle';
                toggleBtn.setAttribute('data-toggle', 'password');
                toggleBtn.setAttribute('aria-label', 'Show password');
                toggleBtn.setAttribute('title', 'Show password');
                toggleBtn.setAttribute('aria-pressed', 'false');
                toggleBtn.innerHTML = EYE_SVG_OPEN;
                wrapper.appendChild(toggleBtn);
            } else {
                if (!toggleBtn.hasAttribute('aria-pressed')) {
                    toggleBtn.setAttribute('aria-pressed', 'false');
                }
                if (!toggleBtn.querySelector('svg') && !toggleBtn.querySelector('i')) {
                    toggleBtn.innerHTML = EYE_SVG_OPEN;
                }
            }
        });
    }

    document.addEventListener('click', function(e) {
        const btn = e.target.closest('.opb-password-toggle, .password-toggle-btn, [data-toggle="password"], [data-toggle-password]');
        if (btn) {
            e.preventDefault();
            togglePasswordField(btn);
        }
    }, { passive: false });

    document.addEventListener('keydown', function(e) {
        if (e.key === 'Enter' || e.key === ' ') {
            const btn = e.target.closest('.opb-password-toggle, .password-toggle-btn, [data-toggle="password"], [data-toggle-password]');
            if (btn && btn.tagName !== 'BUTTON') {
                e.preventDefault();
                togglePasswordField(btn);
            }
        }
    });

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initUniversalPasswordToggles);
    } else {
        initUniversalPasswordToggles();
    }
    
    // Unconditional Mobile Drawer & Modal Clean State on Initial Load / BFCache Restore
    function resetAllMobileOverlays() {
        document.body.classList.remove('drawer-open');
        document.documentElement.classList.remove('drawer-open');
        const drawerCheckbox = document.getElementById('opbMobileDrawerCheckbox');
        if (drawerCheckbox) {
            drawerCheckbox.checked = false;
        }
        const modalBackdrop = document.getElementById('opb-global-modal-backdrop');
        if (modalBackdrop) {
            modalBackdrop.classList.remove('opb-modal-active');
            modalBackdrop.style.display = 'none';
        }
    }

    window.addEventListener('pageshow', resetAllMobileOverlays);
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', resetAllMobileOverlays);
    } else {
        resetAllMobileOverlays();
    }

    // Global Accessible Modal Controller (OPB-MODAL-2026 Invariant)
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' || e.keyCode === 27) {
            // Dismiss desktop workspace dropdowns cleanly
            document.querySelectorAll('.opb-ws-group').forEach(group => {
                group.classList.remove('menu-pinned');
                group.classList.add('menu-closed');
                if (document.activeElement && group.contains(document.activeElement)) {
                    document.activeElement.blur();
                }
            });
            // Dismiss global dynamic modal
            const globalBackdrop = document.getElementById('opb-global-modal-backdrop');
            if (globalBackdrop && globalBackdrop.classList.contains('opb-modal-active')) {
                globalBackdrop.classList.remove('opb-modal-active');
            }
            // Dismiss open custom modals across templates
            document.querySelectorAll('.modal, .opb-modal, .qr-modal, .modal-overlay, .modal-backdrop, .opb-modal-backdrop, [id$="Modal"], [id*="-modal"]').forEach(modal => {
                if (modal.id === 'opb-global-modal-backdrop') return;
                if (modal.style.display !== 'none' && modal.style.display !== '') {
                    modal.style.display = 'none';
                }
                if (modal.classList.contains('active') || modal.classList.contains('visible') || modal.classList.contains('show')) {
                    modal.classList.remove('active', 'visible', 'show');
                }
            });
        }
    });

    // Universal backdrop click and close button handler
    document.addEventListener('click', function(e) {
        // Universal close button dismissal
        const closeBtn = e.target.closest('.opb-modal-close-btn, [data-action="close-signal-test-modal"], [data-action="close-signal-explain-modal"], [id^="closeViewUser"], [id^="closePermModal"], [id^="closeHistoryHeader"]');
        if (closeBtn) {
            const modalWrapper = closeBtn.closest('.modal-overlay, .modal-backdrop, .opb-modal-backdrop, .qr-modal, [id$="Modal"], [id*="-modal"]');
            if (modalWrapper) {
                modalWrapper.style.display = 'none';
                modalWrapper.classList.remove('active', 'visible', 'show');
            }
        }
        // Universal backdrop click dismissal (when clicking directly on the backdrop/overlay)
        if (e.target.matches && e.target.matches('.modal-overlay, .modal-backdrop, .opb-modal-backdrop, .qr-modal, #signalExplainModal, #signalTestModal')) {
            e.target.style.display = 'none';
            e.target.classList.remove('active', 'visible', 'show');
        }
    });

    // Universal Same-Origin CSRF Header Attachment for State-Changing Fetch Calls (OBS-03)
    if (typeof window !== 'undefined' && typeof window.fetch === 'function' && !window.__opbCsrfFetchWrapped) {
        const _origFetch = window.fetch.bind(window);
        window.fetch = function(input, init) {
            try {
                const method = String((init && init.method) || (input && input.method) || 'GET').toUpperCase();
                if (['POST', 'PUT', 'DELETE', 'PATCH'].includes(method)) {
                    const urlStr = typeof input === 'string' ? input : (input && input.url ? input.url : '');
                    const isSameOrigin = !urlStr || urlStr.startsWith('/') || urlStr.startsWith(window.location.origin);
                    if (isSameOrigin) {
                        const m = document.cookie.match(/(?:^|;\s*)opb_csrf=([^;]+)/);
                        const csrf = m ? decodeURIComponent(m[1]) : '';
                        if (csrf) {
                            init = Object.assign({}, init || {});
                            if (!init.credentials) init.credentials = 'include';
                            if (init.headers instanceof Headers) {
                                if (!init.headers.has('X-CSRF-Token')) init.headers.set('X-CSRF-Token', csrf);
                            } else {
                                init.headers = Object.assign({}, init.headers || {});
                                if (!init.headers['X-CSRF-Token'] && !init.headers['x-csrf-token']) {
                                    init.headers['X-CSRF-Token'] = csrf;
                                }
                            }
                        }
                    }
                }
            } catch (_e) {}
            return _origFetch(input, init);
        };
        window.__opbCsrfFetchWrapped = true;
    }
