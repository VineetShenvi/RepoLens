import markdown as md_converter
from playwright.async_api import async_playwright

async def save_as_pdf(tutorial_text: str):
    html_content = md_converter.markdown(
        tutorial_text,
        extensions=['fenced_code', 'tables', 'codehilite']
    )

    styled_html = f"""
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@300;400;500&family=Syne:wght@400;600;700;800&display=swap');

            * {{ margin: 0; padding: 0; box-sizing: border-box; }}

            body {{
                background: #0a0a0f;
                color: #e8e8f0;
                font-family: 'DM Mono', 'Courier New', monospace;
                font-size: 13px;
                line-height: 1.8;
                padding: 60px;
            }}

            /* Header bar */
            .doc-header {{
                border-bottom: 1px solid #2a2a3a;
                padding-bottom: 24px;
                margin-bottom: 48px;
                display: flex;
                align-items: center;
                justify-content: space-between;
            }}

            .doc-brand {{
                font-family: 'Syne', sans-serif;
                font-size: 22px;
                font-weight: 800;
                color: #7c6af7;
                letter-spacing: -0.03em;
            }}

            .doc-tag {{
                font-size: 10px;
                letter-spacing: 0.2em;
                text-transform: uppercase;
                color: #7c6af7;
                border: 1px solid rgba(124,106,247,0.3);
                padding: 3px 10px;
                border-radius: 2px;
            }}

            /* Headings */
            h1 {{
                font-family: 'Syne', sans-serif;
                font-size: 28px;
                font-weight: 800;
                color: #7c6af7;
                letter-spacing: -0.02em;
                margin: 40px 0 16px;
                padding-bottom: 12px;
                border-bottom: 1px solid #2a2a3a;
            }}

            h2 {{
                font-family: 'Syne', sans-serif;
                font-size: 20px;
                font-weight: 700;
                color: #e8e8f0;
                margin: 32px 0 12px;
                padding-left: 12px;
                border-left: 3px solid #7c6af7;
            }}

            h3 {{
                font-family: 'Syne', sans-serif;
                font-size: 15px;
                font-weight: 600;
                color: #f7a26a;
                margin: 24px 0 8px;
                letter-spacing: 0.05em;
            }}

            h4, h5, h6 {{
                font-family: 'Syne', sans-serif;
                font-size: 13px;
                font-weight: 600;
                color: #6b6b80;
                margin: 16px 0 8px;
                text-transform: uppercase;
                letter-spacing: 0.1em;
            }}

            /* Paragraphs */
            p {{
                margin-bottom: 16px;
                color: #c8c8d8;
            }}

            /* Inline code */
            code {{
                background: rgba(124,106,247,0.1);
                border: 1px solid rgba(124,106,247,0.2);
                color: #f7a26a;
                padding: 2px 7px;
                border-radius: 3px;
                font-family: 'DM Mono', monospace;
                font-size: 12px;
            }}

            /* Code blocks */
            pre {{
                background: #111118;
                border: 1px solid #2a2a3a;
                border-left: 3px solid #7c6af7;
                border-radius: 4px;
                padding: 20px;
                margin: 20px 0;
                overflow-x: auto;
            }}

            pre code {{
                background: none;
                border: none;
                padding: 0;
                color: #e8e8f0;
                font-size: 12px;
                line-height: 1.7;
            }}

            /* Syntax highlighting overrides for dark theme */
            .codehilite {{ background: #111118 !important; }}
            .codehilite .k  {{ color: #7c6af7; }}
            .codehilite .s  {{ color: #4ade80; }}
            .codehilite .s1 {{ color: #4ade80; }}
            .codehilite .s2 {{ color: #4ade80; }}
            .codehilite .n  {{ color: #e8e8f0; }}
            .codehilite .o  {{ color: #f7a26a; }}
            .codehilite .c1 {{ color: #3a3a50; font-style: italic; }}
            .codehilite .nd {{ color: #f7a26a; }}
            .codehilite .nf {{ color: #7c6af7; }}
            .codehilite .mi {{ color: #f7a26a; }}

            /* Lists */
            ul, ol {{
                padding-left: 24px;
                margin-bottom: 16px;
                color: #c8c8d8;
            }}

            li {{
                margin-bottom: 6px;
                padding-left: 4px;
            }}

            ul li::marker {{ color: #7c6af7; }}
            ol li::marker {{ color: #7c6af7; font-family: 'DM Mono', monospace; }}

            /* Blockquotes */
            blockquote {{
                border-left: 3px solid #f7a26a;
                padding: 12px 20px;
                margin: 20px 0;
                background: rgba(247,162,106,0.05);
                border-radius: 0 4px 4px 0;
                color: #6b6b80;
                font-style: italic;
            }}

            /* Tables */
            table {{
                width: 100%;
                border-collapse: collapse;
                margin: 24px 0;
                font-size: 12px;
            }}

            th {{
                background: #1a1a24;
                color: #7c6af7;
                padding: 10px 14px;
                text-align: left;
                font-family: 'Syne', sans-serif;
                font-size: 11px;
                letter-spacing: 0.1em;
                text-transform: uppercase;
                border-bottom: 1px solid #2a2a3a;
            }}

            td {{
                padding: 10px 14px;
                border-bottom: 1px solid #1a1a24;
                color: #c8c8d8;
            }}

            tr:last-child td {{ border-bottom: none; }}
            tr:hover td {{ background: rgba(124,106,247,0.03); }}

            /* Horizontal rule */
            hr {{
                border: none;
                border-top: 1px solid #2a2a3a;
                margin: 32px 0;
            }}

            /* Links */
            a {{
                color: #7c6af7;
                text-decoration: none;
                border-bottom: 1px solid rgba(124,106,247,0.3);
            }}

            /* Footer */
            .doc-footer {{
                margin-top: 64px;
                padding-top: 24px;
                border-top: 1px solid #2a2a3a;
                display: flex;
                justify-content: space-between;
                font-size: 10px;
                color: #3a3a50;
                letter-spacing: 0.1em;
                text-transform: uppercase;
            }}
        </style>
    </head>
    <body>
        <div class="doc-header">
            <div class="doc-brand">RepoLens</div>
            <div class="doc-tag">// repository analysis</div>
        </div>

        {html_content}

        <div class="doc-footer">
            <span>Generated by RepoLens</span>
            <span>// code intelligence</span>
        </div>
    </body>
    </html>
    """

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.set_content(styled_html, wait_until='networkidle')
        pdf_bytes = await page.pdf(
            format='A4',
            margin={'top': '0mm', 'bottom': '0mm', 'left': '0mm', 'right': '0mm'},
            print_background=True,
        )
        await browser.close()
    return pdf_bytes