"""Shared visual system for the GitRepo desktop applications."""

# Design tokens. Both applications describe the same surfaces (canvas, cards,
# lists, heroes), so the values live here once and each product only adds what
# is genuinely specific to its own pages.
CARD_RADIUS = "14px"
CARD_BORDER = "1px solid alpha(currentColor, 0.09)"
CARD_SHADOW = "0 2px 8px alpha(black, 0.06)"
CARD_HOVER_SHADOW = "0 7px 18px alpha(black, 0.10)"
HERO_GRADIENT = (
    "linear-gradient(120deg, alpha(@accent_bg_color, 0.18), alpha(@accent_bg_color, 0.06) 58%, alpha(#8b5cf6, 0.10))"
)

_PREMIUM_CSS = f"""
        .sidebar-pane {{
            background-color: @sidebar_bg_color;
        }}

        .navigation-sidebar row {{
            min-height: 44px;
            margin: 2px 0;
            border-radius: 10px;
        }}

        .navigation-button {{
            padding: 0;
            border: none;
            background: none;
            box-shadow: none;
            font-weight: normal;
        }}

        .content-canvas {{
            background-color: @window_bg_color;
            --dim-opacity: 72%;
        }}

        .content-canvas row label.subtitle,
        .content-canvas .caption.dim-label {{
            font-size: inherit;
            line-height: 1.35;
        }}

        @media (prefers-contrast: more) {{
            .content-canvas {{
                --dim-opacity: 90%;
            }}
        }}

        row.combo popover contents modelbutton {{
            min-width: 250px;
        }}

        .page-frame {{
            margin: 20px 24px 28px;
        }}

        .section-heading {{
            font-weight: 700;
            margin-top: 2px;
        }}

        .premium-list {{
            border-radius: {CARD_RADIUS};
            border: 1px solid alpha(currentColor, 0.08);
            background-color: @card_bg_color;
            box-shadow: 0 1px 2px alpha(black, 0.05);
        }}

        .status-ok {{ color: @success_color; }}
        .status-warning {{ color: @warning_color; }}
        .status-error {{ color: @error_color; }}

        .badge.numeric {{
            padding: 2px 7px;
            border-radius: 999px;
            background-color: alpha(@warning_bg_color, 0.14);
            color: @warning_color;
            font-weight: 700;
        }}

        .state-pill {{
            padding: 1px 9px;
            border-radius: 999px;
            background-color: alpha(currentColor, 0.10);
            font-size: 0.82em;
            font-weight: 700;
        }}

        .state-pill.status-ok {{ background-color: alpha(@success_color, 0.16); }}
        .state-pill.status-warning {{ background-color: alpha(@warning_color, 0.16); }}
        .state-pill.status-error {{ background-color: alpha(@error_color, 0.16); }}

        .page-footer-bar {{
            padding: 10px 24px;
            border-top: 1px solid alpha(currentColor, 0.10);
            background-color: @card_bg_color;
        }}

    """


def hero_css(css_prefix: str) -> str:
    """Return the page-hero rules for one product's CSS prefix."""
    return f"""
        .{css_prefix}-expanded-header {{
            background-image: {HERO_GRADIENT};
            box-shadow: none;
        }}
        .{css_prefix}-page-hero {{
            min-height: 56px;
            padding: 0 32px 28px;
            border-bottom: 1px solid alpha(@accent_color, 0.20);
            background-image: {HERO_GRADIENT};
        }}
        .{css_prefix}-page-hero-icon {{
            min-width: 56px;
            min-height: 56px;
        }}
        .{css_prefix}-hero-subtitle {{
            opacity: 0.82;
        }}
    """


def card_css(css_prefix: str, *, status_min_height: str, destination_min_width: str) -> str:
    """Return the shared card surfaces sized for one product's pages."""
    return f"""
        .{css_prefix}-status-card {{
            min-height: {status_min_height};
            padding: 14px;
            border-radius: {CARD_RADIUS};
            border: {CARD_BORDER};
            background-color: @card_bg_color;
            box-shadow: {CARD_SHADOW};
        }}
        .{css_prefix}-destinations flowboxchild {{
            min-width: {destination_min_width};
            padding: 0;
        }}
        .{css_prefix}-destination-card {{
            min-height: 126px;
            padding: 16px;
            border-radius: {CARD_RADIUS};
            border: {CARD_BORDER};
            background-color: @card_bg_color;
            box-shadow: {CARD_SHADOW};
            transition: 180ms ease;
        }}
        .{css_prefix}-destination-card:hover {{
            border-color: alpha(@accent_color, 0.42);
            background-color: alpha(@accent_bg_color, 0.07);
            box-shadow: {CARD_HOVER_SHADOW};
            transform: translateY(-2px);
        }}
    """


def premium_css() -> str:
    """Return theme-adaptive CSS shared by Build Package and Build ISO."""
    return _PREMIUM_CSS
