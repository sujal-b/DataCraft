import React, { useState, useMemo } from 'react';
import '../styles/StatisticsSidebar.premium.css'; 
import { 
    FiDatabase, FiTrendingUp, FiShield, FiBarChart2, FiTool, FiTarget, FiZap,
    FiCheckCircle, FiChevronRight, FiTrendingUp as TrendIcon, FiCode, FiX, FiLock,
    FiTerminal, FiDownload, FiActivity, FiAlertCircle, FiClock, FiAward
} from 'react-icons/fi';
import { toast } from 'react-toastify';
import ActionBacklogPanel from './ActionBacklogPanel';

const Loader = ({ text = "Calculating Statistics..." }) => (
    <div className="stats-loader-container">
        <div className="stats-loader"></div>
        <p>{text}</p>
    </div>
);

// --- NEW: VS Code Themed Modal ---
const CodePreviewModal = ({ plan, onClose }) => {
    if (!plan) return null;

    return (
        <div className="code-modal-overlay" style={{
            position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
            backgroundColor: 'rgba(0,0,0,0.6)', zIndex: 9999,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            backdropFilter: 'blur(4px)'
        }}>
            <div className="code-modal-content" style={{
                width: '600px', maxWidth: '90%', 
                backgroundColor: '#fff', borderRadius: '8px', overflow: 'hidden',
                boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04)'
            }}>
                {/* Header matching App Theme */}
                <div className="code-modal-header" style={{
                    padding: '16px 20px', borderBottom: '1px solid #e5e7eb',
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    backgroundColor: '#f9fafb'
                }}>
                    <h4 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '8px', color: '#1f2937' }}>
                        <FiTerminal size={18} color="#4b5563"/> 
                        {plan.name} Logic
                    </h4>
                    <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#6b7280' }}>
                        <FiX size={20} />
                    </button>
                </div>
                
                {/* The "VS Code" Box */}
                <div style={{ padding: '0' }}> 
                    {/* VS Code Title Bar / Breadcrumbs style */}
                    <div style={{
                        backgroundColor: '#252526', color: '#9ca3af', padding: '8px 16px',
                        fontSize: '12px', fontFamily: 'Consolas, Monaco, monospace',
                        borderBottom: '1px solid #333', display: 'flex', alignItems: 'center', gap: '6px'
                    }}>
                        <span style={{ color: '#61dafb' }}>src</span> 
                        <span>/</span>
                        <span style={{ color: '#e06c75' }}>cleaning_plans</span>
                        <span>/</span>
                        <span style={{ color: '#98c379' }}>{plan.name.toLowerCase().replace(/ /g, '_')}.py</span>
                        <span style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '4px', opacity: 0.7 }}>
                            <FiLock size={10} /> Read-Only
                        </span>
                    </div>

                    {/* The Code Editor Area */}
                    <pre style={{
                        margin: 0, padding: '20px', backgroundColor: '#1e1e1e', color: '#d4d4d4',
                        fontFamily: "'Fira Code', Consolas, Monaco, 'Courier New', monospace",
                        fontSize: '13px', lineHeight: '1.5', overflowX: 'auto',
                        whiteSpace: 'pre-wrap', maxHeight: '400px',
                        borderBottomLeftRadius: '8px', borderBottomRightRadius: '8px'
                    }}>
                        <code>{plan.python_code || "# No python code generated."}</code>
                    </pre>
                </div>
            </div>
        </div>
    );
};

