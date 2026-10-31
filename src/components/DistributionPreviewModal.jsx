import React, { useMemo } from 'react';
import { FiX, FiBarChart2, FiTrendingUp, FiAlertTriangle, FiTag, FiColumns, FiTrash2, FiZap } from 'react-icons/fi';
import '../styles/DistributionPreviewModal.css';

// --- Histogram Chart (numeric) ---
const HistogramChart = ({ bins, title, color = '#4F46E5', maxValue, stats, highlightIdx, highlightCount, highlightColor = '#F59E0B', clipLow, clipHigh }) => {
    if (!bins || bins.length === 0) {
        return (
            <div className="histogram-placeholder">
                <FiBarChart2 size={36} />
                <p>No histogram data</p>
            </div>
        );
    }
    const maxCount = maxValue || Math.max(...bins.map(b => b.count));
    
    return (
        <div className="histogram-chart">
            <h5>{title}</h5>
            <div className="histogram-bars">
                {bins.map((bin, i) => {
                    const isHighlighted = highlightIdx === i && highlightCount > 0;
                    const baseCount = isHighlighted ? Math.max(0, bin.count - highlightCount) : bin.count;
                    const addedCount = isHighlighted ? highlightCount : 0;
                    
                    const baseH = maxCount > 0 ? (baseCount / maxCount) * 100 : 0;
                    const addedH = maxCount > 0 ? (addedCount / maxCount) * 100 : 0;
                    
                    return (
                        <div key={i} className="histogram-bar-wrapper" title={`${bin.edge?.toFixed ? bin.edge.toFixed(3) : bin.edge}: ${bin.count}`}>
                            <div className="histogram-bar-stack" style={{ height: `${baseH + addedH}%` }}>
                                <div className="histogram-bar" style={{ height: `${(baseH / (baseH + addedH)) * 100}%`, backgroundColor: color }} />
                                {isHighlighted && (
                                    <div className="histogram-bar-highlight" style={{ height: `${(addedH / (baseH + addedH)) * 100}%`, backgroundColor: highlightColor }} />
                                )}
                            </div>
                        </div>
                    );
                })}
            </div>
            {(clipLow != null || clipHigh != null) && (() => {
                const minEdge = bins[0]?.edge ?? 0;
                const maxEdge = bins[bins.length - 1]?.edge ?? 1;
                const range = maxEdge - minEdge || 1;
                return (
                    <div className="clip-lines">
                        {clipLow != null && <div className="clip-line" style={{ left: `${Math.max(0, ((clipLow - minEdge) / range) * 100)}%` }} title={`Lower fence: ${clipLow.toFixed(3)}`} />}
                        {clipHigh != null && <div className="clip-line" style={{ left: `${Math.min(100, ((clipHigh - minEdge) / range) * 100)}%` }} title={`Upper fence: ${clipHigh.toFixed(3)}`} />}
                    </div>
                );
            })()}
            <div className="histogram-x-axis">
                <span className="axis-label">{typeof bins[0]?.edge === 'number' ? bins[0].edge.toFixed(2) : bins[0]?.edge}</span>
                <span className="axis-label">{typeof bins[bins.length - 1]?.edge === 'number' ? bins[bins.length - 1].edge.toFixed(2) : bins[bins.length - 1]?.edge}</span>
            </div>
            {stats && (
                <div className="chart-stats">
                    {stats.map((s, i) => <span key={i} className={`chart-stat ${s.highlight ? 'stat-highlight' : ''}`}>{s.label}: <strong>{s.value}</strong></span>)}
                </div>
            )}
        </div>
    );
};

