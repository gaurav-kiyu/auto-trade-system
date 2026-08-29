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
            name: '🌌 Dark Cyber (Default)',
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
                '--success-color': '#22c55e',
                '--warning-color': '#f59e0b',
                '--danger-color': '#ef4444',
                '--card-shadow': '0 20px 40px -15px rgba(0, 0, 0, 0.7)',
                '--input-bg': '#0b1120',
                '--input-border': '#1e293b',
                '--header-glow': 'rgba(56, 189, 248, 0.15)'
            }
        },
        'nordic-frost': {
            name: '❄️ Nordic Frost (High-Contrast Light)',
            type: 'light',
            vars: {
                '--bg-primary': '#f8fafc',
                '--bg-secondary': '#eef2f6',
                '--bg-card': '#ffffff',
                '--bg-card-hover': '#f1f5f9',
                '--text-primary': '#0f172a',
                '--text-secondary': '#334155',
                '--text-muted': '#475569',
                '--border-color': '#cbd5e1',
                '--border-color-hover': '#0369a1',
                '--accent-color': '#0369a1',
                '--accent-gradient': 'linear-gradient(135deg, #0284c7 0%, #2563eb 100%)',
                '--success-color': '#15803d',
                '--warning-color': '#b45309',
                '--danger-color': '#b91c1c',
                '--card-shadow': '0 2px 8px rgba(15, 23, 42, 0.06), 0 0 0 1px #cbd5e1',
                '--input-bg': '#ffffff',
                '--input-border': '#94a3b8',
                '--header-glow': 'rgba(2, 132, 199, 0.08)'
            }
        },
        'ivory-gold': {
            name: '🏛️ Ivory & Gold (Luxury Warm Light)',
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
                '--success-color': '#15803d',
                '--warning-color': '#92400e',
                '--danger-color': '#b91c1c',
                '--card-shadow': '0 4px 20px -2px rgba(68, 64, 60, 0.08), 0 0 0 1px #d6cbba',
                '--input-bg': '#ffffff',
                '--input-border': '#a89f91',
                '--header-glow': 'rgba(217, 119, 6, 0.1)'
            }
        },
        'tokyo-night': {
            name: '🗼 Tokyo Night (Neon Noir)',
            type: 'dark',
            vars: {
                '--bg-primary': '#16161e',
                '--bg-secondary': '#1a1b26',
                '--bg-card': '#24283b',
                '--bg-card-hover': '#2f3549',
                '--text-primary': '#c0caf5',
                '--text-secondary': '#a9b1d6',
                '--text-muted': '#7aa2f7',
                '--border-color': '#414868',
                '--border-color-hover': '#7aa2f7',
                '--accent-color': '#7aa2f7',
                '--accent-gradient': 'linear-gradient(135deg, #7aa2f7 0%, #bb9af7 100%)',
                '--success-color': '#9ece6a',
                '--warning-color': '#e0af68',
                '--danger-color': '#f7768e',
                '--card-shadow': '0 20px 40px -15px rgba(0, 0, 0, 0.75)',
                '--input-bg': '#1a1b26',
                '--input-border': '#414868',
                '--header-glow': 'rgba(122, 162, 247, 0.2)'
            }
        },
        'catppuccin-mocha': {
            name: '🐱 Catppuccin Mocha (Pastel Dark)',
            type: 'dark',
            vars: {
                '--bg-primary': '#11111b',
                '--bg-secondary': '#181825',
                '--bg-card': '#1e1e2e',
                '--bg-card-hover': '#313244',
                '--text-primary': '#cdd6f4',
                '--text-secondary': '#bac2de',
                '--text-muted': '#a6adc8',
                '--border-color': '#45475a',
                '--border-color-hover': '#89b4fa',
                '--accent-color': '#89b4fa',
                '--accent-gradient': 'linear-gradient(135deg, #89b4fa 0%, #cba6f7 100%)',
                '--success-color': '#a6e3a1',
                '--warning-color': '#fab387',
                '--danger-color': '#f38ba8',
                '--card-shadow': '0 20px 40px -15px rgba(0, 0, 0, 0.75)',
                '--input-bg': '#181825',
                '--input-border': '#45475a',
                '--header-glow': 'rgba(137, 180, 250, 0.2)'
            }
        },
        'obsidian-gold': {
            name: '👑 Obsidian Gold (Luxury Dark)',
            type: 'dark',
            vars: {
                '--bg-primary': '#0d0b08',
                '--bg-secondary': '#17130e',
                '--bg-card': '#211c14',
                '--bg-card-hover': '#2d251a',
                '--text-primary': '#fffbeb',
                '--text-secondary': '#fde68a',
                '--text-muted': '#d97706',
                '--border-color': '#3d3324',
                '--border-color-hover': '#f59e0b',
                '--accent-color': '#f59e0b',
                '--accent-gradient': 'linear-gradient(135deg, #fbbf24 0%, #d97706 50%, #92400e 100%)',
                '--success-color': '#10b981',
                '--warning-color': '#fbbf24',
                '--danger-color': '#f87171',
                '--card-shadow': '0 20px 40px -15px rgba(0, 0, 0, 0.8)',
                '--input-bg': '#14110d',
                '--input-border': '#3d3324',
                '--header-glow': 'rgba(245, 158, 11, 0.15)'
            }
        },
        'midnight-slate': {
            name: '☀️ Sapphire Day (Modern Finance Light)',
            type: 'light',
            vars: {
                '--bg-primary': '#f6f8fb',
                '--bg-secondary': '#eaf0f6',
                '--bg-card': '#ffffff',
                '--bg-card-hover': '#f0f5fa',
                '--text-primary': '#0f172a',
                '--text-secondary': '#334155',
                '--text-muted': '#64748b',
                '--border-color': '#cbd5e1',
                '--border-color-hover': '#1d4ed8',
                '--accent-color': '#1d4ed8',
                '--accent-gradient': 'linear-gradient(135deg, #1d4ed8 0%, #0ea5e9 100%)',
                '--success-color': '#15803d',
                '--warning-color': '#a16207',
                '--danger-color': '#b91c1c',
                '--card-shadow': '0 4px 18px -4px rgba(15, 23, 42, 0.08), 0 0 0 1px #dbe3ec',
                '--input-bg': '#ffffff',
                '--input-border': '#94a3b8',
                '--header-glow': 'rgba(29, 78, 216, 0.10)'
            }
        },
        'emerald-matrix': {
            name: '❇️ Emerald Matrix',
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
                '--success-color': '#34d399',
                '--warning-color': '#fbbf24',
                '--danger-color': '#f87171',
                '--card-shadow': '0 20px 40px -15px rgba(3, 18, 11, 0.7)',
                '--input-bg': '#051b11',
                '--input-border': '#14533a',
                '--header-glow': 'rgba(16, 185, 129, 0.15)'
            }
        },
        'dracula-purple': {
            name: '🌸 Plum Cloud (Premium Light)',
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
                '--success-color': '#15803d',
                '--warning-color': '#a16207',
                '--danger-color': '#b91c1c',
                '--card-shadow': '0 4px 20px -4px rgba(76, 58, 87, 0.08), 0 0 0 1px #e3d9ea',
                '--input-bg': '#ffffff',
                '--input-border': '#a78bb8',
                '--header-glow': 'rgba(124, 58, 237, 0.10)'
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

            .opb-modal-backdrop.opb-modal-active {
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

            .opb-modal-backdrop.opb-modal-active .opb-modal {
                transform: scale(1) translateY(0);
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

    function showToast(options) {
        const type = options.type || 'info'; // 'error' | 'success' | 'warning' | 'info'
        const title = options.title || (type.charAt(0).toUpperCase() + type.slice(1));
        const message = options.message || '';
        const duration = options.duration !== undefined ? options.duration : 5000;

        const container = ensureToastContainer();
        const toast = document.createElement('div');
        toast.className = `opb-toast opb-toast-${type}`;
        toast.setAttribute('role', type === 'error' ? 'alert' : 'status');

        let iconClass = 'fa-info-circle';
        if (type === 'error') iconClass = 'fa-exclamation-circle';
        else if (type === 'success') iconClass = 'fa-check-circle';
        else if (type === 'warning') iconClass = 'fa-exclamation-triangle';

        toast.innerHTML = `
            <div class="opb-toast-icon"><i class="fas ${iconClass}"></i></div>
            <div class="opb-toast-content">
                <div class="opb-toast-title">${escapeHtml(title)}</div>
                <div class="opb-toast-message">${escapeHtml(message)}</div>
            </div>
            <button class="opb-toast-close" title="Dismiss" aria-label="Dismiss">
                <i class="fas fa-times"></i>
            </button>
            ${duration > 0 ? `<div class="opb-toast-progress" style="transition: transform ${duration}ms linear; transform: scaleX(1);"></div>` : ''}
        `;

        container.appendChild(toast);

        const closeBtn = toast.querySelector('.opb-toast-close');
        const removeToast = () => {
            if (toast.classList.contains('opb-toast-leaving')) return;
            toast.classList.add('opb-toast-leaving');
            setTimeout(() => {
                if (toast.parentNode) toast.parentNode.removeChild(toast);
            }, 300);
        };

        if (closeBtn) closeBtn.onclick = removeToast;

        if (duration > 0) {
            const progressBar = toast.querySelector('.opb-toast-progress');
            requestAnimationFrame(() => {
                if (progressBar) progressBar.style.transform = 'scaleX(0)';
            });
            setTimeout(removeToast, duration);
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
                    <button class="opb-toast-close" id="opb-modal-close-btn" aria-label="Close">
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
        const theme = THEMES[themeKey] || THEMES['dark-cyber'];
        const root = document.documentElement;
        
        Object.entries(theme.vars).forEach(([key, val]) => {
            root.style.setProperty(key, val);
        });

        if (document.body) {
            document.body.style.backgroundColor = theme.vars['--bg-primary'];
            document.body.style.color = theme.vars['--text-primary'];
            document.body.setAttribute('data-theme', themeKey);
            document.body.setAttribute('data-theme-type', theme.type || 'dark');
        }

        localStorage.setItem('opb_app_theme', themeKey);
        localStorage.setItem('opb_theme', themeKey);
        document.cookie = "opb_theme=" + themeKey + "; path=/; max-age=31536000";

        // Sync all theme dropdown selectors across desktop and mobile
        const THEME_SELECTORS = '.opb-theme-selector, #global-theme-select, #admin-theme-select, .opb-top-theme-select, #opb-theme-select-nav, #drawerThemeSelect, select[data-theme-select], select[data-theme-selector]';
        const selectElements = document.querySelectorAll(THEME_SELECTORS);
        selectElements.forEach(selectEl => {
            if (selectEl && selectEl.value !== themeKey) {
                selectEl.value = themeKey;
            }
        });

        window.dispatchEvent(new CustomEvent('opbThemeChanged', { detail: { theme: themeKey, config: theme } }));
    }

    function setDensity(density) {
        const validDensities = ['compact', 'comfortable', 'spacious'];
        const selected = validDensities.includes(density) ? density : 'comfortable';
        document.documentElement.setAttribute('data-density', selected);
        localStorage.setItem('opb_app_density', selected);
        
        const densitySelects = document.querySelectorAll('.opb-density-select');
        densitySelects.forEach(sel => {
            if (sel) sel.value = selected;
        });
    }

    function initThemeEngine() {
        injectRichStyles();
        const savedTheme = localStorage.getItem('opb_app_theme') || localStorage.getItem('opb_theme') || 'dark-cyber';
        applyTheme(savedTheme);
        const savedDensity = localStorage.getItem('opb_app_density') || 'comfortable';
        setDensity(savedDensity);

        function setupListeners() {
            injectRichStyles();
            const currentTheme = localStorage.getItem('opb_app_theme') || localStorage.getItem('opb_theme') || 'dark-cyber';
            applyTheme(currentTheme);
            setDensity(localStorage.getItem('opb_app_density') || 'comfortable');

            const THEME_SELECTORS = '.opb-theme-selector, #global-theme-select, #admin-theme-select, .opb-top-theme-select, #opb-theme-select-nav, #drawerThemeSelect, select[data-theme-select], select[data-theme-selector]';
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
                    sel.value = localStorage.getItem('opb_app_density') || 'comfortable';
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
                                const res = await fetch('/api/system/kill', { method: 'POST' });
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
    
    // ══════════════════════════════════════════════════════════════════════════
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

        // First click pins the submenu so the pointer cannot outrun it.
        // A second click follows the parent link normally.
        const alreadyPinned = group.classList.contains('menu-pinned');
        document.querySelectorAll('.opb-ws-group.menu-pinned').forEach(function(other) {
            if (other !== group) other.classList.remove('menu-pinned');
        });
        if (alreadyPinned) {
            group.classList.remove('menu-pinned');
            return;
        }
        e.preventDefault();
        group.classList.add('menu-pinned');
    }

    document.addEventListener('click', function(e) {
        handleDesktopWorkspaceMenuClick(e);
        handleGlobalDrawerClick(e);
        handleGlobalThemeSelect(e);
    }, { capture: false, passive: false });

    document.addEventListener('click', function(e) {
        if (!e.target.closest('.opb-ws-group')) {
            document.querySelectorAll('.opb-ws-group.menu-pinned').forEach(function(group) {
                group.classList.remove('menu-pinned');
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
        const savedTheme = localStorage.getItem('opb_theme') || 'dark-cyber';
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
    }

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
                toggleBtn.tabIndex = -1;
                toggleBtn.innerHTML = EYE_SVG_OPEN;
                wrapper.appendChild(toggleBtn);
            } else if (!toggleBtn.querySelector('svg') && !toggleBtn.querySelector('i')) {
                toggleBtn.innerHTML = EYE_SVG_OPEN;
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
