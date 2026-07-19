"""Shared visual system for the GitRepo desktop applications."""

_PREMIUM_CSS = """
        .sidebar-pane {
            background-color: @sidebar_bg_color;
        }

        .navigation-sidebar row {
            min-height: 44px;
            margin: 2px 0;
            border-radius: 10px;
        }

        .navigation-button {
            padding: 0;
            border: none;
            background: none;
            box-shadow: none;
            font-weight: normal;
        }

        .content-canvas {
            background-color: @window_bg_color;
        }

        .page-frame {
            margin: 20px 24px 28px;
        }

        .section-heading {
            font-weight: 700;
            margin-top: 2px;
        }

        .premium-list {
            border-radius: 14px;
            border: 1px solid alpha(currentColor, 0.08);
            background-color: @card_bg_color;
            box-shadow: 0 1px 2px alpha(black, 0.05);
        }

        .status-ok { color: @success_color; }
        .status-warning { color: @warning_color; }
        .status-error { color: @error_color; }

        .badge.numeric {
            padding: 2px 7px;
            border-radius: 999px;
            background-color: alpha(@warning_bg_color, 0.14);
            color: @warning_color;
            font-weight: 700;
        }

    """


def premium_css() -> str:
    """Return theme-adaptive CSS shared by Build Package and Build ISO."""
    return _PREMIUM_CSS