// --- Categorical Bar Chart ---
const CategoricalBarChart = ({ values, title, color = '#4F46E5', labelMap }) => {
    if (!values || values.length === 0) {
        return (
            <div className="histogram-placeholder">
                <FiBarChart2 size={36} />
                <p>No category data</p>
            </div>
        );
    }
    const maxCount = Math.max(...values.map(v => v.count));
    return (
        <div className="histogram-chart categorical-chart">
            <h5>{title}</h5>
            <div className="cat-bars">
                {values.map((v, i) => {
                    const h = maxCount > 0 ? (v.count / maxCount) * 100 : 0;
                    const label = labelMap ? labelMap[v.value] : v.value;
                    return (
                        <div key={i} className="cat-bar-col" title={`${v.value}: ${v.count}`}>
                            <div className="cat-bar" style={{ height: `${h}%`, backgroundColor: color }} />
                            <span className="cat-label">{label ?? v.value}</span>
                        </div>
                    );
                })}
            </div>
            <div className="chart-stats">
                <span className="chart-stat">{values.length} categories shown</span>
            </div>
        </div>
    );
};

// --- Binary Column Preview (for create_missing_flag) ---
const BinaryColumnPreview = ({ missingCount, totalCount, columnName }) => {
    const presentCount = totalCount - missingCount;
    const missingPct = totalCount > 0 ? ((missingCount / totalCount) * 100).toFixed(1) : 0;
    const presentPct = (100 - missingPct).toFixed(1);
    return (
        <div className="binary-preview">
            <h5>New Column: <code>{columnName}_is_missing</code></h5>
            <div className="binary-bars">
                <div className="binary-bar-item">
                    <div className="binary-bar-label">0 (Present)</div>
                    <div className="binary-bar-track">
                        <div className="binary-bar-fill" style={{ width: `${presentPct}%`, backgroundColor: '#4F46E5' }} />
                    </div>
                    <div className="binary-bar-value">{presentCount.toLocaleString()} ({presentPct}%)</div>
                </div>
                <div className="binary-bar-item">
                    <div className="binary-bar-label">1 (Missing)</div>
                    <div className="binary-bar-track">
                        <div className="binary-bar-fill" style={{ width: `${missingPct}%`, backgroundColor: '#F59E0B' }} />
                    </div>
                    <div className="binary-bar-value">{missingCount.toLocaleString()} ({missingPct}%)</div>
                </div>
            </div>
            <p className="binary-note">Original <code>{columnName}</code> column is preserved alongside this new binary indicator.</p>
        </div>
    );
};

