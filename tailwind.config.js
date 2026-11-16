// tailwind.config.js
/** @type {import('tailwindcss').Config} */
const defaultTheme = require('tailwindcss/defaultTheme');
const tailwindColors = require('tailwindcss/colors');

module.exports = {
  content: [
    './app/templates/**/*.html',
    './app/static/js/**/*.js',
  ],
  theme: {
    // Lilac design tokens. DESIGN.md explains how to use them.
    // The colour palette is REPLACED, not extended: only the colours below
    // exist, so off-palette classes (bg-blue-500, text-orange-600, ...) do
    // not compile. tests/unit/test_design_tokens.py guards this too.
    colors: {
      transparent: 'transparent',
      current: 'currentColor',
      white: '#ffffff',
      black: '#000000',
      // Neutral greys with a faint cool cast (surfaces never carry purple)
      gray: {
        '50': '#FAFAFB',
        '100': '#F4F4F6',
        '200': '#ECEBF0',
        '300': '#DCDAE2',
        '400': '#B5B2BE',
        '500': '#8E8A99',
        '600': '#6B6877',
        '700': '#4E4A5A',
        '800': '#2F2B3A',
        '900': '#16121F',
        '950': '#0E0B14',
      },
      // Status ramps, for status only (errors, success, warnings)
      red: tailwindColors.red,
      green: tailwindColors.green,
      amber: tailwindColors.amber,

      // The one brand colour: actions, current state and focus
      primary: {
        DEFAULT: '#5A2BD6',
        light: '#7A55E3',
        dark: '#4920B5',
        soft: '#F1ECFF',   // tonal backgrounds (selected, workflow results, badges)
        tint: '#F6F3FF',   // highlighted zone (audio file drop zone)
        track: '#EDE7FF',  // progress and meter tracks
      },

      // Semantic aliases so templates stay descriptive
      'body-bg': '#ffffff',
      'default-text': '#16121F',
      'surface': '#ffffff',
      'surface-alt': '#FAFAFB',
      'surface-muted': '#F4F4F6',
      'border-default': '#ECEBF0',
      'border-strong': '#DCDAE2',
      'text-muted': '#6B6877',
      'text-strong': '#16121F',
      'accent': '#5A2BD6',
      'accent-soft': '#F1ECFF',
      'accent-border': '#DCD0FF',
      'danger': '#C2352B',
      'warning': '#B45309',
      'success': '#15803D',
      'info': '#5A2BD6',
      // Workflow label colours chosen by users (data, not UI chrome)
      'workflow-label': {
        'default': '#ffffff',
        'pink': '#ffd1dc',
        'bluegray': '#aec6cf',
        'mint': '#cfffd1',
        'lemon': '#fffacd',
        'lavender': '#e6e6fa',
        'orange': '#ffb347',
      },
    },
    extend: {
      fontFamily: {
        sans: ['Onest', '-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'Roboto', '"Helvetica Neue"', 'Arial', 'sans-serif', ...defaultTheme.fontFamily.sans],
      },
      fontSize: {
        'xs': ['0.75rem', { lineHeight: '1.1rem' }],
        'sm': ['0.85rem', { lineHeight: '1.3rem' }],
        'base': ['1rem', { lineHeight: '1.5rem' }],
        'lg': ['1.125rem', { lineHeight: '1.65rem' }],
        'xl': ['1.25rem', { lineHeight: '1.75rem' }],
        '2xl': ['1.5rem', { lineHeight: '2rem' }],
        // Type scale: page 32 · modal 24 · section 20 · group 17
        'page': ['2rem', { lineHeight: '1.25' }],
        'page-sm': ['1.625rem', { lineHeight: '1.25' }],
        'modal': ['1.5rem', { lineHeight: '2rem' }],
        'section': ['1.25rem', { lineHeight: '1.75rem' }],
        'group': ['1.0625rem', { lineHeight: '1.5rem' }],
        // UI text sizes
        'hero': ['0.9375rem', { lineHeight: '1.25rem' }],   // 15px: hero button, panel titles
        'nav': ['0.84375rem', { lineHeight: '1.25rem' }],   // 13.5px: sidebar links
        'control': ['0.8125rem', { lineHeight: '1.25rem' }], // 13px: small controls, labels
        'badge': ['0.78125rem', { lineHeight: '1rem' }],    // 12.5px: status badges, chips
        'tag': ['0.6875rem', { lineHeight: '1rem' }],       // 11px: avatar initials, purpose tags
        // Display numbers
        'stat': ['2.5rem', { lineHeight: '1' }],            // dashboard tiles
        'pct': ['1.75rem', { lineHeight: '1' }],            // progress percentage
      },
      letterSpacing: {
        'display': '-0.035em',  // page titles
        'title': '-0.03em',     // modal titles, percentages
        'heading': '-0.02em',   // section headings
        'snug': '-0.01em',      // group headings, brand
        'stat': '-0.04em',      // big numbers
        'live': '-0.025em',     // live transcript
        'caps': '0.06em',       // uppercase eyebrows
      },
      borderRadius: {
        'xs': '0.125rem',
        'sm': '0.25rem',
        'md': '0.5rem',
        'lg': '0.75rem',
        'xl': '1rem',
        'pill': '9999px',
        // Component radii
        'field': '0.75rem',     // 12px: inputs, selects, segmented controls
        'segment': '9px',       // inner segment of a segmented control
        'card': '1rem',         // 16px: cards, panels, tiles, drop zone
        'modal': '22px',        // modals and drawers
      },
      spacing: {
        '13': '3.25rem',
        '15': '3.75rem',
        '18': '4.5rem',
        '25': '6.25rem',
        '30': '7.5rem',
        // Control heights: buttons and fields share them
        'control': '42px',      // default
        'control-sm': '34px',   // small: chips, Stop, Choose File
        'control-lg': '50px',   // hero call to action (Transcribe)
        'badge': '26px',        // status badges, label swatches
        'icon-btn': '32px',     // round icon buttons
        'rail': '4.5rem',       // collapsed admin sidebar
        'btn': '18px',          // horizontal padding of default buttons
        'modal': '26px',        // modal horizontal padding (sm and up)
        'check': '18px',        // checkbox size
      },
      minHeight: {
        'control': '42px',
        'control-sm': '34px',
        'control-lg': '50px',
      },
      boxShadow: {
        'surface': '0 1px 3px rgba(22, 18, 31, 0.08), 0 1px 2px rgba(22, 18, 31, 0.05)',
        'surface-xl': '0 30px 80px -30px rgba(40, 20, 90, 0.45), 0 2px 6px rgba(22, 18, 31, 0.06)',
        'focus': '0 0 0 4px rgba(90, 43, 214, 0.13)',
        // Raised: white fields and cards lifted by a faint ring + soft shadow
        'raised': '0 0 0 1px rgba(22, 18, 31, 0.07), 0 1px 3px rgba(22, 18, 31, 0.07)',
        'raised-hover': '0 0 0 1px rgba(22, 18, 31, 0.09), 0 4px 12px -4px rgba(22, 18, 31, 0.1)',
        'cta': '0 10px 24px -14px rgba(90, 43, 214, 0.9)',
        'menu': '0 24px 50px -22px rgba(40, 20, 90, 0.5), 0 0 0 1px rgba(22, 18, 31, 0.06)',
        'progress': '0 12px 28px -22px rgba(90, 43, 214, 0.55)',
      },
      borderWidth: {
        '1.5': '1.5px',
      },
      backdropBlur: {
        'scrim': '3px',
      },
      maxWidth: {
        'content': '64rem',
        'narrow': '36rem',
        'page': '52rem',        // single-column app pages (Transcribe, Workflows)
      },
      transitionTimingFunction: {
        'swift': 'cubic-bezier(0.4, 0, 0.2, 1)',
      },
      transitionDuration: {
        '250': '250ms',
      },
    },
  },
  plugins: [
    require('@tailwindcss/forms')({
      strategy: 'class', // Or 'base', if you prefer less opinionated form styles
    }),
    require('@headlessui/tailwindcss'), // Added Headless UI plugin
  ],
}