// ============================================================================
// PHASE 5.2: EFFECTIVENESS GAUGE COMPONENT
// ============================================================================
const EffectivenessGauge = ({ score, components }) => {
    const pct   = Math.round((score ?? 0) * 100);
    const color = pct >= 75 ? '#10b981' : pct >= 50 ? '#f59e0b' : '#ef4444';
    const label = pct >= 75 ? 'Excellent' : pct >= 50 ? 'Good' : 'Needs Work';

    // SVG arc for needle gauge
    const r = 52, cx = 64, cy = 64;
    const startAngle = -210, endAngle = 30;
    const totalDeg   = endAngle - startAngle;
    const toRad = (d) => (d * Math.PI) / 180;
    const arcX  = (angle, radius) => cx + radius * Math.cos(toRad(angle));
    const arcY  = (angle, radius) => cy + radius * Math.sin(toRad(angle));

    const arcPath = [
        'M', arcX(startAngle, r), arcY(startAngle, r),
        'A', r, r, 0, 1, 1, arcX(endAngle, r), arcY(endAngle, r)
    ].join(' ');
    const filledPath = [
        'M', arcX(startAngle, r), arcY(startAngle, r),
        'A', r, r, 0, (totalDeg * (pct / 100) > 180 ? 1 : 0), 1,
        arcX(startAngle + (pct / 100) * totalDeg, r),
        arcY(startAngle + (pct / 100) * totalDeg, r)
    ].join(' ');

    return (
        <div className="effectiveness-gauge-container">
            <h4 style={{ margin: '0 0 12px', display: 'flex', alignItems: 'center', gap: 6, color: '#1f2937' }}>
                <FiAward size={18} color={color} /> Cleaning Effectiveness
            </h4>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                <svg viewBox="0 0 128 80" width="180" style={{ overflow: 'visible' }}>
                    {/* Track */}
                    <path d={arcPath} fill="none" stroke="#e5e7eb" strokeWidth="10" strokeLinecap="round" />
                    {/* Filled */}
                    <path d={filledPath} fill="none" stroke={color} strokeWidth="10" strokeLinecap="round"
                          style={{ transition: 'stroke-dasharray 0.8s ease' }}/>
                    {/* Score text */}
                    <text x={cx} y={cy - 2} textAnchor="middle" fontSize="22" fontWeight="700" fill={color}>{pct}%</text>
                    <text x={cx} y={cy + 14} textAnchor="middle" fontSize="9" fill="#6b7280">{label}</text>
                </svg>

                {/* Component breakdown */}
                {components && (
                    <div className="effectiveness-breakdown">
                        {[
                            { key: 'missing_reduction_score', label: 'Missing↓', weight: '30%' },
                            { key: 'skew_reduction_score',    label: 'Skew↓',    weight: '20%' },
                            { key: 'ml_improvement_score',   label: 'ML↑',      weight: '40%' },
                            { key: 'leakage_absence_score',  label: 'No Leak',  weight: '10%' },
                        ].map(({ key, label, weight }) => {
                            const val = components[key] ?? 0;
                            const valPct = Math.round(val * 100);
                            const c = valPct >= 70 ? '#10b981' : valPct >= 40 ? '#f59e0b' : '#ef4444';
                            return (
                                <div key={key} className="breakdown-row">
                                    <span className="breakdown-label">{label} <small>({weight})</small></span>
                                    <div className="breakdown-bar-track">
                                        <div className="breakdown-bar-fill" style={{ width: `${valPct}%`, backgroundColor: c }} />
                                    </div>
                                    <span className="breakdown-val" style={{ color: c }}>{valPct}%</span>
                                </div>
                            );
                        })}
                    </div>
                )}
            </div>
        </div>
    );
};


// ============================================================================
// PHASE 5.1: PARALLEL SIMULATION RESULTS (live streaming, per-plan cards)
// ============================================================================
const SCENARIO_META = {
    conservative: { label: 'Conservative', color: '#22c55e', desc: 'LOW risk only' },
    balanced:     { label: 'Balanced',     color: '#f59e0b', desc: 'LOW + MEDIUM risk' },
    aggressive:   { label: 'Aggressive',   color: '#ef4444', desc: 'All actions' },
};