// --- Simulate after-histogram for all operations ---
function simulateAfterHistogram(action, columnProfile) {
    const bins = columnProfile?.histogram_bins;
    const missingCount = columnProfile?.missing_count || 0;
    const mean = columnProfile?.mean;
    const std = columnProfile?.std;
    const median = columnProfile?.median;
    const iqrLower = columnProfile?.iqr_lower_fence;
    const iqrUpper = columnProfile?.iqr_upper_fence;
    const topValues = columnProfile?.top_values;

    const fn = action.function_name;

    // Helper: deep clone bins
    const clone = (b) => b.map(x => ({ ...x }));

    switch (fn) {
        case 'delete_column':
            return { type: 'deletion' };

        case 'drop_rows_where_null': {
            if (!bins) return { type: 'no_histogram' };
            const total = bins.reduce((s, b) => s + b.count, 0);
            const keepRatio = total > 0 ? (total - missingCount) / total : 1;
            return { type: 'histogram', bins: clone(bins).map(b => ({ ...b, count: Math.round(b.count * keepRatio) })), label: 'After dropping null rows' };
        }

        case 'impute_mean':
        case 'impute_median': {
            if (!bins) return { type: 'no_histogram' };
            const imputeVal = fn === 'impute_mean' ? mean : median;
            if (imputeVal === null || imputeVal === undefined) return { type: 'no_histogram' };
            const sim = clone(bins);
            let targetIdx = sim.length - 1;
            for (let i = 0; i < sim.length; i++) {
                if (sim[i].edge >= imputeVal) { targetIdx = i; break; }
            }
            sim[targetIdx].count += missingCount;
            return { type: 'histogram', bins: sim, label: `After imputing ${fn === 'impute_mean' ? 'mean' : 'median'} (${imputeVal?.toFixed(3)})`, highlightIdx: targetIdx, highlightCount: missingCount };
        }

        case 'impute_mode': {
            if (!bins) return { type: 'no_histogram' };
            // For numeric columns, mode approximated by highest-count bin
            const modeEdge = bins.reduce((best, b) => b.count > best.count ? b : best, bins[0]).edge;
            const sim = clone(bins);
            let targetIdx = sim.length - 1;
            for (let i = 0; i < sim.length; i++) {
                if (sim[i].edge >= modeEdge) { targetIdx = i; break; }
            }
            sim[targetIdx].count += missingCount;
            return { type: 'histogram', bins: sim, label: `After imputing mode (~${modeEdge?.toFixed(3)})`, highlightIdx: targetIdx, highlightCount: missingCount };
        }

        case 'impute_constant': {
            if (!bins) return { type: 'no_histogram' };
            const constVal = parseFloat(action.recommended_params?.value);
            if (isNaN(constVal)) return { type: 'no_histogram' };
            const sim = clone(bins);
            let closest = 0;
            let minDist = Infinity;
            sim.forEach((b, i) => { const d = Math.abs(b.edge - constVal); if (d < minDist) { minDist = d; closest = i; } });
            sim[closest].count += missingCount;
            return { type: 'histogram', bins: sim, label: `After imputing constant (${constVal})`, highlightIdx: closest, highlightCount: missingCount };
        }

        case 'forward_fill': {
            if (!bins) return { type: 'no_histogram' };
            // Forward fill redistributes missing into neighboring bins — approximate same as mode
            const sim = clone(bins);
            const modeIdx = sim.reduce((best, b, i) => b.count > sim[best].count ? i : best, 0);
            sim[modeIdx].count += missingCount;
            return { type: 'histogram', bins: sim, label: 'After forward fill (time-series imputation)', highlightIdx: modeIdx, highlightCount: missingCount };
        }

        case 'clip_outliers': {
            const rawBins = columnProfile?.raw_histogram_bins || bins;
            if (!rawBins) return { type: 'no_histogram' };
            if (iqrLower === null || iqrUpper === null) return { type: 'no_histogram' };
            let outlierCount = 0;
            const sim = clone(rawBins);
            sim.forEach(b => { if (b.edge < iqrLower || b.edge > iqrUpper) { outlierCount += b.count; b.count = 0; } });
            if (outlierCount > 0) {
                const lIdx = sim.findIndex(b => b.edge >= iqrLower);
                const rIdx = [...sim].reverse().findIndex(b => b.edge <= iqrUpper);
                if (lIdx >= 0) sim[lIdx].count += Math.floor(outlierCount / 2);
                if (rIdx >= 0) sim[sim.length - 1 - rIdx].count += Math.ceil(outlierCount / 2);
            }
            return { type: 'histogram', bins: sim, label: `After clipping [${iqrLower?.toFixed(2)}, ${iqrUpper?.toFixed(2)}]`, useRaw: true, clipLow: iqrLower, clipHigh: iqrUpper };
        }

        case 'winsorize': {
            const rawBins = columnProfile?.raw_histogram_bins || bins;
            if (!rawBins) return { type: 'no_histogram' };
            const lPct = (action.recommended_params?.lower_percentile ?? 5) / 100;
            const uPct = (action.recommended_params?.upper_percentile ?? 95) / 100;
            const allEdges = rawBins.map(b => b.edge);
            const sortedEdges = [...allEdges].sort((a, b) => a - b);
            const lBound = sortedEdges[Math.floor(lPct * sortedEdges.length)] ?? sortedEdges[0];
            const uBound = sortedEdges[Math.floor(uPct * sortedEdges.length)] ?? sortedEdges[sortedEdges.length - 1];
            let winsorCount = 0;
            const sim = clone(rawBins);
            sim.forEach(b => { if (b.edge < lBound || b.edge > uBound) { winsorCount += b.count; b.count = 0; } });
            if (winsorCount > 0) {
                const lIdx = sim.findIndex(b => b.edge >= lBound);
                const rIdx = [...sim].reverse().findIndex(b => b.edge <= uBound);
                if (lIdx >= 0) sim[lIdx].count += Math.floor(winsorCount / 2);
                if (rIdx >= 0) sim[sim.length - 1 - rIdx].count += Math.ceil(winsorCount / 2);
            }
            return { type: 'histogram', bins: sim, label: `After winsorize [P${action.recommended_params?.lower_percentile ?? 5}–P${action.recommended_params?.upper_percentile ?? 95}]`, useRaw: true, clipLow: lBound, clipHigh: uBound };
        }

        case 'robust_scale': {
            if (!bins) return { type: 'no_histogram' };
            const med = columnProfile?.median ?? 0;
            const q1r = columnProfile?.iqr_lower_fence;
            const q3r = columnProfile?.iqr_upper_fence;
            const iqrVal = (q3r != null && q1r != null) ? (q3r - q1r) || 1 : 1;
            const sim = bins.map(b => ({ edge: parseFloat(((b.edge - med) / iqrVal).toFixed(4)), count: b.count }));
            return { type: 'histogram', bins: sim, label: 'After robust scaling (median=0, IQR=1)' };
        }

        case 'yeo_johnson_transform': {
            if (!bins) return { type: 'no_histogram' };
            const sim = bins.map(b => ({ edge: b.edge >= 0 ? parseFloat(Math.log(b.edge + 1).toFixed(4)) : parseFloat((-(Math.log(-b.edge + 1))).toFixed(4)), count: b.count }));
            return { type: 'histogram', bins: sim, label: 'After Yeo-Johnson (skew ↓, handles negatives)' };
        }

        case 'knn_impute': {
            if (!bins) return { type: 'no_histogram' };
            const sim = clone(bins);
            const medIdx = sim.reduce((best, b, i) => b.count > sim[best].count ? i : best, 0);
            sim[medIdx].count += missingCount;
            return { type: 'histogram', bins: sim, label: `After KNN impute (${action.recommended_params?.n_neighbors ?? 5} neighbors)`, highlightIdx: medIdx, highlightCount: missingCount };
        }

        case 'standard_scale': {
            if (!bins || mean === null || !std) return { type: 'no_histogram' };
            const sim = bins.map(b => ({ edge: parseFloat(((b.edge - mean) / std).toFixed(4)), count: b.count }));
            return { type: 'histogram', bins: sim, label: 'After standardization (μ=0, σ=1)' };
        }

        case 'min_max_scale': {
            if (!bins || bins.length < 2) return { type: 'no_histogram' };
            const minEdge = bins[0].edge;
            const maxEdge = bins[bins.length - 1].edge;
            const range = maxEdge - minEdge || 1;
            const sim = bins.map(b => ({ edge: parseFloat(((b.edge - minEdge) / range).toFixed(4)), count: b.count }));
            return { type: 'histogram', bins: sim, label: 'After min-max scaling [0, 1]' };
        }

        case 'log_transform': {
            if (!bins) return { type: 'no_histogram' };
            const positiveBins = bins.filter(b => b.edge > 0);
            if (positiveBins.length < 2) return { type: 'no_histogram' };
            const sim = positiveBins.map(b => ({ edge: parseFloat(Math.log(b.edge).toFixed(4)), count: b.count }));
            return { type: 'histogram', bins: sim, label: 'After log transform (reduces skewness)' };
        }

        case 'one_hot_encode': {
            if (!topValues || topValues.length === 0) return { type: 'no_histogram' };
            return { type: 'one_hot', topValues, label: 'Encoded categories → binary columns' };
        }

        case 'label_encode': {
            if (!topValues || topValues.length === 0) return { type: 'no_histogram' };
            const labelMap = {};
            topValues.forEach((v, i) => { labelMap[v.value] = i; });
            return { type: 'label_encode', topValues, labelMap, label: 'Categories → integer labels' };
        }

        case 'create_missing_flag': {
            const total = (columnProfile?.histogram_bins || []).reduce((s, b) => s + b.count, 0) + missingCount;
            return { type: 'missing_flag', missingCount, totalCount: total || missingCount };
        }

        case 'drop_duplicate_rows': {
            return { type: 'info', message: 'Duplicate rows will be removed across the entire dataset. This column is not individually affected — the row-level deduplication applies globally.' };
        }

        case 'create_date_features': {
            return { type: 'info', message: `Date parts will be extracted as new columns: ${(action.recommended_params?.parts || ['year', 'month', 'day']).join(', ')}. The original column is preserved.` };
        }

        case 'create_interaction': {
            const { col_a, col_b, operation } = action.recommended_params || {};
            return { type: 'info', message: `A new feature column will be created: ${col_a || '?'} ${operation || 'multiply'} ${col_b || '?'}. Both source columns are preserved.` };
        }

        default:
            return { type: 'no_histogram' };
    }
}

