import React, { useState, useMemo, useRef, useEffect } from 'react';
import {
    FiAlertCircle, FiCheckCircle, FiXCircle, FiChevronDown, FiChevronUp,
    FiMove, FiTrash2, FiPlus, FiSettings, FiBarChart2, FiInfo
} from 'react-icons/fi';
import { toast } from 'react-toastify';
import '../styles/ActionBacklogPanel.css';
import DistributionPreviewModal from './DistributionPreviewModal';

const RISK_BADGE_CONFIG = {
    LOW: { color: '#059669', bgColor: '#ECFDF5', icon: FiCheckCircle },
    MEDIUM: { color: '#D97706', bgColor: '#FFFBEB', icon: FiAlertCircle },
    HIGH: { color: '#DC2626', bgColor: '#FEF2F2', icon: FiXCircle }
};

const ACTION_FUNCTION_PARAMS = {
    impute_mean: { schema: {}, description: 'Fill missing values with column mean' },
    impute_median: { schema: {}, description: 'Fill missing values with column median' },
    impute_mode: { schema: {}, description: 'Fill missing values with most frequent value' },
    impute_constant: {
        schema: { value: { type: 'string|number', required: true, label: 'Fill Value' } },
        description: 'Fill missing values with a specified constant'
    },
    clip_outliers: {
        schema: {
            lower_fence: { type: 'float', required: true, label: 'Lower Fence (IQR)' },
            upper_fence: { type: 'float', required: true, label: 'Upper Fence (IQR)' }
        },
        description: 'Cap extreme values at IQR fences'
    },
    standard_scale: { schema: {}, description: 'Standardize to mean=0, std=1' },
    min_max_scale: { schema: {}, description: 'Scale to [0, 1] range' },
    one_hot_encode: {
        schema: {
            drop_first: { type: 'bool', default: false, label: 'Drop First Category' },
            max_categories: { type: 'int', default: null, label: 'Max Categories (null=all)' }
        },
        description: 'Convert categories to binary columns'
    },
    label_encode: { schema: {}, description: 'Convert categories to integer labels' },
    create_missing_flag: {
        schema: {
            new_col_suffix: { type: 'string', default: '_is_missing', label: 'Suffix for Flag Column' }
        },
        description: 'Create binary column indicating missingness'
    },
    create_date_features: {
        schema: {
            parts: {
                type: 'multiselect',
                options: ['year', 'month', 'day', 'dayofweek', 'quarter'],
                default: ['year', 'month', 'day'],
                label: 'Date Parts to Extract'
            }
        },
        description: 'Extract temporal features from datetime column'
    },
    create_interaction: {
        schema: {
            col_a: { type: 'column_select', required: true, label: 'First Column' },
            col_b: { type: 'column_select', required: true, label: 'Second Column' },
            operation: {
                type: 'select',
                options: ['multiply', 'divide', 'add', 'subtract'],
                default: 'multiply',
                label: 'Operation'
            }
        },
        description: 'Create interaction feature between two columns'
    },
    forward_fill: {
        schema: {
            max_gap: { type: 'int', default: null, label: 'Max Consecutive Fills (null=unlimited)' }
        },
        description: 'Forward fill missing values (time series only)'
    },
    log_transform: {
        schema: {
            handle_zeros: {
                type: 'select',
                options: ['add_constant', 'clip_to_min'],
                default: 'add_constant',
                label: 'Zero Handling Strategy'
            }
        },
        description: 'Apply log transformation to reduce skewness'
    },
    delete_column: { schema: {}, description: 'Remove column entirely' },
    drop_rows_where_null: { schema: {}, description: 'Delete rows with missing values in this column' },
    drop_duplicate_rows: { schema: {}, description: 'Remove exact duplicate rows' },
    robust_scale: { schema: {}, description: 'Scale using median+IQR — immune to outliers unlike standard scaling' },
    yeo_johnson_transform: {
        schema: {},
        description: 'Power transform that handles negative values — better than log_transform on mixed-sign columns'
    },
    winsorize: {
        schema: {
            lower_percentile: { type: 'float', default: 5, label: 'Lower Percentile Cap (%)' },
            upper_percentile: { type: 'float', default: 95, label: 'Upper Percentile Cap (%)' }
        },
        description: 'Softer than clipping — caps values at chosen percentile instead of IQR fence, preserves more data'
    },
    knn_impute: {
        schema: {
            n_neighbors: { type: 'int', default: 5, label: 'Number of Neighbors (K)' }
        },
        description: 'Impute using K nearest neighbors from correlated columns — more accurate than mean/median for MAR data'
    }
};

