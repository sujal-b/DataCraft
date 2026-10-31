import React, { useState, useCallback } from 'react';
import {
    FiCheckCircle, FiAlertTriangle, FiRotateCcw, FiDownload,
    FiCpu, FiList, FiX, FiArrowRight, FiDatabase
} from 'react-icons/fi';
import { toast } from 'react-toastify';
import '../styles/PostCommitScreen.css';

// --- Helpers for reading datasetMetrics shape ---------------------------------
// datasetMetrics = { qualityScore, columnStats: [{column, nullPercentage, nullCount, outlierCount, ...}], ... }
const getTotalMissingPct = (metrics) => {
    if (!metrics?.columnStats?.length) return null;
    const total = metrics.columnStats.reduce((s, c) => s + (c.nullPercentage ?? 0), 0);
    return total / metrics.columnStats.length;
};
const getTotalOutliers = (metrics) => {
    if (!metrics?.columnStats?.length) return null;
    return metrics.columnStats.reduce((s, c) => s + (c.outlierCount ?? 0), 0);
};

// --- Data Quality Gauge -------------------------------------------------------
const QualityGauge = ({ score }) => {
    const clamped = Math.max(0, Math.min(100, score ?? 0));
    // Needle: 0 → left (-90°), 100 → right (+90°), mapped to SVG angle
    const angleDeg = (clamped / 100) * 180 - 90;
    const angleRad = (angleDeg * Math.PI) / 180;
    const nx = 100 + 60 * Math.sin(angleRad);
    const ny = 100 - 60 * Math.cos(angleRad);
    const color = clamped >= 75 ? '#10B981' : clamped >= 45 ? '#F59E0B' : '#EF4444';
    const label = clamped >= 75 ? 'Clean' : clamped >= 45 ? 'Improving' : 'Needs Work';
    // Arc length for filled portion (semicircle circumference ≈ 251.2 for r=80)
    const arcLen = (clamped / 100) * 251.2;

    return (
        <div className="gauge-container">
            <svg viewBox="0 0 200 110" className="gauge-svg">
                {/* Track */}
                <path d="M 20 100 A 80 80 0 0 1 180 100" fill="none" stroke="#1E293B" strokeWidth="16" strokeLinecap="round" />
                {/* Fill */}
                {clamped > 0 && (
                    <path
                        d="M 20 100 A 80 80 0 0 1 180 100"
                        fill="none"
                        stroke={color}
                        strokeWidth="16"
                        strokeLinecap="round"
                        strokeDasharray={`${arcLen} 251.2`}
                    />
                )}
                {/* Needle */}
                <line x1="100" y1="100" x2={nx.toFixed(1)} y2={ny.toFixed(1)}
                    stroke="#F1F5F9" strokeWidth="3" strokeLinecap="round" />
                <circle cx="100" cy="100" r="6" fill="#F1F5F9" />
                {/* Labels */}
                <text x="100" y="70" textAnchor="middle" fontSize="28" fontWeight="700" fill={color}>{Math.round(clamped)}</text>
                <text x="100" y="88" textAnchor="middle" fontSize="11" fill="#64748B">{label}</text>
            </svg>
            <div className="gauge-label">Data Quality Score</div>
        </div>
    );
};

// --- Column Health Heatmap ----------------------------------------------------
const ColumnHeatmap = ({ beforeMetrics, afterMetrics }) => {
    const cols = beforeMetrics?.columnStats;
    if (!cols?.length) return null;
    const visible = cols.slice(0, 24);
    return (
        <div className="heatmap-container">
            <h5>Column Health Map</h5>
            <div className="heatmap-grid">
                {visible.map((col) => {
                    const afterCol = afterMetrics?.columnStats?.find(c => c.column === col.column);
                    const missBefore = col.nullPercentage ?? 0;
                    const missAfter  = afterCol?.nullPercentage ?? missBefore;
                    const outliers   = afterCol?.outlierCount ?? col.outlierCount ?? 0;
                    const totalRows  = afterMetrics?.rowCount ?? beforeMetrics?.rowCount ?? 1;
                    const outlierPct = (outliers / totalRows) * 100;
                    const health     = Math.max(0, 100 - missAfter - Math.min(20, outlierPct));
                    const hue        = Math.round((health / 100) * 120); // 0=red, 120=green
                    const improved   = missBefore - missAfter > 0.5;
                    return (
                        <div
                            key={col.column}
                            className="heatmap-cell"
                            style={{ backgroundColor: `hsl(${hue}, 60%, 42%)` }}
                            title={`${col.column}\nMissing: ${missBefore.toFixed(1)}% → ${missAfter.toFixed(1)}%\nHealth: ${health.toFixed(0)}%`}
                        >
                            <span className="heatmap-cell-name">
                                {col.column.length > 9 ? col.column.slice(0, 9) + '…' : col.column}
                            </span>
                            {improved && <span className="heatmap-delta">↑</span>}
                        </div>
                    );
                })}
            </div>
            <div className="heatmap-legend">
                <span style={{ color: '#EF4444' }}>● Needs work</span>
                <span style={{ color: '#F59E0B' }}>● Improving</span>
                <span style={{ color: '#10B981' }}>● Healthy</span>
            </div>
        </div>
    );
};