// --- Stat delta helper ---
function getStatDeltas(fn, columnProfile) {
    const { mean, median, skewness, missing_count, missing_pct, iqr_lower_fence, iqr_upper_fence, outlier_count } = columnProfile || {};
    const deltas = [];
    if (fn === 'standard_scale') {
        deltas.push({ label: 'New Mean', value: '0.000', highlight: true }, { label: 'New Std', value: '1.000', highlight: true });
        if (mean != null) deltas.push({ label: 'Old Mean', value: mean.toFixed(3) });
    } else if (fn === 'robust_scale') {
        deltas.push({ label: 'New Median', value: '0.000', highlight: true }, { label: 'New IQR', value: '1.000', highlight: true });
        if (median != null) deltas.push({ label: 'Old Median', value: median.toFixed(3) });
    } else if (fn === 'min_max_scale') {
        deltas.push({ label: 'New Range', value: '[0, 1]', highlight: true });
    } else if (fn === 'log_transform' || fn === 'yeo_johnson_transform') {
        if (skewness != null) deltas.push({ label: 'Current Skew', value: skewness.toFixed(3) }, { label: 'Expected Skew', value: '↓ reduced', highlight: true });
    } else if (fn === 'clip_outliers') {
        if (iqr_lower_fence != null) deltas.push({ label: 'Cap Lower', value: iqr_lower_fence?.toFixed(3), highlight: true }, { label: 'Cap Upper', value: iqr_upper_fence?.toFixed(3), highlight: true });
        if (outlier_count != null) deltas.push({ label: 'Outliers capped', value: outlier_count.toLocaleString() });
    } else if (fn === 'winsorize') {
        if (outlier_count != null) deltas.push({ label: 'Outliers capped', value: outlier_count.toLocaleString(), highlight: true });
    } else if (['impute_mean', 'impute_median', 'impute_mode', 'impute_constant', 'forward_fill', 'knn_impute'].includes(fn)) {
        if (missing_count != null) deltas.push({ label: 'Rows filled', value: missing_count.toLocaleString(), highlight: true }, { label: 'Was missing', value: `${missing_pct?.toFixed(1)}%` });
    } else if (fn === 'drop_rows_where_null') {
        if (missing_count != null) deltas.push({ label: 'Rows dropped', value: missing_count.toLocaleString(), highlight: true }, { label: 'Was missing', value: `${missing_pct?.toFixed(1)}%` });
    }
    return deltas;
}