// --- Parameter Editor Component ---
const ParameterEditor = ({ action, onChange }) => {
    const funcConfig = ACTION_FUNCTION_PARAMS[action.function_name];
    if (!funcConfig || !funcConfig.schema || Object.keys(funcConfig.schema).length === 0) {
        return null;
    }

    const params = action.recommended_params || {};

    return (
        <div className="parameter-editor">
            <div className="param-editor-header">
                <FiSettings size={14} />
                <span>Parameters for {action.function_name}</span>
            </div>
            <div className="param-fields">
                {Object.entries(funcConfig.schema).map(([key, config]) => {
                    const currentValue = params[key] ?? config.default;

                    if (config.type === 'multiselect') {
                        return (
                            <div key={key} className="param-field">
                                <label>{config.label}</label>
                                <div className="multiselect-container">
                                    {config.options.map(opt => (
                                        <label key={opt} className="multiselect-option">
                                            <input
                                                type="checkbox"
                                                checked={(currentValue || []).includes(opt)}
                                                onChange={(e) => {
                                                    const newValue = e.target.checked
                                                        ? [...(currentValue || []), opt]
                                                        : (currentValue || []).filter(v => v !== opt);
                                                    onChange(action.action_id, { ...params, [key]: newValue });
                                                }}
                                            />
                                            {opt}
                                        </label>
                                    ))}
                                </div>
                            </div>
                        );
                    }

                    if (config.type === 'select') {
                        return (
                            <div key={key} className="param-field">
                                <label>{config.label}</label>
                                <select
                                    value={currentValue || config.default}
                                    onChange={(e) => onChange(action.action_id, { ...params, [key]: e.target.value })}
                                >
                                    {config.options.map(opt => (
                                        <option key={opt} value={opt}>{opt}</option>
                                    ))}
                                </select>
                            </div>
                        );
                    }

                    if (config.type === 'bool') {
                        return (
                            <div key={key} className="param-field checkbox-field">
                                <label>
                                    <input
                                        type="checkbox"
                                        checked={!!currentValue}
                                        onChange={(e) => onChange(action.action_id, { ...params, [key]: e.target.checked })}
                                    />
                                    {config.label}
                                </label>
                            </div>
                        );
                    }

                    // Default: text/number input
                    return (
                        <div key={key} className="param-field">
                            <label>{config.label}</label>
                            <input
                                type={config.type === 'int' || config.type === 'float' ? 'number' : 'text'}
                                step={config.type === 'float' ? 'any' : '1'}
                                value={currentValue ?? ''}
                                placeholder={config.required ? 'Required' : 'Optional'}
                                onChange={(e) => {
                                    let val = e.target.value;
                                    if (config.type === 'int') val = parseInt(val) || null;
                                    else if (config.type === 'float') val = parseFloat(val) || null;
                                    onChange(action.action_id, { ...params, [key]: val });
                                }}
                            />
                        </div>
                    );
                })}
            </div>
        </div>
    );
};

