import json
import logging
import os
import requests
import re
import time

logger = logging.getLogger("datacraft.ai")
_AIServiceError = ValueError


def _get_api_key() -> str:
    """
    Resolve the OpenRouter API key at call time.

    Deliberately lazy: importing this module must never fail because a secret is
    absent, otherwise every non-AI endpoint in the app would fail to start. The
    key is only required when an AI call is actually made.

    There is intentionally no default value here. A baked-in fallback would let a
    missing environment variable silently degrade into using an unknown
    (possibly leaked, possibly someone else's) credential.
    """
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        raise _AIServiceError(
            "OPENROUTER_API_KEY environment variable is not set. "
            "AI features are disabled until it is configured."
        )
    return key


def _call_openrouter_api(system_prompt: str, user_prompt: str, temperature: float = 0.2) -> dict:
    """
    A private helper function to handle the actual API call to OpenRouter.
    Includes RETRY LOGIC to handle malformed JSON responses from the AI.
    """
    MAX_RETRIES = 3

    try:
        api_key = _get_api_key()
    except _AIServiceError as e:
        logger.warning("AI Service unavailable: %s", e)
        return {"error": "AI Service Not Configured", "details": str(e)}

    for attempt in range(MAX_RETRIES):
        try:
            # We use a slight backoff if it's a retry
            if attempt > 0:
                time.sleep(1)

            response = requests.post(
                url="https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "http://localhost:3000",
                    "X-Title": "DataCraft Studio"
                },
                data=json.dumps({
                    "model": "minimax/minimax-m2.7:free",
                    "temperature": temperature,
                    # asking for json_object can help if the model supports it
                    "response_format": { "type": "json_object" },
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ]
                }),
                timeout=120
            )
            response.raise_for_status()
            response_data = response.json()

            if not response_data.get('choices'):
                raise ValueError("AI Service returned no content choices.")

            ai_content_string = response_data['choices'][0]['message']['content']

            # --- Cleaning Step 1: Remove Markdown Code Blocks ---
            # This handles ```json ... ``` or just ``` ... ``` wrapping
            cleaned_string = re.sub(r'^```[a-z]*\s*', '', ai_content_string, flags=re.MULTILINE)
            cleaned_string = re.sub(r'\s*```$', '', cleaned_string, flags=re.MULTILINE)
            cleaned_string = cleaned_string.strip()

            # --- Cleaning Step 2: Find JSON boundaries ---
            # We look for the first '{' and the last '}'
            json_match = re.search(r'\{.*\}', cleaned_string, re.DOTALL)

            if not json_match:
                # If we can't find braces, the output is definitely not JSON.
                logger.debug("DEBUG (Attempt %d): No JSON braces found in output: %s...", attempt + 1, ai_content_string[:100])
                continue # Retry

            json_string = json_match.group(0)

            # --- Validation Step ---
            return json.loads(json_string)

        except json.JSONDecodeError as e:
            logger.warning("JSON Parse Error in _call_openrouter_api (Attempt %d/%d): %s", attempt + 1, MAX_RETRIES, e)
            # If it's the last attempt, we let the loop finish to return the error
            if attempt == MAX_RETRIES - 1:
                logger.debug("DEBUG: Failed Content was:\n%s", ai_content_string)
        except Exception as e:
            logger.warning("Network/API Error in _call_openrouter_api (Attempt %d/%d): %s", attempt + 1, MAX_RETRIES, e)
            if attempt == MAX_RETRIES - 1:
                return {
                    "error": "AI Service Connection Failed",
                    "details": str(e)
                }

    # If we exit the loop, we failed to get valid JSON
    return {
        "error": "AI Generation Failed",
        "details": "The AI model failed to generate valid JSON after multiple attempts. Please try again."
    }