// ---- Main Modal ----
const DistributionPreviewModal = ({ action, columnProfile, onClose, isLoadingProfile }) => {
    const result = useMemo(() => simulateAfterHistogram(action, columnProfile), [action, columnProfile]);
    // Use raw bins for ops that deal with outliers (so the tail is visible in Before chart)
    const outlierOps = ['clip_outliers', 'winsorize'];
    const beforeBins = (outlierOps.includes(action.function_name) && columnProfile?.raw_histogram_bins)
        ? columnProfile.raw_histogram_bins
        : columnProfile?.histogram_bins;
    const beforeStats = [
        ...(columnProfile?.mean != null ? [{ label: 'Mean', value: columnProfile.mean.toFixed(3) }] : []),
        ...(columnProfile?.std != null ? [{ label: 'Std', value: columnProfile.std.toFixed(3) }] : []),
        ...(columnProfile?.skewness != null ? [{ label: 'Skew', value: columnProfile.skewness.toFixed(3) }] : []),
        ...(columnProfile?.outlier_count != null ? [{ label: 'Outliers', value: columnProfile.outlier_count.toLocaleString(), highlight: columnProfile.outlier_count > 0 }] : []),
    ];
    const afterStats = getStatDeltas(action.function_name, columnProfile);
    const sharedMax = (result?.type === 'histogram' && beforeBins)
        ? Math.max(
            Math.max(...beforeBins.map(b => b.count)),
            Math.max(...result.bins.map(b => b.count))
          )
        : undefined;

    return (
        <div className="distribution-preview-modal-overlay" onClick={onClose}>
            <div className="distribution-preview-modal" onClick={e => e.stopPropagation()}>
                <div className="preview-modal-header">
                    <div>
                        <h3><FiBarChart2 size={18} /> Distribution Preview</h3>
                        <p>Column: <strong>{action.column}</strong> · <code>{action.function_name}</code></p>
                    </div>
                    <button className="close-preview-btn" onClick={onClose}><FiX size={20} /></button>
                </div>

                <div className="preview-modal-content">
                    {isLoadingProfile ? (
                        <div className="preview-loading">
                            <div className="preview-spinner" />
                            <p>Loading column profile…</p>
                        </div>
                    ) : (
                    <>
                    {/* DELETION */}
                    {result.type === 'deletion' && (
                        <div className="deletion-warning">
                            <FiTrash2 size={48} />
                            <h4>Column Will Be Deleted</h4>
                            <p>All <strong>{(columnProfile?.unique_count || 0).toLocaleString()}</strong> unique values in <strong>{action.column}</strong> will be permanently removed.</p>
                            <p className="impact-summary"><strong>Rows affected:</strong> {action.rows_affected_estimate?.toLocaleString() || 'all'} · <strong>Reversible:</strong> No</p>
                        </div>
                    )}

                    {/* STANDARD BEFORE/AFTER HISTOGRAM */}
                    {result.type === 'histogram' && (
                        <div className="before-after-comparison">
                            <div className="comparison-chart">
                                <HistogramChart
                                    bins={beforeBins}
                                    title={result.useRaw ? 'Before (full range incl. outliers)' : 'Before'}
                                    color="#94A3B8"
                                    maxValue={sharedMax}
                                    stats={beforeStats}
                                    clipLow={result.clipLow}
                                    clipHigh={result.clipHigh}
                                />
                            </div>
                            <div className="comparison-arrow"><FiTrendingUp size={28} /><span>Transform</span></div>
                            <div className="comparison-chart">
                                <HistogramChart bins={result.bins} title={result.label} color="#4F46E5" maxValue={sharedMax} stats={afterStats} highlightIdx={result.highlightIdx} highlightCount={result.highlightCount} />
                            </div>
                        </div>
                    )}

                    {/* ONE-HOT ENCODE */}
                    {result.type === 'one_hot' && (
                        <div className="before-after-comparison">
                            <div className="comparison-chart">
                                <CategoricalBarChart values={result.topValues} title="Before (Category Frequencies)" color="#94A3B8" />
                            </div>
                            <div className="comparison-arrow"><FiColumns size={28} /><span>Encode</span></div>
                            <div className="comparison-chart encode-preview">
                                <h5>After: {result.topValues.length} New Binary Columns</h5>
                                <div className="onehot-cols">
                                    {result.topValues.slice(0, 8).map((v, i) => (
                                        <div key={i} className="onehot-col-badge">
                                            <span className="badge-name">{action.column}_{v.value}</span>
                                            <span className="badge-type">0 / 1</span>
                                        </div>
                                    ))}
                                    {result.topValues.length > 8 && <div className="onehot-col-badge more">+{result.topValues.length - 8} more…</div>}
                                </div>
                                <p className="binary-note">Each category becomes a binary indicator column.</p>
                            </div>
                        </div>
                    )}

                    {/* LABEL ENCODE */}
                    {result.type === 'label_encode' && (
                        <div className="before-after-comparison">
                            <div className="comparison-chart">
                                <CategoricalBarChart values={result.topValues} title="Before (Categories)" color="#94A3B8" />
                            </div>
                            <div className="comparison-arrow"><FiTag size={28} /><span>Encode</span></div>
                            <div className="comparison-chart">
                                <CategoricalBarChart values={result.topValues} title="After (Integer Labels)" color="#4F46E5" labelMap={result.labelMap} />
                                <div className="label-mapping">
                                    {result.topValues.slice(0, 6).map((v, i) => (
                                        <div key={i} className="label-map-row">
                                            <span className="label-from">{v.value}</span>
                                            <span className="label-arrow">→</span>
                                            <span className="label-to">{i}</span>
                                        </div>
                                    ))}
                                    {result.topValues.length > 6 && <div className="label-map-row"><span className="label-from">…</span><span className="label-arrow">→</span><span className="label-to">…</span></div>}
                                </div>
                            </div>
                        </div>
                    )}

                    {/* MISSING FLAG */}
                    {result.type === 'missing_flag' && (
                        <div className="missing-flag-preview">
                            {beforeBins && (
                                <div className="comparison-chart" style={{ flex: 1 }}>
                                    <HistogramChart bins={beforeBins} title="Original Column (unchanged)" color="#94A3B8" stats={beforeStats} />
                                </div>
                            )}
                            <div style={{ flex: 1 }}>
                                <BinaryColumnPreview missingCount={result.missingCount} totalCount={result.totalCount} columnName={action.column} />
                            </div>
                        </div>
                    )}

                    {/* INFO MESSAGE */}
                    {result.type === 'info' && (
                        <div className="server-preview-required info-preview">
                            <FiZap size={40} />
                            <h4>Structural Transformation</h4>
                            <p>{result.message}</p>
                            {beforeBins && <HistogramChart bins={beforeBins} title="Current Distribution (will be preserved)" color="#94A3B8" stats={beforeStats} />}
                        </div>
                    )}

                    {/* FALLBACK: no histogram data at all */}
                    {result.type === 'no_histogram' && (
                        <div className="server-preview-required">
                            <FiBarChart2 size={40} />
                            <h4>Visual Preview Unavailable</h4>
                            <p>No histogram data found for column <strong>{action.column}</strong>. This may be a categorical or date column. After applying, refresh statistics to see the updated profile.</p>
                            {columnProfile?.top_values && (
                                <CategoricalBarChart values={columnProfile.top_values} title="Category Frequency (Before)" color="#94A3B8" />
                            )}
                        </div>
                    )}

                    {/* Action Detail Panel */}
                    <div className="preview-action-info">
                        <h5>Action Details</h5>
                        <div className="info-grid">
                            <div className="info-item"><span className="label">Issue:</span><span className="value">{action.issue}</span></div>
                            <div className="info-item"><span className="label">Risk:</span><span className={`value risk-${action.risk_level?.toLowerCase()}`}>{action.risk_level}</span></div>
                            {action.missingness_mechanism && action.missingness_mechanism !== 'N/A' && (
                                <div className="info-item"><span className="label">Missingness:</span><span className="value">{action.missingness_mechanism}</span></div>
                            )}
                            {columnProfile?.missing_count > 0 && (
                                <div className="info-item"><span className="label">Missing rows:</span><span className="value">{columnProfile.missing_count.toLocaleString()} ({columnProfile.missing_pct?.toFixed(1)}%)</span></div>
                            )}
                            {action.assumption && (
                                <div className="info-item info-item-full"><span className="label">AI Reasoning:</span><span className="value">{action.assumption}</span></div>
                            )}
                        </div>
                    </div>
                    </>
                    )}
                </div>

                <div className="preview-modal-footer">
                    <button className="cancel-preview-btn" onClick={onClose}>Close</button>
                </div>
            </div>
        </div>
    );
};

export default DistributionPreviewModal;