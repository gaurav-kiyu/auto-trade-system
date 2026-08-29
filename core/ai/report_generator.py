import logging
import os
from typing import Any

_log = logging.getLogger(__name__)

class GenAIReportBuilder:
    def __init__(self) -> None:
        self.api_key = (os.environ.get("GEMINI_API_KEY") or "").strip()
        self.is_active = bool(self.api_key) and not self.api_key.startswith("your_") and len(self.api_key) > 20

    def generate_report(self, portfolio_data: dict[str, Any]) -> str:
        key = (os.environ.get("GEMINI_API_KEY") or "").strip()
        if not key or key.startswith("your_") or len(key) < 20:
            return self._generate_fallback_report(portfolio_data)

        try:
            import concurrent.futures

            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            model = genai.GenerativeModel("gemini-1.5-flash")

            prompt = f"""
            You are a professional quantitative portfolio manager.
            Write a 2-paragraph executive summary to the client ({portfolio_data.get('user_name', 'Client')})
            explaining their portfolio health score of {portfolio_data.get('portfolio_health_score', 0)}
            and total PnL of Rs {portfolio_data.get('total_unrealized_pnl', 0)}.
            """
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(model.generate_content, prompt)
                response = future.result(timeout=0.8)
            return self._format_final_markdown(portfolio_data, response.text)
        except Exception as e:
            _log.warning(f"GenAI generation failed: {e}. Using fallback.")
            return self._generate_fallback_report(portfolio_data)

    def _format_final_markdown(self, data: dict[str, Any], ai_text: str) -> str:
        user = data.get('user_name', 'Client')
        return f"**Dear {user},**\n\n{ai_text}\n\n### 📊 Stock-by-Stock Guidance\n" + \
               "\n".join([f"- **{g['symbol']}**: {g['action_label']} (Target: ₹{g['target_price']})" for g in data.get('stock_guidance', [])])

    def _generate_fallback_report(self, data: dict[str, Any]) -> str:
        # Fallback local template generator
        user = data.get('user_name', 'Valued Client')
        score = data.get('portfolio_health_score', 0)
        pnl = data.get('total_unrealized_pnl', 0)

        intro = f"**Dear {user},**\n\nOur quantitative 16-strategy diagnostic engine has completed a scan of your portfolio. Your current **Health Score is {score}/100**, and your net unrealized PnL stands at **₹{pnl}**.\n\n"

        body = "### 🤖 AI Market Context & Observations\n"
        if score > 80:
            body += "Your portfolio exhibits strong systemic resilience and excellent sector diversification. The risk-adjusted returns remain well within our safety thresholds.\n\n"
        elif score > 60:
            body += "Your portfolio is stable, but we have identified a few positions that are creating an outsized drag on your overall Sharpe ratio. We recommend reviewing the automated 'Sell' signals.\n\n"
        else:
            body += "⚠️ **Action Required**: Your portfolio has triggered multiple tail-risk and concentration alerts. Immediate rebalancing and auto-hedging is highly recommended to protect your capital.\n\n"

        body += "### 📊 Stock-by-Stock Guidance\n"
        for g in data.get('stock_guidance', []):
            body += f"- **{g['symbol']}**: {g['action_label']} (Target: ₹{g['target_price']})\n"

        return intro + body

_report_builder = GenAIReportBuilder()

def get_report_builder() -> GenAIReportBuilder:
    return _report_builder