def get_ai_interpretation(profile: dict) -> dict:
    """
    Sends a detailed statistical profile to an LLM for expert interpretation (existing functionality).
    """
    system_prompt = """
    You are a principal data scientist with 20+ years experience. Your task is to analyze a statistical profile of a column and provide a professional recommendation that reflects how human experts think — not rigid rule-following.

    ## HOW REAL DATA SCIENTISTS THINK (NOT RULE ENGINES)
    When handling missing data, experienced professionals:
    - **Distinguish between count and percentage.** A `missing_count` of 3 is a minor issue in 40,000 rows (low `missing_pct`), but you must still question *why* even those few are missing. A `missing_count` of 3 in 10 rows is critical.
    - **Never treat thresholds as absolute** (e.g., "60% missing" is a signal, not a rule)
    - **Infer domain from data patterns** (e.g., "temperature" + high ACF → sensor data)
    - **Acknowledge uncertainty** ("Without domain knowledge, I'd verify X first")
    - **Explain why alternatives were rejected** ("ffill would distort volatility here")

    ## YOUR ANALYSIS WORKFLOW (CHAIN OF THOUGHT)
    Follow this reasoning pattern **in your <thinking> block**:

    1. **DOMAIN INFERENCE** → What domain does this likely belong to? (IoT, finance, healthcare, etc.)
    → **Evidence**: "Column name='temperature' + high ACF(1)=0.88 → IoT sensor data"
    → **Contradictions**: "But MNAR pattern suggests possible financial context"

    2. **MISSINGNESS PATTERN ASSESSMENT** → "MNAR indicators exist (humidity: -0.65) → systematic bias likely"
    → "BUT high temporal stability (ACF=0.88) suggests gradual change"
    → **Critical question**: "Is the correlation meaningful or coincidental?"

    3.  **RISK-BASED EVALUATION** → "For sensor data, bias could cause safety issues"
    → "For financial data, bias could trigger regulatory penalties"
    → "What's the cost of being wrong? (e.g., $10k vs $1M impact)"

    4.  **TECHNIQUE TRADEOFF ANALYSIS** → "ffill would be fast but assumes stability during gaps"
    → "MICE would be accurate but requires sufficient data"
    → **Key insight**: "For this domain, [X] matters more than [Y]"

    5.  **DECISION WITH UNCERTAINTY** → "Recommend [X], but only if [critical assumption] holds"
    → "Without [domain knowledge], I'd verify [specific check] first"
    → "This assumes [unstated condition] — flag if violated"

    ## CRITICAL SAFEGUARDS (NOT RULES)
    - **High missingness**: "60%+ missing is a red flag, but dropping may lose critical signals"
    - **MNAR patterns**: "Correlation >0.3 suggests systematic bias, but could be coincidental"
    - **Time-series**: "ACF>0.85 supports ffill, but only if gaps align with stable periods"

    ## YOUR RESPONSE FORMAT
    <thinking>
    [Your step-by-step reasoning using the workflow above]
    </thinking>

    {
    "recommendation": "Specific technique with parameters (e.g., 'ffill with max gap=3h')",
    "reasoning_summary": "Concise justification with domain context",
    "assumptions": ["Domain: IoT/sensor (evidence: column name + ACF)", "Gaps occur during calibration"],
    "warning": "Critical risk: If gaps occur during equipment failure, ffill would distort readings"
    }
    """

    user_prompt = f"Here is the statistical profile to analyze:\n{json.dumps(profile, indent=2)}"

    return _call_openrouter_api(system_prompt, user_prompt)

# === HELPER: TOKEN-SAFE REPORT CONDENSATION ===
def _condense_diagnostic_report(report: dict, top_n: int = 25) -> dict:
    """
    Reduces token count by ~90% while preserving critical diagnostic signals.
    Keeps full details only for problematic columns.
    """
    # 1. Base Structure
    condensed = {
        "modeling_context": report.get("modeling_context", {}),
        "missingness_overview": report.get("missingness", {}),
        "skew_overview": report.get("distribution_skew", {}),
        "target_correlations": report.get("target_correlations", {}),
        "note": "Full column details condensed to top problematic columns. Healthy columns omitted."
    }

    # 2. Identify Critical Columns
    critical_cols = set()

    # Add top missing
    missing_cols = sorted(report.get('missingness', {}).items(), key=lambda x: x[1], reverse=True)[:top_n]
    critical_cols.update([c[0] for c in missing_cols])

    # Add high skew
    skew_cols = [col for col, val in report.get('distribution_skew', {}).items() if abs(val) > 1.5]
    critical_cols.update(skew_cols[:top_n])

    # Add strong correlations
    corr_cols = [col for col, val in report.get('target_correlations', {}).items() if abs(val) > 0.2]
    critical_cols.update(corr_cols[:top_n])

    # 3. Filter Detail Dictionary
    if 'column_details' in report:
        condensed['column_details'] = {
            col: details for col, details in report['column_details'].items()
            if col in critical_cols
        }

    return condensed

# === P0-2 REMNANT REMOVED ===
# `_generate_fallback_plan` was deleted: it fabricated a `python_code` blob that
# older code paths exec()'d. Plans are now strictly validated (extra="forbid")
# Pydantic models and applied only through FUNCTION_REGISTRY — no code strings,
# and the registry-based fallback lives in _generate_pdia_fallback below.


