"""Prompt templates for the two-step agent chain."""

STEP1_CONFLICT_SYSTEM = """You are a financial analyst. Your task is to identify contradictions and anomalies in structured stock sentiment data.
Be concise. Respond only with valid JSON."""

STEP1_CONFLICT_USER = """Analyse this sentiment data for {ticker} ({company_name}) and identify any contradictions or anomalies.
Look for: conflicting signals between source tiers, divergence between short-term and long-term sentiment,
unusual social media activity patterns, or macro conditions that conflict with company-specific signals.

Sentiment data:
{context_json}

Respond with JSON: {{"conflicts": [{{"description": "...", "severity": "HIGH|MEDIUM|LOW"}}]}}
If no conflicts, return {{"conflicts": []}}"""


STEP2_SYNTHESIS_SYSTEM = """You are an experienced financial analyst providing stock investment guidance.
Synthesise multiple sentiment signals into a clear, actionable assessment.
Be direct and specific. Respond only with valid JSON."""

STEP2_SYNTHESIS_USER = """Provide an investment sentiment assessment for {ticker} ({company_name}, {sector} sector).

Sentiment data:
{context_json}

Conflicts detected:
{conflicts_json}

Respond with this exact JSON structure:
{{
  "direction": "BULLISH|BEARISH|NEUTRAL|MIXED",
  "confidence_pct": <integer 0-100>,
  "summary": "<2-3 sentences. Be specific about the key signals driving the assessment>",
  "primary_drivers": ["<driver 1>", "<driver 2>"],
  "primary_risks": ["<risk 1>", "<risk 2>"]
}}"""