// --- Custom Technique Select Component (replaces native select) ---
const CustomTechniqueSelect = ({ value, onChange, alternatives }) => {
    const [isOpen, setIsOpen] = useState(false);
    const dropdownRef = useRef(null);

    useEffect(() => {
        const handleClickOutside = (event) => {
            if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
                setIsOpen(false);
            }
        };
        document.addEventListener("mousedown", handleClickOutside);
        return () => document.removeEventListener("mousedown", handleClickOutside);
    }, []);

    // Ensure current value is in the options list. If it changed, we still show it properly.
    const allOptions = useMemo(() => {
        const alts = alternatives || [];
        // The first alt might not be the original value, but usually the first item shown was the initial "Recommended" one.
        // Actually, we just need to ensure the dropdown has a unique list of options to show.
        const currentInAlts = alts.find(a => a.function_name === value);
        const optionsList = [];

        // Add current value at the top if it's not in alternatives
        if (!currentInAlts) {
            optionsList.push({ function_name: value, tradeoff: 'Currently selected technique', isCurrent: true });
        }

        return [...optionsList, ...alts];
    }, [value, alternatives]);

    return (
        <div className="custom-technique-select-container" ref={dropdownRef}>
            <div
                className={`custom-select-trigger ${isOpen ? 'open' : ''}`}
                onClick={() => setIsOpen(!isOpen)}
            >
                <div className="trigger-value">
                    <span className="func-name">{value}</span>
                </div>
                {isOpen ? <FiChevronUp size={16} className="chevron" /> : <FiChevronDown size={16} className="chevron" />}
            </div>

            {isOpen && (
                <div className="custom-select-dropdown">
                    {allOptions.map((opt, idx) => {
                        const isSelected = opt.function_name === value;
                        return (
                            <div
                                key={idx}
                                className={`custom-select-option ${isSelected ? 'selected' : ''}`}
                                onClick={() => { onChange(opt.function_name); setIsOpen(false); }}
                            >
                                <div className="opt-header">
                                    <strong>{opt.function_name}</strong>
                                    {isSelected && <span className="opt-badge">Selected</span>}
                                </div>
                                {opt.tradeoff && <div className="opt-desc">{opt.tradeoff}</div>}
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
};

// --- Single Action Card Component ---
const ActionCard = ({
    action,
    isChecked,
    onToggle,
    onTechniqueChange,
    onParamChange,
    onPreview,
    onRemove,
    canDrag,
}) => {
    const [isExpanded, setIsExpanded] = useState(false);
    const riskConfig = RISK_BADGE_CONFIG[action.risk_level] || RISK_BADGE_CONFIG.MEDIUM;
    const RiskIcon = riskConfig.icon;

    const funcConfig = ACTION_FUNCTION_PARAMS[action.function_name];

    return (
        <div className={`action-card ${isChecked ? 'checked' : 'unchecked'} ${action.risk_level.toLowerCase()}`}>
            {/* Drag Handle & Checkbox */}
            <div className="action-card-drag-handle">
                {canDrag && <FiMove className="drag-icon" />}
                <input
                    type="checkbox"
                    checked={isChecked}
                    onChange={() => onToggle(action.action_id)}
                    className="action-checkbox"
                />
            </div>

            {/* Main Content */}
            <div className="action-card-content">
                {/* Header Row */}
                <div className="action-card-header">
                    <div className="action-column-info">
                        <span className="action-column-name">{action.column}</span>
                        <span className="action-issue">{action.issue}</span>
                    </div>

                    <div className="action-card-actions">
                        {/* Risk Badge */}
                        <div
                            className="risk-badge"
                            style={{ backgroundColor: riskConfig.bgColor, color: riskConfig.color }}
                        >
                            <RiskIcon size={12} />
                            <span>{action.risk_level}</span>
                        </div>

                        {/* Expand Toggle */}
                        <button
                            className="expand-toggle"
                            onClick={() => setIsExpanded(!isExpanded)}
                        >
                            {isExpanded ? <FiChevronUp /> : <FiChevronDown />}
                        </button>

                        {/* Remove Button (if user wants to discard action) */}
                        {onRemove && (
                            <button className="remove-action-btn" onClick={() => onRemove(action.action_id)}>
                                <FiTrash2 size={14} />
                            </button>
                        )}
                    </div>
                </div>

                {/* Technique Selector */}
                <div className="action-technique-row">
                    <label>Technique:</label>
                    <CustomTechniqueSelect
                        value={action.function_name}
                        onChange={(newVal) => onTechniqueChange(action.action_id, newVal)}
                        alternatives={action.alternatives}
                        funcConfig={funcConfig}
                    />

                    {funcConfig && (
                        <span className="technique-description">{funcConfig.description}</span>
                    )}
                </div>

                {/* Impact Estimate */}
                <div className="action-impact-row">
                    <FiBarChart2 size={14} />
                    <span>
                        Affects ~{action.rows_affected_estimate?.toLocaleString() || 'unknown'} rows
                        {!action.reversible && <span className="irreversible-warning"> • Irreversible</span>}
                    </span>

                    {action.missingness_mechanism && action.missingness_mechanism !== 'N/A' && (
                        <span className="missingness-tag">
                            Missingness: {action.missingness_mechanism}
                        </span>
                    )}

                    <button className="preview-btn" onClick={() => onPreview(action)}>
                        <FiBarChart2 size={14} /> Preview
                    </button>
                </div>

                {/* Expanded Details */}
                {isExpanded && (
                    <div className="action-card-expanded">
                        {/* Parameter Editor */}
                        <ParameterEditor
                            action={action}
                            onChange={onParamChange}
                        />

                        {/* Statistical Evidence */}
                        <div className="evidence-section">
                            <h5><FiInfo size={14} /> Statistical Evidence</h5>
                            {action.statistical_evidence && (
                                <div className="evidence-item">
                                    <strong>{action.statistical_evidence.key_stat}:</strong>
                                    <span>{action.statistical_evidence.value}</span>
                                </div>
                            )}
                        </div>

                        {/* Reasoning Trace */}
                        <div className="reasoning-section">
                            <h5>AI Reasoning</h5>
                            <p>{action.assumption}</p>
                            {action.risk_reason && (
                                <p className="risk-reason">
                                    <strong>Risk rationale:</strong> {action.risk_reason}
                                </p>
                            )}
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};

// --- Main Action Backlog Panel Component ---
const ActionBacklogPanel = ({
    actions,
    domainInference,
    leakageWarnings,
    reasoningTrace,
    onExecuteActions,
    isExecuting,
    executionProgress,
    allColumns,
    datasetProfile
}) => {
    const [checkedActions, setCheckedActions] = useState(
        actions.reduce((acc, act) => ({ ...acc, [act.action_id]: true }), {})
    );
    const [actionList, setActionList] = useState(actions);
    const [draggedIndex, setDraggedIndex] = useState(null);
    const [previewAction, setPreviewAction] = useState(null);
    const [previewColumnProfile, setPreviewColumnProfile] = useState(null);
    const [isLoadingProfile, setIsLoadingProfile] = useState(false);

    // Re-order actions based on priority if not manually reordered
    const sortedActions = useMemo(() => {
        return [...actionList].sort((a, b) => a.priority - b.priority);
    }, [actionList]);

    const handleToggle = (actionId) => {
        setCheckedActions(prev => ({
            ...prev,
            [actionId]: !prev[actionId]
        }));
    };

    const handleTechniqueChange = (actionId, newFunctionName) => {
        setActionList(prev => prev.map(act =>
            act.action_id === actionId
                ? { ...act, function_name: newFunctionName, recommended_params: {} }
                : act
        ));
    };

    const handleParamChange = (actionId, newParams) => {
        setActionList(prev => prev.map(act =>
            act.action_id === actionId
                ? { ...act, recommended_params: newParams }
                : act
        ));
    };

    const handleDragStart = (index) => {
        setDraggedIndex(index);
    };

    const handleDragOver = (e, index) => {
        e.preventDefault();
        if (draggedIndex === null || draggedIndex === index) return;

        const newList = [...actionList];
        const draggedItem = newList[draggedIndex];
        newList.splice(draggedIndex, 1);
        newList.splice(index, 0, draggedItem);

        setActionList(newList);
        setDraggedIndex(index);
    };

    const handleDragEnd = () => {
        setDraggedIndex(null);
    };

    const handlePreview = async (action) => {
        setPreviewAction(action);
        setPreviewColumnProfile(null);
        const datasetName = datasetProfile?.filename;
        if (!datasetName) return;
        setIsLoadingProfile(true);
        try {
            const res = await fetch(`/api/dataset/${encodeURIComponent(datasetName)}/column-profile/${encodeURIComponent(action.column)}`);
            if (res.ok) {
                const profile = await res.json();
                setPreviewColumnProfile(profile);
            }
        } catch (e) {
            console.warn('Column profile fetch failed:', e);
        } finally {
            setIsLoadingProfile(false);
        }
    };

    const selectedActions = sortedActions.filter(act => checkedActions[act.action_id]);
    const checkedCount = Object.values(checkedActions).filter(v => v).length;

    const handleExecute = () => {
        if (selectedActions.length === 0) {
            toast.warn('No actions selected for execution');
            return;
        }
        onExecuteActions(selectedActions);
    };

    return (
        <div className="action-backlog-panel">
            {/* Domain Inference Header */}
            {domainInference && (
                <div className="domain-inference-banner">
                    <FiInfo size={18} />
                    <div>
                        <strong>Domain Inference:</strong> {domainInference.likely_domain}
                        <small>{domainInference.evidence}</small>
                    </div>
                    <span className={`confidence-badge confidence-${domainInference.confidence}`}>
                        {domainInference.confidence} confidence
                    </span>
                </div>
            )}

            {/* Leakage Warnings */}
            {leakageWarnings && leakageWarnings.length > 0 && (
                <div className="leakage-warning-banner">
                    <FiAlertCircle size={18} />
                    <div>
                        <strong>Data Leakage Detected</strong>
                        <ul>
                            {leakageWarnings.map((w, i) => <li key={i}>{w}</li>)}
                        </ul>
                    </div>
                </div>
            )}

            {/* Action Cards List */}
            <div className="actions-list">
                <div className="actions-list-header">
                    <h4>Action Backlog ({checkedCount}/{sortedActions.length} selected)</h4>
                    <small>Drag to reorder • Click to expand • Uncheck to veto</small>
                </div>

                {sortedActions.map((action, index) => (
                    <div
                        key={action.action_id}
                        draggable
                        onDragStart={() => handleDragStart(index)}
                        onDragOver={(e) => handleDragOver(e, index)}
                        onDragEnd={handleDragEnd}
                    >
                        <ActionCard
                            action={action}
                            index={index}
                            isChecked={checkedActions[action.action_id]}
                            onToggle={handleToggle}
                            onTechniqueChange={handleTechniqueChange}
                            onParamChange={handleParamChange}
                            onPreview={handlePreview}
                            canDrag={true}
                            allColumns={allColumns}
                        />
                    </div>
                ))}
            </div>

            {/* Execution Footer */}
            <div className="execution-footer">
                <div className="execution-summary">
                    <span>
                        Ready to execute <strong>{checkedCount}</strong> action{checkedCount !== 1 ? 's' : ''}
                    </span>
                    {isExecuting && executionProgress && (
                        <div className="execution-progress">
                            <div className="progress-bar-container">
                                <div
                                    className="progress-bar"
                                    style={{ width: `${executionProgress.percentage}%` }}
                                ></div>
                            </div>
                            <span>{executionProgress.current_action}</span>
                        </div>
                    )}
                </div>

                <button
                    className="execute-actions-btn"
                    onClick={handleExecute}
                    disabled={isExecuting || checkedCount === 0}
                >
                    {isExecuting ? (
                        <>
                            <div className="small-loader"></div>
                            Executing...
                        </>
                    ) : (
                        <>
                            <FiCheckCircle size={18} />
                            Commit Selected Actions
                        </>
                    )}
                </button>
            </div>

            {/* Reasoning Trace (Collapsible) */}
            {reasoningTrace && (
                <details className="reasoning-trace-details">
                    <summary><FiInfo size={14} /> AI Reasoning Summary</summary>
                    <p>{reasoningTrace}</p>
                </details>
            )}

            {/* Modal for Preview */}
            {previewAction && (
                <DistributionPreviewModal
                    action={previewAction}
                    columnProfile={previewColumnProfile}
                    isLoadingProfile={isLoadingProfile}
                    onClose={() => { setPreviewAction(null); setPreviewColumnProfile(null); }}
                />
            )}
        </div>
    );
};

export default ActionBacklogPanel;