def _sanitize_for_prompt(value, max_len: int = 120):
    """
    P0-2 (prompt-injection hardening): dataset-derived values are embedded in
    LLM prompts, so a malicious CSV could instruct the model to emit arbitrary
    content. Strip control characters and cap length before anything leaves
    the process. Model output is never executed regardless — plans must pass
    the strict function-name registry — this is defence in depth.
    """
    if isinstance(value, str):
        cleaned = ''.join(ch for ch in value if ch.isprintable())
        return cleaned[:max_len]
    return value


def get_treatment_plan_hypotheses(diagnostic_report: dict) -> dict:
    """
    Phase 2: PDIA Framework - Profile-Driven Incremental Actions

    Instead of generating four fixed-archetype plans simultaneously (which wastes tokens
    and forces the LLM to reason in four parallel worlds), generate ONE ranked action backlog —
    a prioritized list of independent, atomic cleaning actions, each with:
    - statistical evidence
    - recommended technique with parameters
    - alternative techniques the user can swap to
    - estimated row/column impact
    - risk classification: LOW / MEDIUM / HIGH
    - reversibility flag: true/false

    This backlog composes cleanly into any methodology. Users can cherry-pick low-risk actions
    for conservative cleaning, or take everything for aggressive cleaning.
    """
    # === 1. CONTEXT EXTRACTION & SAFETY DEFAULTS ===
    context = diagnostic_report.get('modeling_context', {})
    target_var = context.get('target_variable', 'target')
    goal = context.get('goal', 'prediction')
    temporal_col = context.get('temporal_column', None)

    # Extract profile data
    columns_data = diagnostic_report.get('columns', {})
    row_count = diagnostic_report.get('row_count', 0)

    # === 2. TOKEN-OPTIMIZED COLUMN SELECTION ===
    # Pass only columns with issues to the LLM. Healthy columns get auto-generated "no_action_needed" entries.
    problematic_columns = {}
    for col_name, col_data in columns_data.items():
        missing_pct = col_data.get('missing_pct') or 0
        outlier_count = col_data.get('outlier_count') or 0
        skewness = col_data.get('skewness') or 0
        leakage_risk = col_data.get('leakage_risk_score') or 0

        # Include if has any issue
        if missing_pct > 0 or outlier_count > 0 or abs(skewness) > 1.5 or leakage_risk > 0.3:
            problematic_columns[col_name] = col_data

    # Build condensed report with only problematic columns
    condensed_columns = problematic_columns if problematic_columns else columns_data

    # === 3. PDIA SYSTEM PROMPT (TOKEN-EFFICIENT, HIGH-REASONING) ===
    system_prompt = """
    ROLE: Principal data scientist. Analyze a statistical column profile.
    Output a ranked list of atomic cleaning actions.

    COLUMN TYPE RULES (violations = rejected by backend):
    - log_transform, clip_outliers, standard_scale, min_max_scale,
      impute_mean, impute_median → numeric only
    - robust_scale, yeo_johnson_transform, winsorize, knn_impute → numeric only
    - one_hot_encode, label_encode → categorical only
    - impute_mode, create_missing_flag, delete_column → any type
    - forward_fill → numeric + is_time_series=true only

    NEW TECHNIQUE SELECTION RULES (prefer these over old defaults when conditions match):
    - robust_scale → prefer over standard_scale when outlier_count > 0 AND skewness abs > 1.0 (outliers distort mean/std)
    - yeo_johnson_transform → prefer over log_transform when column has negative values (min < 0) OR when log_transform would require large offset
    - winsorize → prefer over clip_outliers when outlier_count is moderate (< 10% of rows) and you want softer treatment; params: lower_percentile=5, upper_percentile=95
    - knn_impute → prefer over impute_mean/impute_median when missingness_mechanism=MAR AND mnar_correlations has entries (correlated columns available for neighbor search); params: n_neighbors=5

    MISSINGNESS MECHANISM CLASSIFICATION:
    - MCAR: missing_pct < 5% AND no mnar_correlations → safe to drop rows or impute simply
    - MAR: mnar_correlations present → impute using correlated columns as evidence
    - MNAR: mnar_correlations strong (>0.5) → flag, consider create_missing_flag first
    - HIGH MISSING: missing_pct > 60% → default recommend delete_column unless leakage_risk > 0.5

    REQUIRED JSON OUTPUT:
    {
      "domain_inference": {
        "likely_domain": string,
        "evidence": string,
        "confidence": "low|medium|high"
      },
      "actions": [
        {
          "action_id": "act_001",
          "priority": 1,
          "column": string,
          "issue": string,           // one sentence: what is wrong
          "function_name": string,   // from allowed list only
          "recommended_params": {},  // e.g. {"strategy": "median"}
          "alternatives": [          // other valid techniques user can swap to
            {"function_name": string, "params": {}, "tradeoff": string}
          ],
          "statistical_evidence": {  // cite actual numbers from profile
            "key_stat": string,
            "value": number
          },
          "missingness_mechanism": "MCAR|MAR|MNAR|N/A",
          "assumption": string,
          "risk_level": "LOW|MEDIUM|HIGH",
          "risk_reason": string,
          "rows_affected_estimate": int,
          "reversible": bool
        }
      ],
      "leakage_warnings": [string],
      "reasoning_trace": string    // paragraph: domain reasoning, key decisions made
    }

    COLUMN DATA (analyze only columns listed here. Reference no others):
    {profile_json}
    """

    # === 4. BUILD USER PROMPT WITH PROFILE DATA ===
    profile_summary = {
        "row_count": row_count,
        "target_variable": target_var,
        "goal": goal,
        "temporal_column": temporal_col,
        "problematic_columns": {
            _sanitize_for_prompt(col_name, 80): {
                "data_type": col_data.get("data_type"),
                "missing_pct": col_data.get("missing_pct"),
                "missing_count": col_data.get("missing_count"),
                "outlier_count": col_data.get("outlier_count"),
                "skewness": col_data.get("skewness"),
                "leakage_risk_score": col_data.get("leakage_risk_score"),
                "mnar_correlations": col_data.get("mnar_correlations"),
                "is_time_series": col_data.get("is_time_series"),
                "mean": col_data.get("mean"),
                "median": col_data.get("median"),
                "std": col_data.get("std"),
                "iqr_lower_fence": col_data.get("iqr_lower_fence"),
                "iqr_upper_fence": col_data.get("iqr_upper_fence"),
                "unique_ratio": col_data.get("unique_ratio"),
                # Prompt-injection hardening: cap sample values, length, count
                "top_values": [
                    {"value": _sanitize_for_prompt(tv.get("value"), 60), "count": tv.get("count")}
                    for tv in (col_data.get("top_values") or [])[:5]
                ] if col_data.get("top_values") else None
            }
            for col_name, col_data in condensed_columns.items()
        }
    }

    user_prompt = f"""
    Analyze this statistical profile and generate a ranked action backlog:
    {json.dumps(profile_summary, indent=2)}

    Priority ranking guidelines:
    1. Leakage risks (leakage_risk_score > 0.5) → highest priority
    2. High missingness (>60%) → consider deletion
    3. MNAR patterns (mnar_correlations > 0.5) → requires careful handling
    4. Outliers with high skew (>2.0) → clipping or transformation
    5. Low missingness (<5%) → simple imputation

    For each action, provide realistic alternatives the user can swap to.
    """

    try:
        # Precision mode (low temp) for production safety
        result = _call_openrouter_api(system_prompt, user_prompt, temperature=0.2)

        # Post-process: Add auto-generated "no_action_needed" entries for healthy columns
        if "actions" in result:
            existing_columns = {action["column"] for action in result["actions"]}
            healthy_columns = set(columns_data.keys()) - existing_columns

            # Add placeholder entries for healthy columns (optional, for UI completeness)
            # These won't be shown as actionable items but indicate they were reviewed

        return result

    except Exception as e:
        # Automatic Fallback
        logger.warning("AI Service Failed: %s. Reverting to Failsafe Plan.", e)
        return _generate_pdia_fallback(diagnostic_report, target_var, goal, temporal_col)