// --- Metric Delta Row ---------------------------------------------------------
const DeltaRow = ({ label, before, after, unit = '', lowerIsBetter = false }) => {
    if (before == null && after == null) return null;
    const b = typeof before === 'number' ? before : null;
    const a = typeof after  === 'number' ? after  : null;
    const diff = (a != null && b != null) ? a - b : null;
    const improved = diff != null && (lowerIsBetter ? diff < -0.5 : diff > 0.5);
    const degraded = diff != null && (lowerIsBetter ? diff > 0.5  : diff < -0.5);
    return (
        <div className={`delta-row ${improved ? 'improved' : degraded ? 'degraded' : 'neutral'}`}>
            <span className="delta-label">{label}</span>
            <span className="delta-values">
                {b != null && <span className="delta-before">{b.toFixed(1)}{unit}</span>}
                <FiArrowRight size={12} />
                <span className="delta-after">{a != null ? `${a.toFixed(1)}${unit}` : '—'}</span>
                {diff != null && Math.abs(diff) > 0.1 && (
                    <span className={`delta-badge ${improved ? 'green' : degraded ? 'red' : 'grey'}`}>
                        {diff > 0 ? '+' : ''}{diff.toFixed(1)}{unit}
                    </span>
                )}
            </span>
        </div>
    );
};

// --- Main Component -----------------------------------------------------------
const PostCommitScreen = ({
    commitResult,        // task result: { rows_before, rows_after, columns_before, columns_after, actions_applied, checkpoint, execution_summary }
    datasetName,
    beforeProfile,       // snapshot of datasetMetrics BEFORE commit
    afterProfile,        // fresh datasetMetrics AFTER re-profiling (may be null briefly)
    onViewTable,
    onGenerateNew,
    onRollback,
    onExport,
}) => {
    const [rollbackPending, setRollbackPending] = useState(false);

    const appliedLog  = commitResult?.execution_summary?.execution_log ?? [];
    const actionsApplied = commitResult?.execution_summary?.actions_applied?.length
        ?? appliedLog.filter(l => l?.status === 'SUCCESS').length
        ?? 0;
    const checkpointId  = commitResult?.checkpoint?.checkpoint_id;

    const beforeScore = beforeProfile?.qualityScore ?? null;
    const afterScore  = afterProfile?.qualityScore  ?? null;

    const handleRollback = useCallback(async () => {
        if (!checkpointId) return;
        if (!window.confirm('Restore dataset to the state before this commit? This cannot be undone.')) return;
        setRollbackPending(true);
        try {
            const res = await fetch(`/api/dataset/${datasetName}/checkpoints/${checkpointId}/restore`, { method: 'POST' });
            if (!res.ok) throw new Error(((await res.json()).detail) || 'Rollback failed.');
            toast.success('Dataset restored. Re-profiling in background…');
            onRollback?.();
        } catch (e) {
            toast.error(e.message);
        } finally {
            setRollbackPending(false);
        }
    }, [checkpointId, datasetName, onRollback]);

    return (
        <div className="post-commit-screen">
            {/* Header */}
            <div className="pcs-header">
                <div className="pcs-title-row">
                    <FiCheckCircle size={28} className="pcs-success-icon" />
                    <div>
                        <h2>Batch Committed</h2>
                        <p>
                            {actionsApplied} action{actionsApplied !== 1 ? 's' : ''} applied to{' '}
                            <strong>{datasetName}</strong>
                        </p>
                    </div>
                </div>
                <button className="pcs-close-btn" onClick={onViewTable} title="Back to table">
                    <FiX size={20} />
                </button>
            </div>

            <div className="pcs-body">
                {/* LEFT */}
                <div className="pcs-left">
                    {/* Quality Gauge */}
                    <div className="pcs-card gauge-card">
                        {afterProfile ? (
                            <QualityGauge score={afterScore} />
                        ) : (
                            <div className="pcs-loading-gauge">
                                <div className="pcs-spinner" />
                                <span>Re-profiling…</span>
                            </div>
                        )}
                        {beforeScore != null && afterScore != null && (
                            <div className="gauge-delta-row">
                                <span>Before: <strong>{Math.round(beforeScore)}</strong></span>
                                <FiArrowRight size={14} />
                                <strong style={{ color: afterScore >= beforeScore ? '#10B981' : '#EF4444' }}>
                                    {Math.round(afterScore)}
                                </strong>
                            </div>
                        )}
                    </div>

                    {/* Health Snapshot */}
                    <div className="pcs-card health-card">
                        <h4><FiDatabase size={15} /> Health Snapshot</h4>
                        <DeltaRow
                            label="Avg missing %"
                            before={getTotalMissingPct(beforeProfile)}
                            after={getTotalMissingPct(afterProfile)}
                            unit="%"
                            lowerIsBetter
                        />
                        <DeltaRow
                            label="Total outliers"
                            before={getTotalOutliers(beforeProfile)}
                            after={getTotalOutliers(afterProfile)}
                            lowerIsBetter
                        />
                        <DeltaRow label="Rows" before={commitResult?.rows_before} after={commitResult?.rows_after} />
                        <DeltaRow label="Columns" before={commitResult?.columns_before} after={commitResult?.columns_after} />
                    </div>

                    {/* Rollback */}
                    {checkpointId && (
                        <div className="pcs-card rollback-card">
                            <h4><FiRotateCcw size={15} /> Rollback Available</h4>
                            <p>A snapshot was saved before this batch.</p>
                            <button className="rollback-btn" onClick={handleRollback} disabled={rollbackPending}>
                                {rollbackPending
                                    ? <><div className="pcs-spinner-sm" /> Restoring…</>
                                    : <><FiRotateCcw size={14} /> Undo this commit</>}
                            </button>
                        </div>
                    )}
                </div>

                {/* RIGHT */}
                <div className="pcs-right">
                    {/* Heatmap */}
                    <div className="pcs-card heatmap-card">
                        {(beforeProfile || afterProfile) ? (
                            <ColumnHeatmap beforeMetrics={beforeProfile} afterMetrics={afterProfile} />
                        ) : (
                            <div className="pcs-loading-gauge">
                                <div className="pcs-spinner" />
                                <span>Loading heatmap…</span>
                            </div>
                        )}
                    </div>

                    {/* Actions log */}
                    <div className="pcs-card actions-card">
                        <h4><FiList size={15} /> Actions Applied ({actionsApplied})</h4>
                        {appliedLog.length > 0 ? (
                            <div className="actions-list-pcs">
                                {appliedLog.map((log, i) => (
                                    <div key={i} className={`action-log-row ${log?.status === 'SUCCESS' ? 'ok' : 'fail'}`}>
                                        {log?.status === 'SUCCESS'
                                            ? <FiCheckCircle size={13} />
                                            : <FiAlertTriangle size={13} />}
                                        <span>{log?.action_id ?? `Action ${i + 1}`}</span>
                                        {(log?.report?.values_changed ?? 0) > 0 && (
                                            <span className="log-changed">
                                                {log.report.values_changed.toLocaleString()} cells
                                            </span>
                                        )}
                                    </div>
                                ))}
                            </div>
                        ) : (
                            <p className="no-log-msg">Execution log not available.</p>
                        )}
                    </div>

                    {/* CTAs */}
                    <div className="pcs-card cta-card">
                        <h4>Next Steps</h4>
                        <div className="cta-buttons">
                            <button className="cta-primary" onClick={onGenerateNew}>
                                <FiCpu size={16} /> Generate New AI Recommendations
                            </button>
                            <button className="cta-secondary" onClick={onViewTable}>
                                <FiDatabase size={16} /> Back to Data Table
                            </button>
                            <div className="export-group">
                                <button className="cta-export" onClick={() => onExport?.('csv')}>
                                    <FiDownload size={14} /> CSV
                                </button>
                                <button className="cta-export" onClick={() => onExport?.('xlsx')}>
                                    <FiDownload size={14} /> Excel
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default PostCommitScreen;