const ParallelSimResultsDisplay = ({
    simData, leakageWarnings, onApplySimulatedPlan, isApplying, onDownloadRecipe, recipeAvailable
}) => {
    const plans        = simData?.plans || [];
    const isRunning    = simData?.status === 'RUNNING' || simData?.status === 'INITIALIZING';
    const baselineMetric = simData?.baseline_metric || 'Score';
    const baseline       = simData?.baseline_score;

    const donePlans = plans.filter(p => p.task_state === 'SUCCESS');
    const bestPlan  = donePlans[0];  // Already sorted by effectiveness_score desc

    return (
        <div className="simulation-results-container">
            <h4 style={{ margin: '0 0 4px', display: 'flex', alignItems: 'center', gap: 6 }}>
                <TrendIcon size={18} /> Parallel Impact Simulation
            </h4>
            {baseline != null && (
                <p style={{ fontSize: '0.8em', color: '#6b7280', margin: '0 0 12px' }}>
                    Baseline {baselineMetric}: <strong>{typeof baseline === 'number' ? baseline.toFixed(4) : 'N/A'}</strong>
                </p>
            )}

            {/* Global leakage warnings */}
            {leakageWarnings?.length > 0 && (
                <div className="leakage-warning-box" style={{
                    background: '#fee2e2', border: '1px solid #ef4444',
                    borderRadius: 6, padding: 10, marginBottom: 12
                }}>
                    <div style={{ display:'flex', alignItems:'center', gap:6, color:'#b91c1c', fontWeight:'bold', fontSize:'0.85em' }}>
                        <FiShield size={14}/> Data Leakage Detected (raw data)
                    </div>
                    <ul style={{ margin:'6px 0 0 12px', color:'#7f1d1d', fontSize:'0.8em' }}>
                        {leakageWarnings.map((w, i) => <li key={i}>{w}</li>)}
                    </ul>
                </div>
            )}

            <p className="plans-subtitle" style={{ marginBottom: 10 }}>
                {isRunning ? 'Workers running — results stream in as each completes...' : 'All scenarios validated. Apply the best plan.'}
            </p>

            <div className="plans-list">
                {['conservative', 'balanced', 'aggressive'].map((scenarioKey) => {
                    const plan = plans.find(p => p.scenario_name === scenarioKey);
                    const meta = SCENARIO_META[scenarioKey];
                    const isPending  = !plan || plan.task_state === 'PENDING';
                    const isFailed   = plan?.task_state === 'FAILURE';
                    const isSuccess  = plan?.task_state === 'SUCCESS';
                    const isBest     = isSuccess && plan === bestPlan;

                    const effScore = isSuccess ? Math.round((plan.effectiveness_score ?? 0) * 100) : null;
                    const effColor = effScore >= 70 ? '#10b981' : effScore >= 45 ? '#f59e0b' : '#ef4444';

                    return (
                        <div key={scenarioKey}
                             className={`plan-card ${isBest ? 'best-plan' : ''}`}
                             style={{
                                 borderLeft: `4px solid ${meta.color}`,
                                 position: 'relative',
                                 opacity: isFailed ? 0.65 : 1
                             }}
                        >
                            {/* Header */}
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                                <span style={{
                                    width: 10, height: 10, borderRadius: '50%',
                                    backgroundColor: meta.color, flexShrink: 0
                                }} />
                                <strong style={{ color: '#1f2937' }}>{meta.label}</strong>
                                <small style={{ color: '#9ca3af' }}>({meta.desc})</small>
                                {isBest && (
                                    <span style={{
                                        marginLeft: 'auto', background: '#dcfce7', color: '#16a34a',
                                        borderRadius: 10, padding: '2px 8px', fontSize: '0.7em', fontWeight: 700
                                    }}>★ Best</span>
                                )}
                            </div>

                            {/* State-specific body */}
                            {isPending && (
                                <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: '#6b7280', fontSize:'0.85em', padding: '6px 0' }}>
                                    <div className="small-loader" />
                                    {simData?.status === 'INITIALIZING'
                                        ? 'Computing ML baseline...'
                                        : 'Validation in progress...'}
                                </div>
                            )}

                            {isFailed && (
                                <div style={{ display: 'flex', alignItems: 'center', gap: 6, color: '#dc2626', fontSize: '0.82em' }}>
                                    <FiAlertCircle size={14} />
                                    {plan.error || 'Simulation failed for this scenario.'}
                                </div>
                            )}

                            {isSuccess && (
                                <>
                                    {/* Effectiveness Score */}
                                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                                        <div style={{ flex: 1 }}>
                                            <div style={{ fontSize: '0.82em', color: '#6b7280', marginBottom: 4 }}>Effectiveness Score</div>
                                            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                                <div style={{ flex: 1, height: 8, background: '#e5e7eb', borderRadius: 4, overflow: 'hidden' }}>
                                                    <div style={{
                                                        width: `${effScore}%`, height: '100%',
                                                        backgroundColor: effColor, borderRadius: 4,
                                                        transition: 'width 0.6s ease'
                                                    }} />
                                                </div>
                                                <strong style={{ color: effColor, minWidth: 36 }}>{effScore}%</strong>
                                            </div>
                                        </div>
                                    </div>

                                    {/* Sub-scores */}
                                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px 12px', fontSize: '0.75em', color: '#6b7280', marginBottom: 8 }}>
                                        <span>Missing↓: <b style={{color:'#374151'}}>{Math.round((plan.missing_reduction_score ?? 0)*100)}%</b></span>
                                        <span>Skew↓: <b style={{color:'#374151'}}>{Math.round((plan.skew_reduction_score ?? 0)*100)}%</b></span>
                                        <span>ML↑: <b style={{color:'#374151'}}>{Math.round((plan.ml_improvement_score ?? 0)*100)}%</b></span>
                                        <span>No-Leak: <b style={{color:'#374151'}}>{plan.leakage_absence_score === 1 ? '✓' : '✗'}</b></span>
                                    </div>

                                    {/* Impact string */}
                                    {plan.impact_string && (
                                        <p style={{ fontSize: '0.8em', color: plan.delta_percent >= 0 ? '#16a34a' : '#dc2626', margin: '0 0 10px' }}
                                           dangerouslySetInnerHTML={{ __html: plan.impact_string }}
                                        />
                                    )}

                                    {/* Apply button */}
                                    <button
                                        className={`apply-plan-btn ${isBest ? 'primary' : 'secondary'}`}
                                        onClick={() => onApplySimulatedPlan(scenarioKey, plan.ml_improvement_score)}
                                        disabled={isApplying}
                                        style={{ width: '100%', marginTop: 0 }}
                                    >
                                        {isApplying ? <div className="small-loader"/> : <FiCheckCircle size={14}/>}
                                        {isApplying ? 'Applying...' : `Apply ${meta.label} Plan (${plan.actions_count} actions)`}
                                    </button>

                                    {/* Per-plan leakage */}
                                    {plan.leakage_warnings?.length > 0 && (
                                        <div style={{ marginTop: 6, fontSize: '0.75em', color: '#dc2626', display: 'flex', alignItems: 'flex-start', gap: 4 }}>
                                            <FiAlertCircle size={12} style={{ marginTop: 1, flexShrink: 0 }}/>
                                            {plan.leakage_warnings.length} leakage warning{plan.leakage_warnings.length > 1 ? 's' : ''} in cleaned data
                                        </div>
                                    )}
                                </>
                            )}
                        </div>
                    );
                })}
            </div>

            {/* Download Recipe */}
            {recipeAvailable && (
                <button
                    className="simulation-run-btn"
                    onClick={onDownloadRecipe}
                    style={{ marginTop: 12, background: 'linear-gradient(135deg, #1e40af, #3b82f6)' }}
                >
                    <FiDownload size={16}/> Download Cleaning Recipe (.json)
                </button>
            )}
        </div>
    );
};

const IntelligentValidationEngine = ({ 
    diagnosticReport, isReportLoading, onGeneratePlans, goal, setGoal, 
    targetVariable, setTargetVariable, arePlansLoading 
}) => {
    
    const numericColumns = useMemo(() =>
        diagnosticReport?.column_diagnostics
            ?.filter(c => ['integer', 'float'].includes(c.data_type))
            .map(c => c.column_name) || [],
    [diagnosticReport]);

    const handleGenerateClick = () => {
        if (!targetVariable) {
            toast.warn("Please select a target variable to generate plans.");
            return;
        }
        onGeneratePlans();
    };
    
    if (isReportLoading) return <Loader text="Loading Diagnostic Report..." />;
    if (!diagnosticReport) return (<div className="no-data-message"><FiBarChart2 size={48} /><p>No diagnostic report available.</p></div>);
    
    return (
        <div className="simulation-controls">
            <h4><FiTool size={18} /> Co-pilot: Intelligent Cleaning</h4>
            <p>Let the AI generate and validate cleaning plans to prepare your data for modeling.</p>
            <div className="control-group">
                <label><FiBarChart2 size={16}/> Modeling Goal</label>
                <select value={goal} onChange={e => setGoal(e.target.value)} disabled={arePlansLoading}>
                    <option value="stable_forecasting">Stable Forecasting</option>
                    <option value="max_performance">Maximize Performance</option>
                </select>
            </div>
            <div className="control-group">
                <label><FiTarget size={16}/> Target Variable (to Predict)</label>
                <select value={targetVariable} onChange={e => setTargetVariable(e.target.value)} disabled={arePlansLoading}>
                    <option value="">Select a numeric column...</option>
                    {numericColumns.map(col => <option key={col} value={col}>{col}</option>)}
                </select>
            </div>
            <button onClick={handleGenerateClick} className="generate-plans-btn" disabled={!targetVariable || arePlansLoading}>
                {arePlansLoading ? (
                    <><div className="small-loader"></div> Generating...</>
                ) : (
                    <><FiZap size={16}/> Generate Treatment Plans</>
                )}
            </button>
        </div>
    );
};

const TreatmentPlansDisplay = ({ plans, onRunSimulation, isSimulating, onViewCode }) => {
    const planOrder = ['conservative_plan', 'balanced_plan', 'aggressive_plan', 'architect_plan'];
    
    if (!plans || Object.keys(plans).length === 0) {
        return (
            <div className="error-message">
                <strong>No Plans Generated</strong>
                <p>The AI could not generate treatment plans based on the provided data.</p>
            </div>
        );
    }

    return (
        <div className="treatment-plans-container">
            <h4>AI-Generated Treatment Plans</h4>
            <p className="plans-subtitle">The Co-pilot has generated three strategic plans. Review the logic before simulating.</p>
            <div className="plans-list">
                {planOrder.map(planKey => {
                    const plan = plans[planKey];
                    if (!plan) return null;
                    return (
                        <div key={planKey} className={`plan-card ${planKey}`} style={{ position: 'relative', padding: '16px' }}>
                            {/* --- VIEW CODE BUTTON (Top Right) --- */}
                            <button 
                                onClick={() => onViewCode(plan)}
                                title="View Python Code"
                                style={{
                                    position: 'absolute', top: '12px', right: '12px',
                                    background: 'transparent', border: '1px solid rgba(0,0,0,0.1)',
                                    borderRadius: '4px', padding: '4px', cursor: 'pointer',
                                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                                    color: '#555', zIndex: 10
                                }}
                            >
                                <FiCode size={16} />
                            </button>

                            {/* Fixed Header Layout */}
                            <div className="plan-header" style={{ 
                                display: 'flex', 
                                alignItems: 'center',
                                paddingRight: '40px', // Prevent overlap with button
                                marginBottom: '8px'
                            }}> 
                                <h5 style={{ margin: 0 }}>{plan.name}</h5>
                            </div>
                            
                            <p className="plan-rationale">{plan.rationale}</p>
                            <ul className="plan-steps">
                                {plan.steps && plan.steps.length > 0 ? plan.steps.map((step, index) => (
                                    <li key={index}>
                                        <FiCheckCircle size={14} className="step-icon"/>
                                        <div className="step-details">
                                            <strong>{step.function_name}</strong> on <span>{step.target_columns?.join(', ') || 'Dataset'}</span>
                                            <small>{step.reasoning}</small>
                                        </div>
                                    </li>
                                )) : <li className="no-steps-message">No cleaning steps required for this plan.</li>}
                            </ul>
                        </div>
                    );
                })}
            </div>
            <button className="simulation-run-btn" onClick={onRunSimulation} disabled={isSimulating}>
                {isSimulating ? <div className="small-loader"></div> : <FiChevronRight size={16} />}
                {isSimulating ? 'Simulation in Progress...' : 'Run Impact Simulation'}
            </button>
        </div>
    );
};

const SimulationResultsDisplay = ({ results, warnings, onApplyPlan, isApplying, onViewCode }) => {
    return (
        <div className="simulation-results-container">
            <h4><TrendIcon size={18} /> Impact Simulation Results</h4>

            {warnings && warnings.length > 0 && (
                <div className="leakage-warning-box" style={{
                    backgroundColor: '#fee2e2', 
                    border: '1px solid #ef4444', 
                    borderRadius: '6px', padding: '12px', marginBottom: '16px'
                }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#b91c1c', fontWeight: 'bold' }}>
                        <FiShield size={16} /> Data Leakage Detected
                    </div>
                    <ul style={{ margin: '8px 0 0 6px', color: '#7f1d1d', fontSize: '0.9em' }}>
                        {warnings.map((w, i) => <li key={i}>{w}</li>)}
                    </ul>
                </div>
            )}

            <p className="plans-subtitle">Plans have been validated. Inspect the code or apply the transformation.</p>
            <div className="plans-list">
                {results.map((plan, index) => {
                    const impact = plan.measured_impact;
                    const isImprovement = impact.delta_percent > 0;
                    const isBest = index === 0;

                    return (
                        <div key={`${plan.name}-${index}`} className={`plan-card rank-${index + 1} ${isBest ? 'best-plan' : ''}`} style={{ position: 'relative' }}>
                            {/* --- VIEW CODE BUTTON (Top Right) --- */}
                            <button 
                                onClick={() => onViewCode(plan)}
                                title="View Python Code"
                                style={{
                                    position: 'absolute', top: '12px', right: '12px',
                                    background: 'rgba(255,255,255,0.5)', border: '1px solid rgba(0,0,0,0.1)',
                                    borderRadius: '4px', padding: '4px', cursor: 'pointer',
                                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                                    color: '#333'
                                }}
                            >
                                <FiCode size={16} />
                            </button>

                            <div className="plan-header" style={{ 
                                display: 'flex', 
                                alignItems: 'flex-start',
                                paddingRight: '40px', // Prevent title from hitting the code button
                                gap: '10px',
                                marginBottom: '12px'
                            }}>
                                <div style={{ flex: 1 }}>
                                    <h5 style={{ margin: '0 0 4px 0' }}>{plan.name}</h5>
                                    <p 
                                        className={`impact-string ${isImprovement ? 'positive' : 'negative'}`}
                                        dangerouslySetInnerHTML={{ __html: impact.impact_string }} 
                                        style={{ fontSize: '0.9em', margin: 0, fontWeight: 'bold' }}
                                    />
                                </div>
                            </div>
                            
                            <button 
                                className={`apply-plan-btn ${isBest ? 'primary' : 'secondary'}`}
                                onClick={() => onApplyPlan(plan)}
                                disabled={isApplying}
                                style={{ marginTop: '0', width: '100%' }}
                            >
                                {isApplying ? <div className="small-loader"></div> : <FiCheckCircle size={14} />}
                                {isApplying ? 'Applying...' : 'Apply This Plan'}
                            </button>
                        </div>
                    );
                })}
            </div>
        </div>
    );
};

const StatisticsSidebar = ({ 
    statistics, isLoading, sidebarState, setSidebarState, sidebarMode,
    diagnosticReport, isReportLoading, goal, setGoal, targetVariable, setTargetVariable,
    arePlansLoading, treatmentPlans, onGeneratePlans, onRunSimulation, isSimulating,
    simulationResults, parallelSimResults, simulationWarnings,
    onApplyPlan, onApplySimulatedPlan, isApplying,
    onDownloadRecipe, recipeAvailable
}) => {
    const [activeTab, setActiveTab]       = useState('overview');
    const [planToPreview, setPlanToPreview] = useState(null);

    if (sidebarState === 'closed') return null;

    const renderStatistics = () => {
        if (isLoading) return <Loader />;
        if (!statistics) return (<div className="no-data-message"><FiBarChart2 size={48} /><p>No statistics available.</p></div>);
        
        const hasEffectiveness = statistics.cleaning_effectiveness != null;
        const eff = statistics.cleaning_effectiveness;
        const effPct = hasEffectiveness ? Math.round(eff * 100) : null;
        const effColor = effPct >= 75 ? '#10b981' : effPct >= 50 ? '#f59e0b' : '#ef4444';

        return (
            <>
                <div className="stats-tabs">
                    <button className={`tab-btn ${activeTab === 'overview' ? 'active' : ''}`} onClick={() => setActiveTab('overview')}>Overview</button>
                    <button className={`tab-btn ${activeTab === 'columns' ? 'active' : ''}`} onClick={() => setActiveTab('columns')}>Columns</button>
                </div>
                <div className="stats-content-body">
                    {activeTab === 'overview' && (
                        <>
                            {/* Phase 5: Show effectiveness gauge if available, else quality score */}
                            <div className="stat-group">
                                <div className="stat-group-header"><FiShield size={16}/> Data Quality</div>
                                {hasEffectiveness ? (
                                    <>
                                        <div className="quality-metric">
                                            <span>Cleaning Effectiveness</span>
                                            <strong style={{ color: effColor }}>{effPct}%</strong>
                                        </div>
                                        <div className="progress-bar-container">
                                            <div className="progress-bar" style={{ width: `${effPct}%`, background: `linear-gradient(90deg, ${effColor}, ${effColor}cc)` }}/>
                                        </div>
                                        <div className="quality-metric" style={{ marginTop: 4 }}>
                                            <span style={{ color: '#9ca3af', fontSize:'0.8em' }}>Overall Quality</span>
                                            <strong style={{ color: '#9ca3af', fontSize:'0.8em' }}>{statistics.qualityScore?.toFixed(1)}%</strong>
                                        </div>
                                    </>
                                ) : (
                                    <>
                                        <div className="quality-metric">
                                            <span>Overall Quality</span>
                                            <strong>{statistics.qualityScore?.toFixed(1)}%</strong>
                                        </div>
                                        <div className="progress-bar-container">
                                            <div className="progress-bar" style={{ width: `${statistics.qualityScore}%` }}/>
                                        </div>
                                    </>
                                )}
                            </div>
                            <div className="stat-group">
                                <div className="stat-group-header"><FiDatabase size={16}/> Dataset Overview</div>
                                <div className="overview-grid">
                                    <div className="overview-grid-item rows"><div className="value">{statistics.rows?.toLocaleString()}</div><div className="label">Rows</div></div>
                                    <div className="overview-grid-item columns"><div className="value">{statistics.columns}</div><div className="label">Columns</div></div>
                                    <div className="overview-grid-item cells"><div className="value">{statistics.totalCells?.toLocaleString()}</div><div className="label">Total Cells</div></div>
                                    <div className="overview-grid-item nulls"><div className="value">{statistics.overallNullCount?.toLocaleString()}</div><div className="label">Null Values</div></div>
                                </div>
                            </div>
                            <div className="stat-group">
                                <div className="stat-group-header"><FiTrendingUp size={16}/> Quick Insights</div>
                                <div className="insight-metric">
                                    <span>Numeric Columns</span>
                                    <strong>{statistics.numericColumnCount}</strong>
                                </div>
                                <div className="insight-metric">
                                    <span>Text Columns</span>
                                    <strong>{statistics.textColumnCount}</strong>
                                </div>
                            </div>
                        </>
                    )}
                    {activeTab === 'columns' && (
                        <div className="columns-tab">
                            {statistics.columnStats?.map((stat) => (
                                <div key={stat.column} className="column-stat-card">
                                    <div className="column-header">
                                        <h5 title={stat.column}>{stat.column}</h5>
                                        <span className={`data-type-badge ${stat.dataType}`}>{stat.dataType}</span>
                                    </div>
                                    <div className="column-details-grid">
                                        <div className="label">Values</div><div className="value">{stat.totalValues?.toLocaleString()}</div>
                                        <div className="label">Unique</div><div className="value">{stat.uniqueValues?.toLocaleString()}</div>
                                        <div className="label">Null</div><div className="value null">{stat.nullCount} ({stat.nullPercentage?.toFixed(1)}%)</div>
                                        
                                        {(stat.dataType === 'integer' || stat.dataType === 'float') && (
                                            <>
                                                <div className="label">Mean</div><div className="value">{stat.mean}</div>
                                                <div className="label">Median</div><div className="value">{stat.median}</div>
                                                <div className="label">Mode</div><div className="value">{stat.mode}</div>
                                            </>
                                        )}
                                    </div>
                                    <div className="column-footer">
                                        <div className="quality-metric">
                                            <span className="label">Data Completeness</span>
                                            <strong>{(100 - stat.nullPercentage).toFixed(1)}%</strong>
                                        </div>
                                        <div className="progress-bar-container">
                                            <div className="progress-bar" style={{ width: `${100 - stat.nullPercentage}%` }}></div>
                                        </div>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            </>
        );
    };

    const renderCoPilot = () => {
        // Phase 5: Show parallel simulation results if available (preferred)
        if (isSimulating && !parallelSimResults) {
            return (
                <div className="stats-content-body">
                    <Loader text="Dispatching simulation workers — results appear as each completes..." />
                </div>
            );
        }

        // Streaming parallel sim results (live update during or after simulation)
        if (parallelSimResults) {
            return (
                <div className="stats-content-body">
                    <ParallelSimResultsDisplay
                        simData={parallelSimResults}
                        leakageWarnings={parallelSimResults.leakage_warnings}
                        onApplySimulatedPlan={onApplySimulatedPlan}
                        isApplying={isApplying}
                        onDownloadRecipe={onDownloadRecipe}
                        recipeAvailable={recipeAvailable}
                    />
                    {/* Show effectiveness gauge for best completed plan */}
                    {(() => {
                        const bestPlan = parallelSimResults.plans?.find(p => p.task_state === 'SUCCESS');
                        if (!bestPlan) return null;
                        return (
                            <EffectivenessGauge
                                score={bestPlan.effectiveness_score}
                                components={{
                                    missing_reduction_score: bestPlan.missing_reduction_score,
                                    skew_reduction_score:    bestPlan.skew_reduction_score,
                                    ml_improvement_score:    bestPlan.ml_improvement_score,
                                    leakage_absence_score:   bestPlan.leakage_absence_score,
                                }}
                            />
                        );
                    })()}
                </div>
            );
        }

        // Legacy simulation results (fallback)
        if (simulationResults) {
            return <div className="stats-content-body">
                <SimulationResultsDisplay 
                    results={simulationResults}
                    warnings={simulationWarnings}
                    onApplyPlan={onApplyPlan} 
                    isApplying={isApplying}
                    onViewCode={setPlanToPreview}
                />
            </div>;
        }

        if (treatmentPlans) {
            return <ActionBacklogPanel 
                actions={treatmentPlans.actions || []}
                domainInference={treatmentPlans.domain_inference}
                leakageWarnings={treatmentPlans.leakage_warnings}
                reasoningTrace={treatmentPlans.reasoning_trace}
                onExecuteActions={(selectedActions) => onApplyPlan(selectedActions)}
                isExecuting={isApplying}
                allColumns={diagnosticReport?.column_diagnostics?.map(c => c.column_name) || []}
                datasetProfile={statistics}
                onRunSimulation={onRunSimulation}
                isSimulating={isSimulating}
            />;
        }

        return (
            <IntelligentValidationEngine 
                diagnosticReport={diagnosticReport}
                isReportLoading={isReportLoading}
                onGeneratePlans={onGeneratePlans}
                goal={goal}
                setGoal={setGoal}
                targetVariable={targetVariable}
                setTargetVariable={setTargetVariable}
                arePlansLoading={arePlansLoading}
            />
        );
    };

    return (
        <>
            <div className={`statistics-sidebar ${sidebarState === 'open' ? 'open' : ''}`}>
                <div className="sidebar-header">
                    <h3>{sidebarMode === 'statistics' ? 'Dataset Statistics' : 'Co-pilot Engine'}</h3>
                    <button onClick={() => setSidebarState('closed')} className="close-btn">&times;</button>
                </div>
                <div className="sidebar-content">
                    {sidebarMode === 'statistics' ? <div className="stats-content-body">{renderStatistics()}</div> : renderCoPilot()}
                </div>
            </div>
            
            {/* Modal for viewing code */}
            <CodePreviewModal plan={planToPreview} onClose={() => setPlanToPreview(null)} />
        </>
    );
};

export default StatisticsSidebar;