def _generate_pdia_fallback(diagnostic_report: dict, target_var: str, goal: str, temporal_col: str = None) -> dict:
    """
    Hardcoded fallback for PDIA framework when LLM fails.
    Generates basic actions based on simple rules.
    """
    columns_data = diagnostic_report.get('columns', {})
    row_count = diagnostic_report.get('row_count', 0)

    actions = []
    leakage_warnings = []
    action_counter = 1

    for col_name, col_data in columns_data.items():
        missing_pct = col_data.get('missing_pct', 0)
        leakage_risk = col_data.get('leakage_risk_score', 0) or 0
        data_type = col_data.get('data_type', 'unknown')
        missing_count = col_data.get('missing_count', 0)

        # High leakage risk warning
        if leakage_risk > 0.5:
            leakage_warnings.append(f"Column '{col_name}' has high leakage risk (score={leakage_risk:.2f}). Consider removal before modeling.")

        # High missingness → recommend deletion
        if missing_pct > 60:
            actions.append({
                "action_id": f"act_{action_counter:03d}",
                "priority": action_counter,
                "column": col_name,
                "issue": f"Column has {missing_pct:.1f}% missing values",
                "function_name": "delete_column",
                "recommended_params": {},
                "alternatives": [
                    {"function_name": "create_missing_flag", "params": {}, "tradeoff": "Preserves column but adds binary indicator"}
                ],
                "statistical_evidence": {
                    "key_stat": "missing_pct",
                    "value": missing_pct
                },
                "missingness_mechanism": "HIGH_MISSING",
                "assumption": "Missing data is not informative",
                "risk_level": "MEDIUM",
                "risk_reason": "Deleting column loses potential information",
                "rows_affected_estimate": row_count,
                "reversible": False
            })
            action_counter += 1

        # Low missingness → simple imputation
        elif 0 < missing_pct <= 5:
            if data_type in ['integer', 'float']:
                actions.append({
                    "action_id": f"act_{action_counter:03d}",
                    "priority": action_counter,
                    "column": col_name,
                    "issue": f"Column has {missing_pct:.1f}% missing values",
                    "function_name": "impute_median",
                    "recommended_params": {"strategy": "median"},
                    "alternatives": [
                        {"function_name": "impute_mean", "params": {"strategy": "mean"}, "tradeoff": "Mean sensitive to outliers"},
                        {"function_name": "impute_mode", "params": {}, "tradeoff": "Less precise for continuous data"}
                    ],
                    "statistical_evidence": {
                        "key_stat": "missing_pct",
                        "value": missing_pct
                    },
                    "missingness_mechanism": "MCAR",
                    "assumption": "Missing completely at random",
                    "risk_level": "LOW",
                    "risk_reason": "Low missing percentage, median robust to outliers",
                    "rows_affected_estimate": missing_count,
                    "reversible": True
                })
            else:
                actions.append({
                    "action_id": f"act_{action_counter:03d}",
                    "priority": action_counter,
                    "column": col_name,
                    "issue": f"Column has {missing_pct:.1f}% missing values",
                    "function_name": "impute_mode",
                    "recommended_params": {},
                    "alternatives": [
                        {"function_name": "delete_column", "params": {}, "tradeoff": "Loses column entirely"}
                    ],
                    "statistical_evidence": {
                        "key_stat": "missing_pct",
                        "value": missing_pct
                    },
                    "missingness_mechanism": "MCAR",
                    "assumption": "Missing completely at random",
                    "risk_level": "LOW",
                    "risk_reason": "Mode imputation safe for categorical data",
                    "rows_affected_estimate": missing_count,
                    "reversible": True
                })
            action_counter += 1

        # Medium missingness with MNAR → flag
        elif 5 < missing_pct <= 60:
            mnar_corrs = col_data.get('mnar_correlations', {})
            if mnar_corrs:
                max_corr = max(abs(v) for v in mnar_corrs.values())
                if max_corr > 0.5:
                    actions.append({
                        "action_id": f"act_{action_counter:03d}",
                        "priority": action_counter,
                        "column": col_name,
                        "issue": f"Column has {missing_pct:.1f}% missing with MNAR pattern (corr={max_corr:.2f})",
                        "function_name": "create_missing_flag",
                        "recommended_params": {},
                        "alternatives": [
                            {"function_name": "impute_mode", "params": {}, "tradeoff": "Doesn't capture missingness signal"},
                            {"function_name": "impute_median", "params": {}, "tradeoff": "Only for numeric, ignores MNAR"}
                        ],
                        "statistical_evidence": {
                            "key_stat": "mnar_correlation",
                            "value": max_corr
                        },
                        "missingness_mechanism": "MNAR",
                        "assumption": "Missingness is informative",
                        "risk_level": "MEDIUM",
                        "risk_reason": "MNAR requires careful handling",
                        "rows_affected_estimate": missing_count,
                        "reversible": True
                    })
                    action_counter += 1

    return {
        "domain_inference": {
            "likely_domain": "unknown",
            "evidence": "Fallback mode - LLM unavailable",
            "confidence": "low"
        },
        "actions": actions,
        "leakage_warnings": leakage_warnings,
        "reasoning_trace": "Fallback plan generated using rule-based heuristics due to LLM service unavailability. Actions prioritize safety: high-missingness columns flagged for deletion, low-missingness columns get simple imputation, MNAR patterns get missing flags."
